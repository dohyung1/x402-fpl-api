"""
Tests for DGW/BGW prediction in chip strategy algorithm.

Covers:
- _get_unscheduled_fixtures() — detecting postponed fixtures (event=null)
- _predict_dgw_teams() — identifying teams with pending rescheduled matches
- _estimate_likely_dgw_gameweeks() — predicting which GWs will become DGWs
- _count_dgw_teams() — counting confirmed DGW teams (existing)
- _count_blanking_teams() — counting blank GW teams (existing)
"""

from app.algorithms.chips import (
    _count_blanking_teams,
    _count_dgw_teams,
    _estimate_likely_dgw_gameweeks,
    _get_unscheduled_fixtures,
    _predict_dgw_teams,
)


# --- Fixture factory helpers ---


def _fixture(event, team_h, team_a, finished=False, **kwargs):
    """Create a minimal fixture dict."""
    return {
        "id": kwargs.get("id", 1),
        "event": event,
        "team_h": team_h,
        "team_a": team_a,
        "team_h_difficulty": kwargs.get("team_h_difficulty", 3),
        "team_a_difficulty": kwargs.get("team_a_difficulty", 3),
        "finished": finished,
    }


class TestGetUnscheduledFixtures:
    def test_no_unscheduled(self):
        fixtures = [_fixture(30, 1, 2), _fixture(31, 3, 4)]
        assert _get_unscheduled_fixtures(fixtures) == []

    def test_finds_null_event_fixtures(self):
        fixtures = [
            _fixture(30, 1, 2),
            _fixture(None, 5, 6, id=99),
            _fixture(31, 3, 4),
        ]
        result = _get_unscheduled_fixtures(fixtures)
        assert len(result) == 1
        assert result[0]["team_h"] == 5
        assert result[0]["team_a"] == 6

    def test_ignores_finished_null_fixtures(self):
        """Finished fixtures with null event should be excluded."""
        fixtures = [
            _fixture(None, 5, 6, finished=True),
            _fixture(None, 7, 8, finished=False),
        ]
        result = _get_unscheduled_fixtures(fixtures)
        assert len(result) == 1
        assert result[0]["team_h"] == 7

    def test_multiple_unscheduled(self):
        fixtures = [
            _fixture(None, 1, 2, id=10),
            _fixture(None, 3, 4, id=11),
            _fixture(None, 5, 6, id=12),
        ]
        result = _get_unscheduled_fixtures(fixtures)
        assert len(result) == 3


class TestPredictDgwTeams:
    def test_no_pending(self):
        fixtures = [_fixture(30, 1, 2), _fixture(31, 3, 4)]
        assert _predict_dgw_teams(fixtures) == {}

    def test_single_postponed_fixture(self):
        fixtures = [_fixture(None, 5, 10)]
        result = _predict_dgw_teams(fixtures)
        assert 5 in result
        assert 10 in result
        assert len(result[5]) == 1
        assert result[5][0]["opponent"] == 10
        assert result[5][0]["is_home"] is True
        assert len(result[10]) == 1
        assert result[10][0]["opponent"] == 5
        assert result[10][0]["is_home"] is False

    def test_team_with_multiple_postponed(self):
        """A team with two postponed fixtures should have both listed."""
        fixtures = [
            _fixture(None, 5, 10, id=1),
            _fixture(None, 5, 12, id=2),
        ]
        result = _predict_dgw_teams(fixtures)
        assert len(result[5]) == 2
        assert len(result[10]) == 1
        assert len(result[12]) == 1

    def test_ignores_scheduled_fixtures(self):
        fixtures = [_fixture(30, 1, 2), _fixture(None, 5, 6)]
        result = _predict_dgw_teams(fixtures)
        assert 1 not in result
        assert 2 not in result
        assert 5 in result


