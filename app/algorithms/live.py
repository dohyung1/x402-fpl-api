"""
Live Points algorithm.

Returns a team's live score during an active gameweek:
  - Current live points for each player
  - Projected bonus points with BPS tracking
  - Auto-sub scenarios
  - Rough rank estimate (based on live points vs average)
  - Match BPS rankings showing top performers per fixture
"""

import asyncio
from collections import defaultdict

from app.algorithms import POSITION_MAP
from app.fpl_client import (
    get_bootstrap,
    get_current_gameweek,
    get_event_status,
    get_fixtures,
    get_team_history,
    get_team_picks,
)
from app.fpl_client import (
    get_live_points as fpl_live,
)


def _calculate_fixture_bps(
    fixture_id: int,
    fixture_player_ids: set[int],
    live_elements: dict[int, dict],
    players_by_id: dict[int, dict],
    teams: dict[int, dict],
) -> dict:
    """Calculate BPS rankings and projected bonus for a single fixture.

    FPL bonus rules:
    - Top BPS = 3 bonus points
    - Second highest = 2 bonus points
    - Third highest = 1 bonus point
    - Ties: players share the higher bonus (e.g., two tied at top both get 3)

    Returns a dict with:
      - fixture_id: the fixture ID
      - rankings: list of {element_id, name, team, bps, projected_bonus}
      - player_bonus: dict mapping element_id → {bps, projected_bonus, bps_rank, ...}
    """
    # Gather BPS for all players in this fixture who have played
    bps_entries = []
    for pid in fixture_player_ids:
        el = live_elements.get(pid, {})
        stats = el.get("stats", {})
        bps = stats.get("bps", 0)
        minutes = stats.get("minutes", 0)
        if minutes > 0:
            p = players_by_id.get(pid, {})
            bps_entries.append(
                {
                    "element_id": pid,
                    "name": p.get("web_name", "Unknown"),
                    "team": teams.get(p.get("team"), {}).get("short_name", "?"),
                    "bps": bps,
                }
            )

    # Sort by BPS descending
    bps_entries.sort(key=lambda x: x["bps"], reverse=True)

    # Assign projected bonus using FPL tie rules
    player_bonus: dict[int, dict] = {}
    bonus_pool = [3, 2, 1]  # bonus to assign: 1st, 2nd, 3rd
    pool_idx = 0  # which bonus level we're assigning next

    i = 0
    rank = 1
    while i < len(bps_entries) and pool_idx < len(bonus_pool):
        current_bps = bps_entries[i]["bps"]
        # Find all players tied at this BPS level
        tied = [e for e in bps_entries[i:] if e["bps"] == current_bps]
        bonus_value = bonus_pool[pool_idx]

        for entry in tied:
            entry["projected_bonus"] = bonus_value
            entry["bps_rank"] = rank
            player_bonus[entry["element_id"]] = {
                "bps": entry["bps"],
                "projected_bonus": bonus_value,
                "bps_rank": rank,
            }

        # Tied players consume that many bonus slots
        # e.g., 2 tied at top → both get 3, next gets 1 (skip the 2)
        pool_idx += len(tied)
        i += len(tied)
        rank += len(tied)

    # Remaining players get 0 bonus
    while i < len(bps_entries):
        current_bps = bps_entries[i]["bps"]
        tied = [e for e in bps_entries[i:] if e["bps"] == current_bps]
        for entry in tied:
            entry["projected_bonus"] = 0
            entry["bps_rank"] = rank
            player_bonus[entry["element_id"]] = {
                "bps": entry["bps"],
                "projected_bonus": 0,
                "bps_rank": rank,
            }
        i += len(tied)
        rank += len(tied)

    return {
        "fixture_id": fixture_id,
        "rankings": bps_entries,
        "player_bonus": player_bonus,
    }


