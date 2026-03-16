# x402 FPL Intelligence

AI-agent-native Fantasy Premier League intelligence. Get captain picks, transfer suggestions, differentials, fixture analysis, price predictions, and live points — all powered by real FPL data.

## Use with Claude Desktop (MCP)

Add this to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

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

Restart Claude Desktop. Then ask:

> "Analyze FPL team YOUR_TEAM_ID and give me your full recommendation."

Claude will automatically detect your bank balance, free transfers, chips used, and give you personalized captain picks, transfer suggestions, differentials, and fixture outlook.

## Available Tools

| Tool | Description |
|---|---|
| `fpl_manager_hub` | Full personalized analysis — just provide your FPL team ID |
| `captain_pick` | Top 5 captain recommendations for any gameweek |
| `differential_finder` | Underowned players outperforming their ownership |
| `fixture_outlook` | Teams ranked by upcoming fixture difficulty |
| `price_predictions` | Players likely to rise or fall in price tonight |
| `transfer_suggestions` | Transfer in/out recommendations for a team |
| `live_points` | Live score, projected bonus, auto-sub scenarios |

## HTTP API (x402 Protocol)

The same intelligence is available as a pay-per-query HTTP API using the x402 protocol (HTTP 402 micropayments with USDC on Base).

```bash
# Start the server
uv run uvicorn app.main:app --reload

# Get a 402 response with payment details
curl http://localhost:8000/api/fpl/captain-pick

# Pay and retry with tx hash
curl -H "X-Payment: 0x..." http://localhost:8000/api/fpl/captain-pick
```

## Setup

```bash
git clone https://github.com/dohyung1/x402-fpl-api.git
cd x402-fpl-api
uv sync
cp .env.example .env  # Edit with your wallet address
```

## Find Your FPL Team ID

Go to the [FPL website](https://fantasy.premierleague.com), click "Points", and look at the URL:

```
https://fantasy.premierleague.com/entry/YOUR_TEAM_ID/event/<gw>
```

## Tech Stack

- **Server:** Python + FastAPI
- **MCP:** Model Context Protocol for Claude Desktop integration
- **Data:** Official FPL API (free, real-time, public)
- **Payments:** USDC on Base L2 via x402 protocol
