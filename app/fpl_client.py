"""
FPL API client with in-memory caching.

The official FPL API is free, public, and unauthenticated.
Base URL: https://fantasy.premierleague.com/api/

Cache TTL defaults to 5 minutes (configurable via FPL_CACHE_TTL_SECONDS).
During live matches, callers that need fresh data should pass ttl=0.
"""

import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[Any, float]] = {}  # key → (data, expires_at)

HEADERS = {
    "User-Agent": "x402-fpl-api/1.0 (https://github.com/x402-fpl-api)",
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

    async with httpx.AsyncClient(headers=HEADERS, timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

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
    chip_this_gw = next(
        (c["name"] for c in chips if c["event"] == current_gw), None
    )

    if chip_this_gw in ("wildcard", "freehit"):
        free_transfers = 1
    elif event_transfers == 0:
        # Check if previous GW also had 0 transfers (can't stack beyond 2)
        free_transfers = 2
    else:
        free_transfers = 1

    # Chips remaining
    chips_used = {c["name"] for c in chips}
    all_chips = {"wildcard", "bboost", "freehit", "3xc"}
    # Note: 2 wildcards available (1 per half), simplified here
    chips_remaining = list(all_chips - chips_used)

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
