"""
Squad Scout algorithm.

Uses FPL's own predictive data that most managers don't know about:
  - ep_next: FPL's expected points for next GW
  - ep_this: FPL's expected points for current GW
  - scout_risks: blank GW flags, injury alerts from FPL's own scout
  - value_form / value_season: FPL's value metrics
  - dreamteam_count: consistency measure
  - set piece duties: corners, direct free kicks
  - ICT breakdown: creativity, influence, threat individually

Surfaces hidden gems and risks that other tools miss.
"""

import asyncio

from app.algorithms import INJURY_STATUSES, POSITION_MAP
from app.algorithms.news import get_player_news, has_negative_news
from app.fpl_client import (
    get_bootstrap,
    get_current_gameweek,
    get_fixtures,
    get_next_gameweek,
    get_team_picks,
)

# Premier League yellow card suspension thresholds.
# Format: (card_count, before_gw, ban_length)
#   - 5 yellows before GW19 = 1-match ban
#   - 10 yellows before GW32 = 2-match ban
#   - 15 yellows (any time) = 3-match ban
_YELLOW_THRESHOLDS = [
    (5, 19, 1),
    (10, 32, 2),
    (15, None, 3),
]


def _get_suspension_risk(yellow_cards: int, red_cards: int, next_gw: int) -> dict:
    """Calculate suspension risk for a player based on card accumulation."""
    # Find the next applicable threshold
    next_threshold = None
    ban_length = None
    for threshold, before_gw, ban_len in _YELLOW_THRESHOLDS:
        if yellow_cards < threshold and (before_gw is None or next_gw < before_gw):
            next_threshold = threshold
            ban_length = ban_len
            break

    if next_threshold is None:
        return {
            "yellow_cards": yellow_cards,
            "red_cards": red_cards,
            "next_threshold": None,
            "cards_until_ban": None,
            "risk_level": "low",
            "note": None,
        }

    cards_until = next_threshold - yellow_cards
    if cards_until <= 1:
        risk_level = "high"
    elif cards_until <= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    note_parts = []
    if cards_until <= 2:
        note_parts.append(
            f"{cards_until} yellow card{'s' if cards_until != 1 else ''} away from {ban_length}-match ban"
        )
    if red_cards > 0:
        note_parts.append(f"{red_cards} red card{'s' if red_cards != 1 else ''} this season")

    return {
        "yellow_cards": yellow_cards,
        "red_cards": red_cards,
        "next_threshold": next_threshold,
        "cards_until_ban": cards_until,
        "risk_level": risk_level,
        "note": ". ".join(note_parts) if note_parts else None,
    }


def _ordinal(n: int) -> str:
    """Return ordinal string for set piece order (1 -> '1st', 2 -> '2nd', etc.)."""
    if n == 1:
        return "1st"
    if n == 2:
        return "2nd"
    if n == 3:
        return "3rd"
    return f"{n}th"


