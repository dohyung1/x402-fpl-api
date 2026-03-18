"""
Player news and injury information utilities.

Parses the free-text `news` and `news_added` fields from the FPL bootstrap-static
API to surface injury details, return dates, and staleness in algorithm outputs.

The `news` field is free text like "Hamstring - Expected back 15 Mar" or
"Suspended for 3 matches". The `news_added` field is an ISO timestamp.
"""

from datetime import datetime, timezone

# Keywords in news text that indicate a player should be penalised for transfers.
# These go beyond what chance_of_playing_next_round captures — e.g., a player
# might be 75% to play but news says "Unknown return date", which is worse.
NEGATIVE_NEWS_KEYWORDS = [
    "unknown return",
    "expected back",
    "suspended",
    "international duty",
    "illness",
    "knock",
    "hamstring",
    "ankle",
    "knee",
    "thigh",
    "groin",
    "calf",
    "muscle",
    "ligament",
    "fracture",
    "concussion",
    "surgery",
    "operation",
    "personal reasons",
    "not in squad",
    "self-isolating",
    "match fitness",
]


def format_news_age(news_added: str | None) -> str | None:
    """
    Convert a news_added ISO timestamp to a human-readable age string.

    Returns None if news_added is missing or unparseable.

    Examples:
        "2026-03-17T10:00:00Z" (today) -> "just now"
        "2026-03-15T10:00:00Z" (2 days ago) -> "2 days ago"
        "2026-03-10T10:00:00Z" (7 days ago) -> "7 days ago"
    """
    if not news_added:
        return None
    try:
        # FPL timestamps are ISO format, sometimes with or without timezone
        ts = news_added.replace("Z", "+00:00")
        added = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc)
        # Make added timezone-aware if it isn't
        if added.tzinfo is None:
            added = added.replace(tzinfo=timezone.utc)
        delta = now - added
        days = delta.days
        hours = delta.seconds // 3600

        if days == 0:
            if hours == 0:
                return "just now"
            elif hours == 1:
                return "1 hour ago"
            else:
                return f"{hours} hours ago"
        elif days == 1:
            return "1 day ago"
        elif days < 30:
            return f"{days} days ago"
        elif days < 60:
            return "1 month ago"
        else:
            return f"{days // 30} months ago"
    except (ValueError, TypeError):
        return None


def get_player_news(player: dict) -> dict | None:
    """
    Extract news information from a player dict.

    Returns a dict with news text and age, or None if no news.
    """
    news = player.get("news")
    if not news or not news.strip():
        return None
    news_added = player.get("news_added")
    age = format_news_age(news_added)
    result = {"text": news.strip()}
    if age:
        result["updated"] = age
    return result


def has_negative_news(player: dict) -> bool:
    """
    Check if a player's news text contains keywords indicating they're
    injured, suspended, or otherwise unavailable.

    This is a supplement to chance_of_playing_next_round — some players
    have concerning news but still show 75% or even 100% chance.
    """
    news = player.get("news", "")
    if not news:
        return False
    news_lower = news.lower()
    return any(keyword in news_lower for keyword in NEGATIVE_NEWS_KEYWORDS)


def news_penalty_score(player: dict) -> float:
    """
    Return an additional transfer penalty based on news keywords.

    This supplements the existing chance_of_playing penalty. It catches cases
    where a player has bad news but chance_of_playing hasn't been updated yet,
    or where the news indicates long-term absence.

    Returns:
        -3.0 for "unknown return" (worst — no timeline)
        -2.0 for other negative news keywords
        0.0 if no concerning news
    """
    news = player.get("news", "")
    if not news:
        return 0.0
    news_lower = news.lower()

    if "unknown return" in news_lower:
        return -3.0
    if any(keyword in news_lower for keyword in NEGATIVE_NEWS_KEYWORDS):
        return -2.0
    return 0.0


def format_news_for_reasoning(player: dict) -> str | None:
    """
    Format a player's news for inclusion in reasoning text.

    Returns a string like 'Hamstring - Expected back 15 Mar (2 days ago)'
    or None if no news.
    """
    info = get_player_news(player)
    if not info:
        return None
    text = info["text"]
    if "updated" in info:
        return f"{text} ({info['updated']})"
    return text
