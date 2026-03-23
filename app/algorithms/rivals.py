"""
Mini-League Rival Intelligence.

Answers: "How do I beat my rivals?" and "What are they likely to do next?"

Given a league_id and the user's team_id, this algorithm:
1. Fetches league standings and identifies nearby rivals
2. Compares squads to find differentials (players you have vs they don't)
3. Analyzes rival transfer patterns to predict their next moves
4. Suggests counter-strategies based on rival weaknesses
"""

import asyncio

from app.algorithms import INJURY_STATUSES
from app.algorithms.captain import _build_fixture_map
from app.fpl_client import (
    get_bootstrap,
    get_current_gameweek,
    get_fixtures,
    get_league_standings,
    get_manager_transfers,
    get_next_gameweek,
    get_team_picks,
)

# How many rivals above and below the user to analyze in detail
RIVAL_WINDOW = 3


async def get_rival_analysis(league_id: int, team_id: int) -> dict:
    """
    Full rival intelligence report for a mini-league.

    Fetches league standings, compares squads with nearby rivals,
    analyzes transfer patterns, and suggests counter-strategies.
    """
    bootstrap, fixtures, standings_data = await asyncio.gather(
        get_bootstrap(),
        get_fixtures(),
        get_league_standings(league_id),
    )

    current_gw = get_current_gameweek(bootstrap)
    next_gw = get_next_gameweek(bootstrap)
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}

    league_info = standings_data.get("league", {})
    standings = standings_data.get("standings", {}).get("results", [])

    if not standings:
        return {
            "league_id": league_id,
            "error": "League not found or has no standings.",
        }

    # Find the user's position in the league
    user_standing = None
    user_idx = None
    for i, s in enumerate(standings):
        if s["entry"] == team_id:
            user_standing = s
            user_idx = i
            break

    if user_standing is None:
        return {
            "league_id": league_id,
            "league_name": league_info.get("name", "Unknown"),
            "error": f"Team {team_id} not found in this league. Check your team ID.",
        }

    # Identify rivals: RIVAL_WINDOW above and below the user
    start = max(0, user_idx - RIVAL_WINDOW)
    end = min(len(standings), user_idx + RIVAL_WINDOW + 1)
    rival_standings = [s for s in standings[start:end] if s["entry"] != team_id]

    # Fetch user's picks and all rival picks concurrently
    all_entries = [team_id] + [r["entry"] for r in rival_standings]
    picks_tasks = [get_team_picks(entry, current_gw) for entry in all_entries]
    all_picks = await asyncio.gather(*picks_tasks, return_exceptions=True)

    # Parse user squad
    user_picks_data = all_picks[0]
    if isinstance(user_picks_data, Exception):
        return {"league_id": league_id, "error": "Failed to fetch your squad."}

    user_player_ids = {p["element"] for p in user_picks_data.get("picks", [])}
    user_captain_id = next(
        (p["element"] for p in user_picks_data.get("picks", []) if p["is_captain"]),
        None,
    )

    # Build fixture map for next GW (for player scoring context)
    fixture_map = _build_fixture_map(fixtures, next_gw, teams_by_id=teams_by_id)

    # Analyze each rival
    rival_analyses = []
    for i, rival in enumerate(rival_standings):
        rival_picks_data = all_picks[i + 1]  # +1 because user is index 0
        if isinstance(rival_picks_data, Exception):
            continue

        rival_picks = rival_picks_data.get("picks", [])
        rival_player_ids = {p["element"] for p in rival_picks}
        rival_captain_id = next(
            (p["element"] for p in rival_picks if p["is_captain"]),
            None,
        )

        # Differentials: players in your team but NOT in rival's
        your_differentials = user_player_ids - rival_player_ids
        their_differentials = rival_player_ids - user_player_ids

        # Format differentials with player details
        your_diff_details = _format_player_list(your_differentials, players_by_id, teams_by_id, fixture_map)
        their_diff_details = _format_player_list(their_differentials, players_by_id, teams_by_id, fixture_map)

        # Captain comparison
        captain_info = None
        if rival_captain_id:
            rival_cap = players_by_id.get(rival_captain_id, {})
            user_cap = players_by_id.get(user_captain_id, {})
            captain_info = {
                "rival_captain": {
                    "player_id": rival_cap.get("id"),
                    "name": rival_cap.get("web_name", "?"),
                    "team": teams_by_id.get(rival_cap.get("team"), {}).get("short_name", "?"),
                },
                "your_captain": {
                    "player_id": user_cap.get("id"),
                    "name": user_cap.get("web_name", "?"),
                    "team": teams_by_id.get(user_cap.get("team"), {}).get("short_name", "?"),
                },
                "same_captain": rival_captain_id == user_captain_id,
            }

        # Point gap and direction
        point_gap = user_standing["total"] - rival["total"]

        # Rival squad weaknesses
        weaknesses = _find_weaknesses(rival_picks, players_by_id, fixture_map, teams_by_id)

        rival_analyses.append(
            {
                "manager_name": rival["player_name"],
                "team_name": rival["entry_name"],
                "team_id": rival["entry"],
                "rank": rival["rank"],
                "total_points": rival["total"],
                "gw_points": rival["event_total"],
                "point_gap": point_gap,
                "gap_direction": "ahead" if point_gap > 0 else "behind" if point_gap < 0 else "tied",
                "captain": captain_info,
                "your_differentials": your_diff_details,
                "their_differentials": their_diff_details,
                "shared_players": len(user_player_ids & rival_player_ids),
                "weaknesses": weaknesses,
            }
        )

    # Fetch transfer history for closest rivals (top 2 by proximity)
    closest_rivals = sorted(rival_analyses, key=lambda r: abs(r["point_gap"]))[:2]
    transfer_tasks = [get_manager_transfers(r["team_id"]) for r in closest_rivals]
    transfer_results = await asyncio.gather(*transfer_tasks, return_exceptions=True)

    for i, rival in enumerate(closest_rivals):
        transfers = transfer_results[i]
        if isinstance(transfers, Exception):
            continue
        rival["recent_transfers"] = _format_transfers(transfers, players_by_id, teams_by_id, current_gw)
        rival["transfer_prediction"] = _predict_next_move(
            rival["team_id"],
            [p for r in rival_analyses if r["team_id"] == rival["team_id"] for p in []],
            transfers,
            players_by_id,
            teams_by_id,
            fixture_map,
            # Get rival's actual picks
            next(
                (all_picks[j + 1] for j, r in enumerate(rival_standings) if r["entry"] == rival["team_id"]),
                {},
            ),
        )

    # Strategic summary
    strategy = _build_strategy(user_standing, rival_analyses, players_by_id, teams_by_id, fixture_map)

    # Determine if current GW is finished — if so, frame analysis for next GW
    current_event = next((gw for gw in bootstrap["events"] if gw["id"] == current_gw), {})
    planning_gw = next_gw if current_event.get("finished") else current_gw

    return {
        "league_id": league_id,
        "league_name": league_info.get("name", "Unknown"),
        "total_managers": len(standings),
        "gameweek": planning_gw,
        "standings_as_of_gw": current_gw,
        "your_position": {
            "rank": user_standing["rank"],
            "total_points": user_standing["total"],
            "gw_points": user_standing["event_total"],
            "team_name": user_standing["entry_name"],
        },
        "rivals": rival_analyses,
        "strategy": strategy,
    }


