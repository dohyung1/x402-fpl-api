"""
GW Snapshot — capture player stats before each gameweek deadline.

Saves a snapshot of bootstrap-static data (all player stats, team info,
event deadlines) so the rolling weight optimizer can backtest against
historical per-GW form, ep_next, ppg, etc. — not just today's values.

Usage:
    python scripts/snapshot_gw.py              # snapshot next GW
    python scripts/snapshot_gw.py --gw 31      # snapshot specific GW
    python scripts/snapshot_gw.py --backfill   # save current data as latest finished GW

Run before each GW deadline (e.g., via cron or /loop).
The snapshot captures the state of all player stats AT THAT POINT IN TIME,
which is what managers see when making captain/transfer decisions.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.fpl_client import get_bootstrap, get_fixtures  # noqa: E402

SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots"


def snapshot_path(gw: int) -> Path:
    return SNAPSHOT_DIR / f"gw{gw}.json"


async def take_snapshot(gw: int | None = None, backfill: bool = False) -> Path:
    """
    Capture and save a GW snapshot.

    If gw is None, auto-detects the next upcoming gameweek.
    If backfill is True, saves as the latest finished GW (useful for
    bootstrapping the system mid-season).
    """
    bootstrap = await get_bootstrap()
    fixtures = await get_fixtures()

    events = bootstrap.get("events", [])

    if gw is not None:
        target_gw = gw
    elif backfill:
        # Find the latest finished GW
        finished = [e for e in events if e.get("finished")]
        if not finished:
            print("No finished gameweeks found.")
            sys.exit(1)
        target_gw = max(e["id"] for e in finished)
    else:
        # Find the next upcoming GW (not finished, not started or is_current)
        upcoming = [e for e in events if not e.get("finished")]
        if not upcoming:
            print("No upcoming gameweeks found.")
            sys.exit(1)
        target_gw = min(e["id"] for e in upcoming)

    # Check if snapshot already exists
    path = snapshot_path(target_gw)
    if path.exists():
        print(f"Snapshot for GW{target_gw} already exists at {path}")
        print("Use --gw N to overwrite a specific GW, or skip.")
        return path

    # Build compact snapshot — only the fields we need for weight optimization
    # Full bootstrap is ~4MB; we store ~500KB of relevant data
    player_fields = [
        "id",
        "web_name",
        "first_name",
        "second_name",
        "team",
        "element_type",
        "form",
        "points_per_game",
        "ep_next",
        "ep_this",
        "total_points",
        "minutes",
        "starts",
        "expected_goals",
        "expected_assists",
        "expected_goal_involvements",
        "expected_goals_conceded",
        "expected_goals_conceded_per_90",
        "ict_index",
        "influence",
        "creativity",
        "threat",
        "bonus",
        "bps",
        "goals_scored",
        "assists",
        "clean_sheets",
        "now_cost",
        "selected_by_percent",
        "status",
        "chance_of_playing_next_round",
        "penalties_order",
        "corners_and_indirect_freekicks_order",
        "direct_freekicks_order",
        "transfers_in_event",
        "transfers_out_event",
    ]

    players = []
    for p in bootstrap.get("elements", []):
        player_data = {k: p.get(k) for k in player_fields}
        players.append(player_data)

    teams = []
    for t in bootstrap.get("teams", []):
        teams.append(
            {
                "id": t["id"],
                "name": t.get("name"),
                "short_name": t.get("short_name"),
                "strength": t.get("strength"),
                "strength_overall_home": t.get("strength_overall_home"),
                "strength_overall_away": t.get("strength_overall_away"),
                "strength_attack_home": t.get("strength_attack_home"),
                "strength_attack_away": t.get("strength_attack_away"),
                "strength_defence_home": t.get("strength_defence_home"),
                "strength_defence_away": t.get("strength_defence_away"),
            }
        )

    # GW event metadata
    target_event = next((e for e in events if e["id"] == target_gw), {})

    snapshot = {
        "gameweek": target_gw,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "is_backfill": backfill,
        "event": {
            "id": target_event.get("id"),
            "deadline_time": target_event.get("deadline_time"),
            "finished": target_event.get("finished", False),
            "data_checked": target_event.get("data_checked", False),
        },
        "players": players,
        "teams": teams,
        "fixture_count": len([f for f in fixtures if f.get("event") == target_gw]),
    }

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(snapshot, f)

    size_kb = path.stat().st_size / 1024
    print(f"Snapshot saved: GW{target_gw} → {path} ({size_kb:.0f} KB)")
    print(f"  Players: {len(players)}")
    print(f"  Teams: {len(teams)}")
    print(f"  Captured at: {snapshot['captured_at']}")
    if backfill:
        print(f"  (backfill — using current stats as GW{target_gw} snapshot)")

    return path


async def backfill_all_finished() -> list[Path]:
    """
    Save current data as a snapshot for the latest finished GW.

    We can only backfill ONE snapshot (the current state), not reconstruct
    past GWs. But this bootstraps the system so future snapshots build on it.
    """
    return [await take_snapshot(backfill=True)]


def main():
    parser = argparse.ArgumentParser(description="Capture GW snapshot for rolling weight optimization.")
    parser.add_argument("--gw", type=int, default=None, help="Specific gameweek to snapshot")
    parser.add_argument("--backfill", action="store_true", help="Save current data as latest finished GW")
    args = parser.parse_args()

    if args.backfill:
        asyncio.run(backfill_all_finished())
    else:
        asyncio.run(take_snapshot(gw=args.gw))


if __name__ == "__main__":
    main()
