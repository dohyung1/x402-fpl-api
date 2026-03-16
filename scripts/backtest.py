"""
Backtest script for the captain pick algorithm.

Replays finished gameweeks, compares our algorithm's top picks against
actual FPL point scorers, and reports accuracy metrics.

Usage:
    python scripts/backtest.py                    # all finished GWs
    python scripts/backtest.py --gameweeks 1-10   # GW 1 through 10
    python scripts/backtest.py --gameweeks 5      # just GW 5
    python scripts/backtest.py --suggest-weights   # also output weight suggestions
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Allow running from project root: `python scripts/backtest.py`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.algorithms.captain import (  # noqa: E402
    POSITION_MAP,
    WEIGHTS,
    _build_fixture_map,
    _score_player,
)
from app.fpl_client import get_bootstrap, get_fixtures, get_live_points  # noqa: E402

# ---------------------------------------------------------------------------
# Disk cache — avoid hammering the FPL API across repeated backtest runs
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
# Core backtest logic
# ---------------------------------------------------------------------------


def get_finished_gameweeks(bootstrap: dict) -> list[int]:
    """Return sorted list of finished gameweek IDs."""
    return sorted(gw["id"] for gw in bootstrap["events"] if gw["finished"])


def actual_top_scorers(live_data: dict, bootstrap: dict, n: int = 20) -> list[dict]:
    """
    From the live endpoint, extract the top N scorers for the gameweek.
    Returns list of {id, web_name, team, position, actual_points}.
    """
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}

    scored = []
    for entry in live_data.get("elements", []):
        pid = entry["id"]
        points = entry["stats"]["total_points"]
        player = players_by_id.get(pid)
        if player is None:
            continue
        # Skip players who didn't play (0 minutes)
        minutes = entry["stats"].get("minutes", 0)
        if minutes == 0:
            continue
        team = teams_by_id.get(player["team"], {})
        scored.append(
            {
                "id": pid,
                "web_name": player["web_name"],
                "team": team.get("short_name", "?"),
                "position": POSITION_MAP.get(player["element_type"], "?"),
                "actual_points": points,
            }
        )

    scored.sort(key=lambda x: x["actual_points"], reverse=True)
    return scored[:n]


def run_algorithm_for_gw(bootstrap: dict, fixtures: list, gameweek: int, top_n: int = 5) -> list[dict]:
    """
    Run the captain scoring algorithm against a given gameweek.
    Returns ranked list of {id, web_name, team, position, algo_score}.
    """
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    fixture_map = _build_fixture_map(fixtures, gameweek)

    scored = []
    for player in bootstrap["elements"]:
        player_fixtures = fixture_map.get(player["team"])
        score = _score_player(player, player_fixtures)
        scored.append((score, player))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, player in scored[:top_n]:
        team = teams_by_id.get(player["team"], {})
        results.append(
            {
                "id": player["id"],
                "web_name": player["web_name"],
                "team": team.get("short_name", "?"),
                "position": POSITION_MAP.get(player["element_type"], "?"),
                "algo_score": score,
            }
        )
    return results


def find_haaland_id(bootstrap: dict) -> int | None:
    """Find Haaland's player ID for the baseline comparison."""
    for p in bootstrap["elements"]:
        name = p.get("web_name", "").lower()
        if "haaland" in name:
            return p["id"]
    return None


# ---------------------------------------------------------------------------
# Weight suggestion engine
# ---------------------------------------------------------------------------


