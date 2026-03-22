"""
Accuracy audit — validates all MCP tool outputs against live FPL API data.

Catches hallucination patterns:
  - Wrong team assignments (player at old club after transfer)
  - Blank-GW players in recommendations
  - Injured/doubtful/suspended players recommended
  - Ghost players (IDs that don't exist)
  - Position mismatches
  - Data integrity violations

Runs against the live FPL API. Not a predictive backtest — this checks
structural correctness and data truthfulness.

Usage:
    python scripts/accuracy_audit.py                     # run all checks
    python scripts/accuracy_audit.py --team-id 5293026   # specific team
    python scripts/accuracy_audit.py --tool captain       # single tool
    python scripts/accuracy_audit.py --json-only          # suppress stdout
"""

import argparse
import asyncio
import csv
import json
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.algorithms import INJURY_STATUSES, POSITION_MAP  # noqa: E402
from app.fpl_client import (  # noqa: E402
    get_bootstrap,
    get_current_gameweek,
    get_fixtures,
    get_next_gameweek,
)

AUDIT_JSON = PROJECT_ROOT / "data" / "accuracy_audit.json"
AUDIT_CSV = PROJECT_ROOT / "data" / "accuracy_audit.csv"
DEFAULT_TEAM_ID = 5293026

CSV_COLUMNS = [
    "timestamp",
    "gameweek",
    "total_checks",
    "passed",
    "errors",
    "warnings",
    "pass_rate",
]


@dataclass
class AuditCheck:
    tool: str
    check: str
    passed: bool
    severity: str  # "error" | "warning" | "info"
    detail: str


# ---------------------------------------------------------------------------
# Reference data helpers
# ---------------------------------------------------------------------------

def build_blanking_teams(fixtures: list, gameweek: int) -> set[int]:
    """Return set of team IDs that have NO fixture in the given GW."""
    teams_with_fixture = set()
    for fix in fixtures:
        if fix.get("event") == gameweek:
            teams_with_fixture.add(fix["team_h"])
            teams_with_fixture.add(fix["team_a"])
    # All 20 teams minus those with fixtures
    all_teams = set()
    for fix in fixtures:
        all_teams.add(fix["team_h"])
        all_teams.add(fix["team_a"])
    return all_teams - teams_with_fixture


def verify_team(player_id, claimed_team, players_by_id, teams_by_id, tool_name) -> AuditCheck | None:
    """Verify a player's team assignment matches bootstrap data."""
    ref = players_by_id.get(player_id)
    if ref is None:
        return AuditCheck(tool_name, "ghost_player", False, "error",
                          f"Player ID {player_id} not found in bootstrap data")
    actual_team = teams_by_id.get(ref["team"], {}).get("short_name", "?")
    if claimed_team != actual_team:
        name = ref.get("web_name", "?")
        return AuditCheck(tool_name, "team_assignment", False, "error",
                          f"{name} (ID {player_id}): output says '{claimed_team}', "
                          f"FPL API says '{actual_team}'")
    return None


def verify_position(player_id, claimed_pos, players_by_id, tool_name) -> AuditCheck | None:
    """Verify a player's position matches bootstrap data."""
    ref = players_by_id.get(player_id)
    if ref is None:
        return None  # ghost player already caught
    actual_pos = POSITION_MAP.get(ref["element_type"], "?")
    if claimed_pos != actual_pos:
        name = ref.get("web_name", "?")
        return AuditCheck(tool_name, "position_mismatch", False, "error",
                          f"{name}: output says '{claimed_pos}', FPL API says '{actual_pos}'")
    return None


# ---------------------------------------------------------------------------
# Per-tool audit functions
# ---------------------------------------------------------------------------

