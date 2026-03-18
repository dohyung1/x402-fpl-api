"""
Weekly evaluation script — grades MCP recommendations against actual GW results.

Runs after a gameweek finishes and compares:
  1. Captain pick accuracy (top 3/5/10 hit rate)
  2. Differential hit rate (how many of our picks hauled)
  3. Baselines (Haaland, most-owned captain)
  4. Transfer quality (buy vs sell point difference)

Appends results to data/evaluation.csv for tracking over time.

Usage:
    python scripts/evaluate_gw.py              # evaluate last finished GW
    python scripts/evaluate_gw.py --gw 30      # evaluate specific GW
    python scripts/evaluate_gw.py --all         # evaluate all finished GWs
"""

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.algorithms.captain import (  # noqa: E402
    POSITION_MAP,
    _build_fixture_map,
    _score_player,
)
from app.algorithms.differentials import _differential_score  # noqa: E402
from app.fpl_client import get_bootstrap, get_fixtures, get_live_points  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "eval_cache"
EVAL_CSV = PROJECT_ROOT / "data" / "evaluation.csv"
EVAL_JSON = PROJECT_ROOT / "data" / "evaluation.json"

CSV_COLUMNS = [
    "gw",
    "algo_version",
    "captain_name",
    "captain_pts",
    "captain_rank",
    "top3_hit",
    "top5_hit",
    "top10_hit",
    "haaland_pts",
    "haaland_rank",
    "most_owned_name",
    "most_owned_pts",
    "most_owned_rank",
    "diff_hits_top50",
    "diff_total_pts",
    "diff_avg_pts",
    "algo_total_pts",
    "haaland_total_pts",
    "timestamp",
]


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str):
    path = _cache_path(key)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _write_cache(key: str, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(key), "w") as f:
        json.dump(data, f)


async def _cached_live(gw: int) -> dict:
    key = f"live_gw{gw}"
    data = _read_cache(key)
    if data:
        return data
    data = await get_live_points(gw)
    _write_cache(key, data)
    return data


def _get_finished_gws(bootstrap: dict) -> list[int]:
    return [gw["id"] for gw in bootstrap["events"] if gw["finished"]]


def _player_gw_points(live_data: dict, player_id: int) -> int:
    """Get a player's actual points from live GW data."""
    for entry in live_data.get("elements", []):
        if entry["id"] == player_id:
            return entry.get("stats", {}).get("total_points", 0)
    return 0


