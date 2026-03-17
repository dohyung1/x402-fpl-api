"""
DGW/BGW community intelligence scraper.

Fetches predicted Double Gameweek and Blank Gameweek data from
trusted community sources to supplement FPL API fixture analysis.

Sources:
- FPL API fixtures (event=null for postponed matches)
- Premier League official articles (confirmed schedule changes)
- AllAboutFPL (community-maintained DGW/BGW tracker)

Results are cached for 1 hour to avoid hammering external sites.
"""

import asyncio
import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

# Cache scraped intel for 1 hour — DGW news doesn't change by the minute
_intel_cache: dict[str, tuple[dict, float]] = {}
INTEL_CACHE_TTL = 3600  # seconds

# Known community sources for DGW/BGW predictions
SOURCES = [
    {
        "name": "premierleague.com",
        "url": "https://www.premierleague.com/en/news/4611210/what-we-know-so-far-about-blank-and-double-gameweeks-this-season",
        "type": "official",
    },
    {
        "name": "allaboutfpl.com",
        "url": "https://allaboutfpl.com/2026/01/upcoming-fpl-double-blank-gameweeks-25-26-fpl-season/",
        "type": "community",
    },
]

# PL team names → FPL API short_names (for matching scraped text to team IDs)
TEAM_ALIASES: dict[str, list[str]] = {
    "ARS": ["arsenal", "ars"],
    "AVL": ["aston villa", "villa", "avl"],
    "BOU": ["bournemouth", "bou"],
    "BRE": ["brentford", "bre"],
    "BHA": ["brighton", "bha", "brighton and hove"],
    "CHE": ["chelsea", "che"],
    "CRY": ["crystal palace", "palace", "cry"],
    "EVE": ["everton", "eve"],
    "FUL": ["fulham", "ful"],
    "IPS": ["ipswich", "ips"],
    "LEI": ["leicester", "lei"],
    "LIV": ["liverpool", "liv"],
    "MCI": ["manchester city", "man city", "mci", "city"],
    "MUN": ["manchester united", "man united", "man utd", "mun", "united"],
    "NEW": ["newcastle", "new", "newcastle united"],
    "NFO": ["nottingham forest", "nfo", "forest", "nott'm forest"],
    "SOU": ["southampton", "sou"],
    "SUN": ["sunderland", "sun"],
    "TOT": ["tottenham", "spurs", "tot"],
    "WHU": ["west ham", "whu", "west ham united"],
    "WOL": ["wolves", "wol", "wolverhampton"],
    "LEE": ["leeds", "lee", "leeds united"],
}

# Reverse lookup: alias → short_name
_ALIAS_TO_SHORT: dict[str, str] = {}
for short, aliases in TEAM_ALIASES.items():
    for alias in aliases:
        _ALIAS_TO_SHORT[alias.lower()] = short


def _match_team_name(text: str) -> str | None:
    """Try to match a team name string to an FPL short_name."""
    text_lower = text.lower().strip()
    # Direct match
    if text_lower in _ALIAS_TO_SHORT:
        return _ALIAS_TO_SHORT[text_lower]
    # Substring match (e.g., "Arsenal and Wolves" wouldn't match, but "Arsenal" would)
    for alias, short in _ALIAS_TO_SHORT.items():
        if alias in text_lower:
            return short
    return None


def _extract_dgw_bgw_from_text(text: str) -> dict:
    """
    Parse article text and extract DGW/BGW predictions.

    Looks for patterns like:
    - "Double Gameweek 33" / "DGW33" / "DGW 33"
    - "Blank Gameweek 34" / "BGW34" / "BGW 34"
    - Team names mentioned near these markers

    Returns: {
        "dgws": { gw_number: { "teams": [...], "status": "confirmed"|"predicted" } },
        "bgws": { gw_number: { "teams": [...], "status": "confirmed"|"predicted" } },
    }
    """
    result: dict[str, dict] = {"dgws": {}, "bgws": {}}

    # Normalize text
    text = text.replace("\n", " ").replace("\r", " ")

    # Find DGW mentions: "Double Gameweek 33", "DGW33", "DGW 33"
    dgw_pattern = r"(?:double\s*(?:game\s*week|gw)\s*(\d{1,2})|dgw\s*(\d{1,2}))"
    for match in re.finditer(dgw_pattern, text, re.IGNORECASE):
        gw = int(match.group(1) or match.group(2))
        if gw < 1 or gw > 38:
            continue

        # Extract surrounding context (200 chars) to find team names
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 200)
        context = text[start:end]

        teams = set()
        for alias, short in _ALIAS_TO_SHORT.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", context, re.IGNORECASE):
                teams.add(short)

        # Determine status from context words
        status = "predicted"
        confirmed_words = ["confirmed", "official", "scheduled", "will play"]
        for word in confirmed_words:
            if word in context.lower():
                status = "confirmed"
                break

        gw_key = str(gw)
        if gw_key not in result["dgws"]:
            result["dgws"][gw_key] = {"teams": [], "status": status}

        existing_teams = set(result["dgws"][gw_key]["teams"])
        existing_teams.update(teams)
        result["dgws"][gw_key]["teams"] = sorted(existing_teams)

        # Upgrade to confirmed if any source confirms
        if status == "confirmed":
            result["dgws"][gw_key]["status"] = "confirmed"

    # Find BGW mentions: "Blank Gameweek 34", "BGW34", "BGW 34"
    bgw_pattern = r"(?:blank\s*(?:game\s*week|gw)\s*(\d{1,2})|bgw\s*(\d{1,2}))"
    for match in re.finditer(bgw_pattern, text, re.IGNORECASE):
        gw = int(match.group(1) or match.group(2))
        if gw < 1 or gw > 38:
            continue

        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 200)
        context = text[start:end]

        teams = set()
        for alias, short in _ALIAS_TO_SHORT.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", context, re.IGNORECASE):
                teams.add(short)

        status = "predicted"
        confirmed_words = ["confirmed", "official", "will not play", "will blank"]
        for word in confirmed_words:
            if word in context.lower():
                status = "confirmed"
                break

        gw_key = str(gw)
        if gw_key not in result["bgws"]:
            result["bgws"][gw_key] = {"teams": [], "status": status}

        existing_teams = set(result["bgws"][gw_key]["teams"])
        existing_teams.update(teams)
        result["bgws"][gw_key]["teams"] = sorted(existing_teams)

        if status == "confirmed":
            result["bgws"][gw_key]["status"] = "confirmed"

    return result