async def audit_captain(bootstrap, fixtures, players_by_id, teams_by_id,
                        blanking_teams, next_gw) -> list[AuditCheck]:
    from app.algorithms.captain import get_captain_picks

    checks = []
    try:
        result = await get_captain_picks(top_n=10)
    except Exception as e:
        checks.append(AuditCheck("captain", "tool_crash", False, "error", str(e)))
        return checks

    picks = result.get("picks", [])
    if not picks:
        checks.append(AuditCheck("captain", "empty_output", False, "warning",
                                 "Captain picks returned 0 results"))
        return checks

    checks.append(AuditCheck("captain", "returns_results", True, "info",
                             f"{len(picks)} picks returned"))

    seen_ids = set()
    team_counts: dict[str, int] = {}
    for pick in picks:
        player = pick.get("player", {})
        pid = player.get("id")
        team = player.get("team", "?")
        pos = player.get("position", "?")

        # Ghost player
        if pid not in players_by_id:
            checks.append(AuditCheck("captain", "ghost_player", False, "error",
                                     f"Player ID {pid} ({player.get('name')}) not in FPL data"))
            continue

        # Duplicate
        if pid in seen_ids:
            checks.append(AuditCheck("captain", "duplicate_player", False, "error",
                                     f"{player.get('name')} appears multiple times"))
        seen_ids.add(pid)

        # Team assignment
        tc = verify_team(pid, team, players_by_id, teams_by_id, "captain")
        if tc:
            checks.append(tc)

        # Position
        pc = verify_position(pid, pos, players_by_id, "captain")
        if pc:
            checks.append(pc)

        # Blank GW
        ref = players_by_id[pid]
        if ref["team"] in blanking_teams:
            checks.append(AuditCheck("captain", "blank_gw_leak", False, "error",
                                     f"{player.get('name')} has no fixture in GW{next_gw} "
                                     f"but appears in captain picks"))

        # Status check
        status = ref.get("status", "a")
        if status in INJURY_STATUSES:
            cop = ref.get("chance_of_playing_next_round")
            checks.append(AuditCheck("captain", "injured_player_recommended", False, "warning",
                                     f"{player.get('name')} has status '{status}' "
                                     f"(chance={cop}%) but is recommended"))

        # Score validity
        score = pick.get("score", 0)
        if not isinstance(score, (int, float)) or score != score:  # NaN check
            checks.append(AuditCheck("captain", "invalid_score", False, "error",
                                     f"{player.get('name')} has invalid score: {score}"))

        # Team diversity tracking
        team_counts[team] = team_counts.get(team, 0) + 1

    # Team diversity check
    for t, count in team_counts.items():
        if count >= 4:
            checks.append(AuditCheck("captain", "team_diversity", False, "warning",
                                     f"{count} of {len(picks)} captain picks are from {t}"))

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("captain", "all_checks", True, "info",
                                 f"All checks passed for {len(picks)} picks "
                                 f"(team/pos/status/blank/score validated)"))

    return checks


async def audit_differentials(bootstrap, fixtures, players_by_id, teams_by_id,
                              blanking_teams, next_gw) -> list[AuditCheck]:
    from app.algorithms.differentials import get_differentials

    checks = []
    max_own = 10.0
    try:
        result = await get_differentials(max_ownership_pct=max_own, top_n=10)
    except Exception as e:
        checks.append(AuditCheck("differentials", "tool_crash", False, "error", str(e)))
        return checks

    picks = result.get("differentials", [])
    if not picks:
        checks.append(AuditCheck("differentials", "empty_output", False, "warning",
                                 "Differentials returned 0 results"))
        return checks

    checks.append(AuditCheck("differentials", "returns_results", True, "info",
                             f"{len(picks)} differentials returned"))

    for pick in picks:
        player = pick.get("player", {})
        pid = player.get("id")
        team = player.get("team", "?")
        pos = player.get("position", "?")

        if pid not in players_by_id:
            checks.append(AuditCheck("differentials", "ghost_player", False, "error",
                                     f"Player ID {pid} not in FPL data"))
            continue

        ref = players_by_id[pid]

        # Team
        tc = verify_team(pid, team, players_by_id, teams_by_id, "differentials")
        if tc:
            checks.append(tc)

        # Position
        pc = verify_position(pid, pos, players_by_id, "differentials")
        if pc:
            checks.append(pc)

        # Ownership threshold
        actual_own = float(ref.get("selected_by_percent") or 0)
        if actual_own > max_own + 0.5:  # small tolerance for API lag
            checks.append(AuditCheck("differentials", "ownership_exceeded", False, "error",
                                     f"{player.get('name')} has {actual_own}% ownership "
                                     f"(threshold: {max_own}%)"))

        # Blank GW
        if ref["team"] in blanking_teams:
            checks.append(AuditCheck("differentials", "blank_gw_leak", False, "error",
                                     f"{player.get('name')} has no fixture in GW{next_gw}"))

        # Status
        status = ref.get("status", "a")
        if status in INJURY_STATUSES:
            checks.append(AuditCheck("differentials", "injured_recommended", False, "error",
                                     f"{player.get('name')} has status '{status}' "
                                     f"but is recommended as differential"))

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("differentials", "all_checks", True, "info",
                                 "All differential checks passed"))

    return checks


