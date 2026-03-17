"""
Daily stats snapshot — tracks PyPI downloads and GitHub metrics over time.

Appends one row per run to data/stats.csv with:
- Date, PyPI total downloads, GitHub stars, GitHub forks, GitHub open issues

Usage:
  uv run python scripts/stats_snapshot.py

Output: data/stats.csv (gitignored — local only)
"""

import csv
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "dohyung1/x402-fpl-api"
PACKAGE = "fpl-intelligence"
STATS_FILE = Path(__file__).parent.parent / "data" / "stats.csv"


def fetch_json(url: str, headers: dict | None = None) -> dict:
    """Fetch JSON from a URL."""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_pypi_downloads() -> int:
    """Get total PyPI downloads from pypistats API."""
    try:
        data = fetch_json(f"https://pypistats.org/api/packages/{PACKAGE}/overall")
        # Sum all downloads across all categories
        total = sum(row.get("downloads", 0) for row in data.get("data", []) if row.get("category") == "without_mirrors")
        return total
    except Exception as e:
        print(f"  PyPI stats unavailable: {e}")
        return -1


def get_github_stats() -> dict:
    """Get GitHub repo stats (stars, forks, open issues)."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    # Use token if available for higher rate limits
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        data = fetch_json(f"https://api.github.com/repos/{REPO}", headers)
        return {
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "watchers": data.get("subscribers_count", 0),
        }
    except Exception as e:
        print(f"  GitHub stats unavailable: {e}")
        return {"stars": -1, "forks": -1, "open_issues": -1, "watchers": -1}


def main():
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"Fetching stats for {PACKAGE} / {REPO}...")
    pypi_downloads = get_pypi_downloads()
    gh = get_github_stats()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    row = {
        "date": now,
        "pypi_downloads": pypi_downloads,
        "github_stars": gh["stars"],
        "github_forks": gh["forks"],
        "github_open_issues": gh["open_issues"],
        "github_watchers": gh["watchers"],
    }

    file_exists = STATS_FILE.exists()
    with open(STATS_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    print(f"  Date:           {now}")
    print(f"  PyPI downloads: {pypi_downloads}")
    print(f"  GitHub stars:   {gh['stars']}")
    print(f"  GitHub forks:   {gh['forks']}")
    print(f"  Open issues:    {gh['open_issues']}")
    print(f"  Watchers:       {gh['watchers']}")
    print(f"  Saved to:       {STATS_FILE}")


if __name__ == "__main__":
    main()