def compute_feature_correlations(
    bootstrap: dict,
    fixtures: list,
    all_live: dict[int, dict],
    finished_gws: list[int],
) -> dict[str, float]:
    """
    For each weight factor, compute a simple correlation with actual points.
    Returns {factor_name: correlation_score} where higher = more predictive.

    We use rank-based correlation (Spearman-style) as a lightweight approach:
    for each GW, rank players by the factor, rank by actual points, and
    measure agreement.
    """
    players_by_id = {p["id"]: p for p in bootstrap["elements"]}

    # Accumulate per-factor rank differences
    factor_rank_diffs: dict[str, list[float]] = {k: [] for k in WEIGHTS}

    for gw in finished_gws:
        live = all_live.get(gw)
        if not live:
            continue

        fixture_map = _build_fixture_map(fixtures, gw)

        # Build actual points map (only players who played)
        actual = {}
        for entry in live.get("elements", []):
            if entry["stats"].get("minutes", 0) > 0:
                actual[entry["id"]] = entry["stats"]["total_points"]

        if len(actual) < 20:
            continue

        # For each player who played, compute each factor's raw value
        factor_values: dict[str, list[tuple[int, float]]] = {k: [] for k in WEIGHTS}

        for pid, pts in actual.items():
            player = players_by_id.get(pid)
            if not player:
                continue

            minutes = player.get("minutes", 0)
            nineties = minutes / 90.0 if minutes > 0 else 0
            form = float(player.get("form") or 0)
            ppg = float(player.get("points_per_game") or 0)
            ict = float(player.get("ict_index") or 0)
            gw_played = max(1, round(nineties)) if nineties > 0 else 1
            bonus_pg = player.get("bonus", 0) / gw_played

            xg90 = 0.0
            xa90 = 0.0
            if nineties > 0:
                xg90 = float(player.get("expected_goals") or 0) / nineties
                xa90 = float(player.get("expected_assists") or 0) / nineties

            penalties_order = player.get("penalties_order")
            pen = 1.0 if penalties_order == 1 else 0.0

            starts = player.get("starts", 0)
            possible = max(1, gw_played)
            min_cert = starts / possible if possible > 0 else 0.0

            player_fixtures = fixture_map.get(player["team"], [])
            home_val = sum(1 for f in player_fixtures if f["is_home"])
            fdr_val = sum(f["fdr"] for f in player_fixtures) if player_fixtures else 3

            factor_values["xg90"].append((pid, xg90))
            factor_values["xa90"].append((pid, xa90))
            factor_values["form"].append((pid, form))
            factor_values["ppg"].append((pid, ppg))
            factor_values["home"].append((pid, home_val))
            factor_values["fdr"].append((pid, -fdr_val))  # negative because higher FDR is worse
            factor_values["ict"].append((pid, ict))
            factor_values["bonus_pg"].append((pid, bonus_pg))
            factor_values["penalty"].append((pid, pen))
            factor_values["minutes_cert"].append((pid, min_cert))
            factor_values["playing_chance_max_penalty"].append((pid, 0.0))  # skip for correlation

        # Rank actual points
        actual_ranked = sorted(actual.items(), key=lambda x: x[1], reverse=True)
        actual_rank = {pid: rank for rank, (pid, _) in enumerate(actual_ranked)}

        # For each factor, compute rank correlation
        for factor, values in factor_values.items():
            if factor == "playing_chance_max_penalty":
                continue
            values_sorted = sorted(values, key=lambda x: x[1], reverse=True)
            factor_rank = {pid: rank for rank, (pid, _) in enumerate(values_sorted)}

            n = len(values)
            if n < 10:
                continue

            # Spearman: 1 - 6*sum(d^2) / (n*(n^2-1))
            d_sq_sum = sum((factor_rank[pid] - actual_rank.get(pid, n)) ** 2 for pid, _ in values)
            rho = 1.0 - (6.0 * d_sq_sum) / (n * (n * n - 1))
            factor_rank_diffs[factor].append(rho)

    # Average correlation across gameweeks
    correlations = {}
    for factor, rhos in factor_rank_diffs.items():
        if factor == "playing_chance_max_penalty":
            continue
        if rhos:
            correlations[factor] = sum(rhos) / len(rhos)
        else:
            correlations[factor] = 0.0

    return correlations