def build_bps_data(
    fixtures: list[dict],
    current_gw: int,
    live_elements: dict[int, dict],
    players_by_id: dict[int, dict],
    teams: dict[int, dict],
) -> tuple[list[dict], dict[int, dict]]:
    """Build BPS rankings for all fixtures in the current gameweek.

    Returns:
        match_bps: list of per-fixture BPS summaries (top players per match)
        all_player_bonus: dict mapping element_id → bonus projection info
    """
    # Map each team to its fixture(s) this GW
    gw_fixtures = [f for f in fixtures if f.get("event") == current_gw]

    # Map each player to their fixture based on team
    # Build: fixture_id → set of player element_ids
    fixture_players: dict[int, set[int]] = defaultdict(set)
    team_to_fixture: dict[int, int] = {}

    for fix in gw_fixtures:
        fid = fix["id"]
        team_h = fix["team_h"]
        team_a = fix["team_a"]
        team_to_fixture[team_h] = fid
        team_to_fixture[team_a] = fid

    # Assign all live players to their fixtures
    for pid, el in live_elements.items():
        p = players_by_id.get(pid, {})
        player_team = p.get("team")
        if player_team and player_team in team_to_fixture:
            fixture_players[team_to_fixture[player_team]].add(pid)

    # Calculate BPS for each fixture
    match_bps = []
    all_player_bonus: dict[int, dict] = {}

    for fix in gw_fixtures:
        fid = fix["id"]
        team_h_name = teams.get(fix["team_h"], {}).get("short_name", "?")
        team_a_name = teams.get(fix["team_a"], {}).get("short_name", "?")
        started = fix.get("started", False)
        finished = fix.get("finished", False) or fix.get("finished_provisional", False)

        if not started:
            # Match hasn't started — no BPS data yet
            match_bps.append(
                {
                    "fixture_id": fid,
                    "match": f"{team_h_name} vs {team_a_name}",
                    "status": "not_started",
                    "top_bps": [],
                }
            )
            continue

        result = _calculate_fixture_bps(
            fixture_id=fid,
            fixture_player_ids=fixture_players.get(fid, set()),
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=teams,
        )

        # Add fixture context to each player's bonus info
        for pid, info in result["player_bonus"].items():
            info["fixture_id"] = fid
            info["match"] = f"{team_h_name} vs {team_a_name}"
            # Calculate gap to bonus
            if info["projected_bonus"] == 0 and result["rankings"]:
                # Find the BPS of the last player who gets bonus
                bonus_cutoff = None
                for r in result["rankings"]:
                    if r["projected_bonus"] >= 1:
                        bonus_cutoff = r["bps"]
                if bonus_cutoff is not None:
                    info["bps_behind_bonus"] = bonus_cutoff - info["bps"]
                else:
                    info["bps_behind_bonus"] = 0
            else:
                info["bps_behind_bonus"] = 0

        all_player_bonus.update(result["player_bonus"])

        status = "finished" if finished else "live"
        match_bps.append(
            {
                "fixture_id": fid,
                "match": f"{team_h_name} vs {team_a_name}",
                "status": status,
                "top_bps": result["rankings"][:5],  # Show top 5 per match
            }
        )

    return match_bps, all_player_bonus


def _bonus_narrative(bonus_info: dict | None) -> str:
    """Generate a human-readable bonus status message for a player."""
    if not bonus_info:
        return "No BPS data available"
    bps = bonus_info.get("bps", 0)
    projected = bonus_info.get("projected_bonus", 0)
    behind = bonus_info.get("bps_behind_bonus", 0)

    if projected > 0:
        return f"On track for {projected} bonus ({bps} BPS, rank {bonus_info.get('bps_rank', '?')})"
    elif behind > 0:
        return f"{behind} BPS behind bonus ({bps} BPS, rank {bonus_info.get('bps_rank', '?')})"
    else:
        return f"Not in bonus contention ({bps} BPS)"


