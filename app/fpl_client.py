"""
FPL API client with in-memory caching.

The official FPL API is free, public, and unauthenticated.
Base URL: https://fantasy.premierleague.com/api/

Cache TTL defaults to 5 minutes (configurable via FPL_CACHE_TTL_SECONDS).
During live matches, callers that need fresh data should pass ttl=0.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings

MAX_RETRIES = 2
RETRY_DELAY = 1.0  # seconds

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[Any, float]] = {}  # key → (data, expires_at)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


async def _fetch(path: str, ttl: int | None = None) -> Any:
    """Fetch a FPL API path, returning parsed JSON. Uses cache unless ttl=0."""
    if ttl is None:
        ttl = settings.fpl_cache_ttl_seconds

    url = f"{settings.fpl_base_url}{path}"
    now = time.monotonic()

    if ttl > 0 and url in _cache:
        data, expires_at = _cache[url]
        if now < expires_at:
            return data

    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                break
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                logger.warning("FPL API attempt %d failed for %s: %s", attempt + 1, path, exc)
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise
    else:
        raise last_exc  # type: ignore[misc]

    if ttl > 0:
        _cache[url] = (data, now + ttl)

    return data


async def get_bootstrap() -> dict:
    """
    GET /bootstrap-static/

    Returns all players, teams, gameweeks, scoring rules.
    This is the main data source — ~1 MB JSON, cache aggressively.
    """
    return await _fetch("/bootstrap-static/")


async def get_fixtures() -> list:
    """
    GET /fixtures/

    All 380 fixtures with FDR ratings, scores, gameweek numbers.
    """
    return await _fetch("/fixtures/")


async def get_live_points(gameweek: int) -> dict:
    """
    GET /event/{gw}/live/

    Real-time points during live matches. Short TTL (30s) for accuracy.
    """
    return await _fetch(f"/event/{gameweek}/live/", ttl=30)


async def get_player_summary(player_id: int) -> dict:
    """
    GET /element-summary/{player_id}/

    Per-player fixture history and upcoming fixtures.
    """
    return await _fetch(f"/element-summary/{player_id}/")


async def get_team_picks(team_id: int, gameweek: int) -> dict:
    """
    GET /entry/{team_id}/event/{gw}/picks/

    A specific FPL team's squad picks for a gameweek.
    """
    return await _fetch(f"/entry/{team_id}/event/{gameweek}/picks/", ttl=60)


async def get_team_history(team_id: int) -> dict:
    """
    GET /entry/{team_id}/history/

    Season history, past GW ranks, chips used.
    """
    return await _fetch(f"/entry/{team_id}/history/")


def get_current_gameweek(bootstrap: dict) -> int:
    """Extract the current (or next) gameweek number from bootstrap data."""
    for gw in bootstrap["events"]:
        if gw["is_current"]:
            return gw["id"]
    for gw in bootstrap["events"]:
        if gw["is_next"]:
            return gw["id"]
    # Fallback: last finished
    finished = [gw for gw in bootstrap["events"] if gw["finished"]]
    return finished[-1]["id"] if finished else 1


def get_next_gameweek(bootstrap: dict) -> int:
    """Extract the next gameweek number from bootstrap data."""
    for gw in bootstrap["events"]:
        if gw["is_next"]:
            return gw["id"]
    # If no next, current is the latest
    return get_current_gameweek(bootstrap)


async def get_league_standings(league_id: int) -> dict:
    """
    GET /leagues-classic/{league_id}/standings/

    Classic league standings with manager names, ranks, and total points.
    """
    return await _fetch(f"/leagues-classic/{league_id}/standings/", ttl=120)


async def get_manager_transfers(team_id: int) -> list:
    """
    GET /entry/{team_id}/transfers/

    All transfers made this season, ordered by most recent first.
    """
    return await _fetch(f"/entry/{team_id}/transfers/", ttl=120)


async def get_manager_info(team_id: int) -> dict:
    """
    GET /entry/{team_id}/

    Manager profile: name, team name, overall rank, favourite team.
    """
    return await _fetch(f"/entry/{team_id}/", ttl=120)


async def get_manager_status(team_id: int, bootstrap: dict) -> dict:
    """
    Auto-detect a manager's current status: bank, free transfers,
    chips used, and overall rank.

    Logic for free transfers:
      - Base: 1 FT per gameweek
      - If 0 transfers made last GW → rolled over to 2 (max 2)
      - Wildcard/free hit resets to 1
    """
    current_gw = get_current_gameweek(bootstrap)
    picks_data = await get_team_picks(team_id, current_gw)
    history_data = await get_team_history(team_id)

    entry_history = picks_data.get("entry_history", {})
    bank = entry_history.get("bank", 0) / 10  # convert to millions
    event_transfers = entry_history.get("event_transfers", 0)
    overall_rank = entry_history.get("overall_rank", 0)
    total_points = entry_history.get("total_points", 0)

    # Calculate free transfers for next GW
    chips = history_data.get("chips", [])
    chip_this_gw = next((c["name"] for c in chips if c["event"] == current_gw), None)

    # 2025/26 rule: managers can bank up to 5 free transfers (1 base + 4 rolled).
    # FPL API game_settings.max_extra_free_transfers = 4.
    max_free_transfers = 5
    if chip_this_gw in ("wildcard", "freehit"):
        free_transfers = 1
    elif event_transfers == 0:
        # Rolled over — estimate based on entry_history limit field if available,
        # otherwise assume +1 banked (up to max). The actual count comes from
        # entry_history.event_transfers_cost and bank logic, but a simple heuristic
        # is: previous FTs + 1 (capped at max). Without prior GW data, assume 2.
        free_transfers = min(max_free_transfers, 2)
    else:
        free_transfers = 1

    # Chips remaining — FPL resets all chips at the halfway point (after GW19).
    # Each half of the season gets a full set: wildcard, bench boost, free hit, triple captain.
    all_chips = {"wildcard", "bboost", "freehit", "3xc"}
    halfway_gw = 19  # chips reset after this gameweek

    if current_gw > halfway_gw:
        # Second half: only count chips used in GW20+
        chips_used_this_half = {c["name"] for c in chips if c["event"] > halfway_gw}
    else:
        # First half: only count chips used in GW1-19
        chips_used_this_half = {c["name"] for c in chips if c["event"] <= halfway_gw}

    chips_remaining = sorted(all_chips - chips_used_this_half)

    return {
        "bank": round(bank, 1),
        "free_transfers": free_transfers,
        "overall_rank": overall_rank,
        "total_points": total_points,
        "current_gameweek": current_gw,
        "next_gameweek": get_next_gameweek(bootstrap),
        "chips_used": [{"name": c["name"], "gameweek": c["event"]} for c in chips],
        "chips_remaining": chips_remaining,
        "chip_active_this_gw": chip_this_gw,
        "transfers_made_this_gw": event_transfers,
        "points_on_bench_this_gw": entry_history.get("points_on_bench", 0),
    }
