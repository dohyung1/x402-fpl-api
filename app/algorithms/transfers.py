"""
Transfer Suggestions algorithm.

Given a team's current squad, suggest transfers in/out based on:
  - Fixture swings (bringing in players with easy upcoming runs)
  - Form (sell poor-form players, buy high-form ones)
  - Price change predictions (buy before a rise)
  - Squad gaps by position
  - Budget constraints

DGW support: scores players against all their fixtures in the gameweek.
Uses NEXT gameweek by default (what managers are prepping for).
"""

import asyncio

from app.algorithms.captain import _build_fixture_map
from app.fpl_client import get_bootstrap, get_fixtures, get_next_gameweek, get_team_picks

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _player_value_score(player: dict, fixtures: list[dict] | None) -> float:
    """Score a player's transfer value: form + PPG - FDR (DGW-aware)."""
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)

    if fixtures:
        # Sum fixture contributions across all fixtures (DGW support)
        fixture_score = 0.0
        for fix in fixtures:
            fdr = fix["fdr"]
            is_home = fix.get("is_home", False)
            fixture_score += -fdr * 1.0 + (0.5 if is_home else 0)
        # DGW bonus: more fixtures = more points potential
        fixture_score += max(0, len(fixtures) - 1) * 2.0
    else:
        fixture_score = -3.0

    score = form * 2.0 + ppg * 1.0 + fixture_score
    if player.get("status") in {"i", "d", "s", "u"}:
        score -= 5
    return round(score, 2)


def _first_fixture(fixtures: list[dict] | None) -> dict | None:
    """Return the first fixture dict for backward-compat, or None."""
    if fixtures and len(fixtures) > 0:
        return fixtures[0]
    return None


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

    Uses NEXT gameweek by default (what managers are prepping for).
    """
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    next_gw = get_next_gameweek(bootstrap)

    try:
        picks_data = await get_team_picks(team_id, next_gw)
    except Exception:
        # Fall back to current GW picks if next GW picks aren't available yet
        from app.fpl_client import get_current_gameweek

        current_gw = get_current_gameweek(bootstrap)
        try:
            picks_data = await get_team_picks(team_id, current_gw)
        except Exception:
            return {"error": f"Could not fetch picks for team {team_id}. Check the team ID is correct."}

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, next_gw)

    # Current squad
    squad = []
    for pick in picks_data.get("picks", []):
        p = players_by_id.get(pick["element"])
        if not p:
            continue
        player_fixtures = fixture_map.get(p["team"])
        score = _player_value_score(p, player_fixtures)
        first_fix = _first_fixture(player_fixtures)
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
                "fixture": first_fix,
                "fixtures": player_fixtures,
            }
        )

    # Sort squad by value score ascending -- worst candidates to sell first
    squad.sort(key=lambda x: x["value_score"])
    transfer_out_candidates = squad[: min(free_transfers, len(squad))]

    # FPL selling rule: you get back selling_price, NOT current_price.
    # selling_price ≈ purchase_price + 50% of profit (rounded down).
    # Since we don't know purchase_price, we conservatively estimate
    # selling_price = current_price (user likely bought near current price).
    # The entry_history "value" field (if available) gives the actual
    # squad value including selling prices — but per-player is not exposed.

    suggestions = []
    for sell in transfer_out_candidates:
        # Use current cost as selling estimate — user will see final budget
        # in the FPL app when confirming. This is the best we can do without
        # knowing individual purchase prices.
        budget = sell["cost"] + bank_m
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
            player_fixtures = fixture_map.get(p["team"])
            score = _player_value_score(p, player_fixtures)
            if score > sell["value_score"]:
                first_fix = _first_fixture(player_fixtures)
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
                        "fixture": first_fix,
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
        "gameweek": next_gw,
        "free_transfers": free_transfers,
        "bank_balance_m": bank_m,
        "budget_note": "Budget estimates use current player prices. FPL's selling price may differ if a player's value has risen since purchase — check the FPL app for your exact budget.",
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
    fixture = player.get("fixture")
    fdr = fixture["fdr"] if fixture else 3
    if fdr >= 4:
        reasons.append("tough upcoming fixture (FDR %d)" % fdr)
    if not reasons:
        reasons.append("lowest squad value score")
    return ", ".join(reasons).capitalize()