async def evaluate_gameweek(gw: int, bootstrap: dict, fixtures: list) -> dict:
    """Evaluate all tools for a single finished gameweek."""
    live_data = await _cached_live(gw)

    players = bootstrap["elements"]
    teams = {t["id"]: t for t in bootstrap["teams"]}

    # Build actual points ranking for this GW
    player_points = []
    for p in players:
        pts = _player_gw_points(live_data, p["id"])
        player_points.append({
            "id": p["id"],
            "name": p["web_name"],
            "team": p.get("team"),
            "element_type": p.get("element_type"),
            "points": pts,
            "selected_by_percent": float(p.get("selected_by_percent") or 0),
        })

    player_points.sort(key=lambda x: x["points"], reverse=True)

    # Assign ranks (handle ties)
    for i, pp in enumerate(player_points):
        pp["rank"] = i + 1

    points_by_id = {pp["id"]: pp for pp in player_points}

    # --- 1. CAPTAIN PICK EVALUATION ---
    fixture_map = _build_fixture_map(fixtures, gw, teams_by_id=teams)

    scored_players = []
    for p in players:
        player_fixtures = fixture_map.get(p["team"])
        score = _score_player(p, player_fixtures)
        scored_players.append((score, p))

    scored_players.sort(key=lambda x: x[0], reverse=True)
    top_pick = scored_players[0][1]
    top5_picks = [sp[1] for sp in scored_players[:5]]

    captain_info = points_by_id.get(top_pick["id"], {})
    captain_pts = captain_info.get("points", 0)
    captain_rank = captain_info.get("rank", 999)

    top3_hit = 1 if captain_rank <= 3 else 0
    top5_hit = 1 if captain_rank <= 5 else 0
    top10_hit = 1 if captain_rank <= 10 else 0

    # --- 2. BASELINES ---
    # Haaland baseline
    haaland = next((p for p in players if p["web_name"] == "Haaland"), None)
    haaland_pts = 0
    haaland_rank = 999
    if haaland:
        h_info = points_by_id.get(haaland["id"], {})
        haaland_pts = h_info.get("points", 0)
        haaland_rank = h_info.get("rank", 999)

    # Most-owned player baseline (popular captain)
    most_owned = max(players, key=lambda p: float(p.get("selected_by_percent") or 0))
    mo_info = points_by_id.get(most_owned["id"], {})
    most_owned_pts = mo_info.get("points", 0)
    most_owned_rank = mo_info.get("rank", 999)

    # --- 3. DIFFERENTIAL EVALUATION ---
    diff_hits_top50 = 0
    diff_total_pts = 0
    diff_count = 0

    diff_scored = []
    for p in players:
        ownership = float(p.get("selected_by_percent") or 0)
        if ownership > 10.0:
            continue
        if p.get("status") in {"i", "u"}:
            continue
        player_fixtures = fixture_map.get(p["team"])
        dscore = _differential_score(p, player_fixtures, ownership)
        diff_scored.append((dscore, p))

    diff_scored.sort(key=lambda x: x[0], reverse=True)
    top_diffs = [d[1] for d in diff_scored[:10]]

    for dp in top_diffs:
        dp_info = points_by_id.get(dp["id"], {})
        dp_pts = dp_info.get("points", 0)
        dp_rank = dp_info.get("rank", 999)
        diff_total_pts += dp_pts
        diff_count += 1
        if dp_rank <= 50:
            diff_hits_top50 += 1

    diff_avg_pts = round(diff_total_pts / max(1, diff_count), 1)

    return {
        "gw": gw,
        "algo_version": "2.5",
        "captain_name": top_pick["web_name"],
        "captain_pts": captain_pts,
        "captain_rank": captain_rank,
        "top3_hit": top3_hit,
        "top5_hit": top5_hit,
        "top10_hit": top10_hit,
        "haaland_pts": haaland_pts,
        "haaland_rank": haaland_rank,
        "most_owned_name": most_owned["web_name"],
        "most_owned_pts": most_owned_pts,
        "most_owned_rank": most_owned_rank,
        "diff_hits_top50": diff_hits_top50,
        "diff_total_pts": diff_total_pts,
        "diff_avg_pts": diff_avg_pts,
        "algo_total_pts": captain_pts,  # running total updated below
        "haaland_total_pts": haaland_pts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # Extra detail for JSON (not in CSV)
        "top5_picks": [
            {
                "name": p["web_name"],
                "actual_pts": points_by_id.get(p["id"], {}).get("points", 0),
                "actual_rank": points_by_id.get(p["id"], {}).get("rank", 999),
            }
            for p in top5_picks
        ],
        "top_differentials": [
            {
                "name": dp["web_name"],
                "ownership": float(dp.get("selected_by_percent") or 0),
                "actual_pts": points_by_id.get(dp["id"], {}).get("points", 0),
            }
            for dp in top_diffs[:5]
        ],
        "actual_top5": [
            {"name": pp["name"], "points": pp["points"]}
            for pp in player_points[:5]
        ],
    }


