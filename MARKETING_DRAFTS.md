# Marketing Drafts — Ready to Post

## Reddit r/ClaudeAI (POST FIRST)

**Title:** I built an MCP server that turns Claude into a Fantasy Premier League analyst — just type your team ID

**Body:**

One command to install:

```
pip install fpl-intelligence
```

Add to your Claude Desktop config:

```json
{"mcpServers": {"fpl": {"command": "fpl-intelligence"}}}
```

Restart Claude and type:

> "Analyze FPL team 12345"

That's it. Claude auto-detects your squad, bank balance, free transfers, and chips used — then gives you:

- Who to captain and why (scored by xG, form, fixtures, penalties)
- Which players to sell and who to buy within your budget
- Players about to rise or fall in price tonight
- Low-ownership differentials outperforming their ownership %
- Whether a -4 hit is actually worth it
- When to use your remaining chips

You can also ask things like:

- "Compare Salah, Palmer, and Saka"
- "Who should I captain this week?"
- "Is it worth taking a hit to bring in Gordon for Rogers?"
- "Find me differentials under 5% ownership"

10 tools total. All data comes from the official Premier League API in real-time. No API keys needed.

To find your team ID, go to the FPL website → Points tab → check the URL:
`https://fantasy.premierleague.com/entry/YOUR_ID/event/30`

Open source: https://github.com/dohyung1/x402-fpl-api
PyPI: https://pypi.org/project/fpl-intelligence/

---

## Reddit r/FantasyPL (POST WHEN KARMA ALLOWS)

**Title:** I built a free AI tool that analyzes your FPL team — just type your team ID and get a full recommendation

**Body:**

Install it in 30 seconds:

```
pip install fpl-intelligence
```

Then open Claude Desktop and type:

> "Analyze FPL team 12345"

It auto-detects your squad, bank, free transfers, and chips — then tells you:

- Who to captain (scored by xG/90, form, fixture difficulty, penalty duties)
- Who to sell and who to buy within your budget
- Low-ownership differentials you're missing
- Players about to rise or fall in price tonight
- Whether taking a -4 hit is worth it for a specific transfer
- When to use your remaining chips

You can ask natural questions like "Compare Salah vs Palmer vs Saka" or "Is it worth taking a hit to bring in Gordon?"

Example output for my team this week:
- Flagged that I had **4 blanking players** in my starting XI
- Told me to switch captain from Haaland (blank) to Bruno Fernandes
- Suggested selling Mukiele (doubtful, form 0.2) for Senesi (form 7.5)
- Warned me Haaland is about to drop in price (131k transfers out)

Free and open source: https://github.com/dohyung1/x402-fpl-api

To find your team ID: FPL website → Points → check the URL.

What other analysis would you want? Happy to add features.

---

## Reddit r/PremierLeague (ALTERNATIVE)

**Title:** Built an AI tool that analyzes your Fantasy Premier League team — just type your team ID

**Body:**

(Same as r/FantasyPL post above but add a line at the top:)

If you play FPL, I built a free tool that gives you an instant team analysis.

(Rest of post same as above)
