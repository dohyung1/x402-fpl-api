# FPL Intelligence — MCP Server

[![PyPI version](https://img.shields.io/pypi/v/fpl-intelligence)](https://pypi.org/project/fpl-intelligence/)
[![CI](https://github.com/dohyung1/x402-fpl-api/actions/workflows/ci.yml/badge.svg)](https://github.com/dohyung1/x402-fpl-api/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

Turn Claude into your FPL analyst. Captain picks, transfer advice, rival scouting, chip timing, league predictions — powered by real-time FPL data.

[![FPL Intelligence MCP server](https://glama.ai/mcp/servers/dohyung1/x402-fpl-api/badges/card.svg)](https://glama.ai/mcp/servers/dohyung1/x402-fpl-api)

## Quick Start

### Step 1 — Install

```bash
pip install fpl-intelligence
```

### Step 2 — Connect to Claude Desktop

Open your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the server:

```json
{
  "mcpServers": {
    "fpl": {
      "command": "fpl-intelligence"
    }
  }
}
```

### Step 3 — Restart Claude Desktop

Close and reopen Claude Desktop. You should see `fpl` listed under the MCP servers icon.

### Step 4 — Ask Claude anything about FPL

> "Analyze my FPL team **5456980** — who should I captain, who should I transfer in, and when should I use my chips?"

That's it. Bank balance, free transfers, and chips are all auto-detected from your team ID.

### Where's my team ID?

Go to [fantasy.premierleague.com](https://fantasy.premierleague.com) → click **Points** → grab the number from the URL:

```
https://fantasy.premierleague.com/entry/YOUR_TEAM_ID/event/30
```

Your league ID is in the mini-league URL:

```
https://fantasy.premierleague.com/leagues/YOUR_LEAGUE_ID/standings/c
```

## 13 Tools

| Tool | What it does |
|---|---|
| `fpl_manager_hub` | Full personalized analysis — captain, transfers, differentials, fixtures, price risks |
| `captain_pick` | Top 5 captain picks scored by form, xG, fixtures, and ICT index |
| `transfer_suggestions` | Who to bring in and ship out based on your squad and budget |
| `player_comparison` | Head-to-head compare 2-4 players across every metric |
| `is_hit_worth_it` | Should you take a -4? Projects net points over N gameweeks |
| `chip_strategy` | Optimal gameweek for each chip — factors in DGW predictions |
| `differential_finder` | Hidden gems outperforming their ownership |
| `fixture_outlook` | Teams ranked by upcoming fixture difficulty |
| `price_predictions` | Who's rising and falling tonight |
| `live_points` | Live score, projected bonus, auto-sub scenarios |
| `rival_tracker` | Spy on mini-league rivals — differentials, weaknesses, predicted moves |
| `league_analyzer` | Win probabilities for your league — who's the favourite and why |
| `squad_scout` | Deep scout using FPL's hidden data — ep_next, set pieces, suspension risks |

## Example Prompts

```
"Give me the full breakdown on team 5456980 — captain, transfers, everything"

"I have 2 free transfers and 1.5m in the bank. Who should I bring in?"

"Salah vs Palmer vs Saka — who's the best pick for the next 5 gameweeks?"

"I want to bring in Haaland for a -4. Is it worth the hit?"

"I still have my bench boost and triple captain. When should I use them?"

"Find me some differentials under 3% ownership that are actually returning points"

"It's 60 minutes into the games — how's my team doing? Any auto-subs?"

"Show me everything about mini-league 1189955 — who's going to win?"

"How do I beat my rivals in league 1189955? I'm team 5456980"

"Which players are about to drop in price tonight? I need to sell before the deadline"
```

## How It Works

FPL Intelligence connects to the official [FPL API](https://fantasy.premierleague.com/api/bootstrap-static/) — the same free, public data that powers the FPL website. All data is real-time. See the full [FPL API reference on Postman](https://www.postman.com/fplassist/fpl-assist/collection/zqlmv01/fantasy-premier-league-api?sideView=agentMode) for endpoint documentation.

The server runs locally on your machine and talks to Claude Desktop via [MCP](https://modelcontextprotocol.io). No API keys, no accounts, no data leaves your machine except FPL API calls.

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

## Troubleshooting

<details>
<summary><strong>FPL API calls are blocked / 403 errors</strong></summary>

The FPL API blocks requests that don't look like they come from a browser.

**Test if the API is reachable:**

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" \
  https://fantasy.premierleague.com/api/bootstrap-static/
```

Returns `200`? The API works — the issue is likely Claude Desktop's sandbox (see below). Returns `403`? Your network is blocking it.

**Claude Desktop sandbox:** Claude Desktop may prompt you to approve network access to `fantasy.premierleague.com`. If you dismissed this, restart Claude Desktop and watch for the prompt. Check logs at `~/Library/Logs/Claude/` (macOS).

**VPN / corporate network:** Some networks block `*.premierleague.com`. Try disconnecting from VPN or switching to a personal network.

**FPL API downtime:** The API goes down around deadline time and between seasons (June-July). Test in your browser: [fantasy.premierleague.com/api/bootstrap-static/](https://fantasy.premierleague.com/api/bootstrap-static/)

</details>

<details>
<summary><strong>Server won't start / command not found</strong></summary>

**`command not found: fpl-intelligence`** — The binary isn't on your PATH:

```bash
which fpl-intelligence   # find the full path
pip show fpl-intelligence # check install location
```

Or use `pipx` for isolated installs: `pipx install fpl-intelligence`

**Python version error:** Requires Python 3.12+. Check with `python3 --version`.

</details>

<details>
<summary><strong>Invalid team_id errors</strong></summary>

Use your FPL team ID (a number like `5456980`), not your username. Find it at [fantasy.premierleague.com](https://fantasy.premierleague.com) → **Points** → check the URL.

</details>

<details>
<summary><strong>Still stuck?</strong></summary>

[Open an issue](https://github.com/dohyung1/x402-fpl-api/issues) with your OS, Python version, the error message, and the output of the curl test above.

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
