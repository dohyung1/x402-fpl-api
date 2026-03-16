# FPL Intelligence — Execution Plan

## Positioning
"Intelligence, not data." We are the only FPL MCP server that returns scored recommendations with reasoning. Competitors (rishijatia, owen-lacey) return raw data.

## Competitors
| Competitor | Stars | Strength | Weakness |
|---|---|---|---|
| rishijatia/fantasy-pl-mcp | 69 | PyPI install, prompt templates, 11 tools | No captain scoring, no price predictions, no manager hub. Last updated Aug 2025 |
| owen-lacey/fpl-mcp | 3 | 16 tools, Glama listed, npm | Pure data wrapper. Zero intelligence |

## Our Edge
- `fpl_manager_hub` — unique all-in-one analysis (no competitor has this)
- Scored captain picks with reasoning
- Price predictions
- Live points with auto-sub scenarios
- xG/xA-powered algorithms (v2, after engineer fix)

---

## Sprint 1: Harden & Ship (This Week)

### Track A — Critical Fixes (Engineer Agent) — DONE ✅
- [x] Review complete — 5 critical, 11 warnings found
- [x] SQLite replay protection (replace in-memory set)
- [x] Thread-safe tx hash checking (atomic INSERT OR IGNORE)
- [x] Async verify_payment (asyncio.to_thread for Web3 calls)
- [x] Fix Web3 connection caching (remove lru_cache)
- [x] Double gameweek (DGW) support in fixture map
- [x] Captain/transfer endpoints default to NEXT gameweek
- [x] Refactor fpl_manager_hub to call existing algorithm functions
- [x] Fix web_name collision (use element IDs)
- [x] Upgrade captain algorithm with xG, xA, penalty data from FPL API
- [x] Run tests (15/15 passing), commit, push

### Track B — Distribution (Marketing Agent) — DONE
- [x] GitHub topics added (mcp, fpl, fantasy-premier-league, etc.)
- [x] GitHub description updated
- [x] All directory listing drafts ready (MARKETING_DRAFTS.md)
- [x] Reddit posts drafted (r/FantasyPL, r/ClaudeAI)
- [x] Submit to awesome-mcp-servers PR (#3340)
- [ ] Submit to Glama (manual — visit glama.ai/mcp/servers, click "Add Server")
- [ ] Submit to mcp.so (manual — visit mcp.so/submit)
- [ ] Post on Reddit (after first week of accuracy tracking)

### Track C — Research — DONE
- [x] FPL API has xG/xA/penalty/set piece data we weren't using
- [x] Top competitor gaps identified
- [x] Manager pain points mapped (captaincy, hit decisions, chip timing)
- [x] Monetization model defined ($19.99/season freemium)

---

## Sprint 2: Compete & Monetize (Next Week)

### Close Competitive Gaps
- [ ] Publish to PyPI (`pip install fpl-intelligence`) — one-command install
- [x] Add MCP prompt templates (5 prompts: analyze team, captain, differentials, transfers, price alerts)
- [x] Captain weights v2.1 — backtest-tuned (PPG×3.0, form×2.5, FDR×2.0)
- [x] Backtest script (`scripts/backtest.py`) — replay GWs, Haaland baseline, weight suggestions
- [x] MIT LICENSE added
- [ ] Add blank/double gameweek detection tool
- [ ] Add player comparison tool
- [ ] Add chip strategy advisor tool
- [ ] Add "Is this hit worth it?" tool (unique, no competitor has this)

### Distribution Push
- [ ] Submit to Smithery
- [ ] Post on r/FantasyPL with accuracy data
- [ ] Post on r/ClaudeAI
- [ ] Rebrand MCP as "FPL Intelligence" (drop x402 from public-facing name)

### Revenue Setup
- [ ] Set up LemonSqueezy for season pass ($19.99/season)
- [ ] Define free vs paid tier split
- [ ] Add API key gating for paid features
- [ ] Deploy HTTP API to Railway/Fly.io

---

## Sprint 3: Grow (Weeks 3-4)

### Product
- [ ] Multi-gameweek transfer planning (score targets across next 3-5 GWs)
- [ ] Integrate Understat for rolling per-match xG
- [ ] Add usage metrics tracking (SQLite → PostHog)
- [ ] Track captain pick accuracy weekly — publish as credibility metric

### Growth
- [ ] Weekly "AI captain picks" posts on r/FantasyPL
- [ ] Reach out to FPL content creators (YouTube/Twitter)
- [ ] Iterate on algorithms based on actual GW results
- [ ] First 50 paying users → $1,000 revenue target

---

## Revenue Model

### Free Tier (MCP, no auth)
- Captain pick (top 3, no reasoning)
- Differentials (top 5)
- Fixture outlook (3 GWs)
- Price predictions

### Paid Tier — $19.99/season or $4.99/month
- Full `fpl_manager_hub`
- Transfer suggestions
- Live points
- Full captain picks with reasoning
- Extended fixture outlook (10 GWs)
- Accuracy dashboard

### Projections
| Scale | Users | Revenue/Season |
|---|---|---|
| Minimum | 50 | $1,000 |
| Modest | 250 | $5,000 |
| Good | 1,000 | $20,000 |
| Strong PMF | 5,000 | $100,000 |

---

## Key Metrics to Track
1. GitHub stars + clones
2. MCP directory installs
3. Captain pick accuracy vs community average
4. Free → paid conversion rate (target 3-5%)
5. Weekly active users (tool calls per GW)
