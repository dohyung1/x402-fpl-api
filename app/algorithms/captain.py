"""
Captain Pick algorithm v2.3 — fixture-driven differentiation.

captain_score =
    points_per_game * 3.5        # highest single-GW correlation (0.42)
  + form * 2.8                   # strong correlation (0.26), dynamic per GW
  + ep_next * 1.0                # FPL's own ML prediction (low backtest correlation)
  + xG_per_90 * 1.5              # low single-GW correlation per backtest
  + xA_per_90 * 1.2              # low single-GW correlation per backtest
  + home_bonus (3.0 if home)     # increased — must differentiate GWs
  - fixture_difficulty * 3.0     # increased — THE key differentiator between GWs
  + ict_index * 0.01
  + bonus_per_game * 1.1         # per start, not per 90
  + penalty_taker_bonus * 1.5
  + minutes_certainty * 1.0
  - playing_chance_penalty

v2.3 changes from v2.2:
  - Boosted fixture-dependent weights (fdr 2.0→3.0, home 2.0→3.0) so picks
    vary by gameweek instead of always recommending the same player
  - Applied backtest GW1-29 weight suggestions (ppg up, xg90/xa90/ep_next down)
  - v2.2 bug: always picked B.Fernandes (29/29 GWs) because static factors
    dominated and fixture swings couldn't overcome the gap

Weights tuned against GW1-29 actuals via scripts/backtest.py.
"""

from app.fpl_client import get_bootstrap, get_fixtures, get_next_gameweek

# Statuses that warrant a full injury penalty
INJURY_STATUSES = {"i", "d", "s", "u"}  # injured, doubtful, suspended, unavailable