async def _fetch_article(url: str) -> str | None:
    """Fetch article text from a URL. Returns None on failure."""
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            # Strip HTML tags for basic text extraction
            html = resp.text
            # Remove script and style blocks
            html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            # Remove HTML tags
            text = re.sub(r"<[^>]+>", " ", html)
            # Normalize whitespace
            text = re.sub(r"\s+", " ", text).strip()
            return text
    except Exception as exc:
        logger.warning("Failed to fetch DGW intel from %s: %s", url, exc)
        return None


async def fetch_community_dgw_intel() -> dict:
    """
    Scrape community sources for DGW/BGW predictions.

    Returns cached results if available. Merges data from multiple
    sources, with official sources taking precedence for status.

    Returns: {
        "dgws": { "33": { "teams": ["ARS", "CHE", ...], "status": "predicted", "sources": [...] } },
        "bgws": { "34": { "teams": ["ARS", "LIV", ...], "status": "confirmed", "sources": [...] } },
        "fetched_at": "2026-03-16T...",
        "sources_checked": [...],
        "errors": [...]
    }
    """
    cache_key = "community_dgw_intel"
    now = time.monotonic()

    if cache_key in _intel_cache:
        data, expires_at = _intel_cache[cache_key]
        if now < expires_at:
            return data

    merged: dict[str, dict] = {"dgws": {}, "bgws": {}}
    errors = []
    sources_checked = []

    # Fetch all sources concurrently
    tasks = [(src, _fetch_article(src["url"])) for src in SOURCES]
    results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    for i, (src, _) in enumerate(tasks):
        result = results[i]
        sources_checked.append(src["name"])

        if isinstance(result, Exception):
            errors.append(f"{src['name']}: {type(result).__name__}")
            continue

        if result is None:
            errors.append(f"{src['name']}: failed to fetch")
            continue

        parsed = _extract_dgw_bgw_from_text(result)

        # Merge DGWs
        for gw, info in parsed["dgws"].items():
            if gw not in merged["dgws"]:
                merged["dgws"][gw] = {"teams": [], "status": "predicted", "sources": []}
            existing = set(merged["dgws"][gw]["teams"])
            existing.update(info["teams"])
            merged["dgws"][gw]["teams"] = sorted(existing)
            merged["dgws"][gw]["sources"].append(src["name"])
            # Official source upgrades status
            if info["status"] == "confirmed" or src["type"] == "official":
                merged["dgws"][gw]["status"] = "confirmed"

        # Merge BGWs
        for gw, info in parsed["bgws"].items():
            if gw not in merged["bgws"]:
                merged["bgws"][gw] = {"teams": [], "status": "predicted", "sources": []}
            existing = set(merged["bgws"][gw]["teams"])
            existing.update(info["teams"])
            merged["bgws"][gw]["teams"] = sorted(existing)
            merged["bgws"][gw]["sources"].append(src["name"])
            if info["status"] == "confirmed" or src["type"] == "official":
                merged["bgws"][gw]["status"] = "confirmed"

    output = {
        "dgws": merged["dgws"],
        "bgws": merged["bgws"],
        "sources_checked": sources_checked,
        "errors": errors,
    }

    # Cache the result
    _intel_cache[cache_key] = (output, now + INTEL_CACHE_TTL)

    return output


def merge_intel_with_api_predictions(
    api_predictions: dict[int, list[int]],
    community_intel: dict,
    teams_by_id: dict[int, dict],
) -> dict[int, list[int]]:
    """
    Merge community DGW intel with FPL API-based predictions.

    Community intel uses short_names (e.g., "ARS"), while API predictions
    use team IDs. This function converts and merges both.

    Returns: enhanced { gameweek: [team_ids] } dict.
    """
    # Build short_name → team_id lookup
    short_to_id: dict[str, int] = {}
    for tid, team in teams_by_id.items():
        short_to_id[team.get("short_name", "")] = tid

    merged = dict(api_predictions)

    for gw_str, info in community_intel.get("dgws", {}).items():
        gw = int(gw_str)
        existing_teams = set(merged.get(gw, []))
        for short_name in info.get("teams", []):
            tid = short_to_id.get(short_name)
            if tid:
                existing_teams.add(tid)
        if existing_teams:
            merged[gw] = sorted(existing_teams)

    return merged