def _format_player_list(
    player_ids: set[int],
    players_by_id: dict,
    teams_by_id: dict,
    fixture_map: dict,
) -> list[dict]:
    """Format a set of player IDs into readable details with upcoming fixture info."""
    result = []
    for pid in player_ids:
        p = players_by_id.get(pid)
        if not p:
            continue
        team_short = teams_by_id.get(p["team"], {}).get("short_name", "?")
        player_fixes = fixture_map.get(p["team"], [])
        next_opponents = []
        for f in player_fixes:
            opp = teams_by_id.get(f["opponent"], {}).get("short_name", "?")
            venue = "H" if f["is_home"] else "A"
            next_opponents.append(f"{opp}({venue})")

        result.append(
            {
                "player_id": p["id"],
                "name": p["web_name"],
                "team": team_short,
                "team_full_name": teams_by_id.get(p["team"], {}).get("name", "?"),
                "form": float(p.get("form") or 0),
                "points_per_game": float(p.get("points_per_game") or 0),
                "cost": p.get("now_cost", 0) / 10,
                "next_fixture": ", ".join(next_opponents) if next_opponents else "Blank",
            }
        )
    # Sort by form descending
    result.sort(key=lambda x: x["form"], reverse=True)
    return result


def _find_weaknesses(
    rival_picks: list[dict],
    players_by_id: dict,
    fixture_map: dict,
    teams_by_id: dict,
) -> list[str]:
    """Identify weaknesses in a rival's squad."""
    weaknesses = []

    # Check for injured/doubtful players
    injured = []
    for pick in rival_picks:
        p = players_by_id.get(pick["element"], {})
        if p.get("status") in INJURY_STATUSES:
            injured.append(p.get("web_name", "?"))
    if injured:
        weaknesses.append(f"Injured/doubtful: {', '.join(injured)}")

    # Check for players with blank GW (no fixture)
    blanks = []
    for pick in rival_picks:
        if pick["position"] > 11:
            continue  # skip bench
        p = players_by_id.get(pick["element"], {})
        if not fixture_map.get(p.get("team")):
            blanks.append(p.get("web_name", "?"))
    if blanks:
        weaknesses.append(f"Blank GW (no fixture): {', '.join(blanks)}")

    # Check for poor form starters
    poor_form = []
    for pick in rival_picks:
        if pick["position"] > 11:
            continue
        p = players_by_id.get(pick["element"], {})
        form = float(p.get("form") or 0)
        if form < 3.0:
            poor_form.append(f"{p.get('web_name', '?')} ({form})")
    if len(poor_form) >= 3:
        weaknesses.append(f"Poor form starters: {', '.join(poor_form[:4])}")

    # Check for tough fixtures
    tough_fixtures = []
    for pick in rival_picks:
        if pick["position"] > 11:
            continue
        p = players_by_id.get(pick["element"], {})
        player_fixes = fixture_map.get(p.get("team"), [])
        if player_fixes:
            avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
            if avg_fdr >= 4.0:
                opp = teams_by_id.get(player_fixes[0]["opponent"], {}).get("short_name", "?")
                tough_fixtures.append(f"{p.get('web_name', '?')} vs {opp}")
    if tough_fixtures:
        weaknesses.append(f"Tough fixtures: {', '.join(tough_fixtures[:3])}")

    if not weaknesses:
        weaknesses.append("No obvious weaknesses — strong squad")

    return weaknesses


