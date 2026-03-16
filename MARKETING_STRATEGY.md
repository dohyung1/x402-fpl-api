# FPL Intelligence — Full Marketing Strategy

> Last updated: 2026-03-16 (GW31 deadline approaching)
> Status: Copy-paste ready for all channels

---

## Table of Contents

1. [Twitter/X](#1-twitterx)
2. [Discord](#2-discord)
3. [YouTube](#3-youtube)
4. [Hacker News](#4-hacker-news)
5. [Product Hunt](#5-product-hunt)
6. [Dev.to / Medium](#6-devto--medium)
7. [FPL Podcasts & Newsletters](#7-fpl-podcasts--newsletters)
8. [GitHub SEO](#8-github-seo)
9. [Timing & Execution Calendar](#9-timing--execution-calendar)

---

## 1. Twitter/X

FPL Twitter is enormous — 1M+ active accounts during the season. The key is mixing FPL-native language with tech novelty. Always include the GitHub link. Post during peak FPL hours: Tuesday-Friday evenings UK time (18:00-22:00 GMT), especially before GW deadlines.

**Accounts to tag/engage with:**
- @OfficialFPL (8M+ followers)
- @FPLFocal, @FPL_Salah, @LetsTalk_FPL, @BigManBakar, @FPLGeneral
- @AnthropicAI, @ClaborDe (Claude community)
- @modelcontextprotocol

### Tweet 1 — Launch Announcement

```
I built an AI that analyzes your FPL team in seconds.

Just type your team ID and Claude tells you:
→ Who to captain (and why)
→ Which transfers to make
→ Whether that -4 hit is worth it
→ When to play your chips

One command: pip install fpl-intelligence

Free & open source 👇
https://github.com/dohyung1/x402-fpl-api
```

### Tweet 2 — GW31 Urgency Hook

```
GW31 deadline is coming. Still not sure who to captain?

I built an MCP server that turns Claude into your FPL analyst.

It scored Salah 9.2, Palmer 8.7, Haaland 7.1 for my team this week.

Try it:
pip install fpl-intelligence

Then ask Claude: "Analyze FPL team [YOUR_ID]"

https://github.com/dohyung1/x402-fpl-api
```

### Tweet 3 — Technical/Dev Angle

```
Built an MCP server in Python that gives Claude 10 FPL tools:

• captain_pick — scored recommendations with reasoning
• is_hit_worth_it — projects points over N gameweeks
• chip_strategy — optimal GW for each remaining chip
• player_comparison — head-to-head on 10+ metrics
• differential_finder — low-ownership outperformers

No API key. No signup. Just pip install.

https://github.com/dohyung1/x402-fpl-api
```

### Tweet 4 — Comparison/Competitor Angle

```
Other FPL tools give you raw stats.

This one gives you scored recommendations with reasoning.

"Captain Salah (9.2) — top xG/90 in the league, home to Southampton (FDR 2), on penalties, 100% minutes certainty."

That's what an AI analyst should sound like.

pip install fpl-intelligence
https://github.com/dohyung1/x402-fpl-api
```

### Tweet 5 — Thread Starter (for engagement)

```
I gave Claude 10 FPL superpowers. Here's what happened when I asked it to analyze my team 🧵

1/ First, it pulled my full squad, bank balance (£0.3m), 1 free transfer, and chips remaining (BB, TC)

2/ Captain pick: Salah (9.2) over Haaland (7.1). Reasoning: "Home to Southampton, top xG/90, on penalties. Haaland faces Arsenal away (FDR 5)."

3/ Transfer suggestion: Sell Isak (injured, flagged 25%) → Buy Palmer (form 8.4, fixtures: WHU, EVE, LEI next 3)

4/ Chip strategy: "Play Triple Captain GW33 — Salah has DGW with home fixtures rated FDR 2 and 2"

5/ It even told me a -4 hit for Gordon → Saka would pay for itself in 2.3 gameweeks.

All free. All open source.
pip install fpl-intelligence
https://github.com/dohyung1/x402-fpl-api
```

---

## 2. Discord

### Target Servers

**FPL Discord Servers:**
- **FPL Discord** (Official community, 50k+ members) — look for #tools or #resources channels
- **Fantasy Football Hub Discord** — active community with tools discussion
- **FPL Wire Discord** — podcast community server
- **Fantasy Football Scout Discord** — data-oriented members, perfect audience

**AI/Dev Discord Servers:**
- **Anthropic / Claude Discord** — #showcase or #projects channel
- **MCP Community Discord** — if one exists, or the Anthropic server's MCP channel
- **Python Discord** — #showcase channel
- **AI Tinkerers Discord** — builders community

### Message for FPL Discord Servers

```
Hey everyone — built a free tool that turns Claude (the AI) into an FPL analyst for your specific team.

Install: pip install fpl-intelligence
Then ask Claude: "Analyze FPL team [YOUR_ID]"

It auto-detects your squad, bank, free transfers, and chips, then gives you:
- Captain recommendations scored on xG, form, fixtures, penalties
- Transfer suggestions within your budget
- Whether a -4 hit is actually worth it
- When to use your remaining chips
- Price rise/fall predictions for tonight

10 tools total. Works with Claude Desktop (free tier).

GW31 deadline coming up — give it a shot and tell me what you think.

GitHub: https://github.com/dohyung1/x402-fpl-api
```

### Message for Claude/AI Discord Servers

```
Sharing a project: FPL Intelligence — an MCP server that gives Claude 10 Fantasy Premier League analysis tools.

`pip install fpl-intelligence`

What makes it different from other MCP servers:
- Returns **scored recommendations with reasoning**, not raw data
- 10 specialized tools (captain picks, transfer suggestions, hit calculator, chip strategy, player comparison, differentials, fixture outlook, price predictions, live points, and a full manager hub)
- Single command install, no API keys, no config beyond adding it to claude_desktop_config.json

It's a good example of building an MCP server that does real computation and returns opinionated results rather than just wrapping an API.

GitHub: https://github.com/dohyung1/x402-fpl-api
PyPI: https://pypi.org/project/fpl-intelligence/
```

---

## 3. YouTube

### Should You Make a Demo Video?

Yes — absolutely. FPL YouTube is huge (channels like Let's Talk FPL have 200k+ subs). A 3-5 minute demo is the single highest-leverage piece of content you can create. People need to *see* the conversation flow to understand the value.

### Video Structure (3-5 minutes)

**Title:** "I Gave Claude AI 10 FPL Superpowers — Here's What Happened"

**Thumbnail:** Split screen — Claude Desktop on left, FPL team page on right. Text overlay: "AI FPL Analyst" with a captain armband emoji.

**Script outline:**

```
[0:00-0:20] Hook
"What if you could ask an AI to analyze your exact FPL team and get specific recommendations? I built a tool that does exactly that. Let me show you."

[0:20-1:00] Install (screen recording)
- Show terminal: pip install fpl-intelligence
- Show adding to claude_desktop_config.json
- Show finding team ID on FPL website
- "That's the entire setup. 30 seconds."

[1:00-2:30] Demo — The Money Shot
- Open Claude Desktop
- Type: "Analyze FPL team [ID] and give me your full recommendation"
- Show the full response loading in real-time
- Pause on captain pick — highlight the scoring and reasoning
- Pause on transfer suggestion — show it respects your budget
- Show the hit calculator: "Is it worth taking a -4 to bring in Palmer for Isak?"

[2:30-3:30] Power Features
- "Compare Salah, Palmer, and Saka for me"
- "When should I use my triple captain?"
- "Find me differentials under 5% ownership"
- Quick cuts showing each response

[3:30-4:00] Close
- "Free, open source, 10 tools."
- Show GitHub link
- "Try it before the GW31 deadline. Link in description."
```

**Description:**

```
FPL Intelligence — an MCP server that turns Claude into your personal FPL analyst.

Install: pip install fpl-intelligence
GitHub: https://github.com/dohyung1/x402-fpl-api
PyPI: https://pypi.org/project/fpl-intelligence/

10 tools: captain picks, transfer suggestions, player comparison, hit calculator, chip strategy, differential finder, fixture outlook, price predictions, live points, and full manager hub.

Free and open source. Works with Claude Desktop.

Timestamps:
0:00 — What is it?
0:20 — How to install (30 seconds)
1:00 — Full team analysis demo
2:30 — Power features
3:30 — How to get it

#FPL #FantasyPremierLeague #AI #Claude #MCP
```

---

## 4. Hacker News

**Best time to post:** Tuesday-Thursday, 8-10 AM EST (when US tech audience is active). Title must start with "Show HN:".

### Show HN Post

**Title:**
```
Show HN: FPL Intelligence – MCP server that turns Claude into an FPL analyst (10 tools, pip install)
```

**Body (text field):**
```
I built an MCP server that gives Claude Desktop 10 Fantasy Premier League analysis tools. Install with pip, add to your config, and ask Claude to analyze your team by ID.

What it does:
- Captain recommendations scored by xG/90, form, fixtures, penalty duties, minutes certainty
- Transfer suggestions that respect your budget and free transfers
- "Is a -4 hit worth it?" — projects net points over N gameweeks
- Chip strategy — tells you which GW to play each remaining chip
- Player comparison on 10+ metrics
- Differential finder, fixture outlook, price predictions, live points

What makes it different from other FPL tools: it returns scored recommendations with reasoning, not raw stats. The captain pick algorithm weighs xG, form, home advantage, fixture difficulty, ICT index, bonus rate, penalties, and injury status — then explains why.

What makes it different from other MCP servers: most just wrap an API and return raw JSON. This one does real computation and gives opinionated recommendations. It's closer to a domain expert than a data pipe.

Tech: Python, FastMCP, httpx. Data from the official Premier League API (free, public, no auth). Each tool is an async function that fetches live data and runs scoring algorithms.

pip install fpl-intelligence
https://github.com/dohyung1/x402-fpl-api

Happy to discuss the MCP architecture, scoring algorithms, or FPL data modeling.
```

---

## 5. Product Hunt

**Best day to launch:** Tuesday-Thursday. Avoid Monday (too crowded) and Friday (low traffic).

### Submission

**Name:** FPL Intelligence

**Tagline:** Turn Claude into your Fantasy Premier League analyst — 10 AI-powered tools, one pip install

**Description:**
```
FPL Intelligence is an open-source MCP server that gives Claude 10 Fantasy Premier League analysis tools. Just install with pip, add it to your Claude Desktop config, and ask Claude to analyze your team.

WHAT IT DOES:
- Captain recommendations with scoring breakdown and reasoning
- Transfer suggestions that respect your budget and free transfers
- "Should I take a -4 hit?" calculator with point projections
- Chip strategy — optimal gameweek for each remaining chip
- Head-to-head player comparison on 10+ metrics
- Low-ownership differential finder
- Fixture difficulty outlook
- Price rise/fall predictions
- Live points with projected bonus and auto-subs
- Full manager hub — everything in one analysis

HOW IT WORKS:
1. pip install fpl-intelligence
2. Add one line to your Claude Desktop config
3. Ask Claude: "Analyze FPL team [YOUR_ID]"

Claude auto-detects your squad, bank balance, free transfers, and chips used — then gives you personalized, scored recommendations with reasoning.

WHY WE BUILT IT:
Every FPL tool gives you raw stats and expects you to decide. We built an AI analyst that gives you opinions: "Captain Salah (9.2/10) because he has the highest xG/90 in the league, is at home to Southampton, and is on penalties."

TECH:
Open source, built with Python and FastMCP. Data from the official Premier League API (free, real-time). No API keys, no accounts, no subscriptions.
```

**Topics:** Artificial Intelligence, Fantasy Sports, Open Source, Developer Tools, Python

**Links:**
- GitHub: https://github.com/dohyung1/x402-fpl-api
- PyPI: https://pypi.org/project/fpl-intelligence/

**Maker comment (post immediately after launch):**
```
Hey Product Hunt! I'm the maker of FPL Intelligence.

I play Fantasy Premier League every season and got tired of jumping between 5 different websites for stats, fixture difficulty, price predictions, and transfer advice. So I built an MCP server that gives Claude all of that context at once.

The key insight: most FPL tools show you data and expect you to interpret it. This one gives you scored recommendations with reasoning — like having a knowledgeable friend who's looked at all the stats for you.

Some tools that no competitor has:
- is_hit_worth_it: Projects whether a -4 point hit pays for itself over N gameweeks
- chip_strategy: Tells you the optimal GW for each remaining chip based on fixture difficulty
- player_comparison: Head-to-head on xG, form, fixtures, price, ownership — not just one stat

It's free and open source. Would love feedback on the scoring algorithms — they're the core IP and I'm constantly tuning them against actual GW results.

Ask me anything about MCP server development, FPL data modeling, or the scoring algorithms!
```

---

## 6. Dev.to / Medium

### Article Option A — Dev.to (better for discovery, free, tagged)

**Title:** Building an MCP Server That Actually Thinks: How I Gave Claude 10 Fantasy Premier League Superpowers

**Tags:** `python`, `ai`, `mcp`, `opensource`

**Outline:**

```markdown
# Building an MCP Server That Actually Thinks: How I Gave Claude 10 FPL Superpowers

## Intro — The Problem with Most MCP Servers
- Most MCP servers are thin wrappers around APIs
- They fetch data and return JSON — the LLM does all the thinking
- What if the server did real computation and returned opinionated recommendations?

## What I Built
- FPL Intelligence: 10 tools for Fantasy Premier League analysis
- pip install fpl-intelligence
- Show the one-line Claude Desktop config
- Quick demo: what happens when you ask "Analyze FPL team 12345"

## Architecture: FastMCP + Async Python
- Using Anthropic's FastMCP framework
- Each tool is an async function
- Data fetching with httpx from the official Premier League API
- Code snippet: the captain_pick tool definition (show the decorator pattern)

## The Scoring Algorithm — Where the Value Lives
- Raw data vs. intelligence: showing the captain score formula
- Weighting xG/90, form, fixture difficulty, home advantage, penalties, injury status
- Code snippet: the scoring function
- Why tuning these weights is the real IP

## Tool Design Decisions
- Why 10 specialized tools instead of one mega-tool
- How tool descriptions matter for LLM routing
- The "manager hub" pattern: a meta-tool that orchestrates sub-tools
- Making tools conversational: "is_hit_worth_it" accepts natural player names

## Lessons Learned Building MCP Servers
1. Return opinions, not just data — LLMs are better at presenting conclusions than computing them
2. Keep tool descriptions precise — Claude routes based on them
3. Async everything — FPL API calls are I/O bound
4. Make install frictionless — pip install + one JSON config line
5. Default to the current gameweek — minimize required parameters

## Distribution: Getting an MCP Server to Users
- Publishing to PyPI with hatch
- The claude_desktop_config.json pattern
- Submitting to awesome-mcp-servers, Glama, mcp.so
- Why MCP servers have a discovery problem (and what I'm doing about it)

## Try It
- pip install fpl-intelligence
- GitHub: https://github.com/dohyung1/x402-fpl-api
- 10 tools, free, open source, MIT license

## What's Next
- Tuning weights against historical GW results
- Adding more sports (NFL, NBA, Champions League)
- The x402 vision: pay-per-query agent commerce
```

### Article Option B — Medium (better for FPL audience crossover)

**Title:** I Built an AI That Analyzes Your FPL Team in 10 Seconds — Here's How

**Publication targets:** Towards Data Science, The Startup, or self-publish with FPL + AI tags

**Same outline as above but with more FPL context and less MCP internals. Lead with the user experience, end with the tech.**

---

## 7. FPL Podcasts & Newsletters

### Target List

**Podcasts (sorted by audience size):**
1. **FPL Wire** — ~50k listeners, hosted by Zophar and Lateriser. Very data-driven, would appreciate the algorithmic approach.
2. **Always Cheating** — Popular FPL podcast, discusses tools regularly.
3. **FPL General** — Large following, reviews FPL tools.
4. **Who Got the Assist?** — FPL comedy/analysis podcast, open to community tools.
5. **FPL BlackBox** — Statistics-focused, perfect audience for scored recommendations.
6. **Planet FPL** — Official FPL podcast, long shot but worth trying.

**Newsletters:**
1. **FPL Reports** (fplreports.com) — Data-driven FPL newsletter
2. **Fantasy Football Hub newsletter** — Large subscriber base, features tools
3. **FPL Wire newsletter** — Companion to the podcast
4. **The Athletic FPL coverage** — Long shot but high impact

**FPL Content Creators (for review/feature):**
1. **Let's Talk FPL (YouTube, 200k+ subs)** — Reviews FPL tools
2. **FPL Mate** — Active tool reviewer
3. **Andy LTFPL** — Covers FPL tech/data tools

### Pitch Email Template

**Subject:** Free AI tool for FPL analysis — would love your take on it

```
Hi [NAME],

I'm a regular listener/reader of [PODCAST/NEWSLETTER] — [one specific reference to a recent episode/edition to prove you actually follow them].

I built a free, open-source tool called FPL Intelligence that turns Claude (Anthropic's AI) into a personalized FPL analyst. You install it with one command (pip install fpl-intelligence), give it your team ID, and it gives you:

- Scored captain recommendations (weighing xG/90, form, fixture difficulty, penalties, minutes certainty)
- Transfer suggestions within your exact budget
- A calculator that tells you whether a -4 hit is worth it
- Optimal gameweek for each remaining chip
- Head-to-head player comparison on 10+ metrics

What makes it different from LiveFPL, FPL Review, etc.: it doesn't just show data — it gives opinions with reasoning. "Captain Salah (9.2/10): highest xG/90, home to Southampton (FDR 2), on penalties, 100% minutes certainty."

I'd love to offer you an early look or demo. Happy to jump on a 10-minute call, send a screen recording, or just send you the install instructions so you can try it on your own team.

It's completely free and open source: https://github.com/dohyung1/x402-fpl-api

Would this be interesting for [your audience / a segment / a tools roundup]?

Best,
[YOUR NAME]
```

### Shorter Pitch (for DMs / Twitter outreach)

```
Hey [NAME] — big fan of your work on [specific thing].

I built a free tool that turns Claude AI into an FPL analyst. You give it your team ID and it gives scored captain picks, transfer suggestions, hit calculations, and chip strategy — all personalized to your squad.

10 tools, pip install, open source: https://github.com/dohyung1/x402-fpl-api

Would love your take on it. Happy to demo or just send install instructions.
```

---

## 8. GitHub SEO

### Repository Description (max 350 chars)
```
MCP server that turns Claude into a Fantasy Premier League analyst. 10 tools: captain picks, transfer suggestions, player comparison, hit calculator, chip strategy, differentials, fixtures, price predictions, live points. pip install fpl-intelligence
```

### Topics (add via Settings > Topics)
```
mcp
mcp-server
fantasy-premier-league
fpl
claude
anthropic
ai
fantasy-football
premier-league
python
llm
model-context-protocol
```

### README Badges to Add

Add these at the top of README.md, right below the H1:

```markdown
[![PyPI version](https://img.shields.io/pypi/v/fpl-intelligence)](https://pypi.org/project/fpl-intelligence/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)
```

### Additional GitHub Actions

1. **Add a GitHub social preview image** (Settings > Social preview): Create a 1280x640 image with "FPL Intelligence" title, the 10 tool names, and "pip install fpl-intelligence". This shows up when the link is shared on Twitter/Discord/Slack.

2. **Pin the repo** on your GitHub profile.

3. **Create a GitHub Discussion** or enable Discussions tab — lets users ask questions without filing issues, which feels more welcoming.

4. **Add a "Star History" chart** to the README once you get some traction — social proof drives more stars.

---

## 9. Timing & Execution Calendar

The Premier League season ends in May 2026. Every week matters. GW31 deadline is the immediate hook.

### Week 1 (March 16-22) — Launch Blitz

| Day | Channel | Action |
|-----|---------|--------|
| Mon Mar 16 | GitHub | Add badges, topics, social preview image, update description |
| Mon Mar 16 | Twitter | Post Tweet 1 (launch announcement) |
| Tue Mar 17 | Hacker News | Post Show HN (8-10 AM EST) |
| Tue Mar 17 | Twitter | Post Tweet 2 (GW31 urgency hook) |
| Wed Mar 18 | Discord | Post in FPL Discord servers (2-3 servers) |
| Wed Mar 18 | Discord | Post in Claude/AI Discord servers |
| Thu Mar 19 | Product Hunt | Launch (aim for top of day) |
| Thu Mar 19 | Twitter | Post Tweet 3 (technical angle) |
| Fri Mar 20 | Dev.to | Publish article |
| Fri Mar 20 | Twitter | Post Tweet 5 (thread) |

### Week 2 (March 23-29) — Outreach

| Day | Channel | Action |
|-----|---------|--------|
| Mon Mar 23 | Podcasts | Send pitch emails to FPL Wire, Always Cheating, FPL BlackBox |
| Mon Mar 23 | YouTube creators | DM Let's Talk FPL, FPL Mate with short pitch |
| Tue Mar 24 | Newsletters | Email FPL Reports, Fantasy Football Hub |
| Wed Mar 25 | Twitter | Post Tweet 4 (comparison angle) |
| Thu Mar 26 | Reddit | Post to r/FantasyPL if karma allows |
| Fri Mar 27 | YouTube | Record and upload demo video |

### Week 3+ (March 30 onward) — Sustain

- Post GW-specific tweets before each deadline ("GW32 deadline in 24 hours — here's what my AI analyst says about my team")
- Reply to FPL Twitter conversations with relevant tool screenshots
- Engage with anyone who tweets about FPL tools/AI
- If awesome-mcp-servers PR is merged, tweet about it
- Cross-post Dev.to article to Medium if it performs well
- Share interesting tool outputs (anonymized) as Twitter content

### Ongoing Content Ideas

- **"AI vs Human" series:** Compare FPL Intelligence's captain pick to popular FPL influencers each GW. Track cumulative score.
- **Leaderboard challenge:** Create a team managed purely by FPL Intelligence. Share weekly updates. "Can an AI beat the average FPL manager?"
- **GW review threads:** "My AI said captain Salah, I went with Haaland. Here's what happened..."
- **Feature announcement tweets** for each new capability added

---

## Appendix: Quick Reference

**One-liner for all channels:**
> FPL Intelligence: pip install fpl-intelligence — turns Claude into your FPL analyst with 10 tools

**Key links:**
- GitHub: https://github.com/dohyung1/x402-fpl-api
- PyPI: https://pypi.org/project/fpl-intelligence/

**Unique selling points (use these phrases):**
- "Scored recommendations with reasoning, not raw stats"
- "The only FPL MCP server with a hit calculator, chip strategy, and player comparison"
- "One command to install, one line of config, just type your team ID"
- "Free, open source, no API key, no signup"

**Tools list (for quick copy-paste):**
1. fpl_manager_hub — Full personalized analysis
2. captain_pick — Top 5 captain recommendations
3. transfer_suggestions — Transfer in/out within budget
4. player_comparison — Head-to-head 2-4 players
5. is_hit_worth_it — Should you take a -4?
6. chip_strategy — When to use remaining chips
7. differential_finder — Low-ownership outperformers
8. fixture_outlook — Teams ranked by fixture difficulty
9. price_predictions — Tonight's price changes
10. live_points — Live score and projected bonus
