"""
Rolling Weight Optimizer — dynamically tune captain algorithm weights.

Uses per-GW snapshots (saved by scripts/snapshot_gw.py) and live GW results
to find the weight set that would have maximized captain accuracy over
the last N finished gameweeks.

The optimizer runs a grid search over weight space, scoring each combo
by how well it would have ranked the actual top scorers. Weights that
produce picks matching actual high scorers get boosted.

This replaces static hand-tuned weights with data-driven weights that
adapt to the current season's patterns — e.g., if home advantage has
been weak this season, the home weight decreases automatically.

Usage:
    # From captain.py at startup:
    from app.algorithms.weight_optimizer import get_optimized_weights
    weights = get_optimized_weights()  # returns WEIGHTS dict or None

    # From CLI:
    python -m app.algorithms.weight_optimizer
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots"
LIVE_CACHE_DIR = PROJECT_ROOT / "data" / "backtest_cache"
OPTIMIZED_WEIGHTS_PATH = PROJECT_ROOT / "data" / "optimized_weights.json"

# How many recent GWs to optimize over (rolling window)
ROLLING_WINDOW = 8

# Weight search space: each weight is tried at these multipliers of the base value
# Coarse grid keeps search fast (~3^10 = 59K combos, pruned to ~1K)
SEARCH_MULTIPLIERS = [0.5, 1.0, 1.5]

# Cache optimized weights for this long (seconds)
WEIGHTS_CACHE_TTL = 3600  # 1 hour

# Base weights (v3.0) — the optimizer adjusts these
# Note: home and fdr are now multiplicative (fixture multiplier), not additive
BASE_WEIGHTS = {
    "xg90": 1.07,
    "xa90": 0.92,
    "form": 3.43,
    "ppg": 5.92,
    "ep_next": 0.49,
    "home": 0.10,
    "fdr": 0.30,
    "ict": 0.01,
    "bonus_pg": 1.31,
    "penalty": 1.90,
    "set_piece": 0.84,
    "dreamteam": 0.56,
    "minutes_cert": 1.04,
    "def_contrib": 0.59,
    "playing_chance_max_penalty": -10.0,
}

# Only optimize these weights (the others are too small or binary to tune)
TUNABLE_WEIGHTS = ["ppg", "form", "home", "fdr", "xg90", "xa90", "ep_next", "bonus_pg"]


def _load_snapshot(gw: int) -> dict | None:
    """Load a GW snapshot if it exists."""
    path = SNAPSHOT_DIR / f"gw{gw}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _load_live_data(gw: int) -> dict | None:
    """Load live GW data from backtest cache."""
    path = LIVE_CACHE_DIR / f"live_gw{gw}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _normalize(value: float, low: float, high: float) -> float:
    """Normalize to 0-1 scale."""
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _score_player_with_weights(player: dict, fixtures: list[dict] | None, weights: dict) -> float:
    """Score a player using the given weight set (same logic as captain.py _score_player)."""
    form = float(player.get("form") or 0)
    ppg = float(player.get("points_per_game") or 0)
    ict = float(player.get("ict_index") or 0)

    minutes = player.get("minutes", 0)
    nineties = minutes / 90.0 if minutes > 0 else 0

    xg_per_90 = 0.0
    xa_per_90 = 0.0
    if nineties > 0:
        xg = float(player.get("expected_goals") or 0)
        xa = float(player.get("expected_assists") or 0)
        xg_per_90 = xg / nineties
        xa_per_90 = xa / nineties

    bonus_pg = player.get("bonus", 0) / max(1, player.get("starts", 1))

    penalties_order = player.get("penalties_order")
    penalty_norm = 1.0 if penalties_order == 1 else 0.0

    ep_next = float(player.get("ep_next") or 0)

    starts = player.get("starts", 0)
    gw_played = max(1, round(nineties)) if nineties > 0 else 1
    possible_starts = max(1, gw_played)
    minutes_cert = starts / possible_starts if possible_starts > 0 else 0.0

    # Normalize
    ppg_norm = _normalize(ppg, 0, 10)
    form_norm = _normalize(form, 0, 10)
    xg90_norm = _normalize(xg_per_90, 0, 1.0)
    xa90_norm = _normalize(xa_per_90, 0, 0.5)
    ict_norm = _normalize(ict, 0, 300)
    bonus_norm = _normalize(bonus_pg, 0, 3)
    ep_norm = _normalize(ep_next, 0, 10)

    # Injury penalty
    chance = player.get("chance_of_playing_next_round")
    chance_penalty = 0.0
    if chance is None:
        status = player.get("status", "a")
        if status in {"i", "d", "s", "u"}:
            chance_penalty = weights.get("playing_chance_max_penalty", -10.0)
    else:
        chance_penalty = weights.get("playing_chance_max_penalty", -10.0) * (1.0 - float(chance) / 100.0)

    base_score = (
        xg90_norm * weights.get("xg90", 1.5)
        + xa90_norm * weights.get("xa90", 1.2)
        + form_norm * weights.get("form", 2.8)
        + ppg_norm * weights.get("ppg", 3.5)
        + ep_norm * weights.get("ep_next", 1.0)
        + ict_norm * weights.get("ict", 0.01)
        + bonus_norm * weights.get("bonus_pg", 1.1)
        + penalty_norm * weights.get("penalty", 1.5)
        + minutes_cert * weights.get("minutes_cert", 1.0)
        + chance_penalty
    )

    if fixtures:
        fixture_score = 0.0
        for fixture in fixtures:
            fdr = fixture["fdr"]
            is_home = fixture["is_home"]
            fdr_norm = _normalize(5 - fdr, 0, 4)
            home_bonus = weights.get("home", 3.0) if is_home else 0.0
            fixture_score += home_bonus + fdr_norm * weights.get("fdr", 3.0)
        score = base_score + fixture_score
    else:
        score = base_score + 0.5 * weights.get("fdr", 3.0)

    return score


def _build_fixture_map_from_cache(fixtures_data: list, gameweek: int) -> dict[int, list[dict]]:
    """Build fixture map from raw fixtures data (no team strength blending — optimizer uses raw FDR)."""
    fixture_map: dict[int, list[dict]] = {}
    for fix in fixtures_data:
        if fix.get("event") != gameweek:
            continue
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        fixture_map.setdefault(home_id, []).append(
            {
                "fdr": fix["team_h_difficulty"],
                "is_home": True,
                "opponent": away_id,
            }
        )
        fixture_map.setdefault(away_id, []).append(
            {
                "fdr": fix["team_a_difficulty"],
                "is_home": False,
                "opponent": home_id,
            }
        )
    return fixture_map


def _evaluate_weights(
    weights: dict,
    snapshots: dict[int, dict],
    live_data: dict[int, dict],
    fixtures_data: list,
) -> float:
    """
    Score a weight set by how well it picks captains across multiple GWs.

    For each GW, we:
    1. Score all players using the snapshot data and these weights
    2. Pick the top player as captain
    3. Look up their actual points from live data
    4. Sum actual points across all GWs

    Higher total = better weights.
    """
    total_points = 0

    for gw, snapshot in snapshots.items():
        live = live_data.get(gw)
        if not live:
            continue

        # Build fixture map for this GW
        fixture_map = _build_fixture_map_from_cache(fixtures_data, gw)

        # Build actual points lookup
        actual_points = {}
        for entry in live.get("elements", []):
            actual_points[entry["id"]] = entry["stats"]["total_points"]

        # Score all players using snapshot data (historical stats at that point)
        players = snapshot.get("players", [])
        best_score = -999
        best_player_id = None

        for player in players:
            player_fixtures = fixture_map.get(player.get("team"))
            score = _score_player_with_weights(player, player_fixtures, weights)
            if score > best_score:
                best_score = score
                best_player_id = player.get("id")

        # Captain's actual points
        if best_player_id:
            total_points += actual_points.get(best_player_id, 0)

    return total_points


def optimize_weights(
    max_gws: int = ROLLING_WINDOW,
) -> dict | None:
    """
    Find the best weight set over the last N finished GWs.

    Requires:
    - GW snapshots in data/snapshots/gwN.json
    - Live data in data/backtest_cache/live_gwN.json
    - Fixtures data in data/backtest_cache/fixtures.json

    Returns optimized weights dict, or None if insufficient data.
    """
    # Load fixtures
    fixtures_path = LIVE_CACHE_DIR / "fixtures.json"
    if not fixtures_path.exists():
        logger.warning("No fixtures cache found at %s", fixtures_path)
        return None

    with open(fixtures_path) as f:
        fixtures_data = json.load(f)

    # Find available GW snapshots (in reverse order — most recent first)
    available_gws = []
    for gw in range(38, 0, -1):
        snapshot = _load_snapshot(gw)
        live = _load_live_data(gw)
        if snapshot and live:
            available_gws.append(gw)
        if len(available_gws) >= max_gws:
            break

    if len(available_gws) < 3:
        logger.info("Only %d GW snapshots available (need ≥3 for optimization)", len(available_gws))
        return None

    logger.info("Optimizing weights over GW%s (last %d GWs)", available_gws, len(available_gws))

    # Load all data
    snapshots = {}
    live_data = {}
    for gw in available_gws:
        snapshots[gw] = _load_snapshot(gw)
        live_data[gw] = _load_live_data(gw)

    # Baseline score with current weights
    base_score = _evaluate_weights(BASE_WEIGHTS, snapshots, live_data, fixtures_data)
    logger.info("Base weights score: %d captain points over %d GWs", base_score, len(available_gws))

    # Grid search over tunable weights
    # For efficiency, we search one weight at a time (coordinate descent)
    # then do a final round of pairwise combinations for the top movers
    best_weights = dict(BASE_WEIGHTS)
    best_score = base_score

    # Phase 1: Coordinate descent — optimize each weight independently
    for weight_name in TUNABLE_WEIGHTS:
        best_mult = 1.0
        for mult in [0.3, 0.5, 0.7, 1.0, 1.3, 1.5, 2.0]:
            trial = dict(best_weights)
            trial[weight_name] = BASE_WEIGHTS[weight_name] * mult
            score = _evaluate_weights(trial, snapshots, live_data, fixtures_data)
            if score > best_score:
                best_score = score
                best_mult = mult

        best_weights[weight_name] = round(BASE_WEIGHTS[weight_name] * best_mult, 3)

    # Phase 2: Pairwise refinement of the top 4 most impactful weights
    # (the ones that changed most from base)
    changes = {k: abs(best_weights[k] - BASE_WEIGHTS[k]) / max(0.001, BASE_WEIGHTS[k]) for k in TUNABLE_WEIGHTS}
    top_movers = sorted(changes, key=changes.get, reverse=True)[:4]

    for i, w1 in enumerate(top_movers):
        for w2 in top_movers[i + 1 :]:
            for m1 in [0.5, 0.75, 1.0, 1.25, 1.5]:
                for m2 in [0.5, 0.75, 1.0, 1.25, 1.5]:
                    trial = dict(best_weights)
                    trial[w1] = round(BASE_WEIGHTS[w1] * m1, 3)
                    trial[w2] = round(BASE_WEIGHTS[w2] * m2, 3)
                    score = _evaluate_weights(trial, snapshots, live_data, fixtures_data)
                    if score > best_score:
                        best_score = score
                        best_weights[w1] = trial[w1]
                        best_weights[w2] = trial[w2]

    improvement = best_score - base_score
    logger.info(
        "Optimized: %d pts (base %d, +%d improvement over %d GWs)",
        best_score,
        base_score,
        improvement,
        len(available_gws),
    )

    return best_weights


def get_optimized_weights() -> dict | None:
    """
    Get optimized weights, using cache if fresh enough.

    Returns the optimized weight dict, or None if:
    - No snapshots available
    - Cache is fresh and unchanged
    - Optimization produced no improvement
    """
    # Check cache
    if OPTIMIZED_WEIGHTS_PATH.exists():
        with open(OPTIMIZED_WEIGHTS_PATH) as f:
            cached = json.load(f)
        age = time.time() - cached.get("optimized_at_epoch", 0)
        if age < WEIGHTS_CACHE_TTL:
            return cached.get("weights")

    # Run optimization
    weights = optimize_weights()
    if weights is None:
        return None

    # Save cache
    cache_data = {
        "weights": weights,
        "optimized_at_epoch": time.time(),
        "base_weights": BASE_WEIGHTS,
        "rolling_window": ROLLING_WINDOW,
    }
    OPTIMIZED_WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OPTIMIZED_WEIGHTS_PATH, "w") as f:
        json.dump(cache_data, f, indent=2)

    return weights


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("Rolling Weight Optimizer")
    print("=" * 60)

    # Check available data
    snapshot_count = 0
    live_count = 0
    for gw in range(1, 39):
        if (SNAPSHOT_DIR / f"gw{gw}.json").exists():
            snapshot_count += 1
        if (LIVE_CACHE_DIR / f"live_gw{gw}.json").exists():
            live_count += 1

    print(f"GW snapshots available: {snapshot_count}")
    print(f"Live data cached: {live_count}")
    print()

    if snapshot_count < 3:
        print("Need at least 3 GW snapshots to optimize.")
        print("Run: python scripts/snapshot_gw.py --backfill")
        print("Then capture snapshots before each future GW deadline.")
        sys.exit(0)

    weights = optimize_weights()
    if weights:
        print("\nOptimized weights:")
        for k, v in sorted(weights.items()):
            base = BASE_WEIGHTS.get(k, v)
            delta = ""
            if abs(v - base) > 0.001:
                pct = ((v - base) / base) * 100 if base != 0 else 0
                delta = f" ({pct:+.0f}%)"
            print(f"  {k:<30} {v:>8.3f}{delta}")
    else:
        print("Optimization failed — check data availability.")