async def audit_fixtures(bootstrap, fixtures, players_by_id, teams_by_id,
                         blanking_teams, next_gw) -> list[AuditCheck]:
    from app.algorithms.fixtures import get_fixture_outlook

    checks = []
    try:
        result = await get_fixture_outlook(gameweeks_ahead=5)
    except Exception as e:
        checks.append(AuditCheck("fixtures", "tool_crash", False, "error", str(e)))
        return checks

    teams = result.get("teams_by_difficulty", [])
    valid_team_names = {t["short_name"] for t in bootstrap["teams"]}

    # All 20 teams present
    if len(teams) != 20:
        checks.append(AuditCheck("fixtures", "team_count", False, "error",
                                 f"Expected 20 teams, got {len(teams)}"))
    else:
        checks.append(AuditCheck("fixtures", "team_count", True, "info", "All 20 teams present"))

    # Team names valid
    for t in teams:
        if t.get("team") not in valid_team_names:
            checks.append(AuditCheck("fixtures", "invalid_team_name", False, "error",
                                     f"Unknown team short name: {t.get('team')}"))

    # Players to target
    players_to_target = result.get("players_to_target", [])
    for p in players_to_target:
        name = p.get("name", "?")
        team = p.get("team", "?")

        if team not in valid_team_names:
            checks.append(AuditCheck("fixtures", "invalid_player_team", False, "error",
                                     f"{name} has invalid team: {team}"))

        pos = p.get("position", "?")
        if pos not in {"GKP", "DEF", "MID", "FWD"}:
            checks.append(AuditCheck("fixtures", "invalid_position", False, "error",
                                     f"{name} has invalid position: {pos}"))

        # Check player's team has fixture in next GW
        # Find this player in bootstrap
        matches = [pl for pl in bootstrap["elements"] if pl["web_name"] == name and
                   teams_by_id.get(pl["team"], {}).get("short_name") == team]
        if matches and matches[0]["team"] in blanking_teams:
            checks.append(AuditCheck("fixtures", "blank_gw_leak", False, "error",
                                     f"{name} ({team}) has no fixture in GW{next_gw} "
                                     f"but appears in players_to_target"))

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("fixtures", "all_checks", True, "info",
                                 "All fixture checks passed"))

    return checks


async def audit_compare(bootstrap, fixtures, players_by_id, teams_by_id,
                        blanking_teams, next_gw) -> list[AuditCheck]:
    from app.algorithms.compare import compare_players

    checks = []
    # Use well-known players — pick top 2 by total_points
    top_players = sorted(bootstrap["elements"],
                         key=lambda p: p.get("total_points", 0), reverse=True)[:2]
    names = [p["web_name"] for p in top_players]

    try:
        result = await compare_players(names, gameweeks_ahead=5)
    except Exception as e:
        checks.append(AuditCheck("compare", "tool_crash", False, "error", str(e)))
        return checks

    if "error" in result:
        checks.append(AuditCheck("compare", "match_error", False, "error",
                                 f"Compare failed: {result['error']}"))
        return checks

    profiles = result.get("players", [])
    if len(profiles) != 2:
        checks.append(AuditCheck("compare", "wrong_count", False, "error",
                                 f"Expected 2 profiles, got {len(profiles)}"))
        return checks

    checks.append(AuditCheck("compare", "players_matched", True, "info",
                             f"Matched: {', '.join(p.get('name', '?') for p in profiles)}"))

    for prof in profiles:
        pid = prof.get("id")
        if pid not in players_by_id:
            checks.append(AuditCheck("compare", "ghost_player", False, "error",
                                     f"Player ID {pid} not in FPL data"))
            continue

        ref = players_by_id[pid]

        # Team
        tc = verify_team(pid, prof.get("team", "?"), players_by_id, teams_by_id, "compare")
        if tc:
            checks.append(tc)

        # Position
        pc = verify_position(pid, prof.get("position", "?"), players_by_id, "compare")
        if pc:
            checks.append(pc)

        # Cost should match
        expected_cost = ref["now_cost"] / 10
        if abs(prof.get("cost", 0) - expected_cost) > 0.1:
            checks.append(AuditCheck("compare", "cost_mismatch", False, "error",
                                     f"{prof.get('name')}: cost {prof.get('cost')} != "
                                     f"FPL API {expected_cost}"))

        # Blank GW flagging
        blank_gws = prof.get("blank_gameweeks", [])
        if ref["team"] in blanking_teams and next_gw not in blank_gws:
            checks.append(AuditCheck("compare", "blank_gw_not_flagged", False, "error",
                                     f"{prof.get('name')} blanks GW{next_gw} but "
                                     f"blank_gameweeks={blank_gws}"))

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("compare", "all_checks", True, "info",
                                 "All compare checks passed"))

    return checks


