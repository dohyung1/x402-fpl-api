"""
Captain Pick algorithm v2.5 — set-piece takers, consistency, better FDR.

captain_score =
    points_per_game * 4.55       # highest single-GW correlation (0.42)
  + form * 3.1                   # strong correlation (0.26), dynamic per GW
  + ep_next * 0.7                # FPL's own ML prediction (low backtest correlation)
  + xG_per_90 * 1.27
  + xA_per_90 * 1.05
  + home_bonus (3.0 if home)
  - fixture_difficulty * 3.08    # THE key differentiator between GWs
  + ict_index * 0.01
  + bonus_per_game * 1.2
  + penalty_taker_bonus * 1.69
  + set_piece_bonus * 1.2        # NEW: corners + direct FK taker
  + dreamteam_bonus * 0.8        # NEW: consistency signal from FPL dream team
  + minutes_certainty * 1.02
  + def_contrib_per_90 * 0.84    # defensive contribution (DEF/MID only)
  + news_penalty                 # injury/absence news keyword penalty
  - playing_chance_penalty

v2.5 changes from v2.4:
  - Set-piece taker bonus (corners_and_indirect_freekicks_order, direct_freekicks_order)
  - Dream team consistency signal (dreamteam_count / starts)
  - FDR blend reweighted: 40% raw FDR + 60% team strength (was 60/40)

Weights tuned against GW1-29 actuals via scripts/backtest.py.
"""

import logging

from app.algorithms import INJURY_STATUSES, POSITION_MAP
from app.algorithms.news import format_news_for_reasoning, news_penalty_score
from app.fpl_client import get_bootstrap, get_fixtures, get_next_gameweek

logger = logging.getLogger(__name__)

# Default weights (v2.5) — tuned via backtest correlation analysis (GW1-29)
DEFAULT_WEIGHTS = {
    "xg90": 1.27,  # low single-GW correlation (0.04)
    "xa90": 1.05,  # low single-GW correlation (0.06)
    "form": 3.1,  # strong correlation (0.26), dynamic per GW
    "ppg": 4.55,  # highest correlation (0.42)
    "ep_next": 0.7,  # 0.0 correlation in backtest — reduced
    "home": 3.0,  # must differentiate home vs away GWs
    "fdr": 3.08,  # THE key factor for GW-to-GW variation
    "ict": 0.01,  # already tiny weight
    "bonus_pg": 1.2,  # correlation 0.25
    "penalty": 1.69,  # correlation 0.27
    "set_piece": 1.2,  # corners/FK taker bonus — extra scoring opportunities
    "dreamteam": 0.8,  # consistency signal — players who regularly haul
    "minutes_cert": 1.02,  # correlation 0.19
    "def_contrib": 0.84,  # defensive_contribution_per_90 — DEF/MID only
    "news_penalty": 1.0,  # multiplier for news-based injury penalty
    "playing_chance_max_penalty": -10.0,
}


def _load_weights() -> dict:
    """
    Load the best available weights: optimized (data-driven) or default (hand-tuned).

    The rolling weight optimizer (weight_optimizer.py) writes optimized weights
    to data/optimized_weights.json. If that file exists and is fresh, we use it.
    Otherwise, fall back to DEFAULT_WEIGHTS.
    """
    try:
        from app.algorithms.weight_optimizer import get_optimized_weights

        optimized = get_optimized_weights()
        if optimized:
            logger.info("Using optimized weights from rolling optimizer")
            return optimized
    except Exception:
        pass  # No snapshots yet or optimizer not available

    return dict(DEFAULT_WEIGHTS)


# Active weights — loaded once at import time, refreshable via load_weights()
WEIGHTS = _load_weights()


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

        # Blend FDR with opponent defensive strength for more accurate difficulty.
        # For captaincy (scoring potential), what matters is how WEAK the opponent's
        # defence is, not how strong their attack is. Lower defensive strength = easier
        # fixture for the attacking team's players.
        if teams_by_id:
            away_team = teams_by_id.get(away_id, {})
            home_team = teams_by_id.get(home_id, {})

            # For home team: opponent's away defensive weakness determines scoring ease
            opp_defence_away = away_team.get("strength_defence_away", 1200)
            home_fdr = _blend_fdr(home_fdr, opp_defence_away)

            # For away team: opponent's home defensive weakness determines scoring ease
            opp_defence_home = home_team.get("strength_defence_home", 1200)
            away_fdr = _blend_fdr(away_fdr, opp_defence_home)

        # Home team
        fixture_map.setdefault(home_id, []).append({"fdr": home_fdr, "is_home": True, "opponent": away_id})
        # Away team
        fixture_map.setdefault(away_id, []).append({"fdr": away_fdr, "is_home": False, "opponent": home_id})

    return fixture_map


