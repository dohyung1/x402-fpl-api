# x402 FPL Intelligence API

## Project Vision
An AI-agent-native Fantasy Premier League (FPL) intelligence API. Agents pay per-query using the x402 (HTTP 402) protocol — no API keys, no subscriptions, no signup. We turn free public FPL data into actionable recommendations that AI agents can consume instantly.

The long-term play: FPL is the proving ground. Once x402 works here, we expand to other fantasy sports and eventually the client/server SDK becomes the real product — "Stripe for agent commerce."

## Tech Stack
- **Server:** Python + FastAPI
- **Payment verification:** web3.py (USDC on Base L2)
- **Data source:** FPL public API (https://fantasy.premierleague.com/api/) — free, real-time, no auth
- **Hosting:** Single VPS or serverless (low compute)
- **Agent wallet:** Coinbase CDP SDK or standard EOA

## The x402 Payment Flow
Every paid endpoint follows this pattern:
1. Agent sends request (no token, no auth)
2. Server responds **402** + JSON body: `{ price, wallet_address, service_name }`
3. Agent pays on-chain (USDC on Base L2, sub-penny fees, <1s settlement)
4. Agent retries with `X-Payment` header containing the tx hash
5. Server verifies tx on-chain → delivers response

Two HTTP requests per paid call. Zero auth infrastructure.

## Endpoints & Pricing

| Endpoint | Price | Description |
|---|---|---|
| `GET /api/fpl/captain-pick` | $0.002 | Top 5 captain recommendations with scoring breakdown |
| `GET /api/fpl/transfer-suggest` | $0.005 | Transfer in/out recommendations for a given team |
| `GET /api/fpl/differentials` | $0.001 | Underowned players outperforming their ownership |
| `GET /api/fpl/fixture-outlook` | $0.001 | Teams ranked by upcoming fixture difficulty |
| `GET /api/fpl/price-predictions` | $0.002 | Players likely to rise or fall in price tonight |
| `GET /api/fpl/live-points` | $0.001 | Live score, projected bonus, auto-sub scenarios |

## FPL Data Sources (all free, public)
- `GET /bootstrap-static/` — All players, teams, gameweeks, scoring rules
- `GET /fixtures/` — All 380 fixtures with FDR ratings
- `GET /event/{gw}/live/` — Real-time points during matches
- `GET /element-summary/{player_id}/` — Per-player fixture history
- `GET /entry/{team_id}/event/{gw}/picks/` — Team's picks for a gameweek
- `GET /entry/{team_id}/history/` — Season history and chips used

## Captain Score Algorithm
```
captain_score =
    form × 2.0
  + points_per_game × 1.0
  + home_bonus (1.5 if home, else 0)
  - fixture_difficulty × 1.0      (FDR 1–5)
  + ict_index × 0.01
  + bonus_per_game × 0.5
  - injury_penalty (0 if fit, -10 if doubtful/injured)
```
Weights are tuned over time against actual GW results — this tuning is our core IP.

## Build Order
- **Phase 1:** Real x402 payment flow with USDC on Base testnet
- **Phase 2:** Captain pick endpoint (easiest, highest value)
- **Phase 3:** Differential finder (proves multi-endpoint model)
- **Phase 4:** Extract client SDK as open source package (distribution)
- **Phase 5:** Remaining endpoints (transfers, fixtures, live, prices)
- **Phase 6:** Service directory listing for agent discovery
- **Phase 7:** Expand to NFL, NBA, Champions League

## Project Structure (target)
```
x402-fpl-api/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── app/
│   ├── main.py            # FastAPI app, x402 middleware
│   ├── x402.py            # Payment verification logic
│   ├── fpl_client.py      # FPL API wrapper with caching
│   ├── algorithms/
│   │   ├── captain.py     # Captain pick scoring
│   │   ├── differentials.py
│   │   ├── fixtures.py
│   │   ├── transfers.py
│   │   ├── prices.py
│   │   └── live.py
│   └── models.py          # Pydantic response schemas
├── tests/
└── scripts/
    └── seed_testnet.py    # Fund test wallet on Base Sepolia
```

## Revenue Model
Pay-per-query in USDC on Base L2. No subscriptions, no API keys, no billing infrastructure.

Example at scale: 50 FPL agent apps × 1,000 users × 5 queries/week × $0.002 avg = **~$19,000/season**

## Key Principles
- **Agent-first:** Every response is JSON optimized for machine consumption, not humans
- **Zero friction:** No signup. No API key. Agent discovers, pays, gets data
- **Intelligence over data:** Return recommendations with reasoning, not raw stats
- **Minimize infra:** No frontend, no user management, no auth system
- **Start narrow:** Nail FPL before expanding to other sports