async def audit_prices(bootstrap, fixtures, players_by_id, teams_by_id,
                       blanking_teams, next_gw) -> list[AuditCheck]:
    from app.algorithms.prices import get_price_predictions

    checks = []
    try:
        result = await get_price_predictions()
    except Exception as e:
        checks.append(AuditCheck("prices", "tool_crash", False, "error", str(e)))
        return checks

    risers = result.get("likely_risers", [])
    fallers = result.get("likely_fallers", [])

    if not risers and not fallers:
        checks.append(AuditCheck("prices", "empty_output", False, "info",
                                 "No price movers predicted (may be valid if no transfers yet)"))
        return checks

    checks.append(AuditCheck("prices", "returns_results", True, "info",
                             f"{len(risers)} risers, {len(fallers)} fallers"))

    valid_team_names = {t["short_name"] for t in bootstrap["teams"]}

    for entry in risers + fallers:
        player = entry.get("player", {})
        name = player.get("name", "?")
        team = player.get("team", "?")
        pid = player.get("id")

        if team not in valid_team_names:
            checks.append(AuditCheck("prices", "invalid_team", False, "error",
                                     f"{name} has invalid team: {team}"))

        pos = player.get("position", "?")
        if pos not in {"GKP", "DEF", "MID", "FWD"}:
            checks.append(AuditCheck("prices", "invalid_position", False, "error",
                                     f"{name} has invalid position: {pos}"))

        # Team assignment verification
        if pid and pid in players_by_id:
            tc = verify_team(pid, team, players_by_id, teams_by_id, "prices")
            if tc:
                checks.append(tc)

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("prices", "all_checks", True, "info",
                                 "All price checks passed"))

    return checks


async def audit_transfers(bootstrap, fixtures, players_by_id, teams_by_id,
                          blanking_teams, next_gw, team_id) -> list[AuditCheck]:
    from app.algorithms.transfers import get_transfer_suggestions

    checks = []
    try:
        result = await get_transfer_suggestions(team_id=team_id)
    except Exception as e:
        checks.append(AuditCheck("transfers", "tool_crash", False, "error", str(e)))
        return checks

    suggestions = result.get("suggestions", [])
    if not suggestions:
        checks.append(AuditCheck("transfers", "no_suggestions", True, "info",
                                 "No transfer suggestions (squad may be strong)"))
        return checks

    checks.append(AuditCheck("transfers", "returns_results", True, "info",
                             f"{len(suggestions)} suggestions returned"))

    valid_team_names = {t["short_name"] for t in bootstrap["teams"]}

    for sug in suggestions:
        # Check sell candidate
        sell = sug.get("sell", {})
        sell_name = sell.get("name", "?")

        # Check buy replacements
        for repl in sug.get("replacements", [])[:5]:
            rid = repl.get("id")
            rname = repl.get("name", "?")
            rteam = repl.get("team", "?")
            rpos = repl.get("position", "?")

            if rid and rid not in players_by_id:
                checks.append(AuditCheck("transfers", "ghost_player", False, "error",
                                         f"Replacement {rname} (ID {rid}) not in FPL data"))
                continue

            if rteam not in valid_team_names:
                checks.append(AuditCheck("transfers", "invalid_team", False, "error",
                                         f"Replacement {rname} has invalid team: {rteam}"))

            if rpos not in {"GKP", "DEF", "MID", "FWD"}:
                checks.append(AuditCheck("transfers", "invalid_position", False, "error",
                                         f"Replacement {rname} has invalid position: {rpos}"))

            # Blank GW check
            if rid and rid in players_by_id:
                ref = players_by_id[rid]
                if ref["team"] in blanking_teams:
                    checks.append(AuditCheck("transfers", "blank_gw_leak", False, "error",
                                             f"Replacement {rname} has no fixture in GW{next_gw}"))

                # Status check
                status = ref.get("status", "a")
                if status in INJURY_STATUSES:
                    checks.append(AuditCheck("transfers", "injured_recommended", False, "error",
                                             f"Replacement {rname} has status '{status}'"))

            # Position match
            if sell.get("position") and rpos != POSITION_MAP.get(sell.get("position_type"), rpos):
                checks.append(AuditCheck("transfers", "position_mismatch", False, "error",
                                         f"Selling {sell_name} ({sell.get('position')}) "
                                         f"but replacement {rname} is {rpos}"))

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("transfers", "all_checks", True, "info",
                                 "All transfer checks passed"))

    return checks


