"""
Player Comparison algorithm — head-to-head comparison of 2-4 FPL players.

Fuzzy-matches player names against all FPL players (case-insensitive partial
match on web_name), then computes a rich stat profile for each including
captain score, upcoming fixtures, value metrics, and transfer momentum.

Returns a structured comparison with a verdict recommending the best pick.
"""

import asyncio

from app.algorithms import POSITION_MAP
from app.algorithms.captain import (
    _build_fixture_map,
    _score_player,
)
from app.algorithms.news import get_player_news
from app.fpl_client import get_bootstrap, get_fixtures, get_next_gameweek


def _fuzzy_match_player(name: str, elements: list[dict]) -> dict | None:
    """
    Match a player name against FPL web_name using case-insensitive partial matching.

    Priority:
      1. Exact match (case-insensitive)
      2. web_name starts with the query
      3. Query appears anywhere in web_name
      4. Query appears anywhere in full name (first_name + second_name)

    Returns the best match or None.
    """
    query = name.strip().lower()
    if not query:
        return None

    exact = []
    starts_with = []
    contains = []
    full_name_contains = []

    for p in elements:
        web = p.get("web_name", "").lower()
        full = f"{p.get('first_name', '')} {p.get('second_name', '')}".lower()

        if web == query:
            exact.append(p)
        elif web.startswith(query):
            starts_with.append(p)
        elif query in web:
            contains.append(p)
        elif query in full:
            full_name_contains.append(p)

    # Return the highest-priority match; within a tier, prefer the player
    # with the most total points (most likely the one the user means).
    for group in (exact, starts_with, contains, full_name_contains):
        if group:
            return max(group, key=lambda p: p.get("total_points", 0))

    return None


def _build_upcoming_fixtures(
    team_id: int,
    fixtures: list,
    next_gw: int,
    gameweeks_ahead: int,
    teams_by_id: dict,
) -> list[dict]:
    """Build a list of upcoming fixtures with FDR for the next N gameweeks."""
    upcoming = []
    for gw in range(next_gw, next_gw + gameweeks_ahead):
        fixture_map = _build_fixture_map(fixtures, gw, teams_by_id=teams_by_id)
        gw_fixtures = fixture_map.get(team_id, [])
        for fix in gw_fixtures:
            opp = teams_by_id.get(fix["opponent"], {}).get("short_name", "?")
            venue = "H" if fix["is_home"] else "A"
            upcoming.append(
                {
                    "gameweek": gw,
                    "opponent": f"{opp}({venue})",
                    "fdr": fix["fdr"],
                    "is_home": fix["is_home"],
                }
            )
    return upcoming


def _build_verdict(profiles: list[dict]) -> str:
    """Generate a human-readable verdict recommending the best pick and why."""
    if not profiles:
        return "No players to compare."

    best = max(profiles, key=lambda p: p["captain_score"])
    name = best["name"]

    reasons = []

    # Captain score lead
    others = [p for p in profiles if p["name"] != name]
    if others:
        second_best = max(others, key=lambda p: p["captain_score"])
        margin = best["captain_score"] - second_best["captain_score"]
        if margin > 3:
            reasons.append(
                f"significantly higher captain score ({best['captain_score']:.1f} vs {second_best['captain_score']:.1f})"
            )
        elif margin > 0:
            reasons.append(f"higher captain score ({best['captain_score']:.1f} vs {second_best['captain_score']:.1f})")

    # Form
    if best["form"] >= 5:
        reasons.append(f"strong recent form ({best['form']:.1f})")

    # Fixtures
    upcoming = best.get("upcoming_fixtures", [])
    if upcoming:
        avg_fdr = sum(f["fdr"] for f in upcoming) / len(upcoming)
        if avg_fdr <= 2.5:
            reasons.append("excellent upcoming fixtures")
        elif avg_fdr <= 3.0:
            reasons.append("favourable upcoming fixtures")

    # Value
    if best["value_score"] > 0:
        best_value = max(profiles, key=lambda p: p["value_score"])
        if best_value["name"] == name:
            reasons.append(f"best value at {best['cost']}m")

    # xG
    if best["xg_per_90"] > 0.3:
        reasons.append(f"strong xG/90 ({best['xg_per_90']:.2f})")

    reason_str = ", ".join(reasons) if reasons else "marginally edges out the competition on overall score"

    # Check if it's close
    if others:
        runner_up = max(others, key=lambda p: p["captain_score"])
        gap = best["captain_score"] - runner_up["captain_score"]
        if gap < 1:
            return (
                f"{name} narrowly edges {runner_up['name']} — {reason_str}. "
                f"It's close though; {runner_up['name']} is a viable alternative."
            )

    return f"{name} is the clear pick — {reason_str}."


