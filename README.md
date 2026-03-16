# FPL Intelligence — MCP Server

[![PyPI version](https://img.shields.io/pypi/v/fpl-intelligence)](https://pypi.org/project/fpl-intelligence/)
[![CI](https://github.com/dohyung1/x402-fpl-api/actions/workflows/ci.yml/badge.svg)](https://github.com/dohyung1/x402-fpl-api/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

AI-powered Fantasy Premier League assistant for Claude Desktop. Get personalized captain picks, transfer suggestions, differentials, fixture analysis, price predictions, and live points — all from real FPL data.

[![FPL Intelligence MCP server](https://glama.ai/mcp/servers/dohyung1/x402-fpl-api/badges/card.svg)](https://glama.ai/mcp/servers/dohyung1/x402-fpl-api)

## Quick Start

**1. Install:**

```bash
pip install fpl-intelligence
```

**2. Add to Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fpl": {
      "command": "fpl-intelligence"
    }
  }
}
```

**3. Restart Claude Desktop and ask:**

> "Analyze FPL team **YOUR_TEAM_ID** and give me your full recommendation."

That's it. Bank balance, free transfers, and chips are all auto-detected — just provide your team ID.

### Install from Source

```bash
git clone https://github.com/dohyung1/x402-fpl-api.git
cd x402-fpl-api
uv sync
```

```json
{
  "mcpServers": {
    "fpl": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/x402-fpl-api", "mcp_server.py"]
    }
  }
}
```

## Find Your FPL Team ID

Go to the [FPL website](https://fantasy.premierleague.com), click "Points", and look at the URL:

```
https://fantasy.premierleague.com/entry/YOUR_TEAM_ID/event/<gw>
```

## What Can It Do?

| Tool | What it does |
|---|---|
| `fpl_manager_hub` | **Start here.** Full personalized analysis — captain, transfers, differentials, fixtures, price risks |
| `captain_pick` | Top 5 captain recommendations scored by xG, form, fixtures, and ICT index |
| `transfer_suggestions` | Transfer in/out recommendations based on your squad and budget |
| `player_comparison` | Head-to-head compare 2-4 players (e.g. "Salah vs Palmer vs Saka") |
| `is_hit_worth_it` | Should you take a -4 hit? Projects points over N gameweeks to decide |
| `chip_strategy` | When to use your remaining chips — optimal GW for each based on fixtures |
| `differential_finder` | Underowned players outperforming their ownership % |
| `fixture_outlook` | Teams ranked by upcoming fixture difficulty + best players to target |
| `price_predictions` | Players likely to rise or fall in price tonight |
| `live_points` | Live score, projected bonus, and auto-sub scenarios |
| `squad_scout` | Deep scout using FPL's hidden data — expected points, blank GW warnings, set piece duties, suspension risks |

## Example Prompts

Try these in Claude Desktop:

- "Analyze FPL team 5456980 and give me your full recommendation"
- "Who should I captain this gameweek?"
- "Compare Salah, Palmer, and Saka"
- "Is it worth taking a -4 hit to bring in Haaland?"
- "When should I use my bench boost?"
- "Find me some differentials under 5% ownership"
- "Which teams have the easiest fixtures for the next 6 weeks?"

## How It Works

FPL Intelligence connects directly to the [FPL API](https://www.postman.com/fplassist/fpl-assist/collection/zqlmv01/fantasy-premier-league-api) — the same free, public data source used by the FPL website. All data is real-time. The server runs locally on your machine and communicates with Claude Desktop via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io).

No API keys. No accounts. No data leaves your machine except FPL API calls.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