async def audit_scout(bootstrap, fixtures, players_by_id, teams_by_id,
                      blanking_teams, next_gw, team_id) -> list[AuditCheck]:
    from app.algorithms.scout import get_squad_scout

    checks = []
    try:
        result = await get_squad_scout(team_id=team_id)
    except Exception as e:
        checks.append(AuditCheck("scout", "tool_crash", False, "error", str(e)))
        return checks

    squad = result.get("squad_report", [])
    if not squad:
        checks.append(AuditCheck("scout", "empty_squad", False, "warning",
                                 "Scout returned empty squad (GW may not have started)"))
        return checks

    checks.append(AuditCheck("scout", "returns_results", True, "info",
                             f"{len(squad)} squad players returned"))

    valid_team_names = {t["short_name"] for t in bootstrap["teams"]}
    valid_positions = {"GKP", "DEF", "MID", "FWD"}

    for p in squad:
        name = p.get("name", "?")
        team = p.get("team", "?")
        pos = p.get("position", "?")

        if team not in valid_team_names:
            checks.append(AuditCheck("scout", "invalid_team", False, "error",
                                     f"{name} has invalid team: {team}"))

        if pos not in valid_positions:
            checks.append(AuditCheck("scout", "invalid_position", False, "error",
                                     f"{name} has invalid position: {pos}"))

        # Cross-ref ep_next with bootstrap by matching name + team
        matches = [pl for pl in bootstrap["elements"]
                   if pl["web_name"] == name and
                   teams_by_id.get(pl["team"], {}).get("short_name") == team]
        if matches:
            ref = matches[0]
            ref_ep = float(ref.get("ep_next") or 0)
            tool_ep = float(p.get("ep_next") or 0)
            if abs(ref_ep - tool_ep) > 0.5:
                checks.append(AuditCheck("scout", "ep_next_mismatch", False, "warning",
                                         f"{name}: ep_next {tool_ep} vs FPL API {ref_ep}"))

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("scout", "all_checks", True, "info",
                                 "All scout checks passed"))

    return checks


async def audit_chips(bootstrap, fixtures, players_by_id, teams_by_id,
                      blanking_teams, next_gw, team_id) -> list[AuditCheck]:
    from app.algorithms.chips import get_chip_strategy

    checks = []
    try:
        result = await get_chip_strategy(team_id=team_id)
    except Exception as e:
        checks.append(AuditCheck("chips", "tool_crash", False, "error", str(e)))
        return checks

    recommendations = result.get("recommendations", [])
    current_gw = get_current_gameweek(bootstrap)
    valid_chips = {"wildcard", "bboost", "freehit", "3xc",
                   "Wildcard", "Bench Boost", "Free Hit", "Triple Captain"}

    for rec in recommendations:
        chip = rec.get("chip", "")
        best_gw = rec.get("recommended_gameweek")

        if chip not in valid_chips:
            checks.append(AuditCheck("chips", "invalid_chip", False, "error",
                                     f"Unknown chip: {chip}"))

        if best_gw is not None and best_gw < current_gw:
            checks.append(AuditCheck("chips", "past_gw_recommended", False, "error",
                                     f"Chip {chip} recommended for GW{best_gw} "
                                     f"which is in the past (current: GW{current_gw})"))

        if best_gw is not None and best_gw > 38:
            checks.append(AuditCheck("chips", "invalid_gw", False, "error",
                                     f"Chip {chip} recommended for GW{best_gw} (max is 38)"))

    checks.append(AuditCheck("chips", "returns_results", True, "info",
                             f"{len(recommendations)} chip recommendations"))

    if not any(not c.passed for c in checks):
        checks.append(AuditCheck("chips", "all_checks", True, "info",
                                 "All chip checks passed"))

    return checks


