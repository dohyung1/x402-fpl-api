"""
Differential Finder algorithm.

Finds underowned players outperforming their ownership %.

differential_score =
    recent_form * 3.0
  + points_per_game * 1.0
  - fixture_difficulty * 0.5
  + ict_index * 0.01
  - ownership_pct * 0.1    (penalise highly owned -- we want the differentials)

DGW support: fixture difficulty is the average across all fixtures in the GW.
"""

from app.algorithms import INJURY_STATUSES, POSITION_MAP
from app.algorithms.captain import _build_fixture_map
from app.fpl_client import get_bootstrap, get_fixtures, get_next_gameweek


def _differential_score(player: dict, fixtures: list[dict] | None, ownership_pct: float) -> float:
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)
    ict = float(player.get("ict_index") or 0)

    # Average FDR across all fixtures (DGW support)
    if fixtures:
        avg_fdr = sum(f["fdr"] for f in fixtures) / len(fixtures)
    else:
        avg_fdr = 3

    score = form * 3.0 + ppg * 1.0 - avg_fdr * 0.5 + ict * 0.01 - ownership_pct * 0.1

    # DGW bonus: more fixtures = more points potential
    if fixtures and len(fixtures) > 1:
        score += len(fixtures) * 1.0

    return round(score, 3)


def _build_why(player: dict, fixtures: list[dict] | None) -> str:
    """Build a context-rich explanation for why this differential matters NOW."""
    parts = []
    ownership = player.get("selected_by_percent", 0)
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)

    # Ownership context
    if float(ownership) < 2:
        parts.append(f"only {ownership}% owned — massive differential")
    elif float(ownership) < 5:
        parts.append(f"just {ownership}% owned")
    else:
        parts.append(f"{ownership}% owned")

    # Form context
    if form >= 7:
        parts.append(f"red-hot form ({form})")
    elif form >= 5:
        parts.append(f"strong form ({form})")

    # Fixture context (why THIS gameweek)
    if fixtures:
        avg_fdr = sum(f["fdr"] for f in fixtures) / len(fixtures)
        if len(fixtures) > 1:
            parts.append(f"double gameweek ({len(fixtures)} fixtures)")
        elif avg_fdr <= 2:
            parts.append("easy fixture ahead")
        if all(f.get("is_home") for f in fixtures):
            parts.append("playing at home")

    # Value context
    if ppg >= 5 and float(ownership) < 5:
        parts.append(f"PPG {ppg} massively underowned for output")

    # Set piece duties
    if player.get("corners_and_indirect_freekicks_order") == 1:
        parts.append("on set pieces")
    if player.get("penalties_order") == 1:
        parts.append("on penalties")

    return ". ".join(parts).capitalize() if parts else f"{ownership}% owned, form {form}"


async def get_differentials(
    max_ownership_pct: float = 10.0,
    gameweek: int | None = None,
    top_n: int = 10,
) -> dict:
    """
    Return underowned players outperforming their ownership %.

    max_ownership_pct: only include players selected by fewer than this %.
    Uses the next gameweek by default (what managers are prepping for).
    """
    import asyncio

    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())

    if gameweek is None:
        gameweek = get_next_gameweek(bootstrap)

    teams = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, gameweek, teams_by_id=teams)

    scored = []
    for player in bootstrap["elements"]:
        ownership = float(player.get("selected_by_percent") or 0)
        if ownership > max_ownership_pct:
            continue
        if player.get("status") in INJURY_STATUSES:
            continue

        player_fixtures = fixture_map.get(player["team"])
        if not player_fixtures:
            continue  # skip players with no fixture this GW (blank gameweek)
        score = _differential_score(player, player_fixtures, ownership)
        scored.append((score, player, player_fixtures))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, player, player_fixtures in scored[:top_n]:
        team = teams.get(player["team"], {})

        # Build fixture info supporting DGWs
        fixture_info = None
        if player_fixtures:
            fixture_entries = []
            for fix in player_fixtures:
                opponent_id = fix["opponent"]
                opponent = teams.get(opponent_id, {}).get("short_name", "?")
                fixture_entries.append(
                    {
                        "opponent": opponent,
                        "venue": "Home" if fix["is_home"] else "Away",
                        "fdr": fix["fdr"],
                    }
                )
            fixture_info = {
                "fixtures": fixture_entries,
                "gameweek": gameweek,
                "is_dgw": len(fixture_entries) > 1,
                "opponent": fixture_entries[0]["opponent"],
                "venue": fixture_entries[0]["venue"],
                "fdr": fixture_entries[0]["fdr"],
            }

        results.append(
            {
                "rank": len(results) + 1,
                "player": {
                    "id": player["id"],
                    "name": player["web_name"],
                    "team": team.get("short_name", "?"),
                    "team_full_name": team.get("name", "?"),
                    "position": POSITION_MAP.get(player["element_type"], "?"),
                    "cost": player["now_cost"] / 10,
                    "selected_by_pct": float(player.get("selected_by_percent") or 0),
                },
                "fixture": fixture_info,
                "score": score,
                "stats": {
                    "form": float(player.get("form") or 0),
                    "points_per_game": float(player.get("points_per_game") or 0),
                    "ict_index": float(player.get("ict_index") or 0),
                    "total_points": player.get("total_points", 0),
                },
                "why": _build_why(player, player_fixtures),
            }
        )

    return {
        "gameweek": gameweek,
        "max_ownership_pct": max_ownership_pct,
        "algorithm_version": "1.1",
        "differentials": results,
    }
