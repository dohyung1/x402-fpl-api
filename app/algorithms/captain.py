"""
Captain Pick algorithm v2.1 — backtest-tuned weights.

captain_score =
    points_per_game * 3.0        # highest single-GW correlation (0.42)
  + form * 2.5                   # strong correlation (0.26)
  + xG_per_90 * 2.0              # reduced from 5.0 — low single-GW correlation
  + xA_per_90 * 1.5              # reduced from 3.0 — low single-GW correlation
  + home_bonus (1.5 if home)
  - fixture_difficulty * 1.5     # increased — FDR matters
  + ict_index * 0.01
  + bonus_per_game * 1.0         # increased from 0.5
  + penalty_taker_bonus * 2.0
  + minutes_certainty * 1.0
  - playing_chance_penalty

Weights tuned against GW1-29 actuals via scripts/backtest.py.
"""

from app.fpl_client import get_bootstrap, get_next_gameweek, get_fixtures

# Statuses that warrant a full injury penalty
INJURY_STATUSES = {"i", "d", "s", "u"}  # injured, doubtful, suspended, unavailable

WEIGHTS = {
    "xg90": 2.0,           # reduced — low single-GW correlation per backtest
    "xa90": 1.5,           # reduced — low single-GW correlation per backtest
    "form": 2.5,           # strongest predictor after PPG per backtest
    "ppg": 3.0,            # highest correlation with actual GW points (0.42)
    "home": 2.0,           # increased — home advantage is a key differentiator
    "fdr": 2.0,            # increased — fixture difficulty should drive pick variation
    "ict": 0.01,           # keep
    "bonus_pg": 1.0,       # increased — bonus correlates well
    "penalty": 1.5,        # reduced — less important than fixture context
    "minutes_cert": 1.0,   # keep
    "playing_chance_max_penalty": -10.0,
}

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _playing_chance_penalty(player: dict) -> float:
    """
    Penalise players unlikely to play next round.

    chance_of_playing_next_round:
      100 or None (fit) -> 0 penalty
      75 -> -2.5
      50 -> -5.0
      25 -> -7.5
      0  -> -10.0
    """
    chance = player.get("chance_of_playing_next_round")
    if chance is None:
        # No flag = assumed fit
        status = player.get("status", "a")
        if status in INJURY_STATUSES:
            return WEIGHTS["playing_chance_max_penalty"]
        return 0.0
    chance = float(chance)
    return WEIGHTS["playing_chance_max_penalty"] * (1.0 - chance / 100.0)


def _build_fixture_map(fixtures: list, gameweek: int) -> dict[int, list[dict]]:
    """
    Map team_id -> list of fixture details for the given gameweek.
    Returns: { team_id: [ { fdr, is_home, opponent_team }, ... ] }

    Supports double gameweeks (DGW) where a team plays multiple fixtures.
    """
    fixture_map: dict[int, list[dict]] = {}
    gw_fixtures = [f for f in fixtures if f.get("event") == gameweek]

    for fix in gw_fixtures:
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        home_fdr = fix["team_h_difficulty"]
        away_fdr = fix["team_a_difficulty"]

        # Home team
        fixture_map.setdefault(home_id, []).append(
            {"fdr": home_fdr, "is_home": True, "opponent": away_id}
        )
        # Away team
        fixture_map.setdefault(away_id, []).append(
            {"fdr": away_fdr, "is_home": False, "opponent": home_id}
        )

    return fixture_map


def _score_player(player: dict, fixtures: list[dict] | None) -> float:
    """
    Score a player for captaincy using v2 algorithm with xG/xA data.

    fixtures: list of fixture dicts for the player's team this gameweek.
              Supports DGWs (multiple fixtures) by summing fixture-dependent
              components across all fixtures.
    """
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)
    ict = float(player.get("ict_index") or 0)

    # xG and xA per 90
    minutes = player.get("minutes", 0)
    nineties = minutes / 90.0 if minutes > 0 else 0

    xg_per_90 = 0.0
    xa_per_90 = 0.0
    if nineties > 0:
        xg = float(player.get("expected_goals") or 0)
        xa = float(player.get("expected_assists") or 0)
        xg_per_90 = xg / nineties
        xa_per_90 = xa / nineties

    # bonus_per_game approximation: total bonus / 90s played
    gw_played = max(1, round(nineties)) if nineties > 0 else 1
    bonus_pg = player.get("bonus", 0) / gw_played

    # Penalty taker bonus
    penalties_order = player.get("penalties_order")
    penalty_bonus = WEIGHTS["penalty"] if penalties_order == 1 else 0.0

    # Minutes certainty: starts / possible starts (approximate from GWs played)
    starts = player.get("starts", 0)
    # Count gameweeks where player could have started (events so far)
    possible_starts = max(1, gw_played)
    minutes_cert = starts / possible_starts if possible_starts > 0 else 0.0

    # Playing chance penalty (uses chance_of_playing_next_round or status)
    chance_penalty = _playing_chance_penalty(player)

    # Base score (fixture-independent)
    base_score = (
        xg_per_90 * WEIGHTS["xg90"]
        + xa_per_90 * WEIGHTS["xa90"]
        + form * WEIGHTS["form"]
        + ppg * WEIGHTS["ppg"]
        + ict * WEIGHTS["ict"]
        + bonus_pg * WEIGHTS["bonus_pg"]
        + penalty_bonus
        + minutes_cert * WEIGHTS["minutes_cert"]
        + chance_penalty
    )

    # Fixture-dependent scoring -- sum across all fixtures (DGW support)
    if fixtures:
        fixture_score = 0.0
        for fixture in fixtures:
            fdr = fixture["fdr"]
            is_home = fixture["is_home"]
            home_bonus = WEIGHTS["home"] if is_home else 0.0
            fixture_score += home_bonus - fdr * WEIGHTS["fdr"]
        score = base_score + fixture_score
    else:
        # No fixture data -- assume average difficulty
        score = base_score - 3 * WEIGHTS["fdr"]

    return round(score, 3)


