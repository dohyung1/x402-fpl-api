"""
Captain Pick algorithm.

captain_score =
    form × 2.0
  + points_per_game × 1.0
  + home_bonus (1.5 if home, else 0)
  - fixture_difficulty × 1.0   (FDR 1–5)
  + ict_index × 0.01
  + bonus_per_game × 0.5
  - injury_penalty (0 if fit, -10 if doubtful/injured)
"""

from app.fpl_client import get_bootstrap, get_current_gameweek, get_fixtures

# Statuses that warrant a full injury penalty
INJURY_STATUSES = {"i", "d", "s", "u"}  # injured, doubtful, suspended, unavailable

WEIGHTS = {
    "form": 2.0,
    "ppg": 1.0,
    "home": 1.5,
    "fdr": 1.0,
    "ict": 0.01,
    "bonus_pg": 0.5,
    "injury": -10.0,
}

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _injury_penalty(player: dict) -> float:
    status = player.get("status", "a")
    return WEIGHTS["injury"] if status in INJURY_STATUSES else 0.0


def _build_fixture_map(fixtures: list, gameweek: int) -> dict[int, dict]:
    """
    Map team_id → next fixture details for the given gameweek.
    Returns: { team_id: { fdr, is_home, opponent_team } }
    """
    fixture_map: dict[int, dict] = {}
    gw_fixtures = [f for f in fixtures if f.get("event") == gameweek]

    for fix in gw_fixtures:
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        home_fdr = fix["team_h_difficulty"]
        away_fdr = fix["team_a_difficulty"]

        # Home team
        if home_id not in fixture_map:
            fixture_map[home_id] = {"fdr": home_fdr, "is_home": True, "opponent": away_id}
        # Away team
        if away_id not in fixture_map:
            fixture_map[away_id] = {"fdr": away_fdr, "is_home": False, "opponent": home_id}

    return fixture_map


def _score_player(player: dict, fixture: dict | None) -> float:
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)
    ict = float(player.get("ict_index") or 0)

    # bonus_per_game approximation: total bonus / GW played
    minutes = player.get("minutes", 0)
    gw_played = max(1, round(minutes / 90))
    bonus_pg = player.get("bonus", 0) / gw_played

    fdr = fixture["fdr"] if fixture else 3  # assume average difficulty if no fixture
    is_home = fixture["is_home"] if fixture else False

    home_bonus = WEIGHTS["home"] if is_home else 0.0
    injury_penalty = _injury_penalty(player)

    score = (
        form * WEIGHTS["form"]
        + ppg * WEIGHTS["ppg"]
        + home_bonus
        - fdr * WEIGHTS["fdr"]
        + ict * WEIGHTS["ict"]
        + bonus_pg * WEIGHTS["bonus_pg"]
        + injury_penalty
    )
    return round(score, 3)


def _build_reasoning(player: dict, fixture: dict | None, score: float) -> str:
    parts = []
    form = float(player.get("form") or 0)
    if form >= 7:
        parts.append("exceptional form")
    elif form >= 5:
        parts.append("strong form")
    elif form <= 2:
        parts.append("poor form")

    if fixture:
        fdr = fixture["fdr"]
        if fdr <= 2:
            parts.append("easy fixture (FDR %d)" % fdr)
        elif fdr >= 4:
            parts.append("tough fixture (FDR %d)" % fdr)
        if fixture["is_home"]:
            parts.append("home advantage")

    status = player.get("status", "a")
    if status in INJURY_STATUSES:
        parts.append("⚠ injury concern")

    ict = float(player.get("ict_index") or 0)
    if ict >= 150:
        parts.append("elite ICT index")

    if not parts:
        parts.append("solid all-round score")

    return ", ".join(parts).capitalize() + f" (score: {score})"


async def get_captain_picks(gameweek: int | None = None, top_n: int = 5) -> dict:
    """
    Return top N captain recommendations for the given gameweek.
    If gameweek is None, uses the current/next gameweek.
    """
    bootstrap, fixtures = await _gather_data()

    if gameweek is None:
        gameweek = get_current_gameweek(bootstrap)

    teams = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, gameweek)

    scored = []
    for player in bootstrap["elements"]:
        # Only consider premium attacking assets for captaincy
        # (all positions included, but ranked — GKPs will score low naturally)
        fixture = fixture_map.get(player["team"])
        score = _score_player(player, fixture)
        scored.append((score, player, fixture))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]

    picks = []
    for score, player, fixture in top:
        team = teams.get(player["team"], {})
        opponent_id = fixture["opponent"] if fixture else None
        opponent = teams.get(opponent_id, {}).get("short_name", "?") if opponent_id else "?"

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
                "fixture": {
                    "opponent": opponent,
                    "venue": "Home" if (fixture and fixture["is_home"]) else "Away",
                    "fdr": fixture["fdr"] if fixture else None,
                    "gameweek": gameweek,
                }
                if fixture
                else None,
                "score": score,
                "reasoning": _build_reasoning(player, fixture, score),
                "stats": {
                    "form": float(player.get("form") or 0),
                    "points_per_game": float(player.get("points_per_game") or 0),
                    "ict_index": float(player.get("ict_index") or 0),
                    "total_points": player.get("total_points", 0),
                    "bonus": player.get("bonus", 0),
                },
            }
        )

    return {
        "gameweek": gameweek,
        "algorithm_version": "1.0",
        "picks": picks,
    }


async def _gather_data():
    """Fetch bootstrap and fixtures concurrently."""
    import asyncio

    return await asyncio.gather(get_bootstrap(), get_fixtures())
