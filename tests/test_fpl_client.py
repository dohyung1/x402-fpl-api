"""Tests for app/fpl_client.py — gameweek detection, manager status, caching, retry."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app import fpl_client
from app.fpl_client import (
    _cache,
    _fetch,
    get_current_gameweek,
    get_manager_status,
    get_next_gameweek,
)

# ---------------------------------------------------------------------------
# Helpers — realistic mock data
# ---------------------------------------------------------------------------


def _make_events(current_id=None, next_id=None, finished_ids=None):
    """Build a minimal bootstrap 'events' list."""
    finished_ids = finished_ids or []
    events = []
    for gw in range(1, 39):
        events.append(
            {
                "id": gw,
                "is_current": gw == current_id,
                "is_next": gw == next_id,
                "finished": gw in finished_ids,
            }
        )
    return events


def _bootstrap(current_id=None, next_id=None, finished_ids=None):
    return {"events": _make_events(current_id, next_id, finished_ids)}


# ---------------------------------------------------------------------------
# get_current_gameweek
# ---------------------------------------------------------------------------


class TestGetCurrentGameweek:
    def test_returns_current_when_set(self):
        bs = _bootstrap(current_id=15)
        assert get_current_gameweek(bs) == 15

    def test_falls_back_to_next_when_no_current(self):
        bs = _bootstrap(next_id=20)
        assert get_current_gameweek(bs) == 20

    def test_falls_back_to_last_finished(self):
        bs = _bootstrap(finished_ids=[1, 2, 3, 4, 5])
        assert get_current_gameweek(bs) == 5

    def test_returns_1_when_nothing_matches(self):
        bs = _bootstrap()
        assert get_current_gameweek(bs) == 1


# ---------------------------------------------------------------------------
# get_next_gameweek
# ---------------------------------------------------------------------------


class TestGetNextGameweek:
    def test_returns_next_when_set(self):
        bs = _bootstrap(current_id=10, next_id=11)
        assert get_next_gameweek(bs) == 11

    def test_falls_back_to_current(self):
        bs = _bootstrap(current_id=38)
        assert get_next_gameweek(bs) == 38


# ---------------------------------------------------------------------------
# get_manager_status — chip reset logic
# ---------------------------------------------------------------------------


def _picks_data(event_transfers=1, bank=50, overall_rank=10_000, total_points=1500):
    return {
        "entry_history": {
            "bank": bank,
            "event_transfers": event_transfers,
            "overall_rank": overall_rank,
            "total_points": total_points,
            "points_on_bench": 4,
        }
    }


class TestManagerStatus:
    """Test chip reset logic and free-transfer calculation."""

    @pytest.fixture(autouse=True)
    def _patch_fetches(self):
        """Patch network calls used by get_manager_status."""
        self.picks_data = _picks_data()
        self.history_data = {"chips": []}

        with (
            patch("app.fpl_client.get_team_picks", new_callable=AsyncMock) as mock_picks,
            patch("app.fpl_client.get_team_history", new_callable=AsyncMock) as mock_hist,
        ):
            mock_picks.return_value = self.picks_data
            mock_hist.return_value = self.history_data
            self.mock_picks = mock_picks
            self.mock_hist = mock_hist
            yield

    # -- Chip reset: second half (GW25) ---------------------------------

    async def test_second_half_ignores_first_half_chips(self):
        """GW25: chip used in GW5 should NOT count as used this half."""
        bs = _bootstrap(current_id=25, next_id=26)
        self.history_data["chips"] = [
            {"name": "wildcard", "event": 5},
            {"name": "bboost", "event": 5},
        ]
        result = await get_manager_status(12345, bs)
        # All four chips should be remaining (GW5 is first half, ignored)
        assert sorted(result["chips_remaining"]) == ["3xc", "bboost", "freehit", "wildcard"]

    async def test_second_half_counts_second_half_chips(self):
        """GW25: chip used in GW22 SHOULD count as used this half."""
        bs = _bootstrap(current_id=25, next_id=26)
        self.history_data["chips"] = [
            {"name": "wildcard", "event": 22},
            {"name": "3xc", "event": 24},
        ]
        result = await get_manager_status(12345, bs)
        assert "wildcard" not in result["chips_remaining"]
        assert "3xc" not in result["chips_remaining"]
        assert "bboost" in result["chips_remaining"]
        assert "freehit" in result["chips_remaining"]

    # -- Chip reset: first half (GW15) ----------------------------------

    async def test_first_half_counts_first_half_chips(self):
        """GW15: chip used in GW10 SHOULD count as used."""
        bs = _bootstrap(current_id=15, next_id=16)
        self.history_data["chips"] = [
            {"name": "wildcard", "event": 10},
        ]
        result = await get_manager_status(12345, bs)
        assert "wildcard" not in result["chips_remaining"]

    async def test_first_half_ignores_second_half_chips(self):
        """GW15: chip used in GW25 should NOT count (hasn't happened yet in this half)."""
        bs = _bootstrap(current_id=15, next_id=16)
        self.history_data["chips"] = [
            {"name": "freehit", "event": 25},
        ]
        result = await get_manager_status(12345, bs)
        assert "freehit" in result["chips_remaining"]

    # -- Free transfer calculation --------------------------------------

    async def test_zero_transfers_rolls_over(self):
        """0 transfers made this GW -> free_transfers = 2 (rolled over)."""
        bs = _bootstrap(current_id=20, next_id=21)
        self.mock_picks.return_value = _picks_data(event_transfers=0)
        result = await get_manager_status(12345, bs)
        assert result["free_transfers"] == 2

    async def test_nonzero_transfers_gives_one(self):
        """1+ transfers made this GW -> free_transfers = 1."""
        bs = _bootstrap(current_id=20, next_id=21)
        self.mock_picks.return_value = _picks_data(event_transfers=2)
        result = await get_manager_status(12345, bs)
        assert result["free_transfers"] == 1

    async def test_wildcard_resets_to_one(self):
        """Wildcard this GW -> free_transfers reset to 1."""
        bs = _bootstrap(current_id=20, next_id=21)
        self.mock_picks.return_value = _picks_data(event_transfers=0)
        self.history_data["chips"] = [{"name": "wildcard", "event": 20}]
        result = await get_manager_status(12345, bs)
        assert result["free_transfers"] == 1

    async def test_freehit_resets_to_one(self):
        """Free hit this GW -> free_transfers reset to 1."""
        bs = _bootstrap(current_id=20, next_id=21)
        self.mock_picks.return_value = _picks_data(event_transfers=0)
        self.history_data["chips"] = [{"name": "freehit", "event": 20}]
        result = await get_manager_status(12345, bs)
        assert result["free_transfers"] == 1

    async def test_bank_converted_to_millions(self):
        """Bank value should be divided by 10 to get millions."""
        bs = _bootstrap(current_id=20, next_id=21)
        self.mock_picks.return_value = _picks_data(bank=53)
        result = await get_manager_status(12345, bs)
        assert result["bank"] == 5.3


# ---------------------------------------------------------------------------
# _fetch — caching
# ---------------------------------------------------------------------------


class TestFetchCaching:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _cache.clear()
        yield
        _cache.clear()

    async def test_cache_hit(self):
        """Second call within TTL should return cached data without HTTP call."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result1 = await _fetch("/bootstrap-static/", ttl=300)
            result2 = await _fetch("/bootstrap-static/", ttl=300)

            assert result1 == {"ok": True}
            assert result2 == {"ok": True}
            # Only one actual HTTP call
            assert instance.get.call_count == 1

    async def test_cache_miss_after_expiry(self):
        """Call after TTL expiry should make a fresh HTTP request."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            # Insert expired entry directly
            url = f"{fpl_client.settings.fpl_base_url}/bootstrap-static/"
            _cache[url] = ({"old": True}, time.monotonic() - 10)

            result = await _fetch("/bootstrap-static/", ttl=300)
            assert result == {"ok": True}
            assert instance.get.call_count == 1

    async def test_ttl_zero_bypasses_cache(self):
        """ttl=0 should always fetch fresh data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"fresh": True}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            # Pre-populate cache
            url = f"{fpl_client.settings.fpl_base_url}/bootstrap-static/"
            _cache[url] = ({"stale": True}, time.monotonic() + 9999)

            result = await _fetch("/bootstrap-static/", ttl=0)
            assert result == {"fresh": True}
            assert instance.get.call_count == 1


# ---------------------------------------------------------------------------
# _fetch — retry logic
# ---------------------------------------------------------------------------


class TestFetchRetry:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _cache.clear()
        yield
        _cache.clear()

    async def test_retries_on_failure_then_succeeds(self):
        """Should retry after a transient error and succeed on the next attempt."""
        ok_response = MagicMock()
        ok_response.json.return_value = {"recovered": True}
        ok_response.raise_for_status = MagicMock()

        call_count = 0

        async def mock_get(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("connection refused")
            return ok_response

        with patch("httpx.AsyncClient") as MockClient, patch("asyncio.sleep", new_callable=AsyncMock):
            instance = AsyncMock()
            instance.get = mock_get
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await _fetch("/bootstrap-static/", ttl=0)
            assert result == {"recovered": True}
            assert call_count == 2

    async def test_raises_after_all_retries_exhausted(self):
        """Should raise after MAX_RETRIES+1 total attempts."""

        async def mock_get(url):
            raise httpx.ConnectError("connection refused")

        with patch("httpx.AsyncClient") as MockClient, patch("asyncio.sleep", new_callable=AsyncMock):
            instance = AsyncMock()
            instance.get = mock_get
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            with pytest.raises(httpx.ConnectError):
                await _fetch("/bootstrap-static/", ttl=0)