def _build_reasoning(player: dict, fixtures: list[dict] | None, score: float) -> str:
    parts = []
    form = float(player.get("form") or 0)
    if form >= 7:
        parts.append("exceptional form")
    elif form >= 5:
        parts.append("strong form")
    elif form <= 2:
        parts.append("poor form")

    # xG/xA insight
    minutes = player.get("minutes", 0)
    if minutes > 0:
        nineties = minutes / 90.0
        xg = float(player.get("expected_goals") or 0)
        xa = float(player.get("expected_assists") or 0)
        xg90 = xg / nineties if nineties > 0 else 0
        xa90 = xa / nineties if nineties > 0 else 0
        if xg90 >= 0.5:
            parts.append(f"elite xG/90 ({xg90:.2f})")
        elif xg90 >= 0.3:
            parts.append(f"strong xG/90 ({xg90:.2f})")
        if xa90 >= 0.3:
            parts.append(f"strong xA/90 ({xa90:.2f})")

    if player.get("penalties_order") == 1:
        parts.append("on penalties")

    if fixtures:
        if len(fixtures) > 1:
            parts.append(f"double gameweek ({len(fixtures)} fixtures)")
        for fixture in fixtures:
            fdr = fixture["fdr"]
            if fdr <= 2:
                parts.append("easy fixture (FDR %d)" % fdr)
            elif fdr >= 4:
                parts.append("tough fixture (FDR %d)" % fdr)
            if fixture["is_home"]:
                parts.append("home advantage")

    chance = player.get("chance_of_playing_next_round")
    status = player.get("status", "a")
    if status in INJURY_STATUSES:
        if chance is not None:
            parts.append(f"injury concern ({chance}% chance)")
        else:
            parts.append("injury concern")

    ict = float(player.get("ict_index") or 0)
    if ict >= 150:
        parts.append("elite ICT index")

    if not parts:
        parts.append("solid all-round score")

    return ", ".join(parts).capitalize() + f" (score: {score})"


async def get_captain_picks(gameweek: int | None = None, top_n: int = 5) -> dict:
    """
    Return top N captain recommendations for the given gameweek.
    If gameweek is None, uses the next gameweek (what managers are prepping for).
    """
    bootstrap, fixtures = await _gather_data()

    if gameweek is None:
        gameweek = get_next_gameweek(bootstrap)

    teams = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, gameweek)

    scored = []
    for player in bootstrap["elements"]:
        player_fixtures = fixture_map.get(player["team"])
        score = _score_player(player, player_fixtures)
        scored.append((score, player, player_fixtures))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]

    picks = []
    for score, player, player_fixtures in top:
        team = teams.get(player["team"], {})

        # Build fixture info for all fixtures (DGW support)
        fixture_info = None
        if player_fixtures:
            fixture_entries = []
            for fix in player_fixtures:
                opponent_id = fix["opponent"]
                opponent = teams.get(opponent_id, {}).get("short_name", "?")
                fixture_entries.append({
                    "opponent": opponent,
                    "venue": "Home" if fix["is_home"] else "Away",
                    "fdr": fix["fdr"],
                })
            fixture_info = {
                "fixtures": fixture_entries,
                "gameweek": gameweek,
                "is_dgw": len(fixture_entries) > 1,
                # Keep backward compat: top-level opponent/venue/fdr from first fixture
                "opponent": fixture_entries[0]["opponent"],
                "venue": fixture_entries[0]["venue"],
                "fdr": fixture_entries[0]["fdr"],
            }

        # xG/xA stats
        minutes = player.get("minutes", 0)
        nineties = minutes / 90.0 if minutes > 0 else 0
        xg = float(player.get("expected_goals") or 0)
        xa = float(player.get("expected_assists") or 0)

        picks.append(
            {
                "rank": len(picks) + 1,
                "player": {
                    "id": player["id"],
                    "name": player["web_name"],
                    "team": team.get("short_name", "?"),
                    "position": POSITION_MAP.get(player["element_type"], "?"),
                    "cost": player["now_cost"] / 10,
                    "selected_by_pct": float(player.get("selected_by_percent") or 0),
                    "status": player.get("status", "a"),
                },
                "fixture": fixture_info,
                "score": score,
                "reasoning": _build_reasoning(player, player_fixtures, score),
                "stats": {
                    "form": float(player.get("form") or 0),
                    "points_per_game": float(player.get("points_per_game") or 0),
                    "ict_index": float(player.get("ict_index") or 0),
                    "total_points": player.get("total_points", 0),
                    "bonus": player.get("bonus", 0),
                    "expected_goals": xg,
                    "expected_assists": xa,
                    "expected_goal_involvements": float(player.get("expected_goal_involvements") or 0),
                    "xg_per_90": round(xg / nineties, 3) if nineties > 0 else 0,
                    "xa_per_90": round(xa / nineties, 3) if nineties > 0 else 0,
                    "penalties_order": player.get("penalties_order"),
                    "starts": player.get("starts", 0),
                    "chance_of_playing": player.get("chance_of_playing_next_round"),
                },
            }
        )

    return {
        "gameweek": gameweek,
        "algorithm_version": "2.0",
        "picks": picks,
    }


async def _gather_data():
    """Fetch bootstrap and fixtures concurrently."""
    import asyncio

    return await asyncio.gather(get_bootstrap(), get_fixtures())
