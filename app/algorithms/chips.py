"""
Chip Strategy algorithm v2 — multi-chip sequencing.

Answers: "When should I use my remaining chips?"

Key improvement over v1: evaluates chip COMBINATIONS, not just individual chips.
When multiple chips are available, the algorithm finds the optimal sequence:
  - WC→BB combo: Wildcard 1 GW before Bench Boost to rebuild squad for mega DGW
  - FH for BGWs: Free Hit targets gameweeks where many teams blank
  - TC for DGWs: Triple Captain targets DGWs with premium captaincy options
  - No two chips in the same gameweek

Scoring principles:
  - BB: dominated by confirmed DGW team count (mega DGW with 12 teams >> normal GW)
  - FH: dominated by blank team count (BGW with 16 teams blanking >> normal GW)
  - TC: DGW presence × best captain score (captain plays twice = 2x value)
  - WC: strategic — placed to maximize value of remaining chips (especially BB)

Includes DGW/BGW detection from FPL API (event=null fixtures) and community sources.
"""

import asyncio
import logging

from app.algorithms.captain import (
    INJURY_STATUSES,
    _build_fixture_map,
    _score_player,
)
from app.algorithms.dgw_intel import (
    fetch_community_dgw_intel,
    merge_intel_with_api_predictions,
)
from app.fpl_client import (
    get_bootstrap,
    get_current_gameweek,
    get_fixtures,
    get_next_gameweek,
    get_team_history,
    get_team_picks,
)

logger = logging.getLogger(__name__)

# How many gameweeks ahead to scan for chip opportunities
SCAN_WINDOW = 10

# All chip codes used by the FPL API
ALL_CHIPS = {"wildcard", "bboost", "freehit", "3xc"}

CHIP_DISPLAY = {
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
    "freehit": "Free Hit",
    "wildcard": "Wildcard",
}


def _count_dgw_teams(fixtures: list, gameweek: int) -> int:
    """Count how many teams have a double gameweek (2+ fixtures)."""
    team_counts: dict[int, int] = {}
    for fix in fixtures:
        if fix.get("event") != gameweek:
            continue
        team_counts[fix["team_h"]] = team_counts.get(fix["team_h"], 0) + 1
        team_counts[fix["team_a"]] = team_counts.get(fix["team_a"], 0) + 1
    return sum(1 for c in team_counts.values() if c >= 2)


def _get_dgw_team_ids(fixtures: list, gameweek: int) -> set[int]:
    """Get team IDs that have 2+ fixtures in a gameweek (confirmed DGW teams)."""
    team_counts: dict[int, int] = {}
    for fix in fixtures:
        if fix.get("event") != gameweek:
            continue
        team_counts[fix["team_h"]] = team_counts.get(fix["team_h"], 0) + 1
        team_counts[fix["team_a"]] = team_counts.get(fix["team_a"], 0) + 1
    return {tid for tid, c in team_counts.items() if c >= 2}


def _get_unscheduled_fixtures(fixtures: list) -> list[dict]:
    """Find postponed/unscheduled fixtures (event is null)."""
    return [f for f in fixtures if f.get("event") is None and not f.get("finished")]


def _predict_dgw_teams(fixtures: list) -> dict[int, list[dict]]:
    """Identify teams with pending unscheduled fixtures."""
    unscheduled = _get_unscheduled_fixtures(fixtures)
    teams_with_pending: dict[int, list[dict]] = {}
    for fix in unscheduled:
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        teams_with_pending.setdefault(home_id, []).append(
            {"opponent": away_id, "is_home": True, "fixture_id": fix.get("id")}
        )
        teams_with_pending.setdefault(away_id, []).append(
            {"opponent": home_id, "is_home": False, "fixture_id": fix.get("id")}
        )
    return teams_with_pending


