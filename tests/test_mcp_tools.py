"""
Unit tests for MCP server tool input validation.

Tests that bad inputs are caught and return isError *before* hitting any
algorithm code.  All algorithm imports are mocked so no FPL API calls are made.
"""

import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock every algorithm / client module so importing mcp_server never triggers
# real network calls or missing-dependency errors.
# ---------------------------------------------------------------------------
_ALGO_MODULES = [
    "app",
    "app.algorithms",
    "app.algorithms.captain",
    "app.algorithms.differentials",
    "app.algorithms.fixtures",
    "app.algorithms.prices",
    "app.algorithms.transfers",
    "app.algorithms.compare",
    "app.algorithms.live",
    "app.algorithms.hit_analyzer",
    "app.algorithms.chips",
    "app.algorithms.scout",
    "app.fpl_client",
    "app.models",
]

for mod in _ALGO_MODULES:
    sys.modules.setdefault(mod, MagicMock())

from mcp_server import (  # noqa: E402
    _error,
    _validate_gameweek,
    _validate_team_id,
    captain_pick,
    chip_strategy,
    differential_finder,
    fixture_outlook,
    fpl_manager_hub,
    is_hit_worth_it,
    live_points,
    player_comparison,
    squad_scout,
    transfer_suggestions,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _is_error(result: dict) -> bool:
    return result.get("isError") is True


# ── _error() ───────────────────────────────────────────────────────────────


class TestErrorHelper:
    def test_returns_is_error_flag(self):
        result = _error("something broke")
        assert result["isError"] is True

    def test_returns_message(self):
        result = _error("bad input")
        assert result["error"] == "bad input"

    def test_keys(self):
        result = _error("msg")
        assert set(result.keys()) == {"isError", "error"}


# ── _validate_team_id() ───────────────────────────────────────────────────


class TestValidateTeamId:
    @pytest.mark.parametrize("tid", [1, 100, 1_000_000, 20_000_000])
    def test_valid_ids(self, tid):
        assert _validate_team_id(tid) is None

    @pytest.mark.parametrize("tid", [0, -1, -999, 20_000_001, 99_999_999])
    def test_invalid_ids(self, tid):
        assert _validate_team_id(tid) is not None

    def test_non_int_float(self):
        assert _validate_team_id(1.5) is not None  # type: ignore[arg-type]

    def test_non_int_string(self):
        assert _validate_team_id("abc") is not None  # type: ignore[arg-type]

    def test_non_int_bool(self):
        # bool is a subclass of int in Python, but True == 1 so it passes
        # the isinstance check.  Document the behaviour either way.
        result = _validate_team_id(True)  # type: ignore[arg-type]
        # True is int(1) so it should be valid
        assert result is None


# ── _validate_gameweek() ──────────────────────────────────────────────────


class TestValidateGameweek:
    def test_none_is_valid(self):
        assert _validate_gameweek(None) is None

    @pytest.mark.parametrize("gw", [1, 19, 38])
    def test_valid_gameweeks(self, gw):
        assert _validate_gameweek(gw) is None

    @pytest.mark.parametrize("gw", [0, -1, 39, 100])
    def test_invalid_gameweeks(self, gw):
        assert _validate_gameweek(gw) is not None

    def test_non_int_string(self):
        assert _validate_gameweek("five") is not None  # type: ignore[arg-type]


# ── captain_pick ──────────────────────────────────────────────────────────


class TestCaptainPick:
    @pytest.mark.asyncio
    async def test_invalid_gameweek(self):
        result = await captain_pick(gameweek=99)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_zero_gameweek(self):
        result = await captain_pick(gameweek=0)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_negative_gameweek(self):
        result = await captain_pick(gameweek=-1)
        assert _is_error(result)


# ── differential_finder ───────────────────────────────────────────────────


class TestDifferentialFinder:
    @pytest.mark.asyncio
    async def test_negative_ownership(self):
        result = await differential_finder(max_ownership_pct=-5)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_zero_ownership(self):
        result = await differential_finder(max_ownership_pct=0.0)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_over_100_ownership(self):
        result = await differential_finder(max_ownership_pct=101)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_invalid_gameweek(self):
        result = await differential_finder(gameweek=39)
        assert _is_error(result)


# ── fixture_outlook ───────────────────────────────────────────────────────


class TestFixtureOutlook:
    @pytest.mark.asyncio
    async def test_invalid_position(self):
        result = await fixture_outlook(position="INVALID")
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_invalid_position_striker(self):
        # Common mistake — "STR" is not valid
        result = await fixture_outlook(position="STR")
        assert _is_error(result)


# ── player_comparison ─────────────────────────────────────────────────────


class TestPlayerComparison:
    @pytest.mark.asyncio
    async def test_too_few_players(self):
        result = await player_comparison(player_names=["only_one"])
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await player_comparison(player_names=[])
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_too_many_players(self):
        result = await player_comparison(player_names=["a", "b", "c", "d", "e"])
        assert _is_error(result)


# ── live_points ───────────────────────────────────────────────────────────


class TestLivePoints:
    @pytest.mark.asyncio
    async def test_negative_team_id(self):
        result = await live_points(team_id=-1)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_zero_team_id(self):
        result = await live_points(team_id=0)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_huge_team_id(self):
        result = await live_points(team_id=99_999_999)
        assert _is_error(result)


# ── is_hit_worth_it ───────────────────────────────────────────────────────


class TestIsHitWorthIt:
    @pytest.mark.asyncio
    async def test_same_player(self):
        result = await is_hit_worth_it(player_out_id=5, player_in_id=5)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_negative_player_out(self):
        result = await is_hit_worth_it(player_out_id=-1, player_in_id=10)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_negative_player_in(self):
        result = await is_hit_worth_it(player_out_id=10, player_in_id=-1)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_zero_player_id(self):
        result = await is_hit_worth_it(player_out_id=0, player_in_id=10)
        assert _is_error(result)


# ── fpl_manager_hub ───────────────────────────────────────────────────────


class TestFplManagerHub:
    @pytest.mark.asyncio
    async def test_zero_team_id(self):
        result = await fpl_manager_hub(team_id=0)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_negative_team_id(self):
        result = await fpl_manager_hub(team_id=-1)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_huge_team_id(self):
        result = await fpl_manager_hub(team_id=99_999_999)
        assert _is_error(result)


# ── chip_strategy ─────────────────────────────────────────────────────────


class TestChipStrategy:
    @pytest.mark.asyncio
    async def test_negative_team_id(self):
        result = await chip_strategy(team_id=-1)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_zero_team_id(self):
        result = await chip_strategy(team_id=0)
        assert _is_error(result)


# ── squad_scout ───────────────────────────────────────────────────────────


class TestSquadScout:
    @pytest.mark.asyncio
    async def test_zero_team_id(self):
        result = await squad_scout(team_id=0)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_negative_team_id(self):
        result = await squad_scout(team_id=-1)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_huge_team_id(self):
        result = await squad_scout(team_id=99_999_999)
        assert _is_error(result)


# ── transfer_suggestions ─────────────────────────────────────────────────


class TestTransferSuggestions:
    @pytest.mark.asyncio
    async def test_zero_team_id(self):
        result = await transfer_suggestions(team_id=0)
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_negative_team_id(self):
        result = await transfer_suggestions(team_id=-1)
        assert _is_error(result)