# ---------------------------------------------------------------------------
# Cross-cutting checks
# ---------------------------------------------------------------------------

def check_stale_data(bootstrap) -> list[AuditCheck]:
    """Check if FPL API data looks stale."""
    checks = []

    # If ALL players have 0 transfers_in_event, data might be stale
    total_transfers = sum(p.get("transfers_in_event", 0) for p in bootstrap["elements"])
    if total_transfers == 0:
        checks.append(AuditCheck("data_quality", "stale_transfers", False, "warning",
                                 "All players have 0 transfers_in_event — API data may be stale"))
    else:
        checks.append(AuditCheck("data_quality", "transfers_active", True, "info",
                                 f"Total transfers_in_event: {total_transfers:,}"))

    # Check player count
    count = len(bootstrap["elements"])
    if count < 500:
        checks.append(AuditCheck("data_quality", "low_player_count", False, "warning",
                                 f"Only {count} players in bootstrap (expected ~700+)"))

    # Check team count
    team_count = len(bootstrap["teams"])
    if team_count != 20:
        checks.append(AuditCheck("data_quality", "wrong_team_count", False, "error",
                                 f"Expected 20 teams, got {team_count}"))

    return checks


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def print_report(checks: list[AuditCheck], gameweek: int) -> dict:
    """Print human-readable report and return summary dict."""
    errors = [c for c in checks if not c.passed and c.severity == "error"]
    warnings = [c for c in checks if not c.passed and c.severity == "warning"]
    passed = [c for c in checks if c.passed]

    total = len(checks)
    pass_rate = round(len(passed) / total * 100, 1) if total else 0

    print()
    print("=" * 60)
    print(f"  FPL INTELLIGENCE — ACCURACY AUDIT (GW{gameweek})")
    print("=" * 60)
    print()
    print(f"  Total checks:  {total}")
    print(f"  Passed:        {len(passed)}")
    print(f"  Errors:        {len(errors)}")
    print(f"  Warnings:      {len(warnings)}")
    print(f"  Pass rate:     {pass_rate}%")
    print()

    if errors:
        print("-" * 60)
        print("  ERRORS")
        print("-" * 60)
        for c in errors:
            print(f"  [{c.tool}] {c.check}: {c.detail}")
        print()

    if warnings:
        print("-" * 60)
        print("  WARNINGS")
        print("-" * 60)
        for c in warnings:
            print(f"  [{c.tool}] {c.check}: {c.detail}")
        print()

    # Per-tool summary
    tools = {}
    for c in checks:
        if c.tool not in tools:
            tools[c.tool] = {"checks": 0, "passed": 0, "errors": 0, "warnings": 0}
        tools[c.tool]["checks"] += 1
        if c.passed:
            tools[c.tool]["passed"] += 1
        elif c.severity == "error":
            tools[c.tool]["errors"] += 1
        elif c.severity == "warning":
            tools[c.tool]["warnings"] += 1

    print("-" * 60)
    print(f"  {'Tool':<20} {'Checks':>7} {'Pass':>6} {'Err':>5} {'Warn':>5}")
    print("-" * 60)
    for tool, stats in sorted(tools.items()):
        status = "OK" if stats["errors"] == 0 else "FAIL"
        print(f"  {tool:<20} {stats['checks']:>7} {stats['passed']:>6} "
              f"{stats['errors']:>5} {stats['warnings']:>5}  {status}")
    print("=" * 60)
    print()

    summary = {
        "total_checks": total,
        "passed": len(passed),
        "errors": len(errors),
        "warnings": len(warnings),
        "pass_rate_pct": pass_rate,
    }
    return summary


def save_json(checks: list[AuditCheck], summary: dict, gameweek: int):
    """Save full audit report as JSON."""
    AUDIT_JSON.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gameweek": gameweek,
        "summary": summary,
        "checks": [asdict(c) for c in checks],
        "failures": [asdict(c) for c in checks if not c.passed],
    }
    AUDIT_JSON.write_text(json.dumps(report, indent=2))
    print(f"  Report saved to {AUDIT_JSON}")