WEIGHTS = {
    "xg90": 1.5,  # reduced from 2.0 — low single-GW correlation (0.04)
    "xa90": 1.2,  # reduced from 1.5 — low single-GW correlation (0.06)
    "form": 2.8,  # up from 2.5 — strong correlation (0.26), dynamic per GW
    "ppg": 3.5,  # up from 3.0 — highest correlation (0.42)
    "ep_next": 1.0,  # down from 1.5 — 0.0 correlation in backtest
    "home": 3.0,  # up from 2.0 — must differentiate home vs away GWs
    "fdr": 3.0,  # up from 2.0 — THE key factor for GW-to-GW variation
    "ict": 0.01,  # keep — already tiny weight
    "bonus_pg": 1.1,  # up from 1.0 — correlation 0.25
    "penalty": 1.5,  # keep — correlation 0.27
    "minutes_cert": 1.0,  # keep — correlation 0.19
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


def _build_fixture_map(fixtures: list, gameweek: int, teams_by_id: dict | None = None) -> dict[int, list[dict]]:
    """
    Map team_id -> list of fixture details for the given gameweek.
    Returns: { team_id: [ { fdr, is_home, opponent_team }, ... ] }

    If teams_by_id is provided, blends raw FDR with team strength fields
    for a more accurate fixture difficulty score. The strength fields
    (strength_attack_home/away, strength_defence_home/away) are dynamic
    values updated weekly by FPL, unlike FDR which is static and coarse.

    Supports double gameweeks (DGW) where a team plays multiple fixtures.
    """
    fixture_map: dict[int, list[dict]] = {}
    gw_fixtures = [f for f in fixtures if f.get("event") == gameweek]

    for fix in gw_fixtures:
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        home_fdr = fix["team_h_difficulty"]
        away_fdr = fix["team_a_difficulty"]

        # Blend FDR with team strength for more accurate difficulty
        if teams_by_id:
            away_team = teams_by_id.get(away_id, {})
            home_team = teams_by_id.get(home_id, {})

            # For home team: difficulty = opponent's away attack strength
            # Higher opponent attack = harder fixture
            opp_attack_away = away_team.get("strength_attack_away", 1200)
            home_fdr = _blend_fdr(home_fdr, opp_attack_away)

            # For away team: difficulty = opponent's home attack strength
            opp_attack_home = home_team.get("strength_attack_home", 1200)
            away_fdr = _blend_fdr(away_fdr, opp_attack_home)

        # Home team
        fixture_map.setdefault(home_id, []).append({"fdr": home_fdr, "is_home": True, "opponent": away_id})
        # Away team
        fixture_map.setdefault(away_id, []).append({"fdr": away_fdr, "is_home": False, "opponent": home_id})

    return fixture_map


def _blend_fdr(raw_fdr: int, opponent_strength: int) -> float:
    """
    Blend raw FDR (1-5 scale) with opponent team strength (typically 1000-1400).

    FPL's strength values are ~1000-1400 range. We normalize to a 1-5 scale
    and blend 60% raw FDR + 40% strength-based difficulty.

    This gives better resolution than raw FDR alone — e.g., Man City (FDR 5)
    at home vs away, or newly promoted teams that FPL rates FDR 2 but are
    actually dangerous.
    """
    # Normalize strength to 1-5 scale: 1000→1.0, 1400→5.0
    strength_normalized = max(1.0, min(5.0, (opponent_strength - 1000) / 100 + 1.0))
    return round(raw_fdr * 0.6 + strength_normalized * 0.4, 2)


def _normalize(value: float, low: float, high: float) -> float:
    """Normalize a value to 0-1 scale given expected bounds. Clamps to [0, 1]."""
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _score_player(player: dict, fixtures: list[dict] | None) -> float:
    """
    Score a player for captaincy using v2.3 algorithm with normalized inputs.

    All factors are normalized to 0-1 scale before weighting, so no single
    factor can dominate due to raw scale (e.g., PPG 6.5 vs xG90 0.3).
    This allows fixture-dependent factors to actually differentiate picks
    across gameweeks.

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

    # bonus_per_game: total bonus / starts (more accurate than 90s played)
    bonus_pg = player.get("bonus", 0) / max(1, player.get("starts", 1))

    # Penalty taker bonus (binary: 0 or 1)
    penalties_order = player.get("penalties_order")
    penalty_norm = 1.0 if penalties_order == 1 else 0.0

    # FPL's own expected points prediction
    ep_next = float(player.get("ep_next") or 0)

    # Minutes certainty: starts / possible starts (already 0-1)
    starts = player.get("starts", 0)
    gw_played = max(1, round(nineties)) if nineties > 0 else 1
    possible_starts = max(1, gw_played)
    minutes_cert = starts / possible_starts if possible_starts > 0 else 0.0

    # Playing chance penalty (uses chance_of_playing_next_round or status)
    chance_penalty = _playing_chance_penalty(player)

    # --- NORMALIZE all factors to 0-1 scale ---
    # Bounds based on realistic FPL ranges for viable captain candidates
    ppg_norm = _normalize(ppg, 0, 10)  # PPG: 0-10
    form_norm = _normalize(form, 0, 10)  # Form: 0-10
    xg90_norm = _normalize(xg_per_90, 0, 1.0)  # xG/90: 0-1.0
    xa90_norm = _normalize(xa_per_90, 0, 0.5)  # xA/90: 0-0.5
    ict_norm = _normalize(ict, 0, 300)  # ICT: 0-300
    bonus_norm = _normalize(bonus_pg, 0, 3)  # Bonus/game: 0-3
    ep_norm = _normalize(ep_next, 0, 10)  # EP: 0-10
    # minutes_cert already 0-1, penalty_norm already 0-1

    # Base score (fixture-independent) — all inputs 0-1, weights set importance
    base_score = (
        xg90_norm * WEIGHTS["xg90"]
        + xa90_norm * WEIGHTS["xa90"]
        + form_norm * WEIGHTS["form"]
        + ppg_norm * WEIGHTS["ppg"]
        + ep_norm * WEIGHTS["ep_next"]
        + ict_norm * WEIGHTS["ict"]
        + bonus_norm * WEIGHTS["bonus_pg"]
        + penalty_norm * WEIGHTS["penalty"]
        + minutes_cert * WEIGHTS["minutes_cert"]
        + chance_penalty
    )

    # Fixture-dependent scoring -- sum across all fixtures (DGW support)
    if fixtures:
        fixture_score = 0.0
        for fixture in fixtures:
            fdr = fixture["fdr"]
            is_home = fixture["is_home"]
            # Normalize FDR: lower is better, so invert (5=0.0, 1=1.0)
            fdr_norm = _normalize(5 - fdr, 0, 4)  # FDR 1→1.0, FDR 5→0.0
            home_bonus = WEIGHTS["home"] if is_home else 0.0
            fixture_score += home_bonus + fdr_norm * WEIGHTS["fdr"]
        score = base_score + fixture_score
    else:
        # No fixture data -- assume average difficulty (FDR 3 = 0.5 normalized)
        score = base_score + 0.5 * WEIGHTS["fdr"]

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

    # FPL expected points
    ep_next = float(player.get("ep_next") or 0)
    if ep_next >= 6:
        parts.append(f"FPL predicts {ep_next}pts")
    elif ep_next >= 4:
        parts.append(f"FPL expects {ep_next}pts")

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
    else:
        parts.append("NO FIXTURE this GW — do not captain")

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
    fixture_map = _build_fixture_map(fixtures, gameweek, teams_by_id=teams)

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
                    "ep_next": float(player.get("ep_next") or 0),
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
        "algorithm_version": "2.3",
        "picks": picks,
    }


async def _gather_data():
    """Fetch bootstrap and fixtures concurrently."""
    import asyncio

    return await asyncio.gather(get_bootstrap(), get_fixtures())
