"""
Hit Analyzer algorithm.

Answers: "Should I take a -4 hit for this transfer?"

Projects expected points for both player_out and player_in over the next
N gameweeks, factoring in form, FDR, points per game, and home/away splits.
If the projected gain exceeds 4 points, the hit is worth it.
"""

import asyncio

from app.algorithms import INJURY_STATUSES, POSITION_MAP
from app.fpl_client import get_bootstrap, get_fixtures, get_next_gameweek

# Multipliers for expected-points projection per fixture
HOME_BOOST = 1.15  # 15% boost for home fixtures
AWAY_PENALTY = 0.95  # 5% penalty for away fixtures

# FDR multipliers: easier fixture = more expected points
FDR_MULTIPLIER = {
    1: 1.30,  # very easy
    2: 1.15,  # easy
    3: 1.00,  # average
    4: 0.85,  # tough
    5: 0.70,  # very tough
}


def _build_multi_gw_fixture_map(
    fixtures: list,
    start_gw: int,
    num_gws: int,
) -> dict[int, list[dict]]:
    """
    Map team_id -> list of fixture dicts across multiple gameweeks.
    Each fixture includes gameweek, FDR, is_home, and opponent team ID.
    """
    target_gws = set(range(start_gw, start_gw + num_gws))
    fixture_map: dict[int, list[dict]] = {}

    for fix in fixtures:
        gw = fix.get("event")
        if gw not in target_gws:
            continue

        home_id = fix["team_h"]
        away_id = fix["team_a"]

        fixture_map.setdefault(home_id, []).append(
            {
                "gameweek": gw,
                "fdr": fix["team_h_difficulty"],
                "is_home": True,
                "opponent": away_id,
            }
        )
        fixture_map.setdefault(away_id, []).append(
            {
                "gameweek": gw,
                "fdr": fix["team_a_difficulty"],
                "is_home": False,
                "opponent": home_id,
            }
        )

    return fixture_map


def _project_expected_points(player: dict, fixtures: list[dict]) -> float:
    """
    Project expected points for a player over a set of fixtures.

    Base rate = weighted average of form and PPG.
    Each fixture adjusts the base rate by FDR and home/away.
    """
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)

    # Weighted base: form is more recent so weigh it slightly more
    base_rate = form * 0.6 + ppg * 0.4

    # Playing chance adjustment
    status = player.get("status", "a")
    chance = player.get("chance_of_playing_next_round")
    if status in INJURY_STATUSES:
        if chance is not None:
            playing_pct = float(chance) / 100.0
        else:
            playing_pct = 0.0  # injured with no chance info = assume out
    else:
        playing_pct = 1.0

    total = 0.0
    for fix in fixtures:
        fdr = fix["fdr"]
        fdr_mult = FDR_MULTIPLIER.get(fdr, 1.0)
        venue_mult = HOME_BOOST if fix["is_home"] else AWAY_PENALTY
        total += base_rate * fdr_mult * venue_mult * playing_pct

    return round(total, 2)


def _build_player_summary(
    player: dict,
    team_name: str,
    fixtures: list[dict],
    expected_pts: float,
    teams_by_id: dict,
) -> dict:
    """Build a summary dict for a player in the analysis."""
    fixture_details = []
    for fix in sorted(fixtures, key=lambda f: f["gameweek"]):
        opp = teams_by_id.get(fix["opponent"], {}).get("short_name", "?")
        venue = "H" if fix["is_home"] else "A"
        fixture_details.append(
            {
                "gameweek": fix["gameweek"],
                "opponent": f"{opp}({venue})",
                "fdr": fix["fdr"],
            }
        )

    return {
        "id": player["id"],
        "name": player["web_name"],
        "team": team_name,
        "position": POSITION_MAP.get(player["element_type"], "?"),
        "cost": player["now_cost"] / 10,
        "form": float(player.get("form") or 0),
        "points_per_game": float(player.get("points_per_game") or 0),
        "total_points": player.get("total_points", 0),
        "status": player.get("status", "a"),
        "expected_points_projected": expected_pts,
        "fixtures": fixture_details,
    }


async def analyze_hit(
    player_out_id: int,
    player_in_id: int,
    gameweeks_ahead: int = 5,
) -> dict:
    """
    Analyze whether a -4 point hit is worth it for a given transfer.

    Returns a recommendation with projected points for both players,
    the net gain/loss, and a clear verdict.
    """
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    next_gw = get_next_gameweek(bootstrap)

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}

    player_out = players_by_id.get(player_out_id)
    player_in = players_by_id.get(player_in_id)

    if not player_out:
        return {"error": f"Player with ID {player_out_id} not found."}
    if not player_in:
        return {"error": f"Player with ID {player_in_id} not found."}

    # Build fixture map across the projection window
    fixture_map = _build_multi_gw_fixture_map(fixtures, next_gw, gameweeks_ahead)

    out_fixtures = fixture_map.get(player_out["team"], [])
    in_fixtures = fixture_map.get(player_in["team"], [])

    out_expected = _project_expected_points(player_out, out_fixtures)
    in_expected = _project_expected_points(player_in, in_fixtures)

    net_gain = round(in_expected - out_expected, 2)
    net_after_hit = round(net_gain - 4, 2)
    hit_worth_it = net_after_hit > 0

    # Build reasoning
    if hit_worth_it:
        if net_after_hit >= 8:
            confidence = "high"
            verdict = (
                f"Strongly recommended. {player_in['web_name']} is projected to outscore "
                f"{player_out['web_name']} by {net_gain} points over {gameweeks_ahead} GWs. "
                f"Even after the -4 hit, you gain ~{net_after_hit} points."
            )
        elif net_after_hit >= 4:
            confidence = "medium-high"
            verdict = (
                f"Recommended. The projected gain of {net_gain} points comfortably covers "
                f"the -4 hit, leaving a net benefit of ~{net_after_hit} points."
            )
        else:
            confidence = "medium"
            verdict = (
                f"Marginal but positive. The projected gain of {net_gain} points just about "
                f"covers the -4 hit (net ~{net_after_hit}). Consider waiting if you have "
                f"a free transfer coming."
            )
    else:
        if net_after_hit >= -2:
            confidence = "low"
            verdict = (
                f"Not recommended, but close. The projected gain of {net_gain} points "
                f"doesn't quite cover the -4 hit (net ~{net_after_hit}). "
                f"Wait for a free transfer if possible."
            )
        else:
            confidence = "low"
            verdict = (
                f"Not worth it. {player_in['web_name']} is only projected to outscore "
                f"{player_out['web_name']} by {net_gain} points over {gameweeks_ahead} GWs. "
                f"After the -4 hit, you'd lose ~{abs(net_after_hit)} points."
            )

    out_team = teams_by_id.get(player_out["team"], {}).get("short_name", "?")
    in_team = teams_by_id.get(player_in["team"], {}).get("short_name", "?")

    return {
        "gameweek": next_gw,
        "gameweeks_projected": gameweeks_ahead,
        "player_out": _build_player_summary(
            player_out,
            out_team,
            out_fixtures,
            out_expected,
            teams_by_id,
        ),
        "player_in": _build_player_summary(
            player_in,
            in_team,
            in_fixtures,
            in_expected,
            teams_by_id,
        ),
        "analysis": {
            "player_out_expected_points": out_expected,
            "player_in_expected_points": in_expected,
            "projected_gain": net_gain,
            "hit_cost": -4,
            "net_after_hit": net_after_hit,
            "hit_worth_it": hit_worth_it,
            "confidence": confidence,
        },
        "verdict": verdict,
    }
