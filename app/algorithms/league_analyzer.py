"""
League Win Probability Analyzer.

Answers: "Who is going to win this league?" without requiring the user's team ID.

For each top manager, calculates a win probability based on:
- Points gap from leader (biggest factor — diminishing returns)
- Squad quality (aggregate form + fixture difficulty of starting XI)
- Chips remaining (unused chips = potential points boost)
- Recent momentum (trend over last 5 GWs vs league average)
- Gameweeks remaining (more GWs = more uncertainty = more chances to catch up)
"""

import asyncio

from app.algorithms.captain import INJURY_STATUSES, _build_fixture_map
from app.fpl_client import (
    get_bootstrap,
    get_current_gameweek,
    get_fixtures,
    get_league_standings,
    get_next_gameweek,
    get_team_history,
    get_team_picks,
)

# Max managers to analyze in detail (fetching squad/history is expensive)
MAX_ANALYZED = 10


async def analyze_league(league_id: int) -> dict:
    """
    Full league analysis with win probability for each top manager.

    Fetches standings, then for each top manager: squad, chips, GW history.
    Calculates a composite win probability score.
    """
    bootstrap, fixtures, standings_data = await asyncio.gather(
        get_bootstrap(),
        get_fixtures(),
        get_league_standings(league_id),
    )

    current_gw = get_current_gameweek(bootstrap)
    next_gw = get_next_gameweek(bootstrap)
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}

    # Determine if current GW is finished
    current_event = next((gw for gw in bootstrap["events"] if gw["id"] == current_gw), {})
    planning_gw = next_gw if current_event.get("finished") else current_gw

    # How many GWs left
    finished_gws = sum(1 for e in bootstrap["events"] if e.get("finished"))
    gws_remaining = 38 - finished_gws

    league_info = standings_data.get("league", {})
    standings = standings_data.get("standings", {}).get("results", [])

    if not standings:
        return {"league_id": league_id, "error": "League not found or has no standings."}

    # Analyze top N managers
    top_managers = standings[:MAX_ANALYZED]
    leader_points = top_managers[0]["total"] if top_managers else 0

    # Fetch squad picks and history for all top managers concurrently
    picks_tasks = [get_team_picks(m["entry"], current_gw) for m in top_managers]
    history_tasks = [get_team_history(m["entry"]) for m in top_managers]
    all_results = await asyncio.gather(*picks_tasks, *history_tasks, return_exceptions=True)

    all_picks = all_results[: len(top_managers)]
    all_histories = all_results[len(top_managers) :]

    # Build fixture map for upcoming GW
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, planning_gw, teams_by_id=teams_by_id)

    # Calculate raw scores for each manager
    manager_analyses = []
    for i, manager in enumerate(top_managers):
        picks_data = all_picks[i]
        history_data = all_histories[i]

        if isinstance(picks_data, Exception) or isinstance(history_data, Exception):
            manager_analyses.append(
                {
                    "manager_name": manager["player_name"],
                    "team_name": manager["entry_name"],
                    "team_id": manager["entry"],
                    "rank": manager["rank"],
                    "total_points": manager["total"],
                    "points_from_leader": manager["total"] - leader_points,
                    "win_probability": None,
                    "error": "Could not fetch squad data",
                }
            )
            continue

        entry_history = picks_data.get("entry_history", {})
        picks = picks_data.get("picks", [])
        history_current = history_data.get("current", [])
        chips = history_data.get("chips", [])

        # --- Factor 1: Points gap ---
        points_gap = manager["total"] - leader_points  # negative = behind

        # --- Factor 2: Squad quality (form + fixture ease of starting XI) ---
        squad_quality = _calculate_squad_quality(picks, players_by_id, fixture_map)

        # --- Factor 3: Chips remaining ---
        chips_remaining = _get_chips_remaining(chips, current_gw)

        # --- Factor 4: Recent momentum (last 5 GWs) ---
        momentum = _calculate_momentum(history_current, current_gw)

        # --- Factor 5: Bank balance ---
        bank = entry_history.get("bank", 0) / 10

        # --- Factor 6: Team value ---
        team_value = _calculate_team_value(picks, players_by_id)

        # --- Factor 7: Squad health (injuries/doubts) ---
        injury_count = sum(
            1
            for p in picks
            if p["position"] <= 11 and players_by_id.get(p["element"], {}).get("status") in INJURY_STATUSES
        )

        manager_analyses.append(
            {
                "manager_name": manager["player_name"],
                "team_name": manager["entry_name"],
                "team_id": manager["entry"],
                "rank": manager["rank"],
                "total_points": manager["total"],
                "gw_points": manager["event_total"],
                "points_from_leader": points_gap,
                "squad_quality": round(squad_quality, 1),
                "chips_remaining": chips_remaining,
                "momentum_last_5gw": round(momentum, 1),
                "bank": round(bank, 1),
                "team_value": round(team_value, 1),
                "injured_starters": injury_count,
                "_raw_score": 0.0,  # calculated below
            }
        )

    # Calculate win probabilities from raw scores
    _calculate_win_probabilities(manager_analyses, gws_remaining)

    # Build narrative insights
    insights = _build_insights(manager_analyses, gws_remaining)

    return {
        "league_id": league_id,
        "league_name": league_info.get("name", "Unknown"),
        "total_managers": len(standings),
        "gameweek": planning_gw,
        "gameweeks_remaining": gws_remaining,
        "analyzed_top": len(manager_analyses),
        "managers": manager_analyses,
        "insights": insights,
    }