async def get_squad_scout(team_id: int) -> dict:
    """
    Deep scout report on a manager's squad using FPL's hidden data fields.

    Surfaces:
      - Blank GW warnings from FPL's own scout_risks
      - FPL's expected points (ep_next) vs your current captain
      - Set piece takers you might not know about
      - Most consistent performers (dreamteam appearances)
      - Value picks (points per million this season)
      - ICT breakdown showing who creates vs who finishes
      - Squad risks: yellow card suspensions, fixture congestion
    """
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    current_gw = get_current_gameweek(bootstrap)
    next_gw = get_next_gameweek(bootstrap)

    try:
        picks_data = await get_team_picks(team_id, current_gw)
    except Exception:
        return {"error": f"Could not fetch picks for team {team_id}. Check the team ID is correct."}

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}

    # Analyse each squad player
    squad_report = []
    blank_warnings = []
    set_piece_takers = []
    yellow_card_risks = []
    best_ep_next = []

    for pick in picks_data.get("picks", []):
        p = players_by_id.get(pick["element"])
        if not p:
            continue

        team = teams_by_id.get(p["team"], {})
        ep_next = float(p.get("ep_next") or 0)
        ep_this = float(p.get("ep_this") or 0)
        is_starter = pick["position"] <= 11

        player_info = {
            "name": p["web_name"],
            "team": team.get("short_name", "?"),
            "position": POSITION_MAP.get(p["element_type"], "?"),
            "starter": is_starter,
            "slot": pick["position"],
            "is_captain": pick.get("is_captain", False),
        }

        # FPL expected points
        player_info["ep_next"] = ep_next
        player_info["ep_this"] = ep_this

        # Scout risks (blank GW, injury flags from FPL)
        risks = p.get("scout_risks") or []
        if risks:
            risk_notes = [r.get("notes", "") for r in risks]
            player_info["scout_risks"] = risk_notes
            if is_starter:
                for r in risks:
                    if "blank" in r.get("property", "").lower() or "no" in r.get("notes", "").lower():
                        blank_warnings.append(
                            {
                                "name": p["web_name"],
                                "team": team.get("short_name", "?"),
                                "note": r.get("notes", ""),
                                "gameweek": r.get("gameweek"),
                            }
                        )

        # Set piece duties — per-player detail
        corners_order = p.get("corners_and_indirect_freekicks_order")
        fk_order = p.get("direct_freekicks_order")
        penalties_order = p.get("penalties_order")
        is_set_piece_taker = any(v is not None for v in (corners_order, fk_order, penalties_order))

        # Build human-readable summary parts
        sp_parts = []
        if corners_order is not None:
            sp_parts.append(f"Corners ({_ordinal(corners_order)})")
        if fk_order is not None:
            sp_parts.append(f"Direct FKs ({_ordinal(fk_order)})")
        if penalties_order is not None:
            sp_parts.append(f"Penalties ({_ordinal(penalties_order)})")

        player_info["set_pieces"] = {
            "corners": corners_order,
            "direct_free_kicks": fk_order,
            "penalties": penalties_order,
            "is_set_piece_taker": is_set_piece_taker,
            "summary": ", ".join(sp_parts) if sp_parts else None,
        }

        if is_set_piece_taker:
            set_piece_takers.append(
                {
                    "name": p["web_name"],
                    "team": team.get("short_name", "?"),
                    "duties": sp_parts,
                    "corners": corners_order,
                    "direct_free_kicks": fk_order,
                    "penalties": penalties_order,
                    "starter": is_starter,
                }
            )

        # Suspension risk from card accumulation
        suspension = _get_suspension_risk(
            yellow_cards=p.get("yellow_cards", 0),
            red_cards=p.get("red_cards", 0),
            next_gw=next_gw,
        )
        player_info["suspension_risk"] = suspension
        if suspension["risk_level"] == "high":
            yellow_card_risks.append(
                {
                    "name": p["web_name"],
                    "team": team.get("short_name", "?"),
                    "yellow_cards": suspension["yellow_cards"],
                    "red_cards": suspension["red_cards"],
                    "next_threshold": suspension["next_threshold"],
                    "cards_until_ban": suspension["cards_until_ban"],
                    "note": suspension["note"],
                }
            )

        # ICT breakdown
        player_info["ict"] = {
            "influence": float(p.get("influence") or 0),
            "creativity": float(p.get("creativity") or 0),
            "threat": float(p.get("threat") or 0),
            "influence_rank": p.get("influence_rank"),
            "creativity_rank": p.get("creativity_rank"),
            "threat_rank": p.get("threat_rank"),
        }

        # Value and consistency
        player_info["value_season"] = float(p.get("value_season") or 0)
        player_info["value_form"] = float(p.get("value_form") or 0)
        player_info["dreamteam_count"] = p.get("dreamteam_count", 0)
        player_info["cost"] = p["now_cost"] / 10
        player_info["total_points"] = p.get("total_points", 0)
        player_info["points_per_million"] = (
            round(p.get("total_points", 0) / (p["now_cost"] / 10), 1) if p["now_cost"] > 0 else 0
        )

        # Defensive stats (for DEF/GKP)
        if p["element_type"] in (1, 2):
            player_info["clean_sheets"] = p.get("clean_sheets", 0)
            player_info["clean_sheets_per_90"] = float(p.get("clean_sheets_per_90") or 0)
            player_info["xGC_per_90"] = float(p.get("expected_goals_conceded_per_90") or 0)

        # BPS raw score
        player_info["bps"] = p.get("bps", 0)

        # News/injury information
        news_info = get_player_news(p)
        if news_info:
            player_info["news"] = news_info
            if has_negative_news(p) and is_starter:
                player_info["news_risk"] = True

        best_ep_next.append((ep_next, player_info))
        squad_report.append(player_info)

    # Sort by ep_next to find best captain option
    best_ep_next.sort(key=lambda x: x[0], reverse=True)

    # Find the current captain
    current_captain = next((p for p in squad_report if p.get("is_captain")), None)

    # Captain suggestion based on FPL's own ep_next
    ep_captain_suggestion = None
    if best_ep_next and current_captain:
        best = best_ep_next[0][1]
        if best["name"] != current_captain["name"] and best_ep_next[0][0] > (current_captain.get("ep_next") or 0):
            ep_captain_suggestion = {
                "current_captain": current_captain["name"],
                "current_captain_ep": current_captain.get("ep_next", 0),
                "suggested_captain": best["name"],
                "suggested_captain_ep": best_ep_next[0][0],
                "ep_difference": round(best_ep_next[0][0] - (current_captain.get("ep_next") or 0), 1),
            }

    # Find set piece takers NOT in squad (transfer targets)
    squad_ids = {pick["element"] for pick in picks_data.get("picks", [])}
    external_set_piece = []
    for p in bootstrap["elements"]:
        if p["id"] in squad_ids:
            continue
        if p.get("status") in INJURY_STATUSES:
            continue
        penalties = p.get("penalties_order")
        corners = p.get("corners_and_indirect_freekicks_order")
        fk = p.get("direct_freekicks_order")
        if penalties == 1 or (corners == 1 and fk == 1):
            team = teams_by_id.get(p["team"], {})
            duties = []
            if penalties == 1:
                duties.append("penalties")
            if corners == 1:
                duties.append("corners")
            if fk == 1:
                duties.append("direct free kicks")
            ep = float(p.get("ep_next") or 0)
            if ep >= 3.0:  # only show high-EP targets
                external_set_piece.append(
                    {
                        "name": p["web_name"],
                        "team": team.get("short_name", "?"),
                        "position": POSITION_MAP.get(p["element_type"], "?"),
                        "cost": p["now_cost"] / 10,
                        "ep_next": ep,
                        "duties": duties,
                        "ownership": float(p.get("selected_by_percent") or 0),
                    }
                )

    external_set_piece.sort(key=lambda x: x["ep_next"], reverse=True)

    return {
        "team_id": team_id,
        "gameweek": current_gw,
        "next_gameweek": next_gw,
        "squad_report": squad_report,
        "suspension_warnings": yellow_card_risks,
        "insights": {
            "blank_gw_warnings": blank_warnings,
            "ep_captain_suggestion": ep_captain_suggestion,
            "ep_rankings": [
                {"name": p["name"], "team": p["team"], "ep_next": ep, "starter": p["starter"]}
                for ep, p in best_ep_next[:5]
            ],
            "set_piece_takers_in_squad": set_piece_takers,
            "set_piece_targets_outside_squad": external_set_piece[:5],
            "yellow_card_risks": yellow_card_risks,
        },
        "summary": _build_summary(
            blank_warnings, ep_captain_suggestion, set_piece_takers, yellow_card_risks, best_ep_next
        ),
    }


def _build_summary(blanks, ep_captain, set_pieces, yellows, ep_rankings) -> str:
    """Build a human-readable summary of key findings."""
    parts = []

    if blanks:
        names = ", ".join(b["name"] for b in blanks)
        parts.append(f"Blank GW alert: {names} have no fixture")

    if ep_captain:
        parts.append(
            f"FPL's data suggests {ep_captain['suggested_captain']} "
            f"(EP {ep_captain['suggested_captain_ep']}) over "
            f"{ep_captain['current_captain']} "
            f"(EP {ep_captain['current_captain_ep']}) as captain"
        )

    if yellows:
        names = ", ".join(f"{y['name']} ({y['yellow_cards']} YC, {y['cards_until_ban']} from ban)" for y in yellows)
        parts.append(f"Suspension risk: {names}")

    if not parts:
        parts.append("No major risks detected. Squad looks healthy.")

    return ". ".join(parts) + "."
