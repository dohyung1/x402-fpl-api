"""
Chip Strategy algorithm.

Answers: "When should I use my remaining chips?"

Analyzes upcoming fixtures across 10 gameweeks to recommend the optimal
gameweek for each remaining chip (Bench Boost, Triple Captain, Free Hit,
Wildcard) based on fixture difficulty, DGW detection, blank detection,
and squad health.

Includes predicted DGW/BGW detection: fixtures with event=null are
postponed/unscheduled matches that will be rescheduled into existing
gameweeks, creating future DGWs. The algorithm factors these in.
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


def _get_unscheduled_fixtures(fixtures: list) -> list[dict]:
    """
    Find postponed/unscheduled fixtures (event is null).

    These are matches that have been postponed and will be rescheduled
    into existing gameweeks, creating future DGWs. The FPL API sets
    event=null for these fixtures.
    """
    return [f for f in fixtures if f.get("event") is None and not f.get("finished")]


def _predict_dgw_teams(fixtures: list) -> dict[int, list[dict]]:
    """
    Identify teams with pending unscheduled fixtures that will likely
    create future DGWs when rescheduled.

    Returns: { team_id: [ { opponent_id, opponent_name_placeholder } ] }
    """
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
    """
    Estimate which future gameweeks are likely to become DGWs.

    Heuristic: later gameweeks in the season are more likely targets for
    rescheduled matches (FPL typically slots postponed fixtures into the
    second half of the remaining schedule). We score each gameweek based on:
    - Fewer existing fixtures = more room for rescheduled matches
    - Later in the window = more likely for rescheduling

    Returns: { gameweek: [team_ids likely to have DGW] }
    """
    teams_with_pending = _predict_dgw_teams(fixtures)
    if not teams_with_pending:
        return {}

    # Count existing fixtures per GW for teams with pending matches
    gw_fixture_counts: dict[int, dict[int, int]] = {}
    for gw in scan_gws:
        gw_fixture_counts[gw] = {}
        for fix in fixtures:
            if fix.get("event") != gw:
                continue
            for tid in (fix["team_h"], fix["team_a"]):
                if tid in teams_with_pending:
                    gw_fixture_counts[gw][tid] = gw_fixture_counts[gw].get(tid, 0) + 1

    # For each team with pending fixtures, find GWs where they only have 1 match
    # (room for a rescheduled match to create a DGW)
    likely_dgw_gws: dict[int, list[int]] = {}
    for gw in scan_gws:
        likely_teams = []
        for tid in teams_with_pending:
            existing = gw_fixture_counts.get(gw, {}).get(tid, 0)
            # Team has exactly 1 fixture — room for a second (DGW)
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


async def get_chip_strategy(team_id: int) -> dict:
    """
    Recommend the best gameweek for each remaining chip.

    Fetches the manager's chip history, current squad, and fixture data,
    then scores each upcoming gameweek for each chip type.
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
        # Merge community predictions with API-based predictions
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

    recommendations = []

    # --- BENCH BOOST ---
    if "bboost" in chips_remaining:
        best_bb_gw = None
        best_bb_score = -999

        for gw in scan_gws:
            stats = gw_stats[gw]
            fmap = stats["fixture_map"]
            score = 0.0

            # Score bench players' fixtures this GW
            for player in bench_players:
                player_fixes = fmap.get(player["team"])
                if player_fixes:
                    # DGW bonus: more fixtures = more bench points
                    fixture_bonus = len(player_fixes) * 3.0
                    # Easier fixtures = better
                    avg_fix_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
                    fdr_score = (5 - avg_fix_fdr) * 2.0
                    score += fixture_bonus + fdr_score

                # Predicted DGW bonus: bench players on teams with pending fixtures
                if player["team"] in stats["predicted_dgw_teams"]:
                    score += 2.5  # slightly less than confirmed DGW

            # Confirmed DGW bonus
            score += stats["dgw_teams"] * 2.0
            # Predicted DGW bonus (weighted less than confirmed)
            score += len(stats["predicted_dgw_teams"]) * 1.5

            if score > best_bb_score:
                best_bb_score = score
                best_bb_gw = gw

        if best_bb_gw:
            stats = gw_stats[best_bb_gw]
            reasoning_parts = []
            if stats["dgw_teams"] > 0:
                reasoning_parts.append(f"{stats['dgw_teams']} teams have confirmed DGW")
            if stats["predicted_dgw_teams"]:
                reasoning_parts.append(
                    f"{len(stats['predicted_dgw_teams'])} teams have potential DGW "
                    f"(postponed fixtures pending rescheduling)"
                )
            reasoning_parts.append(f"bench players have favorable fixtures (avg FDR {stats['avg_fdr']})")
            if stats["fixture_count"] > 10:
                reasoning_parts.append(f"{stats['fixture_count']} fixtures scheduled")

            recommendations.append(
                {
                    "chip": "Bench Boost",
                    "chip_code": "bboost",
                    "recommended_gameweek": best_bb_gw,
                    "confidence_score": round(best_bb_score, 1),
                    "reasoning": ". ".join(reasoning_parts) + ".",
                    "gw_details": {
                        "dgw_teams": stats["dgw_teams"],
                        "predicted_dgw_teams": len(stats["predicted_dgw_teams"]),
                        "fixture_count": stats["fixture_count"],
                        "avg_fdr": stats["avg_fdr"],
                    },
                }
            )

    # --- TRIPLE CAPTAIN ---
    if "3xc" in chips_remaining:
        best_tc_gw = None
        best_tc_score = -999
        best_tc_player = None

        for gw in scan_gws:
            stats = gw_stats[gw]
            fmap = stats["fixture_map"]

            # Find the best captain pick for this GW
            top_score = -999
            top_player = None
            for player in bootstrap["elements"]:
                player_fixes = fmap.get(player["team"])
                captain_score = _score_player(player, player_fixes)

                # Boost players on teams with predicted DGWs —
                # TC is most valuable when the captain plays twice
                if player["team"] in stats["predicted_dgw_teams"]:
                    captain_score *= 1.6  # predicted DGW for this player's team

                if captain_score > top_score:
                    top_score = captain_score
                    top_player = player

            # Confirmed DGW massively boosts TC value
            dgw_mult = 1.0 + (stats["dgw_teams"] * 0.3)
            # Predicted DGWs also boost, but less confidently
            dgw_mult += len(stats["predicted_dgw_teams"]) * 0.2
            adjusted_score = top_score * dgw_mult

            if adjusted_score > best_tc_score:
                best_tc_score = adjusted_score
                best_tc_gw = gw
                best_tc_player = top_player

        if best_tc_gw and best_tc_player:
            stats = gw_stats[best_tc_gw]
            player_team = teams_by_id.get(best_tc_player["team"], {}).get("short_name", "?")
            reasoning_parts = [f"Best captain option is {best_tc_player['web_name']} ({player_team})"]
            if stats["dgw_teams"] > 0:
                reasoning_parts.append(f"{stats['dgw_teams']} teams have confirmed DGW")
            if stats["predicted_dgw_teams"]:
                reasoning_parts.append(
                    f"{len(stats['predicted_dgw_teams'])} teams likely to have DGW (postponed fixtures pending)"
                )

            # Check if the top player has a confirmed DGW
            player_fixes = stats["fixture_map"].get(best_tc_player["team"], [])
            if len(player_fixes) > 1:
                reasoning_parts.append(f"{best_tc_player['web_name']} has {len(player_fixes)} confirmed fixtures")
            elif best_tc_player["team"] in stats["predicted_dgw_teams"]:
                reasoning_parts.append(f"{best_tc_player['web_name']}'s team has a postponed fixture pending")

            recommendations.append(
                {
                    "chip": "Triple Captain",
                    "chip_code": "3xc",
                    "recommended_gameweek": best_tc_gw,
                    "confidence_score": round(best_tc_score, 1),
                    "suggested_captain": {
                        "id": best_tc_player["id"],
                        "name": best_tc_player["web_name"],
                        "team": player_team,
                        "form": float(best_tc_player.get("form") or 0),
                    },
                    "reasoning": ". ".join(reasoning_parts) + ".",
                    "gw_details": {
                        "dgw_teams": stats["dgw_teams"],
                        "predicted_dgw_teams": len(stats["predicted_dgw_teams"]),
                        "fixture_count": stats["fixture_count"],
                        "avg_fdr": stats["avg_fdr"],
                    },
                }
            )

    # --- FREE HIT ---
    if "freehit" in chips_remaining:
        best_fh_gw = None
        best_fh_score = -999

        for gw in scan_gws:
            stats = gw_stats[gw]
            score = 0.0

            # Free Hit is best when many teams blank (you can pick from teams playing)
            score += stats["blank_teams"] * 5.0

            # Also good when there are big fixture swings (uneven FDR distribution)
            fmap = stats["fixture_map"]
            fdrs = []
            for team_fixes in fmap.values():
                for f in team_fixes:
                    fdrs.append(f["fdr"])
            if fdrs:
                fdr_variance = sum((f - 3) ** 2 for f in fdrs) / len(fdrs)
                score += fdr_variance * 2.0

            # DGW also helps Free Hit (can load up on DGW players)
            score += stats["dgw_teams"] * 3.0
            # Predicted DGWs also boost Free Hit value
            score += len(stats["predicted_dgw_teams"]) * 2.0

            if score > best_fh_score:
                best_fh_score = score
                best_fh_gw = gw

        if best_fh_gw:
            stats = gw_stats[best_fh_gw]
            reasoning_parts = []
            if stats["blank_teams"] > 0:
                reasoning_parts.append(f"{stats['blank_teams']} teams have no fixture (blank GW)")
            if stats["dgw_teams"] > 0:
                reasoning_parts.append(f"{stats['dgw_teams']} teams have confirmed DGW")
            if stats["predicted_dgw_teams"]:
                reasoning_parts.append(
                    f"{len(stats['predicted_dgw_teams'])} teams likely to have DGW (postponed fixtures pending)"
                )
            reasoning_parts.append("high fixture variance makes squad restructuring valuable")

            recommendations.append(
                {
                    "chip": "Free Hit",
                    "chip_code": "freehit",
                    "recommended_gameweek": best_fh_gw,
                    "confidence_score": round(best_fh_score, 1),
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

    # --- WILDCARD ---
    if "wildcard" in chips_remaining:
        best_wc_gw = None
        best_wc_score = -999

        for gw in scan_gws:
            stats = gw_stats[gw]
            fmap = stats["fixture_map"]
            score = 0.0

            # Count squad players with bad form AND tough fixtures
            bad_form_tough_fixture = 0
            for player in squad_players:
                form = float(player.get("form") or 0)
                player_fixes = fmap.get(player["team"], [])
                if player_fixes:
                    avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes)
                else:
                    avg_fdr = 3.0

                if form <= 3.0 and avg_fdr >= 3.5:
                    bad_form_tough_fixture += 1

            # Wildcard trigger: 4+ players in bad shape
            if bad_form_tough_fixture >= 4:
                score += bad_form_tough_fixture * 5.0

            # Injured/doubtful players increase wildcard need
            injured_count = sum(1 for p in squad_players if p.get("status") in INJURY_STATUSES)
            score += injured_count * 3.0

            # Prefer wildcarding before a good fixture swing
            # Look at average FDR of non-squad teams (potential replacements)
            squad_team_ids = {p["team"] for p in squad_players}
            non_squad_fdrs = []
            for team_id, team_fixes in fmap.items():
                if team_id not in squad_team_ids:
                    for f in team_fixes:
                        non_squad_fdrs.append(f["fdr"])
            if non_squad_fdrs:
                avg_non_squad_fdr = sum(non_squad_fdrs) / len(non_squad_fdrs)
                # Lower FDR for non-squad teams = better time to wildcard to them
                score += (5 - avg_non_squad_fdr) * 2.0

            if score > best_wc_score:
                best_wc_score = score
                best_wc_gw = gw

        if best_wc_gw:
            stats = gw_stats[best_wc_gw]
            fmap = stats["fixture_map"]

            # Recount for reasoning
            troubled_players = []
            for player in squad_players:
                form = float(player.get("form") or 0)
                player_fixes = fmap.get(player["team"], [])
                avg_fdr = sum(f["fdr"] for f in player_fixes) / len(player_fixes) if player_fixes else 3.0
                if form <= 3.0 and avg_fdr >= 3.5:
                    troubled_players.append(player["web_name"])

            injured = [p["web_name"] for p in squad_players if p.get("status") in INJURY_STATUSES]

            reasoning_parts = []
            if troubled_players:
                reasoning_parts.append(
                    f"{len(troubled_players)} squad players have poor form + tough fixtures "
                    f"({', '.join(troubled_players[:4])})"
                )
            if injured:
                reasoning_parts.append(f"{len(injured)} injured/doubtful ({', '.join(injured[:3])})")
            reasoning_parts.append("good fixture swings available for replacements")

            recommendations.append(
                {
                    "chip": "Wildcard",
                    "chip_code": "wildcard",
                    "recommended_gameweek": best_wc_gw,
                    "confidence_score": round(best_wc_score, 1),
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

    # Sort recommendations by confidence
    recommendations.sort(key=lambda r: r["confidence_score"], reverse=True)

    # Build pending DGW summary for transparency
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

    # Add community intelligence if available
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
