"""
Live Points algorithm.

Returns a team's live score during an active gameweek:
  - Current live points for each player
  - Projected bonus points
  - Auto-sub scenarios
  - Rough rank estimate (based on live points vs average)
"""

import asyncio

from app.fpl_client import (
    get_bootstrap,
    get_current_gameweek,
    get_live_points as fpl_live,
    get_team_picks,
    get_team_history,
)

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


async def get_live_points(team_id: int) -> dict:
    bootstrap = await get_bootstrap()
    current_gw = get_current_gameweek(bootstrap)

    picks_data, live_data, history_data = await asyncio.gather(
        get_team_picks(team_id, current_gw),
        fpl_live(current_gw),
        get_team_history(team_id),
    )

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams = {t["id"]: t for t in bootstrap["teams"]}

    # Build live stats map: element_id → live stats
    live_elements = {el["id"]: el for el in live_data.get("elements", [])}

    picks = picks_data.get("picks", [])
    active_chip = picks_data.get("active_chip")

    starters = [p for p in picks if p["position"] <= 11]
    bench = [p for p in picks if p["position"] > 11]

    def live_points_for(element_id: int) -> int:
        el = live_elements.get(element_id, {})
        stats = el.get("stats", {})
        return stats.get("total_points", 0)

    def bonus_for(element_id: int) -> int:
        el = live_elements.get(element_id, {})
        stats = el.get("stats", {})
        return stats.get("bonus", 0)

    def minutes_for(element_id: int) -> int:
        el = live_elements.get(element_id, {})
        stats = el.get("stats", {})
        return stats.get("minutes", 0)

    def enrich(pick: dict) -> dict:
        element_id = pick["element"]
        p = players_by_id.get(element_id, {})
        pts = live_points_for(element_id)
        multiplier = pick.get("multiplier", 1)
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
            "projected_bonus": bonus_for(element_id),
            "minutes_played": minutes_for(element_id),
            "played": minutes_for(element_id) > 0,
        }

    starter_data = [enrich(p) for p in starters]
    bench_data = [enrich(p) for p in bench]

    total_live = sum(s["contributed_points"] for s in starter_data)

    # Auto-sub detection: starters with 0 minutes → suggest bench replacement
    auto_sub_scenarios = []
    bench_players = list(bench_data)
    for starter in starter_data:
        if starter["minutes_played"] == 0 and starter["played"] is False:
            # Find eligible bench player (same position or flexible sub)
            for bench_p in bench_players:
                if bench_p["played"]:
                    auto_sub_scenarios.append(
                        {
                            "out": starter["name"],
                            "in": bench_p["name"],
                            "points_gained": bench_p["live_points"] - starter["live_points"],
                            "note": "Auto-sub if starter didn't play",
                        }
                    )
                    break

    # GW rank estimate: compare to current average points
    gw_event = next(
        (e for e in bootstrap["events"] if e["id"] == current_gw), {}
    )
    avg_points = gw_event.get("average_entry_score", 50)
    points_vs_avg = total_live - avg_points

    return {
        "team_id": team_id,
        "gameweek": current_gw,
        "active_chip": active_chip,
        "live_total": total_live,
        "gameweek_average": avg_points,
        "points_vs_average": round(points_vs_avg, 1),
        "rank_estimate": (
            "Above average" if points_vs_avg > 5
            else "Average" if points_vs_avg >= -5
            else "Below average"
        ),
        "starters": starter_data,
        "bench": bench_data,
        "auto_sub_scenarios": auto_sub_scenarios,
        "note": "Live points update during matches. Bonus points are projected and may change.",
    }