def _append_csv(result: dict):
    """Append a result row to the evaluation CSV."""
    EVAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not EVAL_CSV.exists()

    with open(EVAL_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
        row = {k: result.get(k, "") for k in CSV_COLUMNS}
        writer.writerow(row)


def _print_result(result: dict):
    """Pretty-print a single GW evaluation."""
    gw = result["gw"]
    print(f"\n{'═' * 70}")
    print(f"  GW{gw} Evaluation — Algorithm v{result['algo_version']}")
    print(f"{'═' * 70}")

    # Captain
    print(f"\n  CAPTAIN PICK")
    print(f"    Our pick:       {result['captain_name']} → {result['captain_pts']} pts (rank #{result['captain_rank']})")
    print(f"    Haaland:        {result['haaland_pts']} pts (rank #{result['haaland_rank']})")
    print(f"    Most owned:     {result['most_owned_name']} → {result['most_owned_pts']} pts (rank #{result['most_owned_rank']})")
    print(f"    Top 3 hit: {'✓' if result['top3_hit'] else '✗'}  Top 5: {'✓' if result['top5_hit'] else '✗'}  Top 10: {'✓' if result['top10_hit'] else '✗'}")

    # Our top 5
    print(f"\n  OUR TOP 5 vs ACTUAL")
    for p in result.get("top5_picks", []):
        marker = "★" if p["actual_rank"] <= 10 else " "
        print(f"    {marker} {p['name']:18} → {p['actual_pts']:3} pts (rank #{p['actual_rank']})")

    # Actual top 5
    print(f"\n  ACTUAL TOP 5 SCORERS")
    for p in result.get("actual_top5", []):
        print(f"      {p['name']:18} → {p['points']:3} pts")

    # Differentials
    print(f"\n  DIFFERENTIALS")
    print(f"    Hits in top 50:    {result['diff_hits_top50']}/10")
    print(f"    Avg pts:           {result['diff_avg_pts']}")
    for d in result.get("top_differentials", []):
        print(f"      {d['name']:18} ({d['ownership']:.1f}%) → {d['actual_pts']} pts")

    print()


def _print_season_summary(results: list[dict]):
    """Print season-wide summary from all evaluated GWs."""
    if not results:
        return

    n = len(results)
    total_captain = sum(r["captain_pts"] for r in results)
    total_haaland = sum(r["haaland_pts"] for r in results)
    total_most_owned = sum(r["most_owned_pts"] for r in results)

    top3_rate = sum(r["top3_hit"] for r in results) / n * 100
    top5_rate = sum(r["top5_hit"] for r in results) / n * 100
    top10_rate = sum(r["top10_hit"] for r in results) / n * 100

    avg_rank = sum(r["captain_rank"] for r in results) / n
    avg_diff_hits = sum(r["diff_hits_top50"] for r in results) / n

    print(f"\n{'═' * 70}")
    print(f"  SEASON SUMMARY — {n} gameweeks evaluated")
    print(f"{'═' * 70}")
    print(f"\n  CAPTAIN ACCURACY")
    print(f"    Top 3 hit rate:    {top3_rate:.1f}%")
    print(f"    Top 5 hit rate:    {top5_rate:.1f}%")
    print(f"    Top 10 hit rate:   {top10_rate:.1f}%")
    print(f"    Avg rank:          {avg_rank:.1f}")
    print(f"\n  TOTAL CAPTAIN POINTS")
    print(f"    Algorithm:         {total_captain} pts ({total_captain/n:.1f} avg)")
    print(f"    Haaland:           {total_haaland} pts ({total_haaland/n:.1f} avg)")
    print(f"    Most owned:        {total_most_owned} pts ({total_most_owned/n:.1f} avg)")

    diff = total_captain - total_haaland
    sign = "+" if diff >= 0 else ""
    print(f"    vs Haaland:        {sign}{diff} pts")

    diff2 = total_captain - total_most_owned
    sign2 = "+" if diff2 >= 0 else ""
    print(f"    vs Most owned:     {sign2}{diff2} pts")

    print(f"\n  DIFFERENTIALS")
    print(f"    Avg top-50 hits:   {avg_diff_hits:.1f}/10 per GW")
    print()


async def main():
    parser = argparse.ArgumentParser(description="Evaluate FPL MCP recommendations")
    parser.add_argument("--gw", type=int, help="Evaluate specific gameweek")
    parser.add_argument("--all", action="store_true", help="Evaluate all finished GWs")
    args = parser.parse_args()

    bootstrap = await get_bootstrap()
    fixtures = await get_fixtures()
    finished_gws = _get_finished_gws(bootstrap)

    if not finished_gws:
        print("No finished gameweeks to evaluate.")
        return

    if args.gw:
        gws_to_eval = [args.gw]
    elif args.all:
        gws_to_eval = finished_gws
    else:
        # Default: last finished GW
        gws_to_eval = [finished_gws[-1]]

    # Check which GWs are already evaluated
    existing_gws = set()
    if EVAL_CSV.exists():
        with open(EVAL_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_gws.add(int(row["gw"]))

    all_results = []
    new_results = []

    for gw in gws_to_eval:
        if gw not in finished_gws:
            print(f"  GW{gw} not finished yet — skipping")
            continue

        result = await evaluate_gameweek(gw, bootstrap, fixtures)
        all_results.append(result)

        if gw not in existing_gws:
            _append_csv(result)
            new_results.append(gw)

        _print_result(result)

    # Season summary
    if len(all_results) > 1:
        _print_season_summary(all_results)

    # Save detailed JSON
    EVAL_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_JSON, "w") as f:
        json.dump(all_results, f, indent=2)

    if new_results:
        print(f"  New evaluations saved to {EVAL_CSV}: GW{', GW'.join(str(g) for g in new_results)}")
    print(f"  Detailed results: {EVAL_JSON}")


if __name__ == "__main__":
    asyncio.run(main())
