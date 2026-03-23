"""
Tests for the FPL live points algorithm with BPS bonus tracker.

Tests cover:
- _calculate_fixture_bps() — BPS ranking and bonus assignment per fixture
- _calculate_fixture_bps() with ties — FPL's tie-sharing rules
- _bonus_narrative() — human-readable bonus status messages
- build_bps_data() — multi-fixture BPS aggregation
- get_live_points() — end-to-end with mocked FPL API data
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.algorithms.live import (
    _bonus_narrative,
    _calculate_fixture_bps,
    build_bps_data,
    get_live_points,
)

# ---------------------------------------------------------------------------
# Helpers to build realistic mock data
# ---------------------------------------------------------------------------


def _make_player(id=1, web_name="Salah", team=14, element_type=3, **overrides):
    """Create a minimal FPL player dict for testing."""
    player = {
        "id": id,
        "web_name": web_name,
        "team": team,
        "element_type": element_type,
        "chance_of_playing_this_round": None,
    }
    player.update(overrides)
    return player


def _make_live_element(id=1, total_points=6, bps=30, minutes=90, bonus=0):
    """Create a live element dict as returned by /event/{gw}/live/."""
    return {
        "id": id,
        "stats": {
            "total_points": total_points,
            "bps": bps,
            "minutes": minutes,
            "bonus": bonus,
        },
    }


def _make_fixture(
    id=1,
    event=30,
    team_h=14,
    team_a=20,
    started=True,
    finished=False,
    finished_provisional=False,
):
    """Create a fixture dict."""
    return {
        "id": id,
        "event": event,
        "team_h": team_h,
        "team_a": team_a,
        "started": started,
        "finished": finished,
        "finished_provisional": finished_provisional,
    }


TEAMS = {
    14: {"id": 14, "short_name": "LIV", "name": "Liverpool"},
    20: {"id": 20, "short_name": "WOL", "name": "Wolverhampton Wanderers"},
    1: {"id": 1, "short_name": "ARS", "name": "Arsenal"},
    6: {"id": 6, "short_name": "CHE", "name": "Chelsea"},
}


# ---------------------------------------------------------------------------
# Tests for _calculate_fixture_bps
# ---------------------------------------------------------------------------


class TestCalculateFixtureBps:
    """Test BPS calculation and bonus assignment for a single fixture."""

    def test_standard_top_3(self):
        """Top 3 unique BPS scores get 3, 2, 1 bonus."""
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
            12: _make_player(id=12, web_name="VanDijk", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
            21: _make_player(id=21, web_name="Hwang", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=40, minutes=90),
            11: _make_live_element(id=11, bps=30, minutes=90),
            12: _make_live_element(id=12, bps=25, minutes=90),
            20: _make_live_element(id=20, bps=20, minutes=90),
            21: _make_live_element(id=21, bps=10, minutes=90),
        }

        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids={10, 11, 12, 20, 21},
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        pb = result["player_bonus"]
        assert pb[10]["projected_bonus"] == 3
        assert pb[11]["projected_bonus"] == 2
        assert pb[12]["projected_bonus"] == 1
        assert pb[20]["projected_bonus"] == 0
        assert pb[21]["projected_bonus"] == 0

    def test_two_tied_at_top(self):
        """Two players tied at top BPS both get 3 bonus, next gets 1."""
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
            21: _make_player(id=21, web_name="Hwang", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=40, minutes=90),
            11: _make_live_element(id=11, bps=40, minutes=90),
            20: _make_live_element(id=20, bps=30, minutes=90),
            21: _make_live_element(id=21, bps=20, minutes=90),
        }

        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids={10, 11, 20, 21},
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        pb = result["player_bonus"]
        # Both tied at top get 3
        assert pb[10]["projected_bonus"] == 3
        assert pb[11]["projected_bonus"] == 3
        # Next player gets 1 (the "2" slot is consumed by the tie)
        assert pb[20]["projected_bonus"] == 1
        # Fourth player gets 0
        assert pb[21]["projected_bonus"] == 0

    def test_three_tied_at_top(self):
        """Three players tied at top BPS all get 3 bonus, nobody else gets bonus."""
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
            21: _make_player(id=21, web_name="Hwang", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=40, minutes=90),
            11: _make_live_element(id=11, bps=40, minutes=90),
            20: _make_live_element(id=20, bps=40, minutes=90),
            21: _make_live_element(id=21, bps=20, minutes=90),
        }

        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids={10, 11, 20, 21},
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        pb = result["player_bonus"]
        assert pb[10]["projected_bonus"] == 3
        assert pb[11]["projected_bonus"] == 3
        assert pb[20]["projected_bonus"] == 3
        # All 3 bonus slots consumed by the tie
        assert pb[21]["projected_bonus"] == 0

    def test_two_tied_at_second(self):
        """One player at top gets 3, two tied at second both get 2, no one gets 1."""
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
            21: _make_player(id=21, web_name="Hwang", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=50, minutes=90),
            11: _make_live_element(id=11, bps=40, minutes=90),
            20: _make_live_element(id=20, bps=40, minutes=90),
            21: _make_live_element(id=21, bps=20, minutes=90),
        }

        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids={10, 11, 20, 21},
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        pb = result["player_bonus"]
        assert pb[10]["projected_bonus"] == 3
        assert pb[11]["projected_bonus"] == 2
        assert pb[20]["projected_bonus"] == 2
        # The "1" slot is consumed by the tie at second
        assert pb[21]["projected_bonus"] == 0

    def test_two_tied_at_third(self):
        """Top gets 3, second gets 2, two tied at third both get 1."""
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
            21: _make_player(id=21, web_name="Hwang", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=50, minutes=90),
            11: _make_live_element(id=11, bps=40, minutes=90),
            20: _make_live_element(id=20, bps=30, minutes=90),
            21: _make_live_element(id=21, bps=30, minutes=90),
        }

        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids={10, 11, 20, 21},
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        pb = result["player_bonus"]
        assert pb[10]["projected_bonus"] == 3
        assert pb[11]["projected_bonus"] == 2
        assert pb[20]["projected_bonus"] == 1
        assert pb[21]["projected_bonus"] == 1

    def test_players_with_zero_minutes_excluded(self):
        """Players with 0 minutes should not appear in BPS rankings."""
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=40, minutes=90),
            11: _make_live_element(id=11, bps=30, minutes=0),  # not played
        }

        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids={10, 11},
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        assert 11 not in result["player_bonus"]
        assert len(result["rankings"]) == 1

    def test_bps_rank_assigned(self):
        """Each player gets a rank based on BPS position."""
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=40, minutes=90),
            11: _make_live_element(id=11, bps=30, minutes=90),
            20: _make_live_element(id=20, bps=20, minutes=90),
        }

        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids={10, 11, 20},
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        pb = result["player_bonus"]
        assert pb[10]["bps_rank"] == 1
        assert pb[11]["bps_rank"] == 2
        assert pb[20]["bps_rank"] == 3

    def test_empty_fixture(self):
        """A fixture with no players returns empty results."""
        result = _calculate_fixture_bps(
            fixture_id=1,
            fixture_player_ids=set(),
            live_elements={},
            players_by_id={},
            teams=TEAMS,
        )

        assert result["rankings"] == []
        assert result["player_bonus"] == {}


# ---------------------------------------------------------------------------
# Tests for _bonus_narrative
# ---------------------------------------------------------------------------


class TestBonusNarrative:
    def test_on_track_for_bonus(self):
        info = {"bps": 40, "projected_bonus": 3, "bps_rank": 1, "bps_behind_bonus": 0}
        assert "On track for 3 bonus" in _bonus_narrative(info)

    def test_behind_bonus(self):
        info = {"bps": 25, "projected_bonus": 0, "bps_rank": 5, "bps_behind_bonus": 5}
        assert "5 BPS behind bonus" in _bonus_narrative(info)

    def test_no_data(self):
        assert "No BPS data" in _bonus_narrative(None)

    def test_not_in_contention(self):
        info = {"bps": 5, "projected_bonus": 0, "bps_rank": 10, "bps_behind_bonus": 0}
        assert "Not in bonus contention" in _bonus_narrative(info)


# ---------------------------------------------------------------------------
# Tests for build_bps_data
# ---------------------------------------------------------------------------


class TestBuildBpsData:
    def test_not_started_fixture(self):
        """Fixtures that haven't started should have status 'not_started'."""
        fixtures = [_make_fixture(id=1, event=30, team_h=14, team_a=20, started=False)]
        match_bps, all_bonus = build_bps_data(
            fixtures=fixtures,
            current_gw=30,
            live_elements={},
            players_by_id={},
            teams=TEAMS,
        )
        assert len(match_bps) == 1
        assert match_bps[0]["status"] == "not_started"
        assert match_bps[0]["top_bps"] == []

    def test_live_fixture_with_players(self):
        """A live fixture should have BPS rankings."""
        fixtures = [_make_fixture(id=1, event=30, team_h=14, team_a=20, started=True)]
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=40, minutes=90),
            20: _make_live_element(id=20, bps=30, minutes=90),
        }

        match_bps, all_bonus = build_bps_data(
            fixtures=fixtures,
            current_gw=30,
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        assert len(match_bps) == 1
        assert match_bps[0]["status"] == "live"
        assert match_bps[0]["match"] == "LIV vs WOL"
        assert len(match_bps[0]["top_bps"]) == 2
        assert all_bonus[10]["projected_bonus"] == 3
        assert all_bonus[20]["projected_bonus"] == 2

    def test_finished_fixture_status(self):
        """A finished fixture should have status 'finished'."""
        fixtures = [_make_fixture(id=1, event=30, started=True, finished=True)]
        match_bps, _ = build_bps_data(
            fixtures=fixtures,
            current_gw=30,
            live_elements={},
            players_by_id={},
            teams=TEAMS,
        )
        assert match_bps[0]["status"] == "finished"

    def test_multiple_fixtures(self):
        """Multiple fixtures in the same GW should all be tracked."""
        fixtures = [
            _make_fixture(id=1, event=30, team_h=14, team_a=20, started=True),
            _make_fixture(id=2, event=30, team_h=1, team_a=6, started=True),
        ]
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
            30: _make_player(id=30, web_name="Saka", team=1),
            40: _make_player(id=40, web_name="Palmer", team=6),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=50, minutes=90),
            20: _make_live_element(id=20, bps=30, minutes=90),
            30: _make_live_element(id=30, bps=45, minutes=90),
            40: _make_live_element(id=40, bps=35, minutes=90),
        }

        match_bps, all_bonus = build_bps_data(
            fixtures=fixtures,
            current_gw=30,
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        assert len(match_bps) == 2
        # Salah top in fixture 1
        assert all_bonus[10]["projected_bonus"] == 3
        assert all_bonus[10]["match"] == "LIV vs WOL"
        # Saka top in fixture 2
        assert all_bonus[30]["projected_bonus"] == 3
        assert all_bonus[30]["match"] == "ARS vs CHE"

    def test_bps_behind_bonus_calculated(self):
        """Players not in bonus should have bps_behind_bonus set."""
        fixtures = [_make_fixture(id=1, event=30, team_h=14, team_a=20, started=True)]
        players_by_id = {
            10: _make_player(id=10, web_name="Salah", team=14),
            11: _make_player(id=11, web_name="Diaz", team=14),
            12: _make_player(id=12, web_name="VanDijk", team=14),
            20: _make_player(id=20, web_name="Cunha", team=20),
        }
        live_elements = {
            10: _make_live_element(id=10, bps=40, minutes=90),
            11: _make_live_element(id=11, bps=30, minutes=90),
            12: _make_live_element(id=12, bps=25, minutes=90),
            20: _make_live_element(id=20, bps=20, minutes=90),
        }

        _, all_bonus = build_bps_data(
            fixtures=fixtures,
            current_gw=30,
            live_elements=live_elements,
            players_by_id=players_by_id,
            teams=TEAMS,
        )

        # Cunha is 5 BPS behind VanDijk (who has 25, the last bonus holder)
        assert all_bonus[20]["bps_behind_bonus"] == 5
        # Bonus holders have 0
        assert all_bonus[10]["bps_behind_bonus"] == 0

    def test_ignores_other_gameweek_fixtures(self):
        """Fixtures from other gameweeks should be ignored."""
        fixtures = [
            _make_fixture(id=1, event=29, team_h=14, team_a=20, started=True),
            _make_fixture(id=2, event=30, team_h=1, team_a=6, started=True),
        ]
        match_bps, _ = build_bps_data(
            fixtures=fixtures,
            current_gw=30,
            live_elements={},
            players_by_id={},
            teams=TEAMS,
        )
        assert len(match_bps) == 1
        assert match_bps[0]["fixture_id"] == 2


# ---------------------------------------------------------------------------
# End-to-end test for get_live_points
# ---------------------------------------------------------------------------


class TestGetLivePoints:
    @pytest.mark.asyncio
    async def test_full_response_structure(self):
        """End-to-end test: verify response includes BPS data."""
        bootstrap = {
            "elements": [
                _make_player(id=10, web_name="Salah", team=14, element_type=3),
                _make_player(id=11, web_name="TAA", team=14, element_type=2),
                _make_player(id=20, web_name="Cunha", team=20, element_type=4),
                # Bench players
                _make_player(id=30, web_name="Raya", team=1, element_type=1),
                _make_player(id=31, web_name="Saka", team=1, element_type=3),
            ],
            "teams": [
                {"id": 14, "short_name": "LIV", "name": "Liverpool"},
                {"id": 20, "short_name": "WOL", "name": "Wolverhampton"},
                {"id": 1, "short_name": "ARS", "name": "Arsenal"},
            ],
            "events": [
                {
                    "id": 30,
                    "is_current": True,
                    "is_next": False,
                    "finished": False,
                    "average_entry_score": 45,
                    "highest_score": 100,
                    "top_element": 10,
                }
            ],
        }
        picks_data = {
            "picks": [
                {"element": 10, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
                {"element": 11, "position": 2, "multiplier": 1, "is_captain": False, "is_vice_captain": True},
                {"element": 20, "position": 3, "multiplier": 1, "is_captain": False, "is_vice_captain": False},
                # Bench
                {"element": 30, "position": 12, "multiplier": 0, "is_captain": False, "is_vice_captain": False},
                {"element": 31, "position": 13, "multiplier": 0, "is_captain": False, "is_vice_captain": False},
            ],
            "active_chip": None,
        }
        live_data = {
            "elements": [
                _make_live_element(id=10, total_points=8, bps=45, minutes=90, bonus=0),
                _make_live_element(id=11, total_points=6, bps=30, minutes=90, bonus=0),
                _make_live_element(id=20, total_points=5, bps=25, minutes=80, bonus=0),
                _make_live_element(id=30, total_points=3, bps=15, minutes=90, bonus=0),
                _make_live_element(id=31, total_points=4, bps=20, minutes=70, bonus=0),
            ]
        }
        fixtures = [
            _make_fixture(id=1, event=30, team_h=14, team_a=20, started=True),
            _make_fixture(id=2, event=30, team_h=1, team_a=6, started=True),
        ]
        event_status = {"status": [{"bonus_added": False, "date": "2026-03-23"}]}

        with (
            patch("app.algorithms.live.get_bootstrap", new_callable=AsyncMock, return_value=bootstrap),
            patch("app.algorithms.live.get_team_picks", new_callable=AsyncMock, return_value=picks_data),
            patch("app.algorithms.live.fpl_live", new_callable=AsyncMock, return_value=live_data),
            patch("app.algorithms.live.get_team_history", new_callable=AsyncMock, return_value={"current": []}),
            patch("app.algorithms.live.get_event_status", new_callable=AsyncMock, return_value=event_status),
            patch("app.algorithms.live.get_fixtures", new_callable=AsyncMock, return_value=fixtures),
        ):
            result = await get_live_points(team_id=12345)

        # Verify basic structure
        assert result["team_id"] == 12345
        assert result["gameweek"] == 30
        assert result["bonus_status"] == "provisional"

        # Verify match_bps is present
        assert "match_bps" in result
        assert len(result["match_bps"]) == 2

        # Verify starters have bonus_projection
        salah = result["starters"][0]
        assert salah["element_id"] == 10
        assert "bonus_projection" in salah
        assert salah["bonus_projection"]["bps"] == 45
        assert salah["bonus_projection"]["projected_bonus"] == 3
        assert salah["bonus_projection"]["bps_rank"] == 1
        assert "On track for 3 bonus" in salah["bonus_projection"]["narrative"]

        # Verify projected_bonus field is set
        assert salah["projected_bonus"] == 3

        # Verify TAA gets 2 bonus
        taa = result["starters"][1]
        assert taa["bonus_projection"]["projected_bonus"] == 2

        # Verify Cunha gets 1 bonus
        cunha = result["starters"][2]
        assert cunha["bonus_projection"]["projected_bonus"] == 1

        # Match BPS should show fixture details
        liv_wol = next(m for m in result["match_bps"] if m["match"] == "LIV vs WOL")
        assert liv_wol["status"] == "live"
        assert len(liv_wol["top_bps"]) == 3  # 3 players in that fixture

    @pytest.mark.asyncio
    async def test_confirmed_bonus(self):
        """When bonus is confirmed, status should reflect it."""
        bootstrap = {
            "elements": [_make_player(id=10, web_name="Salah", team=14)],
            "teams": [{"id": 14, "short_name": "LIV", "name": "Liverpool"}],
            "events": [{"id": 30, "is_current": True, "is_next": False, "finished": False, "average_entry_score": 45, "highest_score": 80, "top_element": 10}],
        }
        picks_data = {
            "picks": [{"element": 10, "position": 1, "multiplier": 1, "is_captain": False, "is_vice_captain": False}],
            "active_chip": None,
        }
        live_data = {"elements": [_make_live_element(id=10, total_points=8, bps=40, minutes=90)]}
        fixtures = [_make_fixture(id=1, event=30, team_h=14, team_a=20, started=True, finished=True)]
        event_status = {"status": [{"bonus_added": True, "date": "2026-03-23"}]}

        with (
            patch("app.algorithms.live.get_bootstrap", new_callable=AsyncMock, return_value=bootstrap),
            patch("app.algorithms.live.get_team_picks", new_callable=AsyncMock, return_value=picks_data),
            patch("app.algorithms.live.fpl_live", new_callable=AsyncMock, return_value=live_data),
            patch("app.algorithms.live.get_team_history", new_callable=AsyncMock, return_value={"current": []}),
            patch("app.algorithms.live.get_event_status", new_callable=AsyncMock, return_value=event_status),
            patch("app.algorithms.live.get_fixtures", new_callable=AsyncMock, return_value=fixtures),
        ):
            result = await get_live_points(team_id=12345)

        assert result["bonus_status"] == "confirmed"