def suggest_weights(correlations: dict[str, float]) -> dict[str, float]:
    """
    Suggest new weights based on factor correlations with actual points.
    Factors with higher correlation get upweighted, lower get downweighted.
    """
    # Normalize correlations to [0, 1] range
    vals = [v for v in correlations.values() if v > 0]
    if not vals:
        return dict(WEIGHTS)

    max_corr = max(vals)
    min(vals) if min(vals) > 0 else 0

    suggested = {}
    for factor, current_weight in WEIGHTS.items():
        if factor == "playing_chance_max_penalty":
            suggested[factor] = current_weight
            continue

        corr = correlations.get(factor, 0)
        if corr <= 0:
            # Poorly correlated: reduce weight by 30%
            suggested[factor] = round(current_weight * 0.7, 2)
        elif max_corr > 0:
            # Scale: correlation ratio determines adjustment
            ratio = corr / max_corr
            # Adjust up to +30% for best-correlated, down to -20% for worst
            multiplier = 0.8 + 0.5 * ratio  # range: 0.8 to 1.3
            suggested[factor] = round(current_weight * multiplier, 2)
        else:
            suggested[factor] = current_weight

    return suggested


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------


async def run_backtest(
    gw_start: int | None = None,
    gw_end: int | None = None,
    do_suggest_weights: bool = False,
) -> dict:
    print("Fetching bootstrap data...")
    bootstrap = await cached_bootstrap()
    print("Fetching fixtures...")
    fixtures = await cached_fixtures()

    finished = get_finished_gameweeks(bootstrap)
    if not finished:
        print("No finished gameweeks found.")
        return {"error": "No finished gameweeks"}

    # Apply gameweek range
    if gw_start is not None:
        finished = [gw for gw in finished if gw >= gw_start]
    if gw_end is not None:
        finished = [gw for gw in finished if gw <= gw_end]

    if not finished:
        print("No finished gameweeks in specified range.")
        return {"error": "No finished gameweeks in range"}

    haaland_id = find_haaland_id(bootstrap)
    print(f"Backtesting GW{finished[0]}–GW{finished[-1]} ({len(finished)} gameweeks)")
    if haaland_id:
        print(f"Haaland baseline player ID: {haaland_id}")
    print()

    # Fetch all live data
    all_live: dict[int, dict] = {}
    for gw in finished:
        print(f"  Fetching live data for GW{gw}...", end=" ", flush=True)
        live = await cached_live_points(gw)
        all_live[gw] = live
        print("OK")

    print()

    # Run backtest per gameweek
    gw_results = []
    top1_in_top3 = 0
    top1_in_top5 = 0
    top1_in_top10 = 0
    total_rank_of_pick = 0
    haaland_total_rank = 0
    haaland_counted = 0
    algo_total_points = 0
    haaland_total_points = 0

    for gw in finished:
        live = all_live[gw]

        # Actual top scorers
        top_actual = actual_top_scorers(live, bootstrap, n=50)
        actual_ids_ranked = [p["id"] for p in top_actual]
        {p["id"]: p["actual_points"] for p in top_actual}

        # Also build full actual points map for all players
        full_actual = {}
        for entry in live.get("elements", []):
            full_actual[entry["id"]] = entry["stats"]["total_points"]

        # Algorithm picks
        algo_picks = run_algorithm_for_gw(bootstrap, fixtures, gw, top_n=5)
        top_pick = algo_picks[0] if algo_picks else None

        if not top_pick:
            continue

        top_pick_id = top_pick["id"]
        top_pick_actual_pts = full_actual.get(top_pick_id, 0)
        algo_total_points += top_pick_actual_pts

        # Find rank of our top pick among all players
        all_sorted = sorted(full_actual.items(), key=lambda x: x[1], reverse=True)
        pick_rank = None
        for rank, (pid, pts) in enumerate(all_sorted, 1):
            if pid == top_pick_id:
                pick_rank = rank
                break
        if pick_rank is None:
            pick_rank = len(all_sorted)

        # Check if in top N of actual scorers
        is_top3 = top_pick_id in actual_ids_ranked[:3]
        is_top5 = top_pick_id in actual_ids_ranked[:5]
        is_top10 = top_pick_id in actual_ids_ranked[:10]

        if is_top3:
            top1_in_top3 += 1
        if is_top5:
            top1_in_top5 += 1
        if is_top10:
            top1_in_top10 += 1
        total_rank_of_pick += pick_rank

        # Haaland baseline
        haaland_pts = 0
        haaland_rank = None
        if haaland_id:
            haaland_pts = full_actual.get(haaland_id, 0)
            haaland_total_points += haaland_pts
            for rank, (pid, pts) in enumerate(all_sorted, 1):
                if pid == haaland_id:
                    haaland_rank = rank
                    break
            if haaland_rank is not None:
                haaland_total_rank += haaland_rank
                haaland_counted += 1

        # Top 3 actual scorers for display
        ", ".join(f"{p['web_name']}({p['actual_points']}pts)" for p in top_actual[:3])

        gw_result = {
            "gameweek": gw,
            "our_pick": top_pick["web_name"],
            "our_pick_id": top_pick_id,
            "our_pick_algo_score": top_pick["algo_score"],
            "our_pick_actual_points": top_pick_actual_pts,
            "our_pick_rank": pick_rank,
            "in_top_3": is_top3,
            "in_top_5": is_top5,
            "in_top_10": is_top10,
            "actual_top_3": [{"name": p["web_name"], "points": p["actual_points"]} for p in top_actual[:3]],
            "haaland_points": haaland_pts,
            "haaland_rank": haaland_rank,
            "all_algo_picks": [
                {
                    "name": p["web_name"],
                    "algo_score": p["algo_score"],
                    "actual_points": full_actual.get(p["id"], 0),
                }
                for p in algo_picks
            ],
        }
        gw_results.append(gw_result)

    # Summary statistics
    n = len(gw_results)
    if n == 0:
        print("No results to report.")
        return {"error": "No results"}

    avg_rank = total_rank_of_pick / n
    haaland_avg_rank = haaland_total_rank / haaland_counted if haaland_counted > 0 else None

    summary = {
        "gameweeks_tested": n,
        "gw_range": f"GW{finished[0]}–GW{finished[-1]}",
        "top1_hit_rate_top3": round(top1_in_top3 / n * 100, 1),
        "top1_hit_rate_top5": round(top1_in_top5 / n * 100, 1),
        "top1_hit_rate_top10": round(top1_in_top10 / n * 100, 1),
        "avg_rank_of_top_pick": round(avg_rank, 1),
        "algo_total_captain_points": algo_total_points,
        "algo_avg_captain_points": round(algo_total_points / n, 1),
        "haaland_total_captain_points": haaland_total_points,
        "haaland_avg_captain_points": round(haaland_total_points / n, 1) if n > 0 else 0,
        "haaland_avg_rank": round(haaland_avg_rank, 1) if haaland_avg_rank else None,
        "algo_vs_haaland_diff": algo_total_points - haaland_total_points,
    }

    # Print results table
    _print_results_table(gw_results, summary)

    result = {
        "summary": summary,
        "gameweek_results": gw_results,
        "weights_used": dict(WEIGHTS),
    }

    # Weight suggestions
    if do_suggest_weights:
        print("\n--- Weight Correlation Analysis ---\n")
        correlations = compute_feature_correlations(bootstrap, fixtures, all_live, finished)
        new_weights = suggest_weights(correlations)

        print(f"  {'Factor':<25} {'Correlation':>12} {'Current Wt':>12} {'Suggested Wt':>12}")
        print(f"  {'─' * 25} {'─' * 12} {'─' * 12} {'─' * 12}")
        for factor in sorted(correlations, key=lambda f: correlations[f], reverse=True):
            corr = correlations[factor]
            cur = WEIGHTS.get(factor, 0)
            sug = new_weights.get(factor, cur)
            delta = "  " if abs(sug - cur) < 0.01 else " ^" if sug > cur else " v"
            print(f"  {factor:<25} {corr:>11.4f} {cur:>12.2f} {sug:>10.2f}{delta}")

        result["correlations"] = correlations
        result["suggested_weights"] = new_weights

        print("\nTo apply, update WEIGHTS in app/algorithms/captain.py")

    # Save to JSON
    output_path = PROJECT_ROOT / "data" / "backtest_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults saved to {output_path}")

    return result


