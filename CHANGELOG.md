# Changelog

All notable changes to this project will be documented in this file.

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