def _estimate_likely_dgw_gameweeks(fixtures: list, next_gw: int, scan_gws: list[int]) -> dict[int, list[int]]:
    """Estimate which future gameweeks are likely to become DGWs."""
    teams_with_pending = _predict_dgw_teams(fixtures)
    if not teams_with_pending:
        return {}

    gw_fixture_counts: dict[int, dict[int, int]] = {}
    for gw in scan_gws:
        gw_fixture_counts[gw] = {}
        for fix in fixtures:
            if fix.get("event") != gw:
                continue
            for tid in (fix["team_h"], fix["team_a"]):
                if tid in teams_with_pending:
                    gw_fixture_counts[gw][tid] = gw_fixture_counts[gw].get(tid, 0) + 1

    likely_dgw_gws: dict[int, list[int]] = {}
    for gw in scan_gws:
        likely_teams = []
        for tid in teams_with_pending:
            existing = gw_fixture_counts.get(gw, {}).get(tid, 0)
            if existing == 1:
                likely_teams.append(tid)
        if likely_teams:
            likely_dgw_gws[gw] = likely_teams

    return likely_dgw_gws


def _count_blanking_teams(fixtures: list, gameweek: int, all_team_ids: set[int]) -> int:
    """Count teams that have NO fixture in a given gameweek."""
    playing: set[int] = set()
    for fix in fixtures:
        if fix.get("event") != gameweek:
            continue
        playing.add(fix["team_h"])
        playing.add(fix["team_a"])
    return len(all_team_ids - playing)


def _avg_fdr_for_gw(fixtures: list, gameweek: int) -> float:
    """Average FDR across all fixtures in a gameweek."""
    fdrs = []
    for fix in fixtures:
        if fix.get("event") != gameweek:
            continue
        fdrs.append(fix["team_h_difficulty"])
        fdrs.append(fix["team_a_difficulty"])
    return round(sum(fdrs) / len(fdrs), 2) if fdrs else 3.0


def _gw_fixture_count(fixtures: list, gameweek: int) -> int:
    """Count total fixtures in a gameweek."""
    return sum(1 for f in fixtures if f.get("event") == gameweek)


def _score_bb_for_gw(
    gw: int,
    gw_stats: dict,
    bench_players: list,
    has_wildcard: bool,
) -> float:
    """
    Score a gameweek for Bench Boost.

    When WC is available: score based on GW-level potential (DGW teams, fixture count)
    since WC would rebuild the bench specifically for this GW.
    When WC is not available: score based on actual current bench players' fixtures.
    """
    stats = gw_stats[gw]
    score = 0.0

    if has_wildcard:
        # WC available — bench will be optimized, so score based on GW potential
        # Confirmed DGW teams: each DGW team means a bench player could have 2 fixtures
        # This is the DOMINANT factor — a mega DGW with 12 teams is massive
        score += stats["dgw_teams"] * 8.0
        # Predicted DGW teams (less certain)
        score += len(stats["predicted_dgw_teams"]) * 4.0
        # More fixtures = more total points available for bench players
        score += stats["fixture_count"] * 1.5
        # Easier fixtures = higher expected bench points
        score += (5 - stats["avg_fdr"]) * 2.0
    else:
        # No WC — score based on actual current bench players
        fmap = stats["fixture_map"]
        for player in bench_players:
            player_fixes = fmap.get(player["team"])
            if player_fixes:
                fixture_bonus = len(player_fixes) * 3.0
                avg_fix_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
                fdr_score = (5 - avg_fix_fdr) * 2.0
                score += fixture_bonus + fdr_score

            if player["team"] in stats.get("predicted_dgw_teams", []):
                score += 2.5

        # GW-level DGW bonus (even without WC, more DGW teams = better)
        score += stats["dgw_teams"] * 3.0
        score += len(stats["predicted_dgw_teams"]) * 2.0

    return score


