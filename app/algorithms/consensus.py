"""
Community Consensus algorithm.

Fetches recent FPL YouTube content from top creators and extracts
a consensus view on captain picks, transfer targets, chip timing,
and team news/injuries.

Sources: FPL Mate, Let's Talk FPL, FPL Harry, FPL Focal, FPL Raptor
Data: YouTube RSS feeds (no API key) + youtube-transcript-api
Cache: 2 hours (content doesn't change frequently)
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

# Cache consensus results for 2 hours
_consensus_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 7200

# Channel registry — channel_id resolved at runtime if None
CHANNELS = [
    {"name": "FPL Mate", "channel_id": "UCweDAlFm2LnVcOqaFU4_AGA"},
    {"name": "Let's Talk FPL", "channel_id": "UCxeOc7eFxq37yW_Nc-69deA"},
    {"name": "FPL Focal", "channel_id": "UC72QokPHXQ9r98ROfNZmaDw"},
    {"name": "FPL Raptor", "channel_id": "UC54QLWzsMifTRjNQ02z5pCw"},
    {"name": "FPL Harry", "channel_id": None, "handle": "FPLHarry"},
]

MAX_VIDEOS_PER_CHANNEL = 3
MAX_AGE_DAYS = 10  # only consider videos from the last 10 days
MAX_TRANSCRIPT_CHARS = 20000  # truncate very long transcripts

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# Resolved channel IDs cached in memory
_resolved_ids: dict[str, str] = {}

# --- Keyword patterns for insight extraction ---

CAPTAIN_PATTERNS = [
    re.compile(r"captain(?:cy|ing)?\s+(?:is\s+)?(\w[\w\s'-]{2,25})", re.IGNORECASE),
    re.compile(r"(\w[\w\s'-]{2,25})\s+(?:is|as)\s+(?:my|the|our)\s+captain", re.IGNORECASE),
    re.compile(r"(?:going with|picking|backing)\s+(\w[\w\s'-]{2,25})\s+(?:as\s+)?captain", re.IGNORECASE),
    re.compile(r"captain\s*(?:pick|choice|option)\s*(?:is|:)\s*(\w[\w\s'-]{2,25})", re.IGNORECASE),
]

TRANSFER_IN_PATTERNS = [
    re.compile(r"(?:bring|get|transfer)\s+(?:in|him in)\s+(\w[\w\s'-]{2,25})", re.IGNORECASE),
    re.compile(r"(?:buy|sign|pick up|grab)\s+(\w[\w\s'-]{2,25})", re.IGNORECASE),
    re.compile(r"(\w[\w\s'-]{2,25})\s+is\s+a\s+(?:must[- ]?have|must[- ]?buy|must[- ]?own)", re.IGNORECASE),
]

TRANSFER_OUT_PATTERNS = [
    re.compile(r"(?:sell|get rid of|transfer out|drop|ship out|ditch)\s+(\w[\w\s'-]{2,25})", re.IGNORECASE),
]

CHIP_PATTERNS = [
    re.compile(
        r"(bench\s*boost|triple\s*captain|free\s*hit|wildcard)\s+(?:in\s+)?(?:gw|gameweek)\s*(\d{1,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:play|use|activate)\s+(?:my\s+)?(?:the\s+)?(bench\s*boost|triple\s*captain|free\s*hit|wildcard)"
        r"\s+(?:in\s+)?(?:gw|gameweek)\s*(\d{1,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:gw|gameweek)\s*(\d{1,2})\s+(?:is\s+)?(?:the\s+)?(?:best|ideal|perfect)\s+(?:for\s+)?"
        r"(bench\s*boost|triple\s*captain|free\s*hit|wildcard)",
        re.IGNORECASE,
    ),
]

INJURY_PATTERNS = [
    re.compile(r"(\w[\w\s'-]{2,25})\s+(?:is\s+)?(?:injured|out|doubtful|ruled out|sidelined|a doubt)", re.IGNORECASE),
    re.compile(r"(\w[\w\s'-]{2,25})\s+(?:has\s+)?(?:a\s+)?(?:hamstring|ankle|knee|calf|muscle|groin)", re.IGNORECASE),
    re.compile(r"(\w[\w\s'-]{2,25})\s+(?:is\s+)?(?:suspended|banned)", re.IGNORECASE),
]

# Common non-player words to filter out of regex matches
STOP_WORDS = {
    "the", "this", "that", "your", "my", "our", "his", "her", "a", "an", "it",
    "is", "was", "are", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "can", "may",
    "might", "must", "shall", "not", "no", "yes", "so", "if", "then",
    "but", "and", "or", "for", "to", "in", "on", "at", "by", "of", "from",
    "up", "out", "with", "as", "into", "about", "like", "just", "very",
    "really", "actually", "definitely", "probably", "maybe", "absolutely",
    "honestly", "obviously", "certainly", "basically", "essentially",
    "bench boost", "triple captain", "free hit", "wildcard",
    "gameweek", "fantasy", "premier league", "fpl", "points",
    "i think", "you know", "i mean", "going to", "want to",
}


async def get_community_consensus(gameweek: int | None = None) -> dict:
    """
    Fetch recent FPL YouTube videos and extract consensus on captain picks,
    transfer targets, chip timing, and team news.
    """
    # Check cache
    cache_key = f"consensus_{gameweek}"
    now = time.monotonic()
    if cache_key in _consensus_cache:
        cached, expires = _consensus_cache[cache_key]
        if now < expires:
            return cached

    # Get FPL player names for grounding extracted mentions
    player_names = await _get_player_name_set()

    # Fetch videos from all channels concurrently
    channel_results = await asyncio.gather(
        *[_process_channel(ch, player_names) for ch in CHANNELS],
        return_exceptions=True,
    )

    sources = []
    all_insights = []

    for ch, result in zip(CHANNELS, channel_results):
        if isinstance(result, Exception):
            logger.warning("Channel %s failed: %s", ch["name"], result)
            sources.append({"name": ch["name"], "videos_analyzed": 0, "status": f"error: {result}"})
            continue
        sources.append({
            "name": ch["name"],
            "videos_analyzed": result["video_count"],
            "videos": result.get("video_titles", []),
            "status": "ok" if result["video_count"] > 0 else "no_recent_videos",
        })
        all_insights.extend(result["insights"])

    # Build consensus from all channel insights
    consensus = _build_consensus(all_insights, player_names)

    total_videos = sum(s["videos_analyzed"] for s in sources)
    result = {
        "gameweek": gameweek,
        "sources": sources,
        "total_videos_analyzed": total_videos,
        "data_freshness": f"Videos from last {MAX_AGE_DAYS} days",
        **consensus,
    }

    # Cache
    _consensus_cache[cache_key] = (result, now + CACHE_TTL)

    return result


async def _get_player_name_set() -> set[str]:
    """Get all FPL player web_names for grounding extracted mentions."""
    try:
        from app.fpl_client import get_bootstrap

        bootstrap = await get_bootstrap()
        return {p["web_name"].lower() for p in bootstrap["elements"]}
    except Exception:
        return set()


async def _resolve_channel_id(handle: str) -> str | None:
    """Resolve a YouTube @handle to a channel ID by fetching the page."""
    if handle in _resolved_ids:
        return _resolved_ids[handle]

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"https://www.youtube.com/@{handle}")
            resp.raise_for_status()
            html = resp.text

            # Look for channel ID in page source
            match = re.search(r'"externalId"\s*:\s*"(UC[\w-]+)"', html)
            if not match:
                match = re.search(r'"channelId"\s*:\s*"(UC[\w-]+)"', html)
            if not match:
                match = re.search(r'channel_id=(UC[\w-]+)', html)

            if match:
                channel_id = match.group(1)
                _resolved_ids[handle] = channel_id
                return channel_id
    except Exception as e:
        logger.warning("Failed to resolve handle @%s: %s", handle, e)

    return None


async def _fetch_rss_feed(channel_id: str) -> list[dict]:
    """Fetch YouTube RSS feed and return recent video entries."""
    url = RSS_URL.format(channel_id=channel_id)

    async with httpx.AsyncClient(headers=HEADERS, timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    root = ElementTree.fromstring(resp.text)
    entries = root.findall(f"{ATOM_NS}entry")

    videos = []
    cutoff = datetime.now(timezone.utc).timestamp() - (MAX_AGE_DAYS * 86400)

    for entry in entries[:MAX_VIDEOS_PER_CHANNEL * 2]:  # fetch extra, filter by date
        title = entry.findtext(f"{ATOM_NS}title", "")
        published = entry.findtext(f"{ATOM_NS}published", "")
        video_id_el = entry.find(f"{ATOM_NS}id")
        video_id = ""
        if video_id_el is not None and video_id_el.text:
            # Format: yt:video:VIDEO_ID
            video_id = video_id_el.text.split(":")[-1]

        # Parse published date
        try:
            pub_ts = datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            pub_ts = 0

        if pub_ts < cutoff:
            continue

        # Filter for FPL-related videos by title
        title_lower = title.lower()
        is_fpl = any(kw in title_lower for kw in [
            "fpl", "fantasy", "gameweek", "gw", "captain", "transfer", "wildcard",
            "bench boost", "free hit", "triple captain", "chip", "differential",
            "premier league",
        ])

        if video_id and is_fpl:
            videos.append({
                "video_id": video_id,
                "title": title,
                "published": published,
            })

        if len(videos) >= MAX_VIDEOS_PER_CHANNEL:
            break

    return videos


def _fetch_transcript(video_id: str) -> str | None:
    """Fetch transcript synchronously (youtube-transcript-api is sync)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id)

        text = " ".join(snippet.text for snippet in transcript)
        return text[:MAX_TRANSCRIPT_CHARS]

    except Exception as e:
        logger.debug("Transcript unavailable for %s: %s", video_id, e)
        return None