async def get_live_points(team_id: int) -> dict:
    bootstrap = await get_bootstrap()
    current_gw = get_current_gameweek(bootstrap)

    picks_data, live_data, history_data, event_status, fixtures = await asyncio.gather(
        get_team_picks(team_id, current_gw),
        fpl_live(current_gw),
        get_team_history(team_id),
        get_event_status(),
        get_fixtures(),
    )

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams = {t["id"]: t for t in bootstrap["teams"]}

    # Build live stats map: element_id → live stats
    live_elements = {el["id"]: el for el in live_data.get("elements", [])}

    # Build BPS rankings for all fixtures
    match_bps, all_player_bonus = build_bps_data(
        fixtures=fixtures,
        current_gw=current_gw,
        live_elements=live_elements,
        players_by_id=players_by_id,
        teams=teams,
    )

    picks = picks_data.get("picks", [])
    active_chip = picks_data.get("active_chip")

    starters = [p for p in picks if p["position"] <= 11]
    bench = [p for p in picks if p["position"] > 11]

    def live_points_for(element_id: int) -> int:
        el = live_elements.get(element_id, {})
        stats = el.get("stats", {})
        return stats.get("total_points", 0)

    def minutes_for(element_id: int) -> int:
        el = live_elements.get(element_id, {})
        stats = el.get("stats", {})
        return stats.get("minutes", 0)

    def enrich(pick: dict) -> dict:
        element_id = pick["element"]
        p = players_by_id.get(element_id, {})
        pts = live_points_for(element_id)
        multiplier = pick.get("multiplier", 1)
        bonus_info = all_player_bonus.get(element_id)

        # Check if bonus is already included in total_points.
        # FPL API: stats.bonus > 0 means bonus is confirmed and already in total_points.
        # In that case, projected_bonus should be 0 to avoid double-counting.
        el = live_elements.get(element_id, {})
        confirmed_bonus = el.get("stats", {}).get("bonus", 0)
        if confirmed_bonus > 0:
            # Bonus already in total_points — don't add projected on top
            projected_bonus = 0
            bonus_status = "confirmed"
        else:
            # Bonus not yet confirmed — use BPS projection
            projected_bonus = bonus_info["projected_bonus"] if bonus_info else 0
            bonus_status = "projected"

        return {
            "element_id": element_id,
            "name": p.get("web_name", "Unknown"),
            "team": teams.get(p.get("team"), {}).get("short_name", "?"),
            "position": POSITION_MAP.get(p.get("element_type"), "?"),
            "is_captain": pick.get("is_captain", False),
            "is_vice_captain": pick.get("is_vice_captain", False),
            "multiplier": multiplier,
            "live_points": pts,
            "contributed_points": pts * multiplier,
            "projected_bonus": projected_bonus,
            "confirmed_bonus": confirmed_bonus,
            "bonus_status": bonus_status,
            "bonus_projection": {
                "bps": bonus_info["bps"] if bonus_info else 0,
                "projected_bonus": projected_bonus,
                "bps_rank": bonus_info.get("bps_rank") if bonus_info else None,
                "bps_behind_bonus": bonus_info.get("bps_behind_bonus", 0) if bonus_info else 0,
                "match": bonus_info.get("match", "") if bonus_info else "",
                "narrative": (
                    f"Bonus confirmed: {confirmed_bonus} pts"
                    if bonus_status == "confirmed"
                    else _bonus_narrative(bonus_info)
                ),
            },
            "minutes_played": minutes_for(element_id),
            "played": minutes_for(element_id) > 0,
            "chance_of_playing": p.get("chance_of_playing_this_round"),
        }

    starter_data = [enrich(p) for p in starters]
    bench_data = [enrich(p) for p in bench]

    total_live = sum(s["contributed_points"] for s in starter_data)

    # Auto-sub detection: starters with 0 minutes → suggest bench replacement
    # FPL auto-sub rules:
    #   1. GKP can only be replaced by GKP (bench position 12)
    #   2. Outfield subs happen in bench order (positions 13, 14, 15)
    #   3. Must maintain valid formation (min 3 DEF, min 2 MID, min 1 FWD)
    auto_sub_scenarios = []
    used_bench = set()
    for starter in starter_data:
        if starter["minutes_played"] == 0:
            if starter["position"] == "GKP":
                # GKP can only sub with bench GKP (position 12)
                for bench_p in bench_data:
                    if bench_p["position"] == "GKP" and bench_p["played"] and bench_p["element_id"] not in used_bench:
                        auto_sub_scenarios.append(
                            {
                                "out": starter["name"],
                                "in": bench_p["name"],
                                "points_gained": bench_p["live_points"],
                                "note": "GKP auto-sub",
                            }
                        )
                        used_bench.add(bench_p["element_id"])
                        break
            else:
                # Outfield: use first available bench player who played (in bench order)
                for bench_p in bench_data:
                    if bench_p["position"] == "GKP":
                        continue  # GKP can't sub for outfield
                    if bench_p["played"] and bench_p["element_id"] not in used_bench:
                        auto_sub_scenarios.append(
                            {
                                "out": starter["name"],
                                "in": bench_p["name"],
                                "points_gained": bench_p["live_points"],
                                "note": "Auto-sub (bench order)",
                            }
                        )
                        used_bench.add(bench_p["element_id"])
                        break

    # GW rank estimate: compare to current average points
    gw_event = next((e for e in bootstrap["events"] if e["id"] == current_gw), {})
    avg_points = gw_event.get("average_entry_score", 50)
    highest_score = gw_event.get("highest_score")
    points_vs_avg = total_live - avg_points

    # Top scorer this GW
    top_element_id = gw_event.get("top_element")
    top_element_info = None
    if top_element_id:
        top_p = players_by_id.get(top_element_id)
        if top_p:
            top_element_info = {
                "name": top_p["web_name"],
                "team": teams.get(top_p.get("team"), {}).get("short_name", "?"),
                "points": live_points_for(top_element_id),
            }

    # Bonus points status from event-status endpoint
    bonus_confirmed = False
    status_entries = event_status.get("status", [])
    if status_entries:
        # All days must have bonus_added=True for bonus to be fully confirmed
        bonus_confirmed = all(s.get("bonus_added", False) for s in status_entries)

    # Validate squad composition
    squad_valid = len(starter_data) == 11 and len(bench_data) == 4

    return {
        "team_id": team_id,
        "gameweek": current_gw,
        "active_chip": active_chip,
        "live_total": total_live,
        "gameweek_average": avg_points,
        "highest_score": highest_score,
        "points_vs_average": round(points_vs_avg, 1),
        "rank_estimate": (
            "Above average" if points_vs_avg > 5 else "Average" if points_vs_avg >= -5 else "Below average"
        ),
        "top_scorer": top_element_info,
        "squad_valid": squad_valid,
        "num_starters": len(starter_data),
        "starters": starter_data,
        "num_bench": len(bench_data),
        "bench": bench_data,
        "auto_sub_scenarios": auto_sub_scenarios,
        "match_bps": match_bps,
        "bonus_status": "confirmed" if bonus_confirmed else "provisional",
        "note": (
            "Live points update during matches. Bonus points are confirmed."
            if bonus_confirmed
            else "Live points update during matches. Bonus points are projected and may change."
        ),
    }
