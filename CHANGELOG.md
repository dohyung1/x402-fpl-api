# Changelog

All notable changes to this project will be documented in this file.

## [0.13.0] - 2026-03-18

### Added
- **`fpl-intelligence --setup`** — one-command auto-configuration for Claude Desktop (finds binary path, writes config, preserves existing settings)

### Changed
- **README Quick Start** — simplified from 5 steps to 4 with auto-setup replacing manual config editing

## [0.12.1] - 2026-03-17

### Fixed
- **Chip strategy bug** — manager hub reported all chips as used in the second half of the season (first-half chips reset after GW19 but weren't labeled)
- Hub now includes `chips_remaining` and marks first-half chips as "has reset"

### Changed
- **README setup guide** — full-path install instructions to prevent "Failed to spawn process" errors, expanded troubleshooting

## [0.11.0] - 2026-03-18

### Added
- **News/injury integration** — player news keywords (hamstring, suspended, unknown return, etc.) now penalise captain picks, transfer suggestions, and surface in comparison and scout reports
- **Defensive contribution scoring** — DEF/MID players get scored on `defensive_contribution_per_90` across captain, transfer, and comparison tools

### Changed
- **Captain algorithm v2.4** — weights tuned from GW1-29 backtest correlation analysis
  - ppg 3.5→4.55, form 2.8→3.1, penalty 1.5→1.69, bonus_pg 1.1→1.2
  - ep_next 1.0→0.7, xg90 1.5→1.27, xa90 1.2→1.05, def_contrib 1.2→0.84
  - Backtest: 167→184 pts (+10.2%), gap to Haaland baseline closed from 28→11 pts
  - Top 3 accuracy doubled (3.4%→6.9%), Top 10 accuracy 17.2%→24.1%
- Rolling weight optimizer BASE_WEIGHTS synced to v2.4 defaults

## [0.10.0] - 2026-03-17

### Fixed
- **Chip strategy completely rewritten** — v2 algorithm uses multi-chip sequencing instead of scoring each chip independently
  - WC→BB combo: Wildcard placed 1 GW before Bench Boost to rebuild squad for mega DGW
  - BB heavily weighted toward confirmed DGW team count (mega DGW with 12 teams dominates)
  - FH heavily weighted toward BGW blank team count (BGW with 16 teams blanking → FH essential)
  - TC targets DGWs where premium captain plays twice
  - Constraint solver ensures no two chips in same GW
  - Previous v1 scored chips independently and recommended wrong sequence (WC33 instead of community consensus WC32→BB33→FH34→TC36)
- **Captain algorithm v2.3** — normalized scoring fixes "always picks same player" bug
  - All factors normalized to 0-1 scale before weighting (PPG, form, xG/xA, ICT, etc.)
  - Fixture-dependent factors (FDR, home/away) now actually differentiate picks across GWs
  - v2.2 picked B.Fernandes 29/29 GWs; v2.3 picks from 6 different players based on matchups
  - Backtest: Top 5 hit rate 10.3%→17.2%, total captain points 166→192, nearly matches "always Haaland" baseline
  - Weights updated from backtest GW1-29: fdr 2.0→3.0, home 2.0→3.0, ppg 3.0→3.5, xg90 2.0→1.5

## [0.9.0] - 2026-03-17

### Added
- Team strength blending — fixture difficulty now uses FPL's dynamic `strength_attack_home/away` fields (updated weekly) instead of relying solely on static FDR ratings. Affects all tools: captain, transfers, fixtures, differentials, chips, rivals, league analyzer.
- `xGC/90` (expected goals conceded per 90) for defenders and goalkeepers in player comparison
- `ep_next` (FPL expected points) shown in player comparison output

### Fixed
- Auto-sub logic now follows FPL rules: GKP can only sub for GKP, outfield subs follow bench order, prevents GKP subbing for outfield players
- Fixture outlook now uses blended difficulty scores instead of raw FDR

## [0.8.1] - 2026-03-17

### Added
- `ep_next` (FPL's own expected points prediction) integrated into captain scoring algorithm (v2.2)
- Blank GW warning in captain pick reasoning — "NO FIXTURE this GW — do not captain"
- FPL expected points shown in captain pick stats output
- Budget disclaimer in transfer suggestions — warns that FPL selling prices may differ
- `scripts/stats_snapshot.py` — daily PyPI download + GitHub metrics tracker

### Fixed
- Captain `bonus_per_game` now uses starts instead of 90s played (more accurate denominator)

## [0.8.0] - 2026-03-17

### Added
- `league_analyzer` MCP tool — predict who will win a mini-league
  - Win probability for each top manager based on points gap, squad quality, chips remaining, momentum, team value, and injuries
  - Only requires league ID — no team ID needed
  - Narrative insights: title race closeness, chip advantages, hot streaks, injury concerns

## [0.7.1] - 2026-03-17

### Fixed
- Rival tracker GW bug — now plans for next gameweek when current GW fixtures are finished
- Ruff lint/format errors in test files

### Changed
- Reorganized repo — moved internal docs (BACKLOG, PLAN, MARKETING_*) to `docs/`
- Updated CLAUDE.md with current project structure, tools, and algorithm
- Updated CONTRIBUTING.md with lint/format instructions
- Updated SECURITY.md supported versions to 0.7.x

## [0.7.0] - 2026-03-16

### Added
- `rival_tracker` MCP tool — mini-league rival intelligence (Sprint 1)
  - League standings with point gaps and rank changes
  - Squad comparison: differentials (players you have vs they don't)
  - Rival captain picks revealed
  - Rival weakness detection (injuries, blank GWs, poor form, tough fixtures)
  - Transfer prediction engine: predicts rival's likely next moves
  - Counter-strategy suggestions to overtake rivals
- New FPL API endpoints: league standings, manager transfers, manager info
- Product backlog (`BACKLOG.md`) with 6-sprint development roadmap

## [0.6.0] - 2026-03-16

### Fixed
- FPL API 403 errors — User-Agent header changed from `x402-fpl-api/1.0` to browser-like string, fixing blocked requests for many users

### Added
- Troubleshooting section in README (FPL API 403s, Claude Desktop sandbox, install issues)
- Product backlog (`BACKLOG.md`) with 6-sprint development roadmap

## [0.5.0] - 2026-03-16

### Added
- DGW/BGW prediction engine — detects postponed fixtures (`event: null`) from FPL API to predict future Double Gameweeks
- Community intelligence scraper (`dgw_intel.py`) — scrapes premierleague.com and AllAboutFPL for confirmed/predicted DGW and BGW data
- Team alias matching for 20+ PL teams (handles "Man City", "Spurs", "Wolves", etc.)
- Predicted DGW data merged into chip strategy scoring (TC, BB, FH all benefit)
- `pending_dgws` section in chip strategy output — shows teams with postponed fixtures and likely DGW gameweeks
- `community_intel` section in chip strategy output — shows scraped DGW/BGW predictions with sources
- 43 new tests for DGW prediction and community intel scraping

### Fixed
- Chip strategy no longer recommends Triple Captain in non-DGW weeks when upcoming DGWs are likely
- Triple Captain scoring now boosts players on teams with predicted DGWs (1.6x multiplier)
- Bench Boost scoring factors in predicted DGWs for bench players

## [0.4.0] - 2026-03-16

### Added
- MCP server instructions for better Claude tool routing
- "USE THIS WHEN" guidance in all 11 tool descriptions
- MCP resources: `fpl://status` (gameweek/deadline info), `fpl://teams` (all 20 PL teams)
- `isError` flag on all tool failures (MCP best practice — lets Claude self-correct)
- Input validation at MCP boundary (team_id, gameweek, position, player names)
- GitHub Actions CI (pytest on Python 3.12 + 3.13, ruff lint + format)
- GitHub Actions publish workflow (auto-publish to PyPI on release)
- Issue templates, PR template, CONTRIBUTING.md, SECURITY.md, CHANGELOG.md
- Dependabot for automated dependency updates
- ruff linter + formatter configuration

### Fixed
- Transaction status verification — reject reverted on-chain transactions (status != 1)
- Transaction hash format validation (0x + 64 hex chars)
- SQLite WAL mode for better async concurrency
- Payment error messages no longer leak internal amounts
- CORS now configurable via `CORS_ORIGINS` env var (was hardcoded wildcard)
- CORS allowed headers restricted to `X-Payment` only
- FPL API retry logic (2 retries with exponential backoff)
- Web3 RPC provider timeout (15s, was unlimited)
- TEST_MODE startup guard — refuses to start with mainnet RPC
- MCP error responses no longer leak exception details
- HTTP API gameweek validation (1-38) and max_ownership validation (0.1-100)
- All Python files formatted consistently with ruff

### Changed
- README rewritten with Quick Start flow, example prompts, How It Works section

## [0.3.0] - 2026-03-16

### Added
- `squad_scout` tool — deep analysis using FPL's hidden data fields (ep_next, set piece duties, suspension risks)
- `is_hit_worth_it` tool — projects whether a -4 point hit is worth it over N gameweeks
- `chip_strategy` tool — recommends optimal gameweek for each unused chip
- `player_comparison` tool — head-to-head compare 2-4 players with fuzzy name matching
- MCP prompt templates (5 prompts for Claude Desktop's prompt selector)
- MCP resources (`fpl://status`, `fpl://teams`) for context without tool calls
- Server instructions for better Claude routing
- Input validation on all MCP tools with `isError` flag
- FPL API retry logic (2 retries with exponential backoff)
- GitHub Actions CI (pytest on Python 3.12 + 3.13)
- GitHub Actions publish workflow (auto-publish on release)
- Issue templates, PR template, CONTRIBUTING.md
- Dependabot configuration

### Fixed
- Half-season chip reset — FPL resets all chips after GW19, now correctly detected
- Captain scoring weights v2.1 — backtest-tuned (PPG x3.0, form x2.5, FDR x2.0)
- CORS configuration — now configurable via `CORS_ORIGINS` env var
- Transaction status verification — reject reverted on-chain transactions
- Payment error messages no longer leak internal amounts

## [0.2.1] - 2026-03-15

### Fixed
- Chip detection bug — all chips showing as used in second half of season

## [0.2.0] - 2026-03-15

### Added
- `fpl_manager_hub` tool — full team analysis with auto-detected bank/transfers/chips
- `live_points` tool — live scores during active gameweeks
- Backtest script for captain pick accuracy measurement
- MIT License

## [0.1.0] - 2026-03-14

### Added
- Initial release
- `captain_pick`, `differential_finder`, `fixture_outlook`, `price_predictions`, `transfer_suggestions` tools
- x402 payment protocol with USDC on Base
- FPL API client with in-memory caching
- SQLite replay protection for payment verification