class TestEstimateLikelyDgwGameweeks:
    def test_no_pending_returns_empty(self):
        fixtures = [_fixture(33, 1, 2), _fixture(34, 3, 4)]
        result = _estimate_likely_dgw_gameweeks(fixtures, 33, [33, 34, 35])
        assert result == {}

    def test_team_with_one_fixture_eligible_for_dgw(self):
        """Team 5 has a scheduled GW33 match + an unscheduled match → GW33 is a likely DGW."""
        fixtures = [
            _fixture(33, 5, 2),  # Team 5 plays GW33
            _fixture(None, 5, 10),  # Team 5 has postponed fixture
        ]
        result = _estimate_likely_dgw_gameweeks(fixtures, 33, [33, 34, 35])
        assert 33 in result
        assert 5 in result[33]

    def test_team_with_no_fixture_not_eligible(self):
        """Team 5 has no fixture in GW34 (0 matches), so it has room but isn't counted
        because they need an existing fixture to create a 'double'."""
        fixtures = [
            _fixture(33, 5, 2),  # Team 5 plays GW33 only
            _fixture(None, 5, 10),  # postponed
        ]
        result = _estimate_likely_dgw_gameweeks(fixtures, 33, [33, 34])
        # GW33: team 5 has 1 fixture → eligible
        assert 33 in result
        assert 5 in result[33]
        # GW34: team 5 has 0 fixtures → not counted (needs exactly 1)
        assert 34 not in result or 5 not in result.get(34, [])

    def test_team_already_has_dgw_not_eligible(self):
        """Team with 2 fixtures already (confirmed DGW) shouldn't be predicted again."""
        fixtures = [
            _fixture(33, 5, 2),
            _fixture(33, 5, 8),  # Already a DGW
            _fixture(None, 5, 10),  # Also has postponed
        ]
        result = _estimate_likely_dgw_gameweeks(fixtures, 33, [33, 34])
        # GW33: team 5 already has 2 fixtures → not in predicted (already confirmed)
        assert 5 not in result.get(33, [])

    def test_multiple_teams_multiple_gws(self):
        """Multiple teams with postponed fixtures across multiple GWs."""
        fixtures = [
            _fixture(33, 5, 2),   # Team 5 in GW33
            _fixture(34, 10, 3),  # Team 10 in GW34
            _fixture(None, 5, 7),  # Team 5 postponed
            _fixture(None, 10, 8),  # Team 10 postponed
        ]
        result = _estimate_likely_dgw_gameweeks(fixtures, 33, [33, 34, 35])
        assert 5 in result.get(33, [])
        assert 10 in result.get(34, [])


class TestCountDgwTeams:
    def test_no_dgw(self):
        fixtures = [_fixture(30, 1, 2), _fixture(30, 3, 4)]
        assert _count_dgw_teams(fixtures, 30) == 0

    def test_one_team_dgw(self):
        fixtures = [_fixture(30, 1, 2), _fixture(30, 1, 3)]
        assert _count_dgw_teams(fixtures, 30) == 1  # team 1

    def test_both_teams_dgw(self):
        """Two fixtures with same home/away create DGW for home team."""
        fixtures = [_fixture(30, 1, 2), _fixture(30, 1, 3), _fixture(30, 4, 2)]
        # Team 1: 2 home matches (DGW), Team 2: 2 away matches (DGW)
        assert _count_dgw_teams(fixtures, 30) == 2

    def test_wrong_gameweek(self):
        fixtures = [_fixture(30, 1, 2), _fixture(31, 1, 3)]
        assert _count_dgw_teams(fixtures, 30) == 0


class TestCountBlankingTeams:
    def test_all_teams_play(self):
        all_teams = {1, 2, 3, 4}
        fixtures = [_fixture(30, 1, 2), _fixture(30, 3, 4)]
        assert _count_blanking_teams(fixtures, 30, all_teams) == 0

    def test_some_teams_blank(self):
        all_teams = {1, 2, 3, 4, 5, 6}
        fixtures = [_fixture(30, 1, 2), _fixture(30, 3, 4)]
        assert _count_blanking_teams(fixtures, 30, all_teams) == 2  # teams 5, 6

    def test_all_teams_blank(self):
        all_teams = {1, 2}
        fixtures = [_fixture(31, 1, 2)]  # wrong GW
        assert _count_blanking_teams(fixtures, 30, all_teams) == 2