async def compare_players(
    player_names: list[str],
    gameweeks_ahead: int = 5,
) -> dict:
    """
    Compare 2-4 FPL players head-to-head.

    Args:
        player_names: List of 2-4 player names to compare (fuzzy matched).
        gameweeks_ahead: Number of upcoming gameweeks to include in fixture analysis.

    Returns:
        Structured comparison with per-player profiles and a verdict.
    """
    if len(player_names) < 2:
        return {"error": "Please provide at least 2 player names to compare."}
    if len(player_names) > 4:
        return {"error": "Please provide at most 4 player names to compare."}

    # Clamp gameweeks_ahead
    gameweeks_ahead = max(1, min(10, gameweeks_ahead))

    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    next_gw = get_next_gameweek(bootstrap)
    elements = bootstrap["elements"]
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}

    # Build the next-GW fixture map for captain scoring (with team strength blending)
    fixture_map = _build_fixture_map(fixtures, next_gw, teams_by_id=teams_by_id)

    # Match each name
    matched = []
    errors = []
    for name in player_names:
        player = _fuzzy_match_player(name, elements)
        if player is None:
            errors.append(f"No match found for '{name}'.")
        else:
            matched.append((name, player))

    if errors:
        return {
            "error": "Could not match all player names.",
            "details": errors,
            "matched": [{"query": q, "matched_name": p["web_name"]} for q, p in matched],
        }

    # Build profiles
    profiles = []
    for query, player in matched:
        team_id = player["team"]
        team = teams_by_id.get(team_id, {})
        player_fixtures = fixture_map.get(team_id)

        # Captain score
        captain_score = _score_player(player, player_fixtures)

        # Core stats
        minutes = player.get("minutes", 0)
        nineties = minutes / 90.0 if minutes > 0 else 0
        xg = float(player.get("expected_goals") or 0)
        xa = float(player.get("expected_assists") or 0)
        xg_per_90 = round(xg / nineties, 3) if nineties > 0 else 0.0
        xa_per_90 = round(xa / nineties, 3) if nineties > 0 else 0.0

        form = float(player.get("form") or 0)
        ppg = float(player.get("points_per_game") or 0)
        ep_next = float(player.get("ep_next") or 0)
        total_points = player.get("total_points", 0)
        cost = player["now_cost"] / 10
        ownership = float(player.get("selected_by_percent") or 0)
        ict = float(player.get("ict_index") or 0)

        # Defensive stat for GKP/DEF
        xgc_per_90 = None
        if player["element_type"] in (1, 2):  # GKP or DEF
            xgc_per_90 = float(player.get("expected_goals_conceded_per_90") or 0)

        # Defensive contribution for DEF/MID/FWD (2pts per defensive action)
        defensive_contribution_per_90 = None
        if player["element_type"] in (2, 3, 4):  # DEF, MID, FWD
            defensive_contribution_per_90 = float(player.get("defensive_contribution_per_90") or 0)

        # Net transfers (price pressure)
        transfers_in = player.get("transfers_in_event", 0)
        transfers_out = player.get("transfers_out_event", 0)
        net_transfers = transfers_in - transfers_out

        # Value score
        value_score = round(total_points / cost, 2) if cost > 0 else 0.0

        # Consistency scoring — based on points variance
        # A player who scores 5,5,5,5 is more consistent than 0,0,0,20
        # Lower variance = more reliable captain/pick
        starts = player.get("starts", 0)
        if starts > 0 and total_points > 0:
            # Approximate variance from bonus distribution and form stability
            # FPL doesn't give per-GW points in bootstrap, so we estimate:
            # High form relative to PPG = consistent recent performance
            form_ppg_ratio = form / ppg if ppg > 0 else 0
            consistency_score = round(min(10.0, form_ppg_ratio * ppg), 1)
        else:
            consistency_score = 0.0

        # Upcoming fixtures
        upcoming = _build_upcoming_fixtures(
            team_id,
            fixtures,
            next_gw,
            gameweeks_ahead,
            teams_by_id,
        )
        avg_fdr = round(sum(f["fdr"] for f in upcoming) / len(upcoming), 2) if upcoming else None

        profiles.append(
            {
                "query": query,
                "name": player["web_name"],
                "full_name": f"{player.get('first_name', '')} {player.get('second_name', '')}",
                "id": player["id"],
                "team": team.get("short_name", "?"),
                "team_full_name": team.get("name", "?"),
                "position": POSITION_MAP.get(player["element_type"], "?"),
                "cost": cost,
                "ownership_pct": ownership,
                "form": form,
                "points_per_game": ppg,
                "ep_next": ep_next,
                "total_points": total_points,
                "xg_per_90": xg_per_90,
                "xa_per_90": xa_per_90,
                "xgc_per_90": xgc_per_90,
                "defensive_contribution_per_90": defensive_contribution_per_90,
                "ict_index": ict,
                "captain_score": captain_score,
                "value_score": value_score,
                "consistency_score": consistency_score,
                "net_transfers_this_gw": net_transfers,
                "transfer_pressure": (
                    "Rising" if net_transfers > 50_000 else "Falling" if net_transfers < -50_000 else "Stable"
                ),
                "status": player.get("status", "a"),
                "chance_of_playing": player.get("chance_of_playing_next_round"),
                "news": get_player_news(player),
                "upcoming_fixtures": upcoming,
                "avg_fdr_next_{}_gws".format(gameweeks_ahead): avg_fdr,
            }
        )

    verdict = _build_verdict(profiles)

    return {
        "gameweek": next_gw,
        "gameweeks_ahead": gameweeks_ahead,
        "players": profiles,
        "verdict": verdict,
    }