def _score_fh_for_gw(gw: int, gw_stats: dict) -> float:
    """
    Score a gameweek for Free Hit.

    FH is MOST valuable during BGWs (many teams blank, your squad has non-playing
    players, FH lets you pick from teams that ARE playing).
    Secondary value: mega DGWs (load up on DGW players for one week).
    """
    stats = gw_stats[gw]
    score = 0.0

    # Blank teams: THE dominant factor for FH
    # BGW with 16 teams blanking = only 4 teams playing = FH is essential
    blank_teams = stats["blank_teams"]
    if blank_teams >= 10:
        # Major BGW — FH is almost mandatory
        score += blank_teams * 10.0
    elif blank_teams >= 4:
        # Moderate BGW — FH is very valuable
        score += blank_teams * 7.0
    else:
        # Minor or no BGW — FH has some value from fixture optimization
        score += blank_teams * 3.0

    # DGW also helps FH (load up on DGW players)
    score += stats["dgw_teams"] * 3.0
    score += len(stats["predicted_dgw_teams"]) * 2.0

    # Fixture variance (uneven FDR = more room to optimize)
    fmap = stats["fixture_map"]
    fdrs = []
    for team_fixes in fmap.values():
        for f in team_fixes:
            fdrs.append(f["fdr"])
    if fdrs:
        fdr_variance = sum((f - 3) ** 2 for f in fdrs) / len(fdrs)
        score += fdr_variance * 1.5

    return score


def _score_tc_for_gw(gw: int, gw_stats: dict, all_players: list) -> tuple[float, dict | None]:
    """
    Score a gameweek for Triple Captain.

    TC is most valuable when a premium player has a DGW with easy fixtures
    (captain plays twice = effectively 2x the TC bonus).

    Returns: (score, best_captain_player)
    """
    stats = gw_stats[gw]
    fmap = stats["fixture_map"]

    # Find the best captain for this GW
    top_score = -999
    top_player = None
    for player in all_players:
        player_fixes = fmap.get(player["team"])
        captain_score = _score_player(player, player_fixes)

        # DGW boost: captain plays twice = TC value doubles
        if player_fixes and len(player_fixes) >= 2:
            captain_score *= 2.0  # Confirmed DGW for this player
        elif player["team"] in stats.get("predicted_dgw_teams", []):
            captain_score *= 1.6  # Predicted DGW

        if captain_score > top_score:
            top_score = captain_score
            top_player = player

    # GW-level DGW boost (more teams doubling = higher quality DGW)
    dgw_mult = 1.0
    if stats["dgw_teams"] > 0:
        dgw_mult += stats["dgw_teams"] * 0.15
    if stats["predicted_dgw_teams"]:
        dgw_mult += len(stats["predicted_dgw_teams"]) * 0.1

    return top_score * dgw_mult, top_player


