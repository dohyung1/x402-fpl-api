"""
x402 FPL Intelligence — MCP Server

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

    Each pick is scored by form, points per game, home advantage,
    fixture difficulty, ICT index, and bonus rate. Includes human-readable
    reasoning for each recommendation.

    Args:
        gameweek: Gameweek number (1-38). Defaults to current gameweek if not specified.
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

    Great for gaining competitive edge — surfaces players that most managers
    don't have but are delivering strong returns.

    Args:
        max_ownership_pct: Only include players owned by fewer than this percentage. Default 10%.
        gameweek: Gameweek number (1-38). Defaults to current gameweek if not specified.
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
        bank: Money in the bank in millions (e.g. 1.5 means £1.5m). Default 0.0.
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
    bank balance, free transfers, chips used, and current squad — then runs
    every analysis: captain pick, transfer suggestions, fixture outlook,
    differentials to target, price change risks, and squad health check.

    The user does NOT need to provide bank balance or free transfers —
    everything is auto-detected from the FPL API.

    The team ID is the number in the FPL URL:
    https://fantasy.premierleague.com/entry/<TEAM_ID>/event/30

    Args:
        team_id: FPL team ID from the manager's FPL URL.
        gameweeks_ahead: How many gameweeks to look ahead for fixture analysis (1-10). Default 5.
    """
    import asyncio
    from app.fpl_client import (
        get_bootstrap, get_fixtures, get_current_gameweek,
        get_next_gameweek, get_team_picks, get_team_history,
        get_manager_status,
    )
    from app.algorithms.captain import (
        _build_fixture_map, _score_player, _build_reasoning,
        POSITION_MAP, INJURY_STATUSES,
    )

    # Fetch all base data in parallel
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    current_gw = get_current_gameweek(bootstrap)
    next_gw = get_next_gameweek(bootstrap)

    # Auto-detect manager status + fetch picks in parallel
    manager_status, picks_data, history_data = await asyncio.gather(
        get_manager_status(team_id, bootstrap),
        get_team_picks(team_id, current_gw),
        get_team_history(team_id),
    )

    bank = manager_status["bank"]
    free_transfers = manager_status["free_transfers"]

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    # Use NEXT gameweek fixtures for recommendations (prepping for next GW)
    fixture_map = _build_fixture_map(fixtures, next_gw)

    # --- SQUAD ANALYSIS ---
    squad = []
    squad_ids = set()
    squad_team_ids = set()
    total_value = 0.0

    for pick in picks_data.get("picks", []):
        p = players_by_id.get(pick["element"])
        if not p:
            continue
        squad_ids.add(p["id"])
        squad_team_ids.add(p["team"])
        team = teams_by_id.get(p["team"], {})
        fixture = fixture_map.get(p["team"])
        captain_score = _score_player(p, fixture)
        opponent = teams_by_id.get(fixture["opponent"], {}).get("short_name", "?") if fixture else "?"
        cost = p["now_cost"] / 10
        total_value += cost

        squad.append({
            "slot": pick["position"],
            "starter": pick["position"] <= 11,
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
            "opponent": opponent,
            "venue": "Home" if (fixture and fixture["is_home"]) else "Away",
            "fdr": fixture["fdr"] if fixture else None,
            "captain_score": captain_score,
            "status": p.get("status", "a"),
            "minutes": p.get("minutes", 0),
            "selected_by_pct": float(p.get("selected_by_percent") or 0),
        })

    # --- SQUAD HEALTH ---
    injured = [s for s in squad if s["status"] in INJURY_STATUSES]
    poor_form = [s for s in squad if s["starter"] and s["form"] <= 2.0]
    tough_fixtures = [s for s in squad if s["starter"] and s["fdr"] and s["fdr"] >= 4]

    # --- CAPTAIN RECOMMENDATION (from squad only) ---
    starters = [s for s in squad if s["starter"]]
    starters_sorted = sorted(starters, key=lambda s: s["captain_score"], reverse=True)
    captain_recs = []
    for s in starters_sorted[:5]:
        p = players_by_id.get(next(
            pick["element"] for pick in picks_data["picks"]
            if players_by_id.get(pick["element"], {}).get("web_name") == s["name"]
        ))
        fixture = fixture_map.get(p["team"]) if p else None
        captain_recs.append({
            "name": s["name"],
            "team": s["team"],
            "position": s["position"],
            "opponent": s["opponent"],
            "venue": s["venue"],
            "fdr": s["fdr"],
            "captain_score": s["captain_score"],
            "form": s["form"],
            "ppg": s["points_per_game"],
            "reasoning": _build_reasoning(p, fixture, s["captain_score"]) if p else "",
        })

    # --- TRANSFER SUGGESTIONS ---
    # Find weakest starters and best available replacements
    starters_by_value = sorted(starters, key=lambda s: s["captain_score"])
    transfer_targets = []

    for weak in starters_by_value[:free_transfers]:
        pos_type = next(
            (k for k, v in POSITION_MAP.items() if v == weak["position"]), None
        )
        budget = weak["cost"] + bank

        replacements = []
        for p in bootstrap["elements"]:
            if p["id"] in squad_ids:
                continue
            if p["element_type"] != pos_type:
                continue
            if p["now_cost"] / 10 > budget:
                continue
            if p.get("status") in INJURY_STATUSES:
                continue
            fixture = fixture_map.get(p["team"])
            score = _score_player(p, fixture)
            if score <= weak["captain_score"]:
                continue
            team = teams_by_id.get(p["team"], {})
            opponent = teams_by_id.get(fixture["opponent"], {}).get("short_name", "?") if fixture else "?"
            replacements.append({
                "name": p["web_name"],
                "team": team.get("short_name", "?"),
                "position": POSITION_MAP.get(p["element_type"], "?"),
                "cost": p["now_cost"] / 10,
                "form": float(p.get("form") or 0),
                "ppg": float(p.get("points_per_game") or 0),
                "total_points": p.get("total_points", 0),
                "selected_by_pct": float(p.get("selected_by_percent") or 0),
                "opponent": opponent,
                "venue": "Home" if (fixture and fixture["is_home"]) else "Away",
                "fdr": fixture["fdr"] if fixture else None,
                "value_score": score,
            })

        replacements.sort(key=lambda x: x["value_score"], reverse=True)
        transfer_targets.append({
            "sell": {
                "name": weak["name"],
                "team": weak["team"],
                "position": weak["position"],
                "cost": weak["cost"],
                "form": weak["form"],
                "captain_score": weak["captain_score"],
            },
            "buy_options": replacements[:5],
            "budget": round(budget, 1),
        })

    # --- DIFFERENTIALS IN SQUAD ---
    squad_differentials = [
        s for s in squad if s["selected_by_pct"] < 10.0 and s["form"] >= 4.0
    ]

    # --- DIFFERENTIALS TO BUY ---
    diff_targets = []
    for p in bootstrap["elements"]:
        if p["id"] in squad_ids:
            continue
        ownership = float(p.get("selected_by_percent") or 0)
        if ownership > 10.0:
            continue
        if p.get("status") in INJURY_STATUSES:
            continue
        form = float(p.get("form") or 0)
        if form < 5.0:
            continue
        fixture = fixture_map.get(p["team"])
        if fixture and fixture["fdr"] >= 4:
            continue
        team = teams_by_id.get(p["team"], {})
        opponent = teams_by_id.get(fixture["opponent"], {}).get("short_name", "?") if fixture else "?"
        diff_targets.append({
            "name": p["web_name"],
            "team": team.get("short_name", "?"),
            "position": POSITION_MAP.get(p["element_type"], "?"),
            "cost": p["now_cost"] / 10,
            "form": form,
            "ppg": float(p.get("points_per_game") or 0),
            "selected_by_pct": ownership,
            "opponent": opponent,
            "venue": "Home" if (fixture and fixture["is_home"]) else "Away",
            "fdr": fixture["fdr"] if fixture else None,
        })
    diff_targets.sort(key=lambda x: x["form"], reverse=True)

    # --- FIXTURE OUTLOOK FOR SQUAD TEAMS ---
    target_gws = list(range(next_gw, next_gw + gameweeks_ahead))
    team_fdr: dict[int, list] = {t_id: [] for t_id in squad_team_ids}

    for fix in fixtures:
        gw = fix.get("event")
        if gw not in target_gws:
            continue
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        if home_id in team_fdr:
            team_fdr[home_id].append({
                "gw": gw,
                "opponent": teams_by_id.get(away_id, {}).get("short_name", "?"),
                "venue": "H",
                "fdr": fix["team_h_difficulty"],
            })
        if away_id in team_fdr:
            team_fdr[away_id].append({
                "gw": gw,
                "opponent": teams_by_id.get(home_id, {}).get("short_name", "?"),
                "venue": "A",
                "fdr": fix["team_a_difficulty"],
            })

    squad_fixture_outlook = {}
    for t_id, fix_list in team_fdr.items():
        team_name = teams_by_id.get(t_id, {}).get("short_name", "?")
        sorted_fixes = sorted(fix_list, key=lambda x: x["gw"])
        avg_fdr = round(sum(f["fdr"] for f in sorted_fixes) / len(sorted_fixes), 2) if sorted_fixes else 3.0
        squad_fixture_outlook[team_name] = {
            "fixtures": sorted_fixes,
            "avg_fdr": avg_fdr,
            "verdict": "Easy run" if avg_fdr <= 2.5 else "Decent" if avg_fdr <= 3.2 else "Tough run",
        }

    # --- PRICE CHANGE RISKS ---
    price_risks = []
    for s in squad:
        p_id = next(
            pick["element"] for pick in picks_data["picks"]
            if players_by_id.get(pick["element"], {}).get("web_name") == s["name"]
        )
        p = players_by_id.get(p_id, {})
        net = p.get("transfers_in_event", 0) - p.get("transfers_out_event", 0)
        if net < -50_000:
            price_risks.append({
                "name": s["name"],
                "net_transfers": net,
                "risk": "Likely to fall",
            })

    # --- SEASON HISTORY ---
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
            "injured_or_doubtful": [{"name": s["name"], "status": s["status"]} for s in injured],
            "poor_form_starters": [{"name": s["name"], "form": s["form"]} for s in poor_form],
            "tough_fixtures_this_gw": [{"name": s["name"], "opponent": s["opponent"], "fdr": s["fdr"]} for s in tough_fixtures],
        },
        "captain_recommendation": captain_recs,
        "transfer_suggestions": transfer_targets,
        "differentials_in_squad": [
            {"name": s["name"], "selected_by_pct": s["selected_by_pct"], "form": s["form"]}
            for s in squad_differentials
        ],
        "differential_targets": diff_targets[:10],
        "squad_fixture_outlook": squad_fixture_outlook,
        "price_drop_risks": price_risks,
    }


if __name__ == "__main__":
    mcp.run()
