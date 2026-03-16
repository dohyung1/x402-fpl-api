"""
Price Predictions algorithm.

FPL price changes happen nightly based on net transfer volume:
  - Each player has a "cost_change_start" (change from start of season)
  - "transfers_in_event" / "transfers_out_event" show current GW transfer activity
  - A player rises if net transfers in exceed ~1% of total managers (roughly ~300k)
  - A player falls if net transfers out exceed the same threshold

We estimate rise/fall probability using:
  net_transfers = transfers_in_event - transfers_out_event
  price_rise_score  = net_transfers / transfers_in_event_web   (FPL internal metric)

Since the FPL API doesn't expose the exact threshold, we use relative ranking.
Players with high positive net transfers are "likely risers".
Players with high negative net transfers are "likely fallers".
"""

from app.fpl_client import get_bootstrap

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Rough FPL threshold: net ~1M transfers triggers a price change (±0.1m)
# We normalise relative to this to give a probability estimate
RISE_THRESHOLD = 500_000   # conservative
FALL_THRESHOLD = -500_000


async def get_price_predictions(top_n: int = 20) -> dict:
    bootstrap = await get_bootstrap()
    teams = {t["id"]: t for t in bootstrap["teams"]}
    players = bootstrap["elements"]

    risers = []
    fallers = []

    for p in players:
        if p.get("status") in {"i", "u"}:
            continue

        net = p.get("transfers_in_event", 0) - p.get("transfers_out_event", 0)
        cost = p["now_cost"] / 10
        change_start = p.get("cost_change_start", 0) / 10

        entry = {
            "player": {
                "id": p["id"],
                "name": p["web_name"],
                "team": teams.get(p["team"], {}).get("short_name", "?"),
                "position": POSITION_MAP.get(p["element_type"], "?"),
                "current_price": cost,
                "change_from_start": change_start,
                "selected_by_pct": float(p.get("selected_by_percent") or 0),
            },
            "net_transfers_gw": net,
            "transfers_in_gw": p.get("transfers_in_event", 0),
            "transfers_out_gw": p.get("transfers_out_event", 0),
        }

        if net > 0:
            entry["direction"] = "rise"
            entry["confidence"] = min(100, round(net / RISE_THRESHOLD * 100))
            risers.append(entry)
        elif net < 0:
            entry["direction"] = "fall"
            entry["confidence"] = min(100, round(abs(net) / abs(FALL_THRESHOLD) * 100))
            fallers.append(entry)

    risers.sort(key=lambda x: x["net_transfers_gw"], reverse=True)
    fallers.sort(key=lambda x: x["net_transfers_gw"])

    return {
        "note": (
            "Price changes occur nightly. Confidence is a relative estimate "
            "based on net transfer volume — not a guaranteed prediction."
        ),
        "likely_risers": risers[:top_n],
        "likely_fallers": fallers[:top_n],
    }