def _score_wc_for_gw(
    gw: int,
    gw_stats: dict,
    squad_players: list,
    best_bb_gw: int | None,
    best_fh_gw: int | None,
    chips_remaining: set,
) -> float:
    """
    Score a gameweek for Wildcard.

    WC is STRATEGIC — its value comes from enabling other chips:
    1. WC 1 GW before BB = rebuild bench for mega DGW (highest priority)
    2. WC before a fixture swing = get players with easy upcoming runs
    3. WC to fix squad issues = injured/out-of-form players

    The WC→BB combo is the single most important chip interaction in FPL.
    """
    stats = gw_stats[gw]
    fmap = stats["fixture_map"]
    score = 0.0

    # --- COMBO BONUS: WC 1 GW before best BB GW ---
    # This is THE key insight: WC to rebuild squad/bench for upcoming BB DGW
    if "bboost" in chips_remaining and best_bb_gw is not None:
        if gw == best_bb_gw - 1:
            # Perfect WC→BB combo position
            bb_stats = gw_stats.get(best_bb_gw, {})
            # Scale combo bonus by how good the BB GW is
            dgw_teams = bb_stats.get("dgw_teams", 0) + len(bb_stats.get("predicted_dgw_teams", []))
            score += 50.0 + dgw_teams * 5.0  # massive bonus for WC→BB combo
        elif gw == best_bb_gw - 2:
            # 2 GWs before BB — still good but less ideal
            score += 25.0

    # --- COMBO BONUS: WC before FH to prepare for BGW aftermath ---
    if "freehit" in chips_remaining and best_fh_gw is not None:
        if gw == best_fh_gw - 1 and (best_bb_gw is None or gw != best_bb_gw - 1):
            # WC before FH — build squad that can handle post-FH GWs
            score += 15.0

    # --- Squad issues: injured/doubtful/poor form ---
    injured_count = sum(1 for p in squad_players if p.get("status") in INJURY_STATUSES)
    score += injured_count * 3.0

    bad_form_count = 0
    for player in squad_players:
        form = float(player.get("form") or 0)
        player_fixes = fmap.get(player["team"], [])
        avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes) if player_fixes else 3.0
        if form <= 3.0 and avg_fdr >= 3.5:
            bad_form_count += 1
    if bad_form_count >= 4:
        score += bad_form_count * 3.0

    # --- Fixture swing value ---
    squad_team_ids = {p["team"] for p in squad_players}
    non_squad_fdrs = []
    for team_id, team_fixes in fmap.items():
        if team_id not in squad_team_ids:
            for f in team_fixes:
                non_squad_fdrs.append(f["fdr"])
    if non_squad_fdrs:
        avg_non_squad_fdr = sum(non_squad_fdrs) / len(non_squad_fdrs)
        score += (5 - avg_non_squad_fdr) * 2.0

    return score