async def _fetch_transcript_async(video_id: str) -> str | None:
    """Run sync transcript fetch in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_transcript, video_id)


async def _process_channel(channel: dict, player_names: set[str]) -> dict:
    """Process a single channel: fetch RSS, get transcripts, extract insights."""
    channel_id = channel.get("channel_id")

    # Resolve handle to channel ID if needed
    if not channel_id and channel.get("handle"):
        channel_id = await _resolve_channel_id(channel["handle"])
        if not channel_id:
            return {"video_count": 0, "insights": [], "video_titles": []}

    videos = await _fetch_rss_feed(channel_id)

    if not videos:
        return {"video_count": 0, "insights": [], "video_titles": []}

    # Fetch transcripts concurrently
    transcripts = await asyncio.gather(
        *[_fetch_transcript_async(v["video_id"]) for v in videos],
        return_exceptions=True,
    )

    insights = []
    video_titles = []
    for video, transcript in zip(videos, transcripts):
        if isinstance(transcript, Exception) or transcript is None:
            continue

        video_titles.append(video["title"])
        extracted = _extract_insights(transcript, video["title"], player_names, channel["name"])
        insights.append(extracted)

    return {
        "video_count": len(video_titles),
        "insights": insights,
        "video_titles": video_titles,
    }


def _clean_name(raw: str) -> str:
    """Clean a regex-extracted name."""
    name = raw.strip().strip(".,!?;:'\"()[]")
    # Remove trailing common words
    for suffix in [" is", " as", " for", " in", " and", " or", " the", " to", " a"]:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _is_valid_player_mention(name: str, player_names: set[str]) -> bool:
    """Check if an extracted name matches an FPL player."""
    cleaned = name.lower().strip()
    if cleaned in STOP_WORDS or len(cleaned) < 3:
        return False
    # Direct match
    if cleaned in player_names:
        return True
    # Partial match (e.g., "Salah" matches "M. Salah")
    for pname in player_names:
        if cleaned in pname or pname in cleaned:
            return True
    return False


def _match_to_player_name(name: str, player_names: set[str]) -> str | None:
    """Find the best matching FPL player name."""
    cleaned = name.lower().strip()
    if cleaned in player_names:
        # Return the properly-cased version
        for pname in player_names:
            if pname == cleaned:
                return pname.title()
        return cleaned.title()
    # Partial match
    for pname in player_names:
        if cleaned in pname or pname in cleaned:
            return pname.title()
    return None


def _extract_from_patterns(
    text: str, patterns: list[re.Pattern], player_names: set[str]
) -> list[str]:
    """Extract player names matching patterns, grounded against FPL player list."""
    found = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            # Get the captured group (player name)
            raw_name = match.group(1) if match.lastindex else match.group(0)
            cleaned = _clean_name(raw_name)
            matched = _match_to_player_name(cleaned, player_names)
            if matched and matched not in found:
                found.append(matched)
    return found


def _extract_insights(
    transcript: str, title: str, player_names: set[str], channel_name: str
) -> dict:
    """Extract FPL insights from a video transcript."""
    # Combine title and transcript for searching
    full_text = f"{title} {transcript}"

    captains = _extract_from_patterns(full_text, CAPTAIN_PATTERNS, player_names)
    transfers_in = _extract_from_patterns(full_text, TRANSFER_IN_PATTERNS, player_names)
    transfers_out = _extract_from_patterns(full_text, TRANSFER_OUT_PATTERNS, player_names)
    injuries = _extract_from_patterns(full_text, INJURY_PATTERNS, player_names)

    # Extract chip advice
    chip_advice = []
    for pattern in CHIP_PATTERNS:
        for match in pattern.finditer(full_text):
            groups = match.groups()
            if len(groups) >= 2:
                # Determine which group is the chip and which is the GW
                g1, g2 = groups[0], groups[1]
                if g1.isdigit():
                    gw, chip = int(g1), g2.lower()
                else:
                    chip, gw = g1.lower(), int(g2)
                chip_norm = chip.replace(" ", "_")
                chip_advice.append({"chip": chip_norm, "gameweek": gw})

    return {
        "channel": channel_name,
        "title": title,
        "captains": captains,
        "transfers_in": transfers_in,
        "transfers_out": transfers_out,
        "chip_advice": chip_advice,
        "injuries": injuries,
    }


def _build_consensus(insights: list[dict], player_names: set[str]) -> dict:
    """Aggregate insights across all channels into a consensus view."""
    captain_counts: dict[str, list[str]] = {}
    transfer_in_counts: dict[str, list[str]] = {}
    transfer_out_counts: dict[str, list[str]] = {}
    chip_counts: dict[str, list[dict]] = {}
    injury_mentions: dict[str, list[str]] = {}

    for insight in insights:
        channel = insight["channel"]

        for captain in insight["captains"]:
            captain_counts.setdefault(captain, [])
            if channel not in captain_counts[captain]:
                captain_counts[captain].append(channel)

        for player in insight["transfers_in"]:
            transfer_in_counts.setdefault(player, [])
            if channel not in transfer_in_counts[player]:
                transfer_in_counts[player].append(channel)

        for player in insight["transfers_out"]:
            transfer_out_counts.setdefault(player, [])
            if channel not in transfer_out_counts[player]:
                transfer_out_counts[player].append(channel)

        for player in insight["injuries"]:
            injury_mentions.setdefault(player, [])
            if channel not in injury_mentions[player]:
                injury_mentions[player].append(channel)

        for chip_info in insight["chip_advice"]:
            key = f"{chip_info['chip']}_gw{chip_info['gameweek']}"
            chip_counts.setdefault(key, [])
            if channel not in [c for c in chip_counts[key]]:
                chip_counts[key].append({"channel": channel, **chip_info})

    total_channels = len({i["channel"] for i in insights})

    # Build captain consensus
    captain_picks = sorted(
        [
            {
                "player": player,
                "mentioned_by": channels,
                "count": len(channels),
                "consensus_pct": round(len(channels) / max(1, total_channels) * 100),
            }
            for player, channels in captain_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    # Agreement level
    if captain_picks:
        top_pct = captain_picks[0]["consensus_pct"]
        agreement = "strong" if top_pct >= 60 else "moderate" if top_pct >= 40 else "split"
    else:
        agreement = "no_data"

    # Build transfer consensus
    transfers_in = sorted(
        [
            {"player": player, "mentioned_by": channels, "count": len(channels)}
            for player, channels in transfer_in_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    transfers_out = sorted(
        [
            {"player": player, "mentioned_by": channels, "count": len(channels)}
            for player, channels in transfer_out_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    # Build chip consensus
    chip_advice = []
    for key, entries in chip_counts.items():
        chip_advice.append({
            "chip": entries[0]["chip"],
            "suggested_gw": entries[0]["gameweek"],
            "mentioned_by": [e["channel"] for e in entries],
            "count": len(entries),
        })
    chip_advice.sort(key=lambda x: x["count"], reverse=True)

    # Build injury flags
    injury_flags = sorted(
        [
            {"player": player, "mentioned_by": channels, "count": len(channels)}
            for player, channels in injury_mentions.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    return {
        "captain_consensus": {
            "top_picks": captain_picks[:10],
            "agreement_level": agreement,
        },
        "transfer_targets_in": transfers_in,
        "transfer_targets_out": transfers_out,
        "chip_advice": chip_advice,
        "injury_flags": injury_flags,
    }