def append_csv(summary: dict, gameweek: int):
    """Append summary row to CSV for trend tracking."""
    AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
    file_exists = AUDIT_CSV.exists()
    with open(AUDIT_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gameweek": gameweek,
            "total_checks": summary["total_checks"],
            "passed": summary["passed"],
            "errors": summary["errors"],
            "warnings": summary["warnings"],
            "pass_rate": summary["pass_rate_pct"],
        })
    print(f"  CSV appended to {AUDIT_CSV}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_audit(team_id: int, tool_filter: str | None = None) -> list[AuditCheck]:
    bootstrap, fixtures = await asyncio.gather(get_bootstrap(), get_fixtures())
    next_gw = get_next_gameweek(bootstrap)

    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    blanking_teams = build_blanking_teams(fixtures, next_gw)

    if blanking_teams:
        blanking_names = [teams_by_id.get(t, {}).get("short_name", "?") for t in blanking_teams]
        print(f"\n  Blank teams in GW{next_gw}: {', '.join(sorted(blanking_names))}")
    else:
        print(f"\n  No blank teams in GW{next_gw}")

    all_checks: list[AuditCheck] = []

    # Define all audit tasks
    audit_tasks = {
        "captain": lambda: audit_captain(bootstrap, fixtures, players_by_id,
                                         teams_by_id, blanking_teams, next_gw),
        "differentials": lambda: audit_differentials(bootstrap, fixtures, players_by_id,
                                                     teams_by_id, blanking_teams, next_gw),
        "fixtures": lambda: audit_fixtures(bootstrap, fixtures, players_by_id,
                                           teams_by_id, blanking_teams, next_gw),
        "compare": lambda: audit_compare(bootstrap, fixtures, players_by_id,
                                         teams_by_id, blanking_teams, next_gw),
        "prices": lambda: audit_prices(bootstrap, fixtures, players_by_id,
                                       teams_by_id, blanking_teams, next_gw),
        "transfers": lambda: audit_transfers(bootstrap, fixtures, players_by_id,
                                             teams_by_id, blanking_teams, next_gw, team_id),
        "scout": lambda: audit_scout(bootstrap, fixtures, players_by_id,
                                     teams_by_id, blanking_teams, next_gw, team_id),
        "chips": lambda: audit_chips(bootstrap, fixtures, players_by_id,
                                     teams_by_id, blanking_teams, next_gw, team_id),
    }

    # Filter if requested
    if tool_filter:
        if tool_filter not in audit_tasks:
            print(f"  Unknown tool: {tool_filter}")
            print(f"  Available: {', '.join(audit_tasks.keys())}")
            return []
        audit_tasks = {tool_filter: audit_tasks[tool_filter]}

    # Run all audit tasks concurrently
    task_names = list(audit_tasks.keys())
    results = await asyncio.gather(
        *(fn() for fn in audit_tasks.values()),
        return_exceptions=True,
    )

    for name, result in zip(task_names, results):
        if isinstance(result, Exception):
            all_checks.append(AuditCheck(name, "audit_crash", False, "error",
                                         f"Audit function crashed: {result}"))
            traceback.print_exception(type(result), result, result.__traceback__)
        else:
            all_checks.extend(result)

    # Cross-cutting checks
    all_checks.extend(check_stale_data(bootstrap))

    return all_checks


def main():
    parser = argparse.ArgumentParser(description="FPL Intelligence accuracy audit")
    parser.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID,
                        help="FPL team ID for team-dependent tools")
    parser.add_argument("--tool", type=str, default=None,
                        help="Run checks for a single tool only")
    parser.add_argument("--json-only", action="store_true",
                        help="Suppress stdout, just write JSON")
    args = parser.parse_args()

    checks = asyncio.run(run_audit(team_id=args.team_id, tool_filter=args.tool))

    bootstrap = asyncio.run(get_bootstrap())
    gw = get_next_gameweek(bootstrap)

    if not args.json_only:
        summary = print_report(checks, gw)
    else:
        errors = [c for c in checks if not c.passed and c.severity == "error"]
        warnings = [c for c in checks if not c.passed and c.severity == "warning"]
        passed = [c for c in checks if c.passed]
        total = len(checks)
        summary = {
            "total_checks": total,
            "passed": len(passed),
            "errors": len(errors),
            "warnings": len(warnings),
            "pass_rate_pct": round(len(passed) / total * 100, 1) if total else 0,
        }

    save_json(checks, summary, gw)
    append_csv(summary, gw)

    # Exit with error code if any errors found
    if summary["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
