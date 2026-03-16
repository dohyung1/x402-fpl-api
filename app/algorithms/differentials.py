"""
Differential Finder algorithm.

Finds underowned players outperforming their ownership %.

differential_score =
    recent_form × 3.0
  + points_per_game × 1.0
  - fixture_difficulty × 0.5
  + ict_index × 0.01
  - ownership_pct × 0.1    (penalise highly owned — we want the differentials)
"""

from app.fpl_client import get_bootstrap, get_current_gameweek, get_fixtures
from app.algorithms.captain import _build_fixture_map

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _differential_score(player: dict, fixture: dict | None, ownership_pct: float) -> float:
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)
    ict = float(player.get("ict_index") or 0)
    fdr = fixture["fdr"] if fixture else 3

    score = (
        form * 3.0
        + ppg * 1.0
        - fdr * 0.5
        + ict * 0.01
        - ownership_pct * 0.1
    )
    return round(score, 3)


async def get_differentials(
    max_ownership_pct: float = 10.0,
    gameweek: int | None = None,
    top_n: int = 10,
) -> dict:
    """
    Return underowned players outperforming their ownership %.

    max_ownership_pct: only include players selected by fewer than this %.
    """
    import asyncio
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())

    if gameweek is None:
        gameweek = get_current_gameweek(bootstrap)

    teams = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, gameweek)

    scored = []
    for player in bootstrap["elements"]:
        ownership = float(player.get("selected_by_percent") or 0)
        if ownership > max_ownership_pct:
            continue
        if player.get("status") in {"i", "u"}:  # skip injured/unavailable
            continue

        fixture = fixture_map.get(player["team"])
        score = _differential_score(player, fixture, ownership)
        scored.append((score, player, fixture))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, player, fixture in scored[:top_n]:
        team = teams.get(player["team"], {})
        opponent_id = fixture["opponent"] if fixture else None
        opponent = teams.get(opponent_id, {}).get("short_name", "?") if opponent_id else "?"

        results.append(
            {
                "rank": len(results) + 1,
                "player": {
                    "id": player["id"],
                    "name": player["web_name"],
                    "team": team.get("short_name", "?"),
                    "position": POSITION_MAP.get(player["element_type"], "?"),
                    "cost": player["now_cost"] / 10,
                    "selected_by_pct": float(player.get("selected_by_percent") or 0),
                },
                "fixture": {
                    "opponent": opponent,
                    "venue": "Home" if (fixture and fixture["is_home"]) else "Away",
                    "fdr": fixture["fdr"] if fixture else None,
                    "gameweek": gameweek,
                }
                if fixture
                else None,
                "score": score,
                "stats": {
                    "form": float(player.get("form") or 0),
                    "points_per_game": float(player.get("points_per_game") or 0),
                    "ict_index": float(player.get("ict_index") or 0),
                    "total_points": player.get("total_points", 0),
                },
                "why": (
                    f"Only {player.get('selected_by_percent', 0)}% owned, "
                    f"form {player.get('form', 0)}, PPG {player.get('points_per_game', 0)}"
                ),
            }
        )

    return {
        "gameweek": gameweek,
        "max_ownership_pct": max_ownership_pct,
        "algorithm_version": "1.0",
        "differentials": results,
    }