def _blend_fdr(raw_fdr: int, opponent_strength: int) -> float:
    """
    Blend raw FDR (1-5 scale) with opponent team strength (typically 1000-1400).

    FPL's strength values are ~1000-1400 range with finer granularity than
    raw FDR (1-5). We normalize strength to a 1-5 scale and blend
    40% raw FDR + 60% strength-based difficulty, favouring the dynamic
    strength values which update weekly over static FDR.
    """
    # Normalize strength to 1-5 scale: 1000→1.0, 1400→5.0
    strength_normalized = max(1.0, min(5.0, (opponent_strength - 1000) / 100 + 1.0))
    return round(raw_fdr * 0.4 + strength_normalized * 0.6, 2)


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

    # News-based injury/absence penalty (supplements chance_of_playing)
    news_pen = news_penalty_score(player) * WEIGHTS.get("news_penalty", 1.0)

    # Defensive contribution per 90 (DEF and MID only — element_type 2 and 3)
    def_contrib_per_90 = 0.0
    element_type = player.get("element_type", 0)
    if element_type in (2, 3):  # DEF or MID
        def_contrib_per_90 = float(player.get("defensive_contribution_per_90") or 0)

    # Set-piece taker bonus — corners, indirect FKs, direct FKs
    # Players on set pieces get extra scoring opportunities (goals + assists)
    corners_order = player.get("corners_and_indirect_freekicks_order")
    fk_order = player.get("direct_freekicks_order")
    set_piece_norm = 0.0
    if corners_order == 1 and fk_order == 1:
        set_piece_norm = 1.0  # primary on both — elite set piece taker
    elif corners_order == 1 or fk_order == 1:
        set_piece_norm = 0.6  # primary on one
    elif corners_order == 2 or fk_order == 2:
        set_piece_norm = 0.2  # secondary

    # Dream team consistency — how often this player makes FPL's weekly best XI
    dreamteam_count = player.get("dreamteam_count", 0)
    dreamteam_rate = dreamteam_count / max(1, starts) if starts > 0 else 0
    dreamteam_norm = _normalize(dreamteam_rate, 0, 0.3)  # 30% dream team rate = elite

    # --- NORMALIZE all factors to 0-1 scale ---
    # Bounds based on realistic FPL ranges for viable captain candidates
    ppg_norm = _normalize(ppg, 0, 10)  # PPG: 0-10
    form_norm = _normalize(form, 0, 10)  # Form: 0-10
    xg90_norm = _normalize(xg_per_90, 0, 1.0)  # xG/90: 0-1.0
    xa90_norm = _normalize(xa_per_90, 0, 0.5)  # xA/90: 0-0.5
    ict_norm = _normalize(ict, 0, 300)  # ICT: 0-300
    bonus_norm = _normalize(bonus_pg, 0, 3)  # Bonus/game: 0-3
    ep_norm = _normalize(ep_next, 0, 10)  # EP: 0-10
    def_contrib_norm = _normalize(def_contrib_per_90, 0, 5.0)  # Def contrib/90: 0-5
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
        + set_piece_norm * WEIGHTS.get("set_piece", 1.2)
        + dreamteam_norm * WEIGHTS.get("dreamteam", 0.8)
        + minutes_cert * WEIGHTS["minutes_cert"]
        + def_contrib_norm * WEIGHTS["def_contrib"]
        + chance_penalty
        + news_pen
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

    # Set piece duties
    corners_order = player.get("corners_and_indirect_freekicks_order")
    fk_order = player.get("direct_freekicks_order")
    if corners_order == 1 and fk_order == 1:
        parts.append("on corners + free kicks")
    elif corners_order == 1:
        parts.append("on corners")
    elif fk_order == 1:
        parts.append("on direct free kicks")

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

    # News/injury information
    news_text = format_news_for_reasoning(player)
    if news_text:
        parts.append(f"news: {news_text}")

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
                    "defensive_contribution_per_90": float(player.get("defensive_contribution_per_90") or 0),
                    "penalties_order": player.get("penalties_order"),
                    "starts": player.get("starts", 0),
                    "chance_of_playing": player.get("chance_of_playing_next_round"),
                },
            }
        )

    # Community consensus: who is the most-captained player this GW?
    most_captained_info = None
    for event in bootstrap.get("events", []):
        if event["id"] == gameweek:
            mc_id = event.get("most_captained")
            if mc_id:
                mc_player = {p["id"]: p for p in bootstrap["elements"]}.get(mc_id)
                if mc_player:
                    mc_team = teams.get(mc_player["team"], {})
                    most_captained_info = {
                        "player_id": mc_id,
                        "name": mc_player["web_name"],
                        "team": mc_team.get("short_name", "?"),
                        "selected_by_pct": float(mc_player.get("selected_by_percent") or 0),
                        "captaincy_pct": float(event.get("most_captained_pct") or 0)
                        if event.get("most_captained_pct")
                        else None,
                    }
            break

    return {
        "gameweek": gameweek,
        "algorithm_version": "2.5",
        "most_captained": most_captained_info,
        "picks": picks,
    }


async def _gather_data():
    """Fetch bootstrap and fixtures concurrently."""
    import asyncio as _asyncio

    return await _asyncio.gather(get_bootstrap(), get_fixtures())