def _find_optimal_chip_assignment(
    chips_remaining: set,
    scan_gws: list[int],
    gw_stats: dict,
    bench_players: list,
    squad_players: list,
    all_players: list,
) -> dict[str, tuple[int, float, dict | None]]:
    """
    Find the optimal assignment of chips to gameweeks.

    Evaluates chip combinations to maximize total value across all chips.
    Key constraint: no two chips in the same gameweek.

    Returns: { chip_code: (best_gw, score, extra_data) }
    """
    chips = list(chips_remaining)
    has_wildcard = "wildcard" in chips_remaining

    # Step 1: Score each (chip, gw) pair independently first
    # to find the best GWs for BB and FH (needed for WC combo scoring)
    bb_scores: dict[int, float] = {}
    fh_scores: dict[int, float] = {}
    tc_scores: dict[int, tuple[float, dict | None]] = {}

    for gw in scan_gws:
        if "bboost" in chips_remaining:
            bb_scores[gw] = _score_bb_for_gw(gw, gw_stats, bench_players, has_wildcard)
        if "freehit" in chips_remaining:
            fh_scores[gw] = _score_fh_for_gw(gw, gw_stats)
        if "3xc" in chips_remaining:
            tc_scores[gw] = _score_tc_for_gw(gw, gw_stats, all_players)

    # Find preliminary best GWs for BB and FH (for WC combo scoring)
    best_bb_gw = max(bb_scores, key=bb_scores.get) if bb_scores else None
    best_fh_gw = max(fh_scores, key=fh_scores.get) if fh_scores else None

    # Step 2: Score WC with combo awareness
    wc_scores: dict[int, float] = {}
    if "wildcard" in chips_remaining:
        for gw in scan_gws:
            wc_scores[gw] = _score_wc_for_gw(gw, gw_stats, squad_players, best_bb_gw, best_fh_gw, chips_remaining)

    # Step 3: Find optimal assignment (no two chips same GW)
    # For <= 4 chips, brute force all valid assignments is feasible
    best_total = -999
    best_assignment: dict[str, tuple[int, float, dict | None]] = {}

    if len(chips) <= 1:
        # Single chip — just pick the best GW
        for chip in chips:
            scores = {"bboost": bb_scores, "freehit": fh_scores, "wildcard": wc_scores}.get(chip, {})
            if chip == "3xc":
                if tc_scores:
                    best_gw = max(tc_scores, key=lambda g: tc_scores[g][0])
                    score, player = tc_scores[best_gw]
                    best_assignment[chip] = (best_gw, score, player)
            elif scores:
                best_gw = max(scores, key=scores.get)
                best_assignment[chip] = (best_gw, scores[best_gw], None)
    else:
        # Multiple chips — try all valid GW assignments
        # Build score lookup for each chip
        chip_gw_scores: dict[str, dict[int, float]] = {}
        chip_gw_extra: dict[str, dict[int, dict | None]] = {}
        for chip in chips:
            if chip == "bboost":
                chip_gw_scores[chip] = bb_scores
                chip_gw_extra[chip] = {gw: None for gw in scan_gws}
            elif chip == "freehit":
                chip_gw_scores[chip] = fh_scores
                chip_gw_extra[chip] = {gw: None for gw in scan_gws}
            elif chip == "3xc":
                chip_gw_scores[chip] = {gw: tc_scores[gw][0] for gw in tc_scores}
                chip_gw_extra[chip] = {gw: tc_scores[gw][1] for gw in tc_scores}
            elif chip == "wildcard":
                chip_gw_scores[chip] = wc_scores
                chip_gw_extra[chip] = {gw: None for gw in scan_gws}

        # For each chip, get top 5 candidate GWs to limit search space
        chip_candidates: dict[str, list[int]] = {}
        for chip in chips:
            scores = chip_gw_scores.get(chip, {})
            if scores:
                sorted_gws = sorted(scores.keys(), key=lambda g: scores[g], reverse=True)
                chip_candidates[chip] = sorted_gws[:5]
            else:
                chip_candidates[chip] = []

        # Try all combinations of candidate GWs (max 5^4 = 625 combos)
        def _try_assignments(chip_idx: int, used_gws: set, current: dict, current_score: float):
            nonlocal best_total, best_assignment

            if chip_idx == len(chips):
                if current_score > best_total:
                    best_total = current_score
                    best_assignment = dict(current)
                return

            chip = chips[chip_idx]
            for gw in chip_candidates.get(chip, []):
                if gw in used_gws:
                    continue
                score = chip_gw_scores.get(chip, {}).get(gw, -999)
                extra = chip_gw_extra.get(chip, {}).get(gw)
                current[chip] = (gw, score, extra)
                used_gws.add(gw)
                _try_assignments(chip_idx + 1, used_gws, current, current_score + score)
                used_gws.remove(gw)
                del current[chip]

        _try_assignments(0, set(), {}, 0.0)

    return best_assignment


