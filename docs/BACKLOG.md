# FPL Intelligence MCP Server — Product Backlog

> Living development roadmap. Updated: 2026-03-18
>
> **How to read this:** Each sprint is ordered by business priority. Work top-down. Items marked `[x]` are shipped. The Icebox holds ideas we are not committing to yet.

---

## Sprint 1 — Rival Intelligence (KILLER FEATURE)

The single highest-value feature set. Mini-league rivalry is the emotional core of FPL. Agents that can reason about rivals unlock a category of advice no other tool provides.

### Mini-League Rival Tracker

- [x] Accept `league_id`, show standings with point gaps — **S** ✅ v0.7.0
  - API: `GET /leagues-classic/{league_id}/standings/`
- [x] Fetch each rival's squad and compare with user's team — **M** ✅ v0.7.0
  - API: `GET /entry/{manager_id}/event/{gw}/picks/` (already implemented)
- [x] Identify differential players (you have vs they don't, and vice versa) — **M** ✅ v0.7.0
- [x] Show rival captain picks — **S** ✅ v0.7.0
- [x] Calculate "You need X points to overtake rival Y" — **S** ✅ v0.7.0

### Rival Prediction Engine

- [x] Analyze rival transfer history to detect patterns — **L** ✅ v0.7.0
  - API: `GET /entry/{manager_id}/transfers/`
- [x] Predict likely next transfer based on: injured players, poor performers, price rises they are priced out of — **L** ✅ v0.7.0
- [x] Show "rival vulnerabilities" — where their squad is weak (e.g., no playing keeper cover, reliance on a single premium) — **M** ✅ v0.7.0
- [x] Suggest counter-moves: "Your rival doesn't have Salah — if he hauls, you gain ground" — **M** ✅ v0.7.0

### New API Endpoints Required

- [x] `GET /entry/{manager_id}/transfers/` — transfer history — **S** ✅ v0.7.0
- [x] `GET /leagues-classic/{league_id}/standings/` — league standings — **S** ✅ v0.7.0
- [x] `GET /entry/{manager_id}/event/{gw}/picks/` — already implemented

---

## Sprint 2 — Scoring Intelligence Upgrades

Sharpen the existing captain and chip tools with data fields we already have access to but are not yet using.

- [x] Integrate `ep_next` (FPL's expected points) into captain scoring algorithm — **M** ✅ v0.8.1
  - Blend formula: `final_score = 0.6 * custom_score + 0.4 * ep_next_normalized`
  - This is FPL's own ML prediction — free, high signal
- [x] Use team strength fields (`strength_attack_home/away`, `strength_defence_home/away`) in fixture difficulty calculation — **M** ✅ v0.9.0
  - Better than raw FDR which is static and coarse
- [x] Add `most_captained` percentage to captain pick output (show community consensus) — **S** ✅ v0.15.0
- [x] Add `chip_plays` per event to chip strategy tool (show when other managers are using chips) — **S** ✅ v0.15.0

### API Endpoints Required

- None new — all fields available in existing `GET /bootstrap-static/` payload

---

## Sprint 3 — Live Game Enhancement

Make the live gameweek experience dramatically better. Bonus point tracking is the most-requested FPL feature globally.

- [x] Bonus points tracker in `live_points` tool — **L** ✅ v0.19.0
  - Parse BPS from fixture stats during live matches
  - Show projected bonus (top 3 per match)
  - "Your player is on track for 3 bonus" or "X BPS behind bonus"
- [ ] Use `chance_of_playing_this_round` in live analysis — **S**
- [x] Add `highest_score`, `top_element` per event for context ("You're beating the GW average by 14") — **S** ✅ v0.15.0
- [x] Event status checking for bonus finalization — **S** ✅ v0.15.0
  - API: `GET /event-status/`

### API Endpoints Required

- [x] `GET /event-status/` — bonus confirmed / points finalized status — **S** ✅ v0.15.0

---

## Sprint 4 — Player Deep Dive

Turn every player into a full scouting report. This is what separates a tool from an intelligence platform.

### Player History Analysis

- [ ] Home vs away form splits — **M**
  - API: `GET /element-summary/{player_id}/`
- [ ] Performance against specific opponents (historical matchup data) — **M**
- [ ] Consistency scoring based on points variance — **S**
- [ ] Hot streak / cold streak detection — **M**
- [ ] Season-over-season comparison using `history_past` — **S**

### Dream Team Comparison

- [ ] "You had 7/11 dream team players this GW" — **M**
  - API: `GET /dream-team/{event_id}/`
- [ ] Identify trending dream team players you are missing — **S**

### API Endpoints Required

- [ ] `GET /element-summary/{player_id}/` — full player history — **S**
- [ ] `GET /dream-team/{event_id}/` — GW dream team — **S**

---

## Sprint 5 — Set Piece & Transfer Intelligence

- [ ] Set piece intelligence tool — **M**
  - API: `GET /team/set-piece-notes/`
  - Official PL set piece data per club (corner takers, free kick takers, penalty takers)
  - Feed into captain and transfer scoring (set piece involvement is a huge points driver)
- [ ] Transfer history analysis for user's own team — **L**
  - Total hits taken, points impact of each transfer
  - "Transfers that paid off" vs "transfers that cost you"
  - ROI per transfer (points gained vs 4-point hit cost)

### API Endpoints Required

- [ ] `GET /team/set-piece-notes/` — set piece assignments — **S**

---

## Sprint 6 — External Intelligence

Move beyond the official FPL API. This is where we build a true information advantage.

- [ ] Press conference / injury news scraper — **L**
  - Scrape PL news for injury updates before FPL flags them
  - Starting XI hints from manager quotes
- [ ] Expand community DGW/BGW sources (more sites beyond current scraper) — **M**
- [ ] Reddit r/FantasyPL sentiment scraping (if feasible) — **L**

---

## Icebox (Future Consideration)

Not committed. Revisit when Sprints 1-6 are substantially complete or if priorities shift.

- [ ] H2H league support — **M**
  - API: `GET /leagues-h2h/{league_id}/standings/`
- [ ] FPL Cup tracker — **S**
  - API: `GET /entry/{id}/cup/`
- [ ] Most valuable teams stats — **S**
  - API: `GET /stats/most-valuable-teams/`
- [ ] Manager search / discovery — **M**
- [ ] Multi-season historical analysis — **L**
- [ ] Deploy HTTP paid API (revenue generation via x402 micropayments) — **L**
- [ ] Submit to Smithery MCP directory — **S**

---

## Complexity Key

| Size | Meaning |
|------|---------|
| **S** | Small — a few hours. Mostly wiring up existing data. |
| **M** | Medium — half a day to a day. New logic or non-trivial data transformation. |
| **L** | Large — multiple days. New subsystem, external integration, or significant algorithmic work. |