def _calculate_squad_quality(
    picks: list[dict],
    players_by_id: dict,
    fixture_map: dict,
) -> float:
    """
    Score squad quality based on form and fixture ease of the starting XI.

    Higher = better squad. Range roughly 0-100.
    """
    total = 0.0
    for pick in picks:
        if pick["position"] > 11:
            continue  # bench
        p = players_by_id.get(pick["element"], {})
        form = float(p.get("form") or 0)
        ppg = float(p.get("points_per_game") or 0)

        # Fixture ease: lower FDR = better
        player_fixes = fixture_map.get(p.get("team"), [])
        if player_fixes:
            avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
            fixture_bonus = (5 - avg_fdr) * 1.5  # max ~6
        else:
            fixture_bonus = -2.0  # blank GW penalty

        total += form + ppg + fixture_bonus

    return total


def _get_chips_remaining(chips: list[dict], current_gw: int) -> list[str]:
    """Get list of unused chips for the current half of the season."""
    all_chips = {"wildcard", "bboost", "freehit", "3xc"}
    halfway_gw = 19

    if current_gw > halfway_gw:
        chips_used = {c["name"] for c in chips if c["event"] > halfway_gw}
    else:
        chips_used = {c["name"] for c in chips if c["event"] <= halfway_gw}

    return sorted(all_chips - chips_used)


def _calculate_momentum(history_current: list[dict], current_gw: int) -> float:
    """
    Calculate recent momentum — average points over last 5 GWs.
    Higher = on an upswing.
    """
    recent = [h for h in history_current if current_gw - 5 < h.get("event", 0) <= current_gw]
    if not recent:
        return 0.0
    return sum(h.get("points", 0) for h in recent) / len(recent)


def _calculate_team_value(picks: list[dict], players_by_id: dict) -> float:
    """Calculate total squad value in millions."""
    total = 0
    for pick in picks:
        p = players_by_id.get(pick["element"], {})
        total += p.get("now_cost", 0)
    return total / 10