async def get_chip_strategy(team_id: int) -> dict:
    """
    Recommend the best gameweek for each remaining chip using multi-chip sequencing.

    When multiple chips are available, finds the optimal COMBINATION:
    - WC→BB: Wildcard to rebuild squad 1 GW before Bench Boost DGW
    - FH for BGWs: Free Hit during blank gameweeks
    - TC for DGWs: Triple Captain when premium player has 2 fixtures
    """
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    current_gw = get_current_gameweek(bootstrap)
    next_gw = get_next_gameweek(bootstrap)

    # Fetch team data
    picks_data, history_data = await asyncio.gather(
        get_team_picks(team_id, current_gw),
        get_team_history(team_id),
    )

    # Determine chips remaining — FPL resets all chips at halfway (after GW19)
    chips_used_list = history_data.get("chips", [])
    halfway_gw = 19
    if current_gw > halfway_gw:
        chips_used_names = {c["name"] for c in chips_used_list if c["event"] > halfway_gw}
    else:
        chips_used_names = {c["name"] for c in chips_used_list if c["event"] <= halfway_gw}
    chips_remaining = ALL_CHIPS - chips_used_names

    if not chips_remaining:
        return {
            "team_id": team_id,
            "gameweek": current_gw,
            "chips_remaining": [],
            "chips_used": [
                {"chip": CHIP_DISPLAY.get(c["name"], c["name"]), "gameweek": c["event"]} for c in chips_used_list
            ],
            "recommendations": [],
            "message": "All chips have been used this season.",
        }

    # Build data structures
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    all_team_ids = set(teams_by_id.keys())

    # Get squad player IDs and data
    squad_picks = picks_data.get("picks", [])
    squad_players = []
    bench_players = []
    for pick in squad_picks:
        player = players_by_id.get(pick["element"])
        if not player:
            continue
        if pick["position"] <= 11:
            squad_players.append(player)
        else:
            bench_players.append(player)

    # Scan upcoming gameweeks
    scan_gws = list(range(next_gw, min(next_gw + SCAN_WINDOW, 39)))

    # Detect unscheduled fixtures and predict future DGWs
    teams_with_pending = _predict_dgw_teams(fixtures)
    likely_dgw_gws = _estimate_likely_dgw_gameweeks(fixtures, next_gw, scan_gws)

    # Fetch community DGW/BGW intelligence (best-effort, non-blocking)
    community_intel: dict = {}
    try:
        community_intel = await fetch_community_dgw_intel()
        likely_dgw_gws = merge_intel_with_api_predictions(likely_dgw_gws, community_intel, teams_by_id)
    except Exception:
        logger.warning("Community DGW intel fetch failed, using API data only")

    # Pre-compute per-GW stats
    gw_stats = {}
    for gw in scan_gws:
        dgw_teams = _count_dgw_teams(fixtures, gw)
        blank_teams = _count_blanking_teams(fixtures, gw, all_team_ids)
        avg_fdr = _avg_fdr_for_gw(fixtures, gw)
        fix_count = _gw_fixture_count(fixtures, gw)
        fixture_map = _build_fixture_map(fixtures, gw, teams_by_id=teams_by_id)
        predicted_dgw_teams = likely_dgw_gws.get(gw, [])

        gw_stats[gw] = {
            "dgw_teams": dgw_teams,
            "predicted_dgw_teams": predicted_dgw_teams,
            "total_dgw_teams": dgw_teams + len(predicted_dgw_teams),
            "blank_teams": blank_teams,
            "avg_fdr": avg_fdr,
            "fixture_count": fix_count,
            "fixture_map": fixture_map,
        }

    # Find optimal chip assignment using multi-chip sequencing
    assignment = _find_optimal_chip_assignment(
        chips_remaining, scan_gws, gw_stats, bench_players, squad_players, bootstrap["elements"]
    )

    # Build recommendations from assignment
    recommendations = []

    for chip_code, (best_gw, score, extra) in assignment.items():
        stats = gw_stats[best_gw]

        if chip_code == "bboost":
            reasoning_parts = []
            if stats["dgw_teams"] > 0:
                reasoning_parts.append(f"{stats['dgw_teams']} teams have confirmed DGW")
            if stats["predicted_dgw_teams"]:
                reasoning_parts.append(
                    f"{len(stats['predicted_dgw_teams'])} teams have potential DGW "
                    f"(postponed fixtures pending rescheduling)"
                )
            if stats["fixture_count"] > 10:
                reasoning_parts.append(f"{stats['fixture_count']} fixtures scheduled")
            reasoning_parts.append(f"avg FDR {stats['avg_fdr']}")

            # Note WC→BB combo if applicable
            wc_entry = assignment.get("wildcard")
            if wc_entry and wc_entry[0] == best_gw - 1:
                reasoning_parts.append(f"use Wildcard in GW{wc_entry[0]} to rebuild bench specifically for this DGW")

            recommendations.append(
                {
                    "chip": "Bench Boost",
                    "chip_code": "bboost",
                    "recommended_gameweek": best_gw,
                    "confidence_score": round(score, 1),
                    "reasoning": ". ".join(reasoning_parts) + ".",
                    "gw_details": {
                        "dgw_teams": stats["dgw_teams"],
                        "predicted_dgw_teams": len(stats["predicted_dgw_teams"]),
                        "fixture_count": stats["fixture_count"],
                        "avg_fdr": stats["avg_fdr"],
                    },
                }
            )

        elif chip_code == "3xc":
            tc_player = extra
            reasoning_parts = []
            if tc_player:
                player_team = teams_by_id.get(tc_player["team"], {}).get("short_name", "?")
                reasoning_parts.append(f"Best captain option is {tc_player['web_name']} ({player_team})")
                player_fixes = stats["fixture_map"].get(tc_player["team"], [])
                if len(player_fixes) > 1:
                    reasoning_parts.append(f"{tc_player['web_name']} has {len(player_fixes)} confirmed fixtures (DGW)")
                elif tc_player["team"] in stats.get("predicted_dgw_teams", []):
                    reasoning_parts.append(f"{tc_player['web_name']}'s team has a postponed fixture pending")
            if stats["dgw_teams"] > 0:
                reasoning_parts.append(f"{stats['dgw_teams']} teams have confirmed DGW")
            if stats["predicted_dgw_teams"]:
                reasoning_parts.append(f"{len(stats['predicted_dgw_teams'])} teams likely to have DGW")

            rec = {
                "chip": "Triple Captain",
                "chip_code": "3xc",
                "recommended_gameweek": best_gw,
                "confidence_score": round(score, 1),
                "reasoning": ". ".join(reasoning_parts) + ".",
                "gw_details": {
                    "dgw_teams": stats["dgw_teams"],
                    "predicted_dgw_teams": len(stats["predicted_dgw_teams"]),
                    "fixture_count": stats["fixture_count"],
                    "avg_fdr": stats["avg_fdr"],
                },
            }
            if tc_player:
                player_team = teams_by_id.get(tc_player["team"], {}).get("short_name", "?")
                rec["suggested_captain"] = {
                    "id": tc_player["id"],
                    "name": tc_player["web_name"],
                    "team": player_team,
                    "form": float(tc_player.get("form") or 0),
                }
            recommendations.append(rec)

        elif chip_code == "freehit":
            reasoning_parts = []
            if stats["blank_teams"] > 0:
                reasoning_parts.append(f"{stats['blank_teams']} teams have no fixture (blank GW)")
            if stats["blank_teams"] >= 10:
                reasoning_parts.append("major BGW — Free Hit is essential to field 11 playing players")
            if stats["dgw_teams"] > 0:
                reasoning_parts.append(f"{stats['dgw_teams']} teams have confirmed DGW")
            if stats["predicted_dgw_teams"]:
                reasoning_parts.append(f"{len(stats['predicted_dgw_teams'])} teams likely to have DGW")
            if not reasoning_parts:
                reasoning_parts.append("best fixture variance for squad optimization")

            recommendations.append(
                {
                    "chip": "Free Hit",
                    "chip_code": "freehit",
                    "recommended_gameweek": best_gw,
                    "confidence_score": round(score, 1),
                    "reasoning": ". ".join(reasoning_parts) + ".",
                    "gw_details": {
                        "dgw_teams": stats["dgw_teams"],
                        "predicted_dgw_teams": len(stats["predicted_dgw_teams"]),
                        "blank_teams": stats["blank_teams"],
                        "fixture_count": stats["fixture_count"],
                        "avg_fdr": stats["avg_fdr"],
                    },
                }
            )

        elif chip_code == "wildcard":
            fmap = stats["fixture_map"]

            # Identify squad issues for reasoning
            troubled_players = []
            for player in squad_players:
                form = float(player.get("form") or 0)
                player_fixes = fmap.get(player["team"], [])
                avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes) if player_fixes else 3.0
                if form <= 3.0 and avg_fdr >= 3.5:
                    troubled_players.append(player["web_name"])

            injured = [p["web_name"] for p in squad_players if p.get("status") in INJURY_STATUSES]

            reasoning_parts = []
            # Check for WC→BB combo
            bb_entry = assignment.get("bboost")
            if bb_entry and best_gw == bb_entry[0] - 1:
                bb_stats = gw_stats[bb_entry[0]]
                reasoning_parts.append(
                    f"Wildcard→Bench Boost combo: rebuild squad and bench for GW{bb_entry[0]} "
                    f"mega DGW ({bb_stats['dgw_teams']} confirmed + "
                    f"{len(bb_stats['predicted_dgw_teams'])} predicted DGW teams)"
                )
            if troubled_players:
                reasoning_parts.append(
                    f"{len(troubled_players)} squad players have poor form + tough fixtures "
                    f"({', '.join(troubled_players[:4])})"
                )
            if injured:
                reasoning_parts.append(f"{len(injured)} injured/doubtful ({', '.join(injured[:3])})")
            if not reasoning_parts:
                reasoning_parts.append("good fixture swings available for replacements")

            recommendations.append(
                {
                    "chip": "Wildcard",
                    "chip_code": "wildcard",
                    "recommended_gameweek": best_gw,
                    "confidence_score": round(score, 1),
                    "reasoning": ". ".join(reasoning_parts) + ".",
                    "squad_issues": {
                        "poor_form_tough_fixtures": troubled_players,
                        "injured_or_doubtful": injured,
                    },
                    "gw_details": {
                        "dgw_teams": stats["dgw_teams"],
                        "predicted_dgw_teams": len(stats.get("predicted_dgw_teams", [])),
                        "fixture_count": stats["fixture_count"],
                        "avg_fdr": stats["avg_fdr"],
                    },
                }
            )

    # Sort: WC first (if combo), then by recommended GW order
    chip_order = {"wildcard": 0, "bboost": 1, "freehit": 2, "3xc": 3}
    recommendations.sort(key=lambda r: (r["recommended_gameweek"], chip_order.get(r["chip_code"], 99)))

    # Build pending DGW summary
    pending_dgws = []
    if teams_with_pending:
        for tid, pending_fixes in teams_with_pending.items():
            team_name = teams_by_id.get(tid, {}).get("short_name", f"Team {tid}")
            opponents = []
            for pf in pending_fixes:
                opp_name = teams_by_id.get(pf["opponent"], {}).get("short_name", f"Team {pf['opponent']}")
                venue = "home" if pf["is_home"] else "away"
                opponents.append(f"{opp_name} ({venue})")
            pending_dgws.append(
                {
                    "team": team_name,
                    "team_id": tid,
                    "unscheduled_fixtures": opponents,
                    "likely_dgw_gameweeks": [gw for gw, teams in likely_dgw_gws.items() if tid in teams],
                }
            )

    result = {
        "team_id": team_id,
        "gameweek": current_gw,
        "scan_window": f"GW{next_gw}-GW{scan_gws[-1]}" if scan_gws else "N/A",
        "chips_remaining": [CHIP_DISPLAY.get(c, c) for c in chips_remaining],
        "chips_used": [
            {"chip": CHIP_DISPLAY.get(c["name"], c["name"]), "gameweek": c["event"]} for c in chips_used_list
        ],
        "recommendations": recommendations,
    }

    if pending_dgws:
        result["pending_dgws"] = {
            "summary": (
                f"{len(teams_with_pending)} teams have postponed fixtures that will create future DGWs. "
                f"Consider waiting for official scheduling before using Triple Captain or Bench Boost."
            ),
            "teams": pending_dgws,
        }

    if community_intel:
        intel_summary = {}
        if community_intel.get("dgws"):
            intel_summary["predicted_dgws"] = community_intel["dgws"]
        if community_intel.get("bgws"):
            intel_summary["predicted_bgws"] = community_intel["bgws"]
        if community_intel.get("sources_checked"):
            intel_summary["sources"] = community_intel["sources_checked"]
        if community_intel.get("errors"):
            intel_summary["source_errors"] = community_intel["errors"]
        if intel_summary:
            result["community_intel"] = intel_summary

    return result
