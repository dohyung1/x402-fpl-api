"""Shared constants and helpers for FPL algorithm modules."""

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
INJURY_STATUSES = {"i", "d", "s", "u"}  # injured, doubtful, suspended, unavailable


def detect_streak(player: dict) -> dict:
    """
    Detect hot/cold streak by comparing recent form to season points_per_game.

    Uses FPL bootstrap-static fields (no extra API calls):
    - form: recent average points (string like "6.2")
    - points_per_game: season PPG (string like "4.8")

    Heuristic:
    - form > ppg * 1.3 → hot streak (significantly outperforming)
    - form < ppg * 0.7 → cold streak (significantly underperforming)
    - otherwise → neutral
    """
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)

    # Need meaningful minutes to judge streaks
    if ppg <= 0 or form <= 0:
        return {"streak": "neutral", "detail": "Insufficient data"}

    ratio = form / ppg

    if ratio > 1.3:
        return {
            "streak": "hot",
            "detail": f"Form {form} well above season avg {ppg}",
        }
    elif ratio < 0.7:
        return {
            "streak": "cold",
            "detail": f"Form {form} well below season avg {ppg}",
        }
    else:
        return {
            "streak": "neutral",
            "detail": f"Form {form} in line with season avg {ppg}",
        }