def _print_results_table(gw_results: list[dict], summary: dict) -> None:
    """Print a readable results table to stdout."""
    # Header
    hdr = (
        f"{'GW':>3}  {'Our Pick':<18} {'Pts':>4} {'Rank':>5} "
        f"{'Top3':>4} {'Top5':>4}  {'Actual Top 3':<50} {'Haaland':>7}"
    )
    sep = "─" * len(hdr)

    print(sep)
    print("CAPTAIN PICK BACKTEST RESULTS")
    print(f"Algorithm v2 | Weights: {WEIGHTS}")
    print(sep)
    print(hdr)
    print(sep)

    for r in gw_results:
        top3_str = ", ".join(f"{p['name']}({p['points']})" for p in r["actual_top_3"])
        t3 = "Y" if r["in_top_3"] else "-"
        t5 = "Y" if r["in_top_5"] else "-"
        print(
            f"{r['gameweek']:>3}  {r['our_pick']:<18} {r['our_pick_actual_points']:>4} "
            f"{r['our_pick_rank']:>5}    {t3:>2}    {t5:>2}  {top3_str:<50} "
            f"{r['haaland_points']:>7}"
        )

    print(sep)
    print()
    print("SUMMARY")
    print(sep)
    print(f"  Gameweeks tested:           {summary['gameweeks_tested']}")
    print(f"  Range:                      {summary['gw_range']}")
    print(f"  Top pick in actual Top 3:   {summary['top1_hit_rate_top3']}%")
    print(f"  Top pick in actual Top 5:   {summary['top1_hit_rate_top5']}%")
    print(f"  Top pick in actual Top 10:  {summary['top1_hit_rate_top10']}%")
    print(f"  Average rank of top pick:   {summary['avg_rank_of_top_pick']}")
    print(f"  Algo total captain points:  {summary['algo_total_captain_points']}")
    print(f"  Algo avg captain points:    {summary['algo_avg_captain_points']}")
    print()
    print("  --- vs 'Always Pick Haaland' Baseline ---")
    print(f"  Haaland total points:       {summary['haaland_total_captain_points']}")
    print(f"  Haaland avg points:         {summary['haaland_avg_captain_points']}")
    if summary["haaland_avg_rank"]:
        print(f"  Haaland avg rank:           {summary['haaland_avg_rank']}")
    diff = summary["algo_vs_haaland_diff"]
    label = "AHEAD" if diff > 0 else "BEHIND" if diff < 0 else "TIED"
    print(f"  Algo vs Haaland:            {abs(diff)} pts {label}")
    print(sep)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the captain pick algorithm against finished gameweeks.")
    parser.add_argument(
        "--gameweeks",
        type=str,
        default=None,
        help="Gameweek range, e.g. '1-10', '5', '15-20'. Default: all finished.",
    )
    parser.add_argument(
        "--suggest-weights",
        action="store_true",
        default=False,
        help="Compute factor correlations and suggest weight adjustments.",
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

    asyncio.run(
        run_backtest(
            gw_start=gw_start,
            gw_end=gw_end,
            do_suggest_weights=args.suggest_weights,
        )
    )


if __name__ == "__main__":
    main()
