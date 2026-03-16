"""
x402 FPL Intelligence -- MCP Server

Exposes all FPL intelligence endpoints as MCP tools that Claude,
Cursor, Windsurf, and any MCP-compatible agent can call directly.

No payment required through MCP (free tier).
Agents get the same intelligence as the paid HTTP API.

Usage:
  # Run directly
  uv run mcp_server.py

  # Or add to Claude Desktop config:
  # {
  #   "mcpServers": {
  #     "fpl": {
  #       "command": "uv",
  #       "args": ["run", "--directory", "/path/to/x402-fpl-api", "mcp_server.py"]
  #     }
  #   }
  # }
"""

import asyncio

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("FPL Intelligence")


@mcp.tool()
async def captain_pick(gameweek: int | None = None) -> dict:
    """
    Get top 5 captain recommendations for a given FPL gameweek.

    Each pick is scored by xG/90, xA/90, form, points per game, home advantage,
    fixture difficulty, ICT index, bonus rate, penalty duties, and minutes certainty.
    Includes human-readable reasoning for each recommendation.

    Args:
        gameweek: Gameweek number (1-38). Defaults to next gameweek if not specified.
    """
    from app.algorithms.captain import get_captain_picks

    return await get_captain_picks(gameweek=gameweek)


@mcp.tool()
async def differential_finder(
    max_ownership_pct: float = 10.0,
    gameweek: int | None = None,
) -> dict:
    """
    Find underowned FPL players who are outperforming their ownership percentage.

    Great for gaining competitive edge -- surfaces players that most managers
    don't have but are delivering strong returns.

    Args:
        max_ownership_pct: Only include players owned by fewer than this percentage. Default 10%.
        gameweek: Gameweek number (1-38). Defaults to next gameweek if not specified.
    """
    from app.algorithms.differentials import get_differentials

    return await get_differentials(max_ownership_pct=max_ownership_pct, gameweek=gameweek)


@mcp.tool()
async def fixture_outlook(
    gameweeks_ahead: int = 5,
    position: str | None = None,
) -> dict:
    """
    Rank all 20 Premier League teams by upcoming fixture difficulty.

    Shows which teams have the easiest run of games coming up,
    and surfaces the best players to target from those teams.
    Essential for planning transfers 4-6 weeks ahead.

    Args:
        gameweeks_ahead: How many gameweeks to look ahead (1-10). Default 5.
        position: Filter players by position: GKP, DEF, MID, or FWD. Optional.
    """
    from app.algorithms.fixtures import get_fixture_outlook

    return await get_fixture_outlook(gameweeks_ahead=gameweeks_ahead, position=position)


@mcp.tool()
async def price_predictions() -> dict:
    """
    Predict which FPL players are likely to rise or fall in price tonight.

    Based on net transfer volume trends. Buy before a rise to gain free
    team value. Sell before a fall to avoid losing value.
    Price changes happen overnight based on transfer activity.
    """
    from app.algorithms.prices import get_price_predictions

    return await get_price_predictions()


@mcp.tool()
async def transfer_suggestions(
    team_id: int,
    free_transfers: int = 1,
    bank: float = 0.0,
) -> dict:
    """
    Get transfer recommendations for a specific FPL team.

    Analyzes the current squad, identifies the weakest players based on
    form and fixtures, and suggests replacements within budget.

    Args:
        team_id: Your FPL team ID (find it in the URL when you view your team on the FPL website).
        free_transfers: Number of free transfers available (1 or 2). Default 1.
        bank: Money in the bank in millions (e.g. 1.5 means 1.5m). Default 0.0.
    """
    from app.algorithms.transfers import get_transfer_suggestions

    return await get_transfer_suggestions(
        team_id=team_id,
        free_transfers=free_transfers,
        bank_m=bank,
    )


