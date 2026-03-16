"""
Transfer Suggestions algorithm.

Given a team's current squad, suggest transfers in/out based on:
  - Fixture swings (bringing in players with easy upcoming runs)
  - Form (sell poor-form players, buy high-form ones)
  - Price change predictions (buy before a rise)
  - Squad gaps by position
  - Budget constraints
"""

import asyncio

from app.fpl_client import get_bootstrap, get_current_gameweek, get_fixtures, get_team_picks
from app.algorithms.captain import _build_fixture_map

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _player_value_score(player: dict, fixture: dict | None) -> float:
    """Score a player's transfer value: form + PPG - FDR."""
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)
    fdr = fixture["fdr"] if fixture else 3
    is_home = fixture.get("is_home", False) if fixture else False

    score = form * 2.0 + ppg * 1.0 - fdr * 1.0 + (0.5 if is_home else 0)
    if player.get("status") in {"i", "d", "s", "u"}:
        score -= 5
    return round(score, 2)


async def get_transfer_suggestions(
    team_id: int,
    free_transfers: int = 1,
    bank_m: float = 0.0,
) -> dict:
    """
    Return transfer suggestions for the given FPL team.

    team_id: FPL manager's team ID
    free_transfers: how many free transfers available (1 or 2)
    bank_m: bank balance in millions (e.g. 1.5)
    """
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    current_gw = get_current_gameweek(bootstrap)

    try:
        picks_data = await get_team_picks(team_id, current_gw)
    except Exception:
        return {"error": f"Could not fetch picks for team {team_id}. Check the team ID is correct."}

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, current_gw)

    # Current squad
    squad = []
    for pick in picks_data.get("picks", []):
        p = players_by_id.get(pick["element"])
        if not p:
            continue
        fixture = fixture_map.get(p["team"])
        score = _player_value_score(p, fixture)
        squad.append(
            {
                "id": p["id"],
                "name": p["web_name"],
                "team": teams.get(p["team"], {}).get("short_name", "?"),
                "position_type": p["element_type"],
                "position": POSITION_MAP.get(p["element_type"], "?"),
                "cost": p["now_cost"] / 10,
                "form": float(p.get("form") or 0),
                "ppg": float(p.get("points_per_game") or 0),
                "status": p.get("status", "a"),
                "value_score": score,
                "fixture": fixture,
            }
        )

    # Sort squad by value score ascending — worst candidates to sell first
    squad.sort(key=lambda x: x["value_score"])
    transfer_out_candidates = squad[: min(free_transfers, len(squad))]

    suggestions = []
    for sell in transfer_out_candidates:
        budget = sell["cost"] + bank_m  # how much we can spend
        pos_type = sell["position_type"]

        # Find best replacements: same position, affordable, better value
        replacements = []
        for p in bootstrap["elements"]:
            if p["id"] == sell["id"]:
                continue
            if p["element_type"] != pos_type:
                continue
            if p["now_cost"] / 10 > budget:
                continue
            if p.get("status") in {"i", "u"}:
                continue
            # Don't suggest players already in squad
            if p["id"] in {s["id"] for s in squad}:
                continue
            fixture = fixture_map.get(p["team"])
            score = _player_value_score(p, fixture)
            if score > sell["value_score"]:
                replacements.append(
                    {
                        "id": p["id"],
                        "name": p["web_name"],
                        "team": teams.get(p["team"], {}).get("short_name", "?"),
                        "position": POSITION_MAP.get(p["element_type"], "?"),
                        "cost": p["now_cost"] / 10,
                        "form": float(p.get("form") or 0),
                        "ppg": float(p.get("points_per_game") or 0),
                        "value_score": score,
                        "fixture": fixture,
                    }
                )

        replacements.sort(key=lambda x: x["value_score"], reverse=True)

        suggestions.append(
            {
                "transfer_out": {
                    "id": sell["id"],
                    "name": sell["name"],
                    "team": sell["team"],
                    "position": sell["position"],
                    "cost": sell["cost"],
                    "form": sell["form"],
                    "value_score": sell["value_score"],
                    "reasoning": _sell_reason(sell),
                },
                "transfer_in_options": replacements[:5],
                "budget_available": round(budget, 1),
            }
        )

    return {
        "team_id": team_id,
        "gameweek": current_gw,
        "free_transfers": free_transfers,
        "bank_balance_m": bank_m,
        "transfer_suggestions": suggestions,
        "squad_overview": [
            {
                "name": s["name"],
                "team": s["team"],
                "position": s["position"],
                "form": s["form"],
                "value_score": s["value_score"],
            }
            for s in squad
        ],
    }


def _sell_reason(player: dict) -> str:
    reasons = []
    if player["form"] <= 2.0:
        reasons.append("poor form")
    if player["status"] in {"d", "i", "s"}:
        reasons.append("injury/suspension concern")
    fdr = player["fixture"]["fdr"] if player["fixture"] else 3
    if fdr >= 4:
        reasons.append("tough upcoming fixture (FDR %d)" % fdr)
    if not reasons:
        reasons.append("lowest squad value score")
    return ", ".join(reasons).capitalize()
