"""
Fixture Outlook algorithm.

Ranks teams by aggregate fixture difficulty over the next N gameweeks.
Home fixtures are weighted lighter (home_weight=0.85) as home advantage eases difficulty.
"""

from app.fpl_client import get_bootstrap, get_current_gameweek, get_fixtures

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
POSITION_NAMES = {"GKP", "DEF", "MID", "FWD"}
HOME_WEIGHT = 0.85  # Home FDR counts 85% — home advantage reduces effective difficulty


async def get_fixture_outlook(
    gameweeks_ahead: int = 5,
    position: str | None = None,
) -> dict:
    """
    Return teams ranked by upcoming fixture difficulty (easiest first)
    and the best players to target from those teams.
    """
    import asyncio

    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    current_gw = get_current_gameweek(bootstrap)

    target_gws = list(range(current_gw, current_gw + gameweeks_ahead))
    teams = {t["id"]: t for t in bootstrap["teams"]}

    # Build per-team fixture list for target GWs
    team_fixtures: dict[int, list[dict]] = {t_id: [] for t_id in teams}

    for fix in fixtures:
        if fix.get("event") not in target_gws:
            continue
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        gw = fix["event"]

        team_fixtures[home_id].append(
            {
                "gameweek": gw,
                "opponent": teams.get(away_id, {}).get("short_name", "?"),
                "venue": "H",
                "fdr": fix["team_h_difficulty"],
                "weighted_fdr": fix["team_h_difficulty"] * HOME_WEIGHT,
            }
        )
        team_fixtures[away_id].append(
            {
                "gameweek": gw,
                "opponent": teams.get(home_id, {}).get("short_name", "?"),
                "venue": "A",
                "fdr": fix["team_a_difficulty"],
                "weighted_fdr": fix["team_a_difficulty"],
            }
        )

    # Score each team
    team_scores = []
    for team_id, team_data in teams.items():
        team_fix = team_fixtures.get(team_id, [])
        if not team_fix:
            avg_wfdr = 3.0
            fixture_count = 0
        else:
            avg_wfdr = round(sum(f["weighted_fdr"] for f in team_fix) / len(team_fix), 2)
            fixture_count = len(team_fix)

        team_scores.append(
            {
                "team_id": team_id,
                "team": team_data["short_name"],
                "team_name": team_data["name"],
                "avg_difficulty": avg_wfdr,
                "fixture_count": fixture_count,
                "fixtures": sorted(team_fix, key=lambda x: x["gameweek"]),
            }
        )

    # Sort easiest first
    team_scores.sort(key=lambda x: x["avg_difficulty"])
    for i, t in enumerate(team_scores):
        t["rank"] = i + 1

    # Find best players to target from easiest teams
    position_filter: set[int] | None = None
    if position and position.upper() in POSITION_NAMES:
        pos_upper = position.upper()
        position_filter = {k for k, v in POSITION_MAP.items() if v == pos_upper}

    # Top 5 easiest teams → surface best players
    easiest_team_ids = {t["team_id"] for t in team_scores[:5]}
    players = bootstrap["elements"]

    target_players = []
    for p in players:
        if p["team"] not in easiest_team_ids:
            continue
        if position_filter and p["element_type"] not in position_filter:
            continue
        if p.get("status") in {"i", "u"}:
            continue
        target_players.append(p)

    target_players.sort(key=lambda p: float(p.get("form") or 0), reverse=True)

    players_to_target = [
        {
            "name": p["web_name"],
            "team": teams.get(p["team"], {}).get("short_name", "?"),
            "position": POSITION_MAP.get(p["element_type"], "?"),
            "cost": p["now_cost"] / 10,
            "form": float(p.get("form") or 0),
            "points_per_game": float(p.get("points_per_game") or 0),
            "selected_by_pct": float(p.get("selected_by_percent") or 0),
        }
        for p in target_players[:10]
    ]

    return {
        "current_gameweek": current_gw,
        "gameweeks_ahead": gameweeks_ahead,
        "target_gameweeks": target_gws,
        "position_filter": position.upper() if position else None,
        "teams_by_difficulty": team_scores,
        "players_to_target": players_to_target,
    }