@mcp.tool()
async def live_points(team_id: int) -> dict:
    """
    Get live points for a specific FPL team during an active gameweek.

    Shows each player's live score, projected bonus points,
    auto-sub scenarios if a starter didn't play, and how
    the team compares to the gameweek average.

    Args:
        team_id: Your FPL team ID (find it in the URL when you view your team on the FPL website).
    """
    from app.algorithms.live import get_live_points

    return await get_live_points(team_id=team_id)


@mcp.tool()
async def fpl_manager_hub(
    team_id: int,
    gameweeks_ahead: int = 5,
) -> dict:
    """
    Complete FPL intelligence report for a manager's team.

    Given an FPL team ID, this tool automatically detects the manager's
    bank balance, free transfers, chips used, and current squad -- then runs
    every analysis: captain pick, transfer suggestions, fixture outlook,
    differentials to target, price change risks, and squad health check.

    The user does NOT need to provide bank balance or free transfers --
    everything is auto-detected from the FPL API.

    The team ID is the number in the FPL URL:
    https://fantasy.premierleague.com/entry/<TEAM_ID>/event/30

    Args:
        team_id: FPL team ID from the manager's FPL URL.
        gameweeks_ahead: How many gameweeks to look ahead for fixture analysis (1-10). Default 5.
    """
    from app.fpl_client import (
        get_bootstrap, get_fixtures, get_current_gameweek,
        get_next_gameweek, get_team_picks, get_team_history,
        get_manager_status,
    )
    from app.algorithms.captain import get_captain_picks
    from app.algorithms.transfers import get_transfer_suggestions
    from app.algorithms.differentials import get_differentials
    from app.algorithms.fixtures import get_fixture_outlook
    from app.algorithms.prices import get_price_predictions

    # Fetch base data to get manager status
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    current_gw = get_current_gameweek(bootstrap)
    next_gw = get_next_gameweek(bootstrap)

    # Auto-detect manager status + fetch picks and history in parallel
    manager_status, picks_data, history_data = await asyncio.gather(
        get_manager_status(team_id, bootstrap),
        get_team_picks(team_id, current_gw),
        get_team_history(team_id),
    )

    bank = manager_status["bank"]
    free_transfers = manager_status["free_transfers"]

    # Run all algorithm functions in parallel -- reuse existing code, no duplication
    captain_result, transfer_result, diff_result, fixture_result, price_result = await asyncio.gather(
        get_captain_picks(gameweek=next_gw),
        get_transfer_suggestions(
            team_id=team_id,
            free_transfers=free_transfers,
            bank_m=bank,
        ),
        get_differentials(gameweek=next_gw),
        get_fixture_outlook(gameweeks_ahead=gameweeks_ahead),
        get_price_predictions(),
    )

    # Build squad overview using element IDs (Fix 8: no web_name collisions)
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    from app.algorithms.captain import POSITION_MAP, INJURY_STATUSES, _build_fixture_map, _score_player

    fixture_map = _build_fixture_map(fixtures, next_gw)

    squad = []
    squad_ids = set()
    total_value = 0.0

    for pick in picks_data.get("picks", []):
        element_id = pick["element"]  # Fix 8: use element ID directly
        p = players_by_id.get(element_id)
        if not p:
            continue
        squad_ids.add(element_id)
        team = teams_by_id.get(p["team"], {})
        player_fixtures = fixture_map.get(p["team"])
        captain_score = _score_player(p, player_fixtures)
        cost = p["now_cost"] / 10
        total_value += cost

        # Build opponent string from fixtures (DGW-aware)
        if player_fixtures:
            opponents = []
            for fix in player_fixtures:
                opp = teams_by_id.get(fix["opponent"], {}).get("short_name", "?")
                venue = "H" if fix["is_home"] else "A"
                opponents.append(f"{opp}({venue})")
            opponent_str = ", ".join(opponents)
            venue = "Home" if player_fixtures[0]["is_home"] else "Away"
            fdr = player_fixtures[0]["fdr"]
        else:
            opponent_str = "?"
            venue = "?"
            fdr = None

        squad.append({
            "slot": pick["position"],
            "starter": pick["position"] <= 11,
            "element_id": element_id,  # Fix 8: include element ID
            "name": p["web_name"],
            "team": team.get("short_name", "?"),
            "position": POSITION_MAP.get(p["element_type"], "?"),
            "cost": cost,
            "form": float(p.get("form") or 0),
            "points_per_game": float(p.get("points_per_game") or 0),
            "total_points": p.get("total_points", 0),
            "ict_index": float(p.get("ict_index") or 0),
            "is_captain": pick.get("is_captain", False),
            "is_vice_captain": pick.get("is_vice_captain", False),
            "opponent": opponent_str,
            "venue": venue,
            "fdr": fdr,
            "captain_score": captain_score,
            "status": p.get("status", "a"),
            "minutes": p.get("minutes", 0),
            "selected_by_pct": float(p.get("selected_by_percent") or 0),
        })

    # Squad health (using element IDs for lookups)
    injured = [s for s in squad if s["status"] in INJURY_STATUSES]
    poor_form = [s for s in squad if s["starter"] and s["form"] <= 2.0]
    tough_fixtures = [s for s in squad if s["starter"] and s["fdr"] and s["fdr"] >= 4]

    # Price drop risks for squad players (using element IDs)
    price_risks = []
    for s in squad:
        p = players_by_id.get(s["element_id"], {})
        net = p.get("transfers_in_event", 0) - p.get("transfers_out_event", 0)
        if net < -50_000:
            price_risks.append({
                "name": s["name"],
                "element_id": s["element_id"],
                "net_transfers": net,
                "risk": "Likely to fall",
            })

    # Season history
    season = history_data.get("current", [])
    total_points = sum(gw.get("points", 0) for gw in season)
    best_gw = max(season, key=lambda g: g.get("points", 0)) if season else {}
    worst_gw = min(season, key=lambda g: g.get("points", 0)) if season else {}
    chips_used = [
        {"chip": c["name"], "gameweek": c["event"]}
        for c in history_data.get("chips", [])
    ]

    return {
        "team_id": team_id,
        "gameweek": current_gw,
        "prepping_for": f"GW{next_gw}",
        "manager_status": manager_status,
        "total_squad_value": round(total_value + bank, 1),
        "season_summary": {
            "total_points": total_points,
            "gameweeks_played": len(season),
            "avg_points_per_gw": round(total_points / len(season), 1) if season else 0,
            "best_gameweek": {"gw": best_gw.get("event"), "points": best_gw.get("points")} if best_gw else None,
            "worst_gameweek": {"gw": worst_gw.get("event"), "points": worst_gw.get("points")} if worst_gw else None,
            "chips_used": chips_used,
        },
        "squad": squad,
        "squad_health": {
            "injured_or_doubtful": [{"name": s["name"], "element_id": s["element_id"], "status": s["status"]} for s in injured],
            "poor_form_starters": [{"name": s["name"], "element_id": s["element_id"], "form": s["form"]} for s in poor_form],
            "tough_fixtures_this_gw": [{"name": s["name"], "element_id": s["element_id"], "opponent": s["opponent"], "fdr": s["fdr"]} for s in tough_fixtures],
        },
        # Fix 7: Use results from existing algorithm functions instead of duplicating logic
        "captain_recommendation": captain_result["picks"],
        "transfer_suggestions": transfer_result.get("transfer_suggestions", []),
        "differential_targets": diff_result.get("differentials", [])[:10],
        "fixture_outlook": {
            "teams_by_difficulty": fixture_result.get("teams_by_difficulty", [])[:10],
            "players_to_target": fixture_result.get("players_to_target", []),
        },
        "price_drop_risks": price_risks,
        "price_predictions": {
            "likely_risers": price_result.get("likely_risers", [])[:5],
            "likely_fallers": price_result.get("likely_fallers", [])[:5],
        },
    }


if __name__ == "__main__":
    mcp.run()
