"""
Full-suite backtest for FPL algorithm accuracy.

Runs four backtest categories across finished gameweeks:
  1. Differentials   — did our low-ownership picks actually score well?
  2. Transfers       — did sell candidates underperform and buys outperform?
  3. BPS accuracy    — projected bonus vs actual confirmed bonus
  4. Blank-GW detect — did we correctly identify teams with no fixtures?

Reuses the disk-cache pattern from scripts/backtest.py.

Usage:
    python scripts/backtest_full.py                  # all finished GWs
    python scripts/backtest_full.py --gameweeks 25-31
    python scripts/backtest_full.py --clear-cache
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Allow running from project root: `python scripts/backtest_full.py`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.algorithms.captain import _build_fixture_map  # noqa: E402
from app.algorithms.differentials import _differential_score  # noqa: E402
from app.algorithms.live import _calculate_fixture_bps  # noqa: E402
from app.algorithms.transfers import _player_value_score  # noqa: E402
from app.fpl_client import get_bootstrap, get_fixtures, get_live_points  # noqa: E402

# ---------------------------------------------------------------------------
# Disk cache — reuse the same cache dir as scripts/backtest.py
# ---------------------------------------------------------------------------
CACHE_DIR = PROJECT_ROOT / "data" / "backtest_cache"


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> Any | None:
    path = _cache_path(key)
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return None


def _write_cache(key: str, data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(key), "w") as f:
        json.dump(data, f)


async def cached_bootstrap() -> dict:
    data = _read_cache("bootstrap")
    if data is not None:
        return data
    data = await get_bootstrap()
    _write_cache("bootstrap", data)
    return data


async def cached_fixtures() -> list:
    data = _read_cache("fixtures")
    if data is not None:
        return data
    data = await get_fixtures()
    _write_cache("fixtures", data)
    return data


async def cached_live_points(gw: int) -> dict:
    key = f"live_gw{gw}"
    data = _read_cache(key)
    if data is not None:
        return data
    data = await get_live_points(gw)
    _write_cache(key, data)
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_finished_gameweeks(bootstrap: dict) -> list[int]:
    """Return sorted list of finished gameweek IDs."""
    return sorted(gw["id"] for gw in bootstrap["events"] if gw["finished"])


def _build_actual_points_map(live_data: dict) -> dict[int, int]:
    """Map player ID -> total_points from live data."""
    return {el["id"]: el["stats"]["total_points"] for el in live_data.get("elements", [])}


def _build_actual_minutes_map(live_data: dict) -> dict[int, int]:
    """Map player ID -> minutes from live data."""
    return {el["id"]: el["stats"].get("minutes", 0) for el in live_data.get("elements", [])}


# ---------------------------------------------------------------------------
# 1. Differentials backtest
# ---------------------------------------------------------------------------


def backtest_differentials_gw(
    bootstrap: dict,
    fixtures: list,
    live_data: dict,
    gameweek: int,
    max_ownership_pct: float = 10.0,
    top_n: int = 10,
) -> dict:
    """
    Run differential algorithm for a GW, then check performance.

    Metrics:
      - avg_points: average actual points of our differential picks
      - hit_rate_top50: fraction of our picks that landed in the GW top 50
      - avg_rank: average rank of our picks among all players
    """
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, gameweek, teams_by_id=teams_by_id)
    actual_pts = _build_actual_points_map(live_data)
    actual_mins = _build_actual_minutes_map(live_data)

    # Top 50 scorers (players who played)
    played_pts = [(pid, pts) for pid, pts in actual_pts.items() if actual_mins.get(pid, 0) > 0]
    played_pts.sort(key=lambda x: x[1], reverse=True)
    top50_ids = {pid for pid, _ in played_pts[:50]}

    # Run differential algorithm
    scored = []
    for player in bootstrap["elements"]:
        ownership = float(player.get("selected_by_percent") or 0)
        if ownership > max_ownership_pct:
            continue
        # Skip unavailable players (same filter as production)
        if player.get("status") in {"i", "d", "s", "u"}:
            continue
        player_fixtures = fixture_map.get(player["team"])
        if not player_fixtures:
            continue
        score = _differential_score(player, player_fixtures, ownership)
        scored.append((score, player))

    scored.sort(key=lambda x: x[0], reverse=True)
    picks = scored[:top_n]

    if not picks:
        return {"gameweek": gameweek, "num_picks": 0, "avg_points": 0, "hit_rate_top50": 0, "avg_rank": 0}

    # Evaluate picks
    total_pts = 0
    hits = 0
    total_rank = 0
    pick_details = []

    for _score, player in picks:
        pid = player["id"]
        pts = actual_pts.get(pid, 0)
        total_pts += pts

        if pid in top50_ids:
            hits += 1

        # Rank among all who played
        rank = 1
        for other_pid, _other_pts in played_pts:
            if other_pid == pid:
                break
            rank += 1
        else:
            rank = len(played_pts)
        total_rank += rank

        pick_details.append(
            {
                "name": player["web_name"],
                "ownership_pct": float(player.get("selected_by_percent") or 0),
                "actual_points": pts,
                "rank": rank,
                "in_top50": pid in top50_ids,
            }
        )

    n = len(picks)
    return {
        "gameweek": gameweek,
        "num_picks": n,
        "avg_points": round(total_pts / n, 2),
        "hit_rate_top50": round(hits / n * 100, 1),
        "avg_rank": round(total_rank / n, 1),
        "picks": pick_details,
    }


# ---------------------------------------------------------------------------
# 2. Transfer suggestions backtest
# ---------------------------------------------------------------------------


def backtest_transfers_gw(
    bootstrap: dict,
    fixtures: list,
    live_data: dict,
    gameweek: int,
) -> dict:
    """
    Evaluate transfer algorithm by scoring all players via _player_value_score,
    then checking if the worst-scored (sell candidates) actually underperformed
    and the best-scored (buy candidates) actually outperformed.

    We use a position-balanced sample: bottom 2 per position as sells,
    top 2 per position as buys.
    """
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, gameweek, teams_by_id=teams_by_id)
    actual_pts = _build_actual_points_map(live_data)
    actual_mins = _build_actual_minutes_map(live_data)

    # Score all available players
    by_position: dict[int, list[tuple[float, dict]]] = defaultdict(list)
    for player in bootstrap["elements"]:
        if player.get("status") in {"i", "d", "s", "u"}:
            continue
        player_fixtures = fixture_map.get(player["team"])
        if not player_fixtures:
            continue
        # Only consider players with meaningful minutes this season
        if player.get("minutes", 0) < 90:
            continue
        score = _player_value_score(player, player_fixtures)
        by_position[player["element_type"]].append((score, player))

    sell_pts_list = []
    buy_pts_list = []
    sell_details = []
    buy_details = []

    for pos_type in sorted(by_position):
        players = by_position[pos_type]
        players.sort(key=lambda x: x[0])

        # Bottom 2 = sell candidates
        sells = players[:2]
        # Top 2 = buy candidates
        buys = players[-2:]

        for _score, player in sells:
            pid = player["id"]
            pts = actual_pts.get(pid, 0)
            mins = actual_mins.get(pid, 0)
            # Only count if the player actually had a chance to play
            if mins > 0 or pts > 0:
                sell_pts_list.append(pts)
            sell_details.append(
                {
                    "name": player["web_name"],
                    "value_score": _score,
                    "actual_points": pts,
                    "minutes": mins,
                }
            )

        for _score, player in buys:
            pid = player["id"]
            pts = actual_pts.get(pid, 0)
            mins = actual_mins.get(pid, 0)
            if mins > 0 or pts > 0:
                buy_pts_list.append(pts)
            buy_details.append(
                {
                    "name": player["web_name"],
                    "value_score": _score,
                    "actual_points": pts,
                    "minutes": mins,
                }
            )

    avg_sell = round(sum(sell_pts_list) / len(sell_pts_list), 2) if sell_pts_list else 0
    avg_buy = round(sum(buy_pts_list) / len(buy_pts_list), 2) if buy_pts_list else 0

    return {
        "gameweek": gameweek,
        "avg_sell_points": avg_sell,
        "avg_buy_points": avg_buy,
        "buy_minus_sell": round(avg_buy - avg_sell, 2),
        "num_sells_scored": len(sell_pts_list),
        "num_buys_scored": len(buy_pts_list),
        "sell_candidates": sell_details,
        "buy_candidates": buy_details,
    }


# ---------------------------------------------------------------------------
# 3. BPS accuracy backtest
# ---------------------------------------------------------------------------


def backtest_bps_gw(
    bootstrap: dict,
    fixtures: list,
    live_data: dict,
    gameweek: int,
) -> dict:
    """
    Compare our projected bonus from _calculate_fixture_bps against the
    actual confirmed bonus (stats.bonus) from the live API.

    Metrics:
      - exact_match_rate: fraction of players where projected == actual
      - mean_absolute_error: avg |projected - actual| across all players
      - total_players: how many players we evaluated
    """
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    live_elements = {el["id"]: el for el in live_data.get("elements", [])}

    gw_fixtures = [f for f in fixtures if f.get("event") == gameweek]

    # Build fixture -> player mapping
    team_to_fixture: dict[int, int] = {}
    for fix in gw_fixtures:
        team_to_fixture[fix["team_h"]] = fix["id"]
        team_to_fixture[fix["team_a"]] = fix["id"]

    fixture_players: dict[int, set[int]] = defaultdict(set)
    for pid in live_elements:
        p = players_by_id.get(pid, {})
        player_team = p.get("team")
        if player_team and player_team in team_to_fixture:
            fixture_players[team_to_fixture[player_team]].add(pid)

    # Run BPS algorithm per fixture, collect projected bonus
    all_projected: dict[int, int] = {}
    for fix in gw_fixtures:
        fid = fix["id"]
        started = fix.get("started", False)
        if not started:
            continue
        result = _calculate_fixture_bps(
            fixture_id=fid,
            fixture_player_ids=fixture_players.get(fid, set()),
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=teams_by_id,
        )
        for pid, info in result["player_bonus"].items():
            all_projected[pid] = info["projected_bonus"]

    # Compare against actual bonus
    exact_matches = 0
    total_error = 0
    total_compared = 0
    mismatches = []

    for pid, projected in all_projected.items():
        el = live_elements.get(pid, {})
        actual_bonus = el.get("stats", {}).get("bonus", 0)
        mins = el.get("stats", {}).get("minutes", 0)

        # Only compare players who actually played
        if mins == 0:
            continue

        total_compared += 1
        error = abs(projected - actual_bonus)
        total_error += error

        if projected == actual_bonus:
            exact_matches += 1
        elif projected > 0 or actual_bonus > 0:
            # Only log interesting mismatches (where bonus was in play)
            p = players_by_id.get(pid, {})
            mismatches.append(
                {
                    "name": p.get("web_name", "?"),
                    "projected": projected,
                    "actual": actual_bonus,
                    "error": error,
                }
            )

    exact_rate = round(exact_matches / total_compared * 100, 1) if total_compared > 0 else 0
    mae = round(total_error / total_compared, 3) if total_compared > 0 else 0

    # Sort mismatches by error descending, keep top 5
    mismatches.sort(key=lambda x: x["error"], reverse=True)

    return {
        "gameweek": gameweek,
        "total_players": total_compared,
        "exact_match_rate": exact_rate,
        "mean_absolute_error": mae,
        "exact_matches": exact_matches,
        "top_mismatches": mismatches[:5],
    }


# ---------------------------------------------------------------------------
# 4. Blank-GW detection backtest
# ---------------------------------------------------------------------------


def backtest_blanks_gw(
    bootstrap: dict,
    fixtures: list,
    live_data: dict,
    gameweek: int,
) -> dict:
    """
    For a given GW, identify which teams had no fixtures scheduled (blanking
    teams) from the fixture list. Then verify against live data: did any
    player from those teams actually get minutes?

    Also check the inverse: did any team WITH a scheduled fixture have zero
    players get minutes? (unlikely but would indicate a data issue)

    Metrics:
      - num_blanking_teams: teams with no fixture in this GW
      - detection_correct: True if our blank detection was accurate
      - false_positives: teams we said blank but had players with minutes
      - false_negatives: teams we said had fixtures but no player got minutes
    """
    all_team_ids = {t["id"] for t in bootstrap["teams"]}
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}

    # Teams with fixtures in this GW
    gw_fixtures = [f for f in fixtures if f.get("event") == gameweek]
    teams_with_fixture = set()
    for fix in gw_fixtures:
        teams_with_fixture.add(fix["team_h"])
        teams_with_fixture.add(fix["team_a"])

    blanking_teams = all_team_ids - teams_with_fixture

    # From live data: which teams had at least one player get minutes?
    teams_with_minutes: set[int] = set()
    for el in live_data.get("elements", []):
        pid = el["id"]
        mins = el["stats"].get("minutes", 0)
        if mins > 0:
            player = players_by_id.get(pid, {})
            team_id = player.get("team")
            if team_id:
                teams_with_minutes.add(team_id)

    # False positives: we said they blank but they had minutes
    false_positives = blanking_teams & teams_with_minutes

    # False negatives: we said they have a fixture but no one played
    # (This can happen legitimately if a match was postponed after fixture
    # data was published, so it's more of a data-staleness indicator.)
    teams_no_minutes = all_team_ids - teams_with_minutes
    false_negatives = teams_with_fixture & teams_no_minutes

    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    detection_correct = len(false_positives) == 0 and len(false_negatives) == 0

    return {
        "gameweek": gameweek,
        "num_blanking_teams": len(blanking_teams),
        "blanking_teams": sorted(teams_by_id.get(t, {}).get("short_name", "?") for t in blanking_teams),
        "detection_correct": detection_correct,
        "false_positives": sorted(teams_by_id.get(t, {}).get("short_name", "?") for t in false_positives),
        "false_negatives": sorted(teams_by_id.get(t, {}).get("short_name", "?") for t in false_negatives),
    }


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def _print_report(results: dict) -> None:
    """Print a comprehensive report to stdout."""
    sep = "=" * 80
    thin = "-" * 80

    print(sep)
    print("FULL ALGORITHM BACKTEST REPORT")
    print(f"Gameweeks: {results['gw_range']}  ({results['gameweeks_tested']} GWs)")
    print(sep)

    # --- Differentials ---
    diff = results["differentials_summary"]
    print()
    print("1. DIFFERENTIALS")
    print(thin)
    print(f"  Avg points per differential pick:  {diff['avg_points']}")
    print(f"  Hit rate (pick in GW top 50):      {diff['hit_rate_top50']}%")
    print(f"  Avg rank of picks:                 {diff['avg_rank']}")
    print(f"  GWs evaluated:                     {diff['gws_evaluated']}")

    # --- Transfers ---
    xfer = results["transfers_summary"]
    print()
    print("2. TRANSFER SUGGESTIONS")
    print(thin)
    print(f"  Avg points of sell candidates:     {xfer['avg_sell_points']}")
    print(f"  Avg points of buy candidates:      {xfer['avg_buy_points']}")
    print(f"  Buy - Sell spread:                 {xfer['avg_spread']}")
    direction = "CORRECT" if xfer["avg_spread"] > 0 else "WRONG"
    print(f"  Direction:                         {direction} (buys should outscore sells)")
    print(f"  GWs evaluated:                     {xfer['gws_evaluated']}")

    # --- BPS ---
    bps = results["bps_summary"]
    print()
    print("3. BPS ACCURACY")
    print(thin)
    print(f"  Exact match rate:                  {bps['exact_match_rate']}%")
    print(f"  Mean absolute error:               {bps['mean_absolute_error']}")
    print(f"  Total players evaluated:           {bps['total_players']}")
    print(f"  GWs evaluated:                     {bps['gws_evaluated']}")

    # --- Blanks ---
    blanks = results["blanks_summary"]
    print()
    print("4. BLANK-GW DETECTION")
    print(thin)
    print(f"  GWs with blanks:                   {blanks['gws_with_blanks']}")
    print(f"  Detection accuracy:                {blanks['accuracy']}%")
    print(f"  Total false positives:             {blanks['total_false_positives']}")
    print(f"  Total false negatives:             {blanks['total_false_negatives']}")
    print(f"  GWs evaluated:                     {blanks['gws_evaluated']}")

    # --- Per-GW detail table ---
    print()
    print(sep)
    print("PER-GAMEWEEK DETAIL")
    print(sep)
    hdr = (
        f"{'GW':>3}  {'Diff Avg':>8} {'Diff Hit%':>9} "
        f"{'Sell Pts':>8} {'Buy Pts':>8} {'Spread':>7} "
        f"{'BPS Match%':>10} {'BPS MAE':>8} "
        f"{'Blanks':>6} {'BlankOK':>7}"
    )
    print(hdr)
    print(thin)

    diff_gws = {r["gameweek"]: r for r in results["differentials_detail"]}
    xfer_gws = {r["gameweek"]: r for r in results["transfers_detail"]}
    bps_gws = {r["gameweek"]: r for r in results["bps_detail"]}
    blank_gws = {r["gameweek"]: r for r in results["blanks_detail"]}

    all_gws = sorted(set(diff_gws) | set(xfer_gws) | set(bps_gws) | set(blank_gws))

    for gw in all_gws:
        d = diff_gws.get(gw, {})
        x = xfer_gws.get(gw, {})
        b = bps_gws.get(gw, {})
        bl = blank_gws.get(gw, {})

        d_avg = f"{d.get('avg_points', 0):>8.1f}"
        d_hit = f"{d.get('hit_rate_top50', 0):>8.1f}%"
        x_sell = f"{x.get('avg_sell_points', 0):>8.1f}"
        x_buy = f"{x.get('avg_buy_points', 0):>8.1f}"
        x_spread = f"{x.get('buy_minus_sell', 0):>+7.1f}"
        b_match = f"{b.get('exact_match_rate', 0):>9.1f}%"
        b_mae = f"{b.get('mean_absolute_error', 0):>8.3f}"
        bl_n = f"{bl.get('num_blanking_teams', 0):>6}"
        bl_ok = "Y" if bl.get("detection_correct", True) else "N"

        print(f"{gw:>3}  {d_avg} {d_hit} {x_sell} {x_buy} {x_spread} {b_match} {b_mae} {bl_n} {bl_ok:>7}")

    print(sep)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def run_full_backtest(
    gw_start: int | None = None,
    gw_end: int | None = None,
) -> dict:
    print("Fetching bootstrap data...")
    bootstrap = await cached_bootstrap()
    print("Fetching fixtures...")
    fixtures = await cached_fixtures()

    finished = get_finished_gameweeks(bootstrap)
    if not finished:
        print("No finished gameweeks found.")
        return {"error": "No finished gameweeks"}

    if gw_start is not None:
        finished = [gw for gw in finished if gw >= gw_start]
    if gw_end is not None:
        finished = [gw for gw in finished if gw <= gw_end]

    if not finished:
        print("No finished gameweeks in specified range.")
        return {"error": "No finished gameweeks in range"}

    print(f"Backtesting GW{finished[0]}--GW{finished[-1]} ({len(finished)} gameweeks)")
    print()

    # Fetch all live data
    all_live: dict[int, dict] = {}
    for gw in finished:
        print(f"  Fetching live data for GW{gw}...", end=" ", flush=True)
        live = await cached_live_points(gw)
        all_live[gw] = live
        print("OK")

    print()
    print("Running backtests...")
    print()

    # --- Run all 4 categories ---
    diff_results = []
    xfer_results = []
    bps_results = []
    blank_results = []

    for gw in finished:
        live = all_live[gw]

        diff_results.append(backtest_differentials_gw(bootstrap, fixtures, live, gw))
        xfer_results.append(backtest_transfers_gw(bootstrap, fixtures, live, gw))
        bps_results.append(backtest_bps_gw(bootstrap, fixtures, live, gw))
        blank_results.append(backtest_blanks_gw(bootstrap, fixtures, live, gw))

    # --- Aggregate summaries ---

    # Differentials
    diff_with_picks = [r for r in diff_results if r["num_picks"] > 0]
    diff_summary = {
        "avg_points": round(sum(r["avg_points"] for r in diff_with_picks) / len(diff_with_picks), 2)
        if diff_with_picks
        else 0,
        "hit_rate_top50": round(sum(r["hit_rate_top50"] for r in diff_with_picks) / len(diff_with_picks), 1)
        if diff_with_picks
        else 0,
        "avg_rank": round(sum(r["avg_rank"] for r in diff_with_picks) / len(diff_with_picks), 1)
        if diff_with_picks
        else 0,
        "gws_evaluated": len(diff_with_picks),
    }

    # Transfers
    xfer_with_data = [r for r in xfer_results if r["num_buys_scored"] > 0]
    xfer_summary = {
        "avg_sell_points": round(sum(r["avg_sell_points"] for r in xfer_with_data) / len(xfer_with_data), 2)
        if xfer_with_data
        else 0,
        "avg_buy_points": round(sum(r["avg_buy_points"] for r in xfer_with_data) / len(xfer_with_data), 2)
        if xfer_with_data
        else 0,
        "avg_spread": round(sum(r["buy_minus_sell"] for r in xfer_with_data) / len(xfer_with_data), 2)
        if xfer_with_data
        else 0,
        "gws_evaluated": len(xfer_with_data),
    }

    # BPS
    bps_with_data = [r for r in bps_results if r["total_players"] > 0]
    bps_summary = {
        "exact_match_rate": round(sum(r["exact_match_rate"] for r in bps_with_data) / len(bps_with_data), 1)
        if bps_with_data
        else 0,
        "mean_absolute_error": round(sum(r["mean_absolute_error"] for r in bps_with_data) / len(bps_with_data), 3)
        if bps_with_data
        else 0,
        "total_players": sum(r["total_players"] for r in bps_with_data),
        "gws_evaluated": len(bps_with_data),
    }

    # Blanks
    gws_with_blanks = sum(1 for r in blank_results if r["num_blanking_teams"] > 0)
    correct_detections = sum(1 for r in blank_results if r["detection_correct"])
    blanks_summary = {
        "gws_with_blanks": gws_with_blanks,
        "accuracy": round(correct_detections / len(blank_results) * 100, 1) if blank_results else 0,
        "total_false_positives": sum(len(r["false_positives"]) for r in blank_results),
        "total_false_negatives": sum(len(r["false_negatives"]) for r in blank_results),
        "gws_evaluated": len(blank_results),
    }

    result = {
        "gw_range": f"GW{finished[0]}--GW{finished[-1]}",
        "gameweeks_tested": len(finished),
        "differentials_summary": diff_summary,
        "transfers_summary": xfer_summary,
        "bps_summary": bps_summary,
        "blanks_summary": blanks_summary,
        "differentials_detail": diff_results,
        "transfers_detail": xfer_results,
        "bps_detail": bps_results,
        "blanks_detail": blank_results,
    }

    _print_report(result)

    # Save to JSON
    output_path = PROJECT_ROOT / "data" / "backtest_full.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults saved to {output_path}")

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Full-suite backtest for all FPL algorithms across finished gameweeks."
    )
    parser.add_argument(
        "--gameweeks",
        type=str,
        default=None,
        help="Gameweek range, e.g. '1-10', '5', '25-31'. Default: all finished.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        default=False,
        help="Clear the backtest API cache before running.",
    )
    return parser.parse_args()


def parse_gw_range(s: str) -> tuple[int | None, int | None]:
    """Parse '5', '1-10', etc. into (start, end)."""
    if "-" in s:
        parts = s.split("-", 1)
        return int(parts[0]), int(parts[1])
    else:
        gw = int(s)
        return gw, gw


def main() -> None:
    args = parse_args()

    if args.clear_cache and CACHE_DIR.exists():
        import shutil

        shutil.rmtree(CACHE_DIR)
        print("Backtest cache cleared.\n")

    gw_start = None
    gw_end = None
    if args.gameweeks:
        gw_start, gw_end = parse_gw_range(args.gameweeks)

    asyncio.run(run_full_backtest(gw_start=gw_start, gw_end=gw_end))


if __name__ == "__main__":
    main()
