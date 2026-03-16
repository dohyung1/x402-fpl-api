# FPL Intelligence — MCP Server

AI-powered Fantasy Premier League assistant for Claude Desktop. Get personalized captain picks, transfer suggestions, differentials, fixture analysis, price predictions, and live points — all from real FPL data.

## Install

```bash
pip install fpl-intelligence
```

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fpl": {
      "command": "fpl-intelligence"
    }
  }
}
```

**Or install from source:**

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

Restart Claude Desktop and ask:

> "Analyze FPL team YOUR_TEAM_ID and give me your full recommendation."

Bank balance, free transfers, and chips are all auto-detected — just provide your team ID.

## Find Your FPL Team ID

Go to the [FPL website](https://fantasy.premierleague.com), click "Points", and look at the URL:

```
https://fantasy.premierleague.com/entry/YOUR_TEAM_ID/event/<gw>
```

## Available Tools

| Tool | What it does |
|---|---|
| `fpl_manager_hub` | Full personalized analysis — captain, transfers, differentials, fixtures, price risks |
| `captain_pick` | Top 5 captain recommendations scored by xG, form, fixtures, and ICT index |
| `transfer_suggestions` | Transfer in/out recommendations based on your squad and budget |
| `player_comparison` | Head-to-head compare 2-4 players (e.g. "Salah vs Palmer vs Saka") |
| `is_hit_worth_it` | Should you take a -4 hit? Projects points over N gameweeks to decide |
| `chip_strategy` | When to use your remaining chips — optimal GW for each based on fixtures |
| `differential_finder` | Underowned players outperforming their ownership % |
| `fixture_outlook` | Teams ranked by upcoming fixture difficulty + best players to target |
| `price_predictions` | Players likely to rise or fall in price tonight |
| `live_points` | Live score, projected bonus, and auto-sub scenarios |