def _format_transfers(
    transfers: list[dict],
    players_by_id: dict,
    teams_by_id: dict,
    current_gw: int,
) -> list[dict]:
    """Format recent transfers (last 3 GWs) into readable details."""
    recent = [t for t in transfers if t.get("event", 0) >= current_gw - 2]
    result = []
    for t in recent[:6]:  # max 6 recent transfers
        player_in = players_by_id.get(t["element_in"], {})
        player_out = players_by_id.get(t["element_out"], {})
        result.append(
            {
                "gameweek": t["event"],
                "in": {
                    "player_id": player_in.get("id"),
                    "name": player_in.get("web_name", "?"),
                    "team": teams_by_id.get(player_in.get("team"), {}).get("short_name", "?"),
                    "cost": t["element_in_cost"] / 10,
                },
                "out": {
                    "player_id": player_out.get("id"),
                    "name": player_out.get("web_name", "?"),
                    "team": teams_by_id.get(player_out.get("team"), {}).get("short_name", "?"),
                    "cost": t["element_out_cost"] / 10,
                },
            }
        )
    return result


def _predict_next_move(
    rival_team_id: int,
    _unused: list,
    transfers: list[dict],
    players_by_id: dict,
    teams_by_id: dict,
    fixture_map: dict,
    rival_picks_data: dict,
) -> dict:
    """
    Predict a rival's likely next transfer based on their squad and patterns.

    Heuristics:
    - Injured starters are top transfer-out candidates
    - Players with tough fixtures + poor form are likely transfers out
    - Popular players rising in price that the rival doesn't own are likely transfers in
    """
    rival_picks = rival_picks_data.get("picks", []) if isinstance(rival_picks_data, dict) else []
    rival_player_ids = {p["element"] for p in rival_picks}

    # Find likely transfer OUT candidates (from their squad)
    transfer_out_candidates = []
    for pick in rival_picks:
        if pick["position"] > 11:
            continue  # bench players less likely to be transferred
        p = players_by_id.get(pick["element"], {})
        urgency = 0.0

        # Injured = high urgency
        if p.get("status") in INJURY_STATUSES:
            urgency += 10.0

        # Poor form
        form = float(p.get("form") or 0)
        if form < 3.0:
            urgency += (3.0 - form) * 2.0

        # Tough upcoming fixtures
        player_fixes = fixture_map.get(p.get("team"), [])
        if player_fixes:
            avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
            if avg_fdr >= 3.5:
                urgency += (avg_fdr - 3.0) * 2.0
        else:
            urgency += 3.0  # blank GW

        # Price dropping
        cost_change = p.get("cost_change_event", 0)
        if cost_change < 0:
            urgency += 2.0

        if urgency > 3.0:
            transfer_out_candidates.append(
                {
                    "player_id": p.get("id"),
                    "name": p.get("web_name", "?"),
                    "team": teams_by_id.get(p.get("team"), {}).get("short_name", "?"),
                    "reason": _transfer_out_reason(p, fixture_map, teams_by_id),
                    "urgency": round(urgency, 1),
                }
            )

    transfer_out_candidates.sort(key=lambda x: x["urgency"], reverse=True)

    # Find likely transfer IN candidates (popular players they don't own)
    transfer_in_candidates = []
    for p in bootstrap_top_transfers_in(players_by_id, rival_player_ids, fixture_map, teams_by_id):
        transfer_in_candidates.append(p)

    return {
        "likely_transfers_out": transfer_out_candidates[:3],
        "likely_transfers_in": transfer_in_candidates[:3],
    }