def _calculate_win_probabilities(managers: list[dict], gws_remaining: int) -> None:
    """
    Convert raw factors into win probabilities using a scoring model.

    The model weights:
    - Points gap (dominant factor, especially late season)
    - Squad quality (matters more with more GWs remaining)
    - Chips remaining (each unused chip ≈ 5-15 point potential)
    - Momentum (recent form as a trend indicator)
    - Team value + bank (transfer flexibility)
    """
    valid = [m for m in managers if m.get("win_probability") is not None or "error" not in m]

    if not valid:
        return

    # Late-season factor: points gap matters more as season ends
    # Early = 0.3, Late = 0.9
    season_progress = max(0.0, min(1.0, (38 - gws_remaining) / 38))
    gap_weight = 0.3 + 0.6 * season_progress

    leader_points = max(m["total_points"] for m in valid)

    for m in managers:
        if "error" in m:
            continue

        # Points gap score (0-100): leader gets 100, others decrease
        # Each point behind reduces score, but diminishing effect
        gap = leader_points - m["total_points"]
        if gws_remaining > 0:
            # Normalize gap by remaining GWs — a 20pt gap with 10 GWs left
            # is more surmountable than with 2 GWs left
            gap_per_gw = gap / gws_remaining
            gap_score = max(0, 100 - gap_per_gw * 8)
        else:
            gap_score = 100 if gap == 0 else 0

        # Squad quality score (normalized to 0-100)
        squad_scores = [m2["squad_quality"] for m2 in valid if "error" not in m2]
        max_sq = max(squad_scores) if squad_scores else 1
        min_sq = min(squad_scores) if squad_scores else 0
        sq_range = max_sq - min_sq if max_sq != min_sq else 1
        squad_score = ((m["squad_quality"] - min_sq) / sq_range) * 100

        # Chip advantage score (each chip ≈ 15 points on gap_score scale)
        chip_count = len(m["chips_remaining"])
        chip_score = min(100, chip_count * 25)

        # Momentum score (normalized)
        momentums = [m2["momentum_last_5gw"] for m2 in valid if "error" not in m2]
        max_mom = max(momentums) if momentums else 1
        min_mom = min(momentums) if momentums else 0
        mom_range = max_mom - min_mom if max_mom != min_mom else 1
        momentum_score = ((m["momentum_last_5gw"] - min_mom) / mom_range) * 100

        # Injury penalty
        injury_penalty = m["injured_starters"] * 10

        # Weighted composite score
        raw = (
            gap_score * gap_weight
            + squad_score * (0.25 * (1 - season_progress))  # matters less late season
            + chip_score * 0.15
            + momentum_score * 0.15
            - injury_penalty
        )
        m["_raw_score"] = max(0, raw)

    # Convert raw scores to probabilities (softmax-like normalization)
    total_raw = sum(m["_raw_score"] for m in managers if "error" not in m)
    for m in managers:
        if "error" in m:
            m["win_probability"] = 0.0
            continue
        if total_raw > 0:
            m["win_probability"] = round(m["_raw_score"] / total_raw * 100, 1)
        else:
            m["win_probability"] = round(100 / len(valid), 1)
        del m["_raw_score"]


def _build_insights(managers: list[dict], gws_remaining: int) -> list[str]:
    """Generate narrative insights about the title race."""
    insights = []
    valid = [m for m in managers if "error" not in m]
    if not valid:
        return ["Could not analyze managers."]

    # Sort by win probability
    by_prob = sorted(valid, key=lambda m: m.get("win_probability", 0), reverse=True)
    favourite = by_prob[0]

    insights.append(
        f"{favourite['manager_name']} ({favourite['team_name']}) is the favourite "
        f"at {favourite['win_probability']}% win probability — "
        f"{favourite['total_points']}pts, rank {favourite['rank']}."
    )

    # Check if it's a close race
    if len(by_prob) >= 2:
        gap = favourite["total_points"] - by_prob[1]["total_points"]
        if gap <= 10:
            insights.append(
                f"Tight race — only {gap}pts separate {favourite['manager_name']} "
                f"and {by_prob[1]['manager_name']}. With {gws_remaining} GWs left, anything can happen."
            )
        elif gap >= 50 and gws_remaining <= 8:
            insights.append(
                f"{favourite['manager_name']} has a commanding {gap}pt lead with only "
                f"{gws_remaining} GWs remaining — very difficult to overtake."
            )

    # Chip advantages
    for m in by_prob[:5]:
        chips = m.get("chips_remaining", [])
        if len(chips) >= 3:
            chip_names = ", ".join(
                c.replace("3xc", "Triple Captain").replace("bboost", "Bench Boost").replace("freehit", "Free Hit")
                for c in chips
            )
            insights.append(
                f"{m['manager_name']} still has {len(chips)} chips ({chip_names}) — "
                f"significant upside potential in the final stretch."
            )

    # Momentum swings
    hot_managers = [m for m in by_prob if m["momentum_last_5gw"] >= 65]
    cold_managers = [m for m in by_prob[:5] if m["momentum_last_5gw"] <= 45]

    for m in hot_managers[:2]:
        if m != favourite:
            insights.append(
                f"{m['manager_name']} is on a hot streak — averaging "
                f"{m['momentum_last_5gw']}pts over the last 5 GWs. Watch out."
            )

    for m in cold_managers[:1]:
        if m == favourite:
            insights.append(
                f"Warning: {m['manager_name']} leads but has cooled off recently "
                f"({m['momentum_last_5gw']}pts avg last 5 GWs). Door is open for challengers."
            )

    # Injury concerns for contenders
    for m in by_prob[:3]:
        if m["injured_starters"] >= 2:
            insights.append(
                f"{m['manager_name']} has {m['injured_starters']} injured starters — "
                f"may need to burn transfers or take hits."
            )

    return insights