def _transfer_out_reason(player: dict, fixture_map: dict, teams_by_id: dict) -> str:
    """Generate a human-readable reason for a predicted transfer out."""
    reasons = []
    if player.get("status") in INJURY_STATUSES:
        reasons.append("injured/doubtful")
    form = float(player.get("form") or 0)
    if form < 3.0:
        reasons.append(f"poor form ({form})")
    player_fixes = fixture_map.get(player.get("team"), [])
    if not player_fixes:
        reasons.append("blank GW")
    elif player_fixes:
        avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
        if avg_fdr >= 4.0:
            opp = teams_by_id.get(player_fixes[0]["opponent"], {}).get("short_name", "?")
            reasons.append(f"tough fixture ({opp})")
    return ", ".join(reasons) if reasons else "underperforming"


def bootstrap_top_transfers_in(
    players_by_id: dict,
    rival_player_ids: set[int],
    fixture_map: dict,
    teams_by_id: dict,
) -> list[dict]:
    """Find the most likely transfer-in targets a rival might pick."""
    candidates = []
    for pid, p in players_by_id.items():
        if pid in rival_player_ids:
            continue
        # Only consider in-form players with good fixtures
        form = float(p.get("form") or 0)
        if form < 5.0:
            continue
        if p.get("status") in INJURY_STATUSES:
            continue

        player_fixes = fixture_map.get(p.get("team"), [])
        if not player_fixes:
            continue

        # Score based on form + transfers in volume + easy fixtures
        transfers_in = p.get("transfers_in_event", 0)
        avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
        score = form * 2.0 + (5 - avg_fdr) * 1.5 + (transfers_in / 100000)

        candidates.append(
            {
                "player_id": pid,
                "name": p.get("web_name", "?"),
                "team": teams_by_id.get(p.get("team"), {}).get("short_name", "?"),
                "form": form,
                "cost": p.get("now_cost", 0) / 10,
                "transfers_in_this_gw": transfers_in,
                "score": round(score, 1),
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:5]


def _build_strategy(
    user_standing: dict,
    rival_analyses: list[dict],
    players_by_id: dict,
    teams_by_id: dict,
    fixture_map: dict,
) -> list[str]:
    """Build strategic recommendations based on rival analysis."""
    tips = []

    # Rivals ahead
    rivals_ahead = [r for r in rival_analyses if r["point_gap"] < 0]
    rivals_behind = [r for r in rival_analyses if r["point_gap"] > 0]

    if rivals_ahead:
        closest_ahead = min(rivals_ahead, key=lambda r: abs(r["point_gap"]))
        gap = abs(closest_ahead["point_gap"])
        tips.append(
            f"You're {gap}pts behind {closest_ahead['manager_name']} (rank {closest_ahead['rank']}). "
            f"You share {closest_ahead['shared_players']} players — "
            f"focus on your {len(closest_ahead['your_differentials'])} differentials to close the gap."
        )

        # Check if rival's captain is different
        cap = closest_ahead.get("captain", {})
        if cap and not cap.get("same_captain"):
            tips.append(
                f"{closest_ahead['manager_name']} captained {cap['rival_captain']['name']}. "
                f"If your captain {cap['your_captain']['name']} outscores theirs, you gain double the margin."
            )

    if rivals_behind:
        closest_behind = min(rivals_behind, key=lambda r: r["point_gap"])
        gap = closest_behind["point_gap"]
        tips.append(
            f"You're {gap}pts ahead of {closest_behind['manager_name']}. "
            f"They have {len(closest_behind['their_differentials'])} players you don't — "
            f"watch for hauls from those differentials."
        )

    # Differential exploitation
    for rival in rival_analyses[:2]:
        for diff in rival.get("your_differentials", [])[:2]:
            if diff["form"] >= 5.0:
                tips.append(
                    f"Your differential {diff['name']} (form {diff['form']}) isn't in "
                    f"{rival['manager_name']}'s squad — a haul here widens the gap."
                )
                break

    # Weakness exploitation
    for rival in rival_analyses[:2]:
        for weakness in rival.get("weaknesses", []):
            if "Injured" in weakness or "Blank" in weakness:
                tips.append(
                    f"{rival['manager_name']}'s vulnerability: {weakness}. They may need to use a transfer on this."
                )
                break

    if not tips:
        tips.append("Your league is tight — every captain pick and transfer counts.")

    return tips
