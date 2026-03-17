"""
Comprehensive tests for the FPL captain pick algorithm.

Tests cover:
- _build_fixture_map() — fixture mapping including DGW and blank GW
- _score_player() — scoring with various player profiles
- _playing_chance_penalty() — injury/doubtful/suspended penalty logic
- get_captain_picks() — end-to-end with mocked FPL API data
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.algorithms.captain import (
    WEIGHTS,
    _build_fixture_map,
    _playing_chance_penalty,
    _score_player,
    get_captain_picks,
)

# ---------------------------------------------------------------------------
# Helpers to build realistic mock data
# ---------------------------------------------------------------------------


def _make_player(
    id=1,
    web_name="Salah",
    team=14,
    element_type=3,
    form="8.0",
    points_per_game="7.5",
    ict_index="200.0",
    minutes=2700,
    expected_goals="15.0",
    expected_assists="10.0",
    expected_goal_involvements="25.0",
    bonus=30,
    starts=28,
    now_cost=130,
    selected_by_percent="45.0",
    penalties_order=1,
    status="a",
    chance_of_playing_next_round=None,
    total_points=200,
    **overrides,
):
    """Create a realistic FPL player dict."""
    player = {
        "id": id,
        "web_name": web_name,
        "team": team,
        "element_type": element_type,
        "form": form,
        "points_per_game": points_per_game,
        "ict_index": ict_index,
        "minutes": minutes,
        "expected_goals": expected_goals,
        "expected_assists": expected_assists,
        "expected_goal_involvements": expected_goal_involvements,
        "bonus": bonus,
        "starts": starts,
        "now_cost": now_cost,
        "selected_by_percent": selected_by_percent,
        "penalties_order": penalties_order,
        "status": status,
        "chance_of_playing_next_round": chance_of_playing_next_round,
        "total_points": total_points,
    }
    player.update(overrides)
    return player


def _make_fixture(
    event=30,
    team_h=14,
    team_a=20,
    team_h_difficulty=2,
    team_a_difficulty=4,
):
    """Create a realistic FPL fixture dict."""
    return {
        "event": event,
        "team_h": team_h,
        "team_a": team_a,
        "team_h_difficulty": team_h_difficulty,
        "team_a_difficulty": team_a_difficulty,
    }


def _make_bootstrap(players=None, teams=None, events=None):
    """Create a realistic bootstrap-static response."""
    if teams is None:
        teams = [
            {"id": 1, "short_name": "ARS", "name": "Arsenal"},
            {"id": 7, "short_name": "EVE", "name": "Everton"},
            {"id": 14, "short_name": "LIV", "name": "Liverpool"},
            {"id": 15, "short_name": "MCI", "name": "Man City"},
            {"id": 20, "short_name": "TOT", "name": "Spurs"},
        ]
    if events is None:
        events = [
            {"id": 29, "is_current": True, "is_next": False, "finished": True},
            {"id": 30, "is_current": False, "is_next": True, "finished": False},
        ]
    if players is None:
        players = []
    return {"elements": players, "teams": teams, "events": events}


# ---------------------------------------------------------------------------
# Tests: _build_fixture_map
# ---------------------------------------------------------------------------


class TestBuildFixtureMap:
    """Tests for building the team -> fixtures mapping."""

    def test_single_fixture_per_team(self):
        """Standard GW: each team has exactly one fixture."""
        fixtures = [
            _make_fixture(event=30, team_h=14, team_a=20, team_h_difficulty=2, team_a_difficulty=4),
            _make_fixture(event=30, team_h=1, team_a=7, team_h_difficulty=2, team_a_difficulty=3),
        ]
        result = _build_fixture_map(fixtures, 30)

        # Liverpool (14) plays at home
        assert 14 in result
        assert len(result[14]) == 1
        assert result[14][0]["is_home"] is True
        assert result[14][0]["fdr"] == 2
        assert result[14][0]["opponent"] == 20

        # Spurs (20) plays away
        assert 20 in result
        assert len(result[20]) == 1
        assert result[20][0]["is_home"] is False
        assert result[20][0]["fdr"] == 4
        assert result[20][0]["opponent"] == 14

    def test_double_gameweek(self):
        """DGW: a team has two fixtures in the same gameweek."""
        fixtures = [
            _make_fixture(event=30, team_h=14, team_a=20, team_h_difficulty=2, team_a_difficulty=4),
            _make_fixture(event=30, team_h=14, team_a=7, team_h_difficulty=2, team_a_difficulty=3),
        ]
        result = _build_fixture_map(fixtures, 30)

        # Liverpool (14) has 2 home fixtures
        assert len(result[14]) == 2
        assert all(f["is_home"] for f in result[14])
        opponents = {f["opponent"] for f in result[14]}
        assert opponents == {20, 7}

    def test_blank_gameweek_missing_team(self):
        """BGW: a team not in any fixture for the GW is absent from the map."""
        fixtures = [
            _make_fixture(event=30, team_h=14, team_a=20),
        ]
        result = _build_fixture_map(fixtures, 30)

        # Arsenal (1) has no fixture in GW30
        assert 1 not in result

    def test_empty_fixtures_list(self):
        """No fixtures at all returns an empty map."""
        result = _build_fixture_map([], 30)
        assert result == {}

    def test_filters_by_gameweek(self):
        """Only fixtures matching the requested gameweek are included."""
        fixtures = [
            _make_fixture(event=29, team_h=14, team_a=20),
            _make_fixture(event=30, team_h=1, team_a=7),
            _make_fixture(event=31, team_h=14, team_a=7),
        ]
        result = _build_fixture_map(fixtures, 30)

        # Only GW30 fixture: Arsenal vs Everton
        assert 1 in result
        assert 7 in result
        assert 14 not in result
        assert 20 not in result


# ---------------------------------------------------------------------------
# Tests: _playing_chance_penalty
# ---------------------------------------------------------------------------


class TestPlayingChancePenalty:
    """Tests for the injury/availability penalty calculation."""

    def test_fit_player_no_flag(self):
        """Fit player (status='a', no chance flag) gets 0 penalty."""
        player = _make_player(status="a", chance_of_playing_next_round=None)
        assert _playing_chance_penalty(player) == 0.0

    def test_fit_player_100_percent(self):
        """Player with 100% chance gets 0 penalty."""
        player = _make_player(chance_of_playing_next_round=100)
        assert _playing_chance_penalty(player) == 0.0

    def test_injured_player_0_percent(self):
        """Injured player with 0% chance gets full penalty."""
        player = _make_player(status="i", chance_of_playing_next_round=0)
        assert _playing_chance_penalty(player) == WEIGHTS["playing_chance_max_penalty"]

    def test_doubtful_75_percent(self):
        """Doubtful player with 75% chance gets 25% of max penalty."""
        player = _make_player(status="d", chance_of_playing_next_round=75)
        expected = WEIGHTS["playing_chance_max_penalty"] * (1.0 - 75 / 100.0)
        assert _playing_chance_penalty(player) == pytest.approx(expected)

    def test_doubtful_50_percent(self):
        """Doubtful player with 50% chance gets 50% of max penalty."""
        player = _make_player(status="d", chance_of_playing_next_round=50)
        expected = WEIGHTS["playing_chance_max_penalty"] * 0.5
        assert _playing_chance_penalty(player) == pytest.approx(expected)

    def test_doubtful_25_percent(self):
        """Doubtful player with 25% chance gets 75% of max penalty."""
        player = _make_player(status="d", chance_of_playing_next_round=25)
        expected = WEIGHTS["playing_chance_max_penalty"] * 0.75
        assert _playing_chance_penalty(player) == pytest.approx(expected)

    def test_injured_no_chance_flag(self):
        """Injured status with no chance_of_playing flag -> full penalty."""
        player = _make_player(status="i", chance_of_playing_next_round=None)
        assert _playing_chance_penalty(player) == WEIGHTS["playing_chance_max_penalty"]

    def test_suspended_no_chance_flag(self):
        """Suspended status with no chance flag -> full penalty."""
        player = _make_player(status="s", chance_of_playing_next_round=None)
        assert _playing_chance_penalty(player) == WEIGHTS["playing_chance_max_penalty"]

    def test_unavailable_no_chance_flag(self):
        """Unavailable status with no chance flag -> full penalty."""
        player = _make_player(status="u", chance_of_playing_next_round=None)
        assert _playing_chance_penalty(player) == WEIGHTS["playing_chance_max_penalty"]


# ---------------------------------------------------------------------------
# Tests: _score_player
# ---------------------------------------------------------------------------


class TestScorePlayer:
    """Tests for the player scoring function."""

    def test_basic_scoring_home_fixture(self):
        """Player at home with easy fixture scores higher than baseline."""
        player = _make_player(
            form="6.0",
            points_per_game="5.0",
            ict_index="100.0",
            minutes=1800,
            expected_goals="8.0",
            expected_assists="5.0",
            bonus=15,
            starts=18,
            penalties_order=1,
        )
        fixtures = [{"fdr": 2, "is_home": True, "opponent": 20}]
        score = _score_player(player, fixtures)
        assert isinstance(score, float)
        # Home bonus + low FDR should give positive fixture contribution
        # home_bonus = 2.0, fdr_cost = 2 * 2.0 = 4.0 -> fixture_score = -2.0
        # Still, form + ppg + xG + penalty should make overall score positive
        assert score > 0

    def test_away_fixture_scores_lower_than_home(self):
        """Same player should score lower away than at home."""
        player = _make_player(form="6.0", points_per_game="5.0")
        home_fixtures = [{"fdr": 3, "is_home": True, "opponent": 20}]
        away_fixtures = [{"fdr": 3, "is_home": False, "opponent": 20}]

        home_score = _score_player(player, home_fixtures)
        away_score = _score_player(player, away_fixtures)
        assert home_score > away_score
        assert home_score - away_score == pytest.approx(WEIGHTS["home"])

    def test_zero_minutes_player(self):
        """Player with 0 minutes has no xG/xA per 90 contribution."""
        player = _make_player(
            minutes=0,
            expected_goals="0.0",
            expected_assists="0.0",
            bonus=0,
            starts=0,
            form="0.0",
            points_per_game="0.0",
            ict_index="0.0",
            penalties_order=None,
            status="a",
        )
        fixtures = [{"fdr": 3, "is_home": True, "opponent": 20}]
        score = _score_player(player, fixtures)
        # With all zeros normalized, base score is 0. Fixture: home + fdr_norm(FDR 3)
        # FDR 3 → normalized (5-3)/4 = 0.5 → 0.5 * fdr_weight + home_weight
        expected = WEIGHTS["home"] + 0.5 * WEIGHTS["fdr"]
        assert score == pytest.approx(expected)

    def test_no_fixtures_blank_gw(self):
        """Player with no fixtures (BGW) gets default -3*FDR penalty."""
        player = _make_player(
            form="6.0",
            points_per_game="5.0",
            ict_index="100.0",
            minutes=1800,
            expected_goals="8.0",
            expected_assists="5.0",
            bonus=15,
            starts=18,
            penalties_order=None,
        )
        score_no_fixtures = _score_player(player, None)
        score_with_fixtures = _score_player(player, [{"fdr": 3, "is_home": False, "opponent": 20}])

        # No fixtures: base_score + 0.5 * fdr_weight
        # Away fdr=3: base_score + 0 + 0.5 * fdr_weight (same when away fdr=3)
        assert score_no_fixtures == pytest.approx(score_with_fixtures)

    def test_empty_fixtures_list_treated_as_blank(self):
        """Empty list (not None) also triggers the blank GW path."""
        player = _make_player(form="6.0", points_per_game="5.0")
        score = _score_player(player, [])
        score_none = _score_player(player, None)
        assert score == pytest.approx(score_none)

    def test_dgw_bonus(self):
        """DGW player gets fixture-dependent components summed twice."""
        player = _make_player(form="6.0", points_per_game="5.0")
        single = [{"fdr": 2, "is_home": True, "opponent": 20}]
        double = [
            {"fdr": 2, "is_home": True, "opponent": 20},
            {"fdr": 3, "is_home": False, "opponent": 7},
        ]
        score_single = _score_player(player, single)
        score_double = _score_player(player, double)

        # DGW should always score higher than single fixture (second fixture adds value)
        # Second fixture (FDR 3, away): 0 (no home bonus) + 0.5 * fdr_weight
        extra = 0 + 0.5 * WEIGHTS["fdr"]
        assert score_double == pytest.approx(score_single + extra)

    def test_penalty_taker_bonus(self):
        """Player with penalties_order=1 gets penalty bonus; others don't."""
        pen_taker = _make_player(penalties_order=1)
        non_pen = _make_player(penalties_order=2)
        no_pen = _make_player(penalties_order=None)

        fixtures = [{"fdr": 3, "is_home": True, "opponent": 20}]
        score_pen = _score_player(pen_taker, fixtures)
        score_non = _score_player(non_pen, fixtures)
        score_none = _score_player(no_pen, fixtures)

        assert score_pen > score_non
        assert score_pen - score_non == pytest.approx(WEIGHTS["penalty"])
        assert score_non == pytest.approx(score_none)

    def test_injured_player_penalised(self):
        """Injured player with 0% chance gets heavily penalised."""
        fit = _make_player(status="a", chance_of_playing_next_round=None)
        injured = _make_player(status="i", chance_of_playing_next_round=0)

        fixtures = [{"fdr": 3, "is_home": True, "opponent": 20}]
        score_fit = _score_player(fit, fixtures)
        score_inj = _score_player(injured, fixtures)

        assert score_fit > score_inj
        assert score_fit - score_inj == pytest.approx(-WEIGHTS["playing_chance_max_penalty"])

    def test_higher_form_scores_higher(self):
        """Player with higher form scores higher, all else equal."""
        high_form = _make_player(form="8.0")
        low_form = _make_player(form="2.0")

        fixtures = [{"fdr": 3, "is_home": True, "opponent": 20}]
        assert _score_player(high_form, fixtures) > _score_player(low_form, fixtures)

    def test_higher_fdr_scores_lower(self):
        """Tougher fixture (higher FDR) lowers the score."""
        player = _make_player()
        easy = [{"fdr": 2, "is_home": True, "opponent": 20}]
        hard = [{"fdr": 5, "is_home": True, "opponent": 15}]

        assert _score_player(player, easy) > _score_player(player, hard)

    def test_xg_xa_contribution(self):
        """Players with higher xG/xA per 90 score higher."""
        high_xg = _make_player(minutes=1800, expected_goals="12.0", expected_assists="8.0")
        low_xg = _make_player(minutes=1800, expected_goals="2.0", expected_assists="1.0")

        fixtures = [{"fdr": 3, "is_home": True, "opponent": 20}]
        assert _score_player(high_xg, fixtures) > _score_player(low_xg, fixtures)


# ---------------------------------------------------------------------------
# Tests: get_captain_picks (end-to-end, mocked API)
# ---------------------------------------------------------------------------


class TestGetCaptainPicks:
    """End-to-end tests for get_captain_picks with mocked FPL API."""

    @pytest.fixture
    def mock_players(self):
        """A set of diverse test players."""
        return [
            _make_player(
                id=1,
                web_name="Salah",
                team=14,
                element_type=3,
                form="8.0",
                points_per_game="7.5",
                ict_index="200.0",
                minutes=2700,
                expected_goals="15.0",
                expected_assists="10.0",
                bonus=30,
                starts=28,
                penalties_order=1,
                status="a",
                total_points=200,
                now_cost=130,
                selected_by_percent="45.0",
            ),
            _make_player(
                id=2,
                web_name="Haaland",
                team=15,
                element_type=4,
                form="7.0",
                points_per_game="6.8",
                ict_index="180.0",
                minutes=2500,
                expected_goals="18.0",
                expected_assists="3.0",
                bonus=25,
                starts=26,
                penalties_order=None,
                status="a",
                total_points=190,
                now_cost=145,
                selected_by_percent="60.0",
            ),
            _make_player(
                id=3,
                web_name="Saka",
                team=1,
                element_type=3,
                form="5.5",
                points_per_game="5.2",
                ict_index="150.0",
                minutes=2200,
                expected_goals="8.0",
                expected_assists="7.0",
                bonus=18,
                starts=23,
                penalties_order=None,
                status="a",
                total_points=140,
                now_cost=100,
                selected_by_percent="30.0",
            ),
            # Injured player
            _make_player(
                id=4,
                web_name="InjuredGuy",
                team=7,
                element_type=3,
                form="6.0",
                points_per_game="5.0",
                ict_index="120.0",
                minutes=1800,
                expected_goals="6.0",
                expected_assists="4.0",
                bonus=12,
                starts=18,
                penalties_order=None,
                status="i",
                chance_of_playing_next_round=0,
                total_points=100,
                now_cost=70,
                selected_by_percent="5.0",
            ),
            # Zero-minutes player (never plays)
            _make_player(
                id=5,
                web_name="Benchwarmer",
                team=20,
                element_type=2,
                form="0.0",
                points_per_game="0.0",
                ict_index="0.0",
                minutes=0,
                expected_goals="0.0",
                expected_assists="0.0",
                bonus=0,
                starts=0,
                penalties_order=None,
                status="a",
                total_points=0,
                now_cost=40,
                selected_by_percent="0.1",
            ),
        ]

    @pytest.fixture
    def mock_fixtures(self):
        """Fixtures for GW30."""
        return [
            # Liverpool (14) vs Spurs (20) — LIV home
            _make_fixture(event=30, team_h=14, team_a=20, team_h_difficulty=2, team_a_difficulty=4),
            # Man City (15) vs Arsenal (1) — MCI home
            _make_fixture(event=30, team_h=15, team_a=1, team_h_difficulty=3, team_a_difficulty=4),
            # Note: Everton (7) has no fixture in GW30 — blank gameweek for them
        ]

    @pytest.mark.asyncio
    async def test_returns_correct_structure(self, mock_players, mock_fixtures):
        """Response has gameweek, algorithm_version, and picks list."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=5)

        assert result["gameweek"] == 30
        assert "algorithm_version" in result
        assert "picks" in result
        assert isinstance(result["picks"], list)

    @pytest.mark.asyncio
    async def test_picks_ordered_by_score_descending(self, mock_players, mock_fixtures):
        """Picks are ordered from highest to lowest score."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=5)

        scores = [p["score"] for p in result["picks"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_top_n_limits_picks(self, mock_players, mock_fixtures):
        """top_n parameter limits the number of picks returned."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=3)

        assert len(result["picks"]) == 3

    @pytest.mark.asyncio
    async def test_injured_player_ranked_low(self, mock_players, mock_fixtures):
        """Injured player (0% chance) should not appear in top picks."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=3)

        pick_names = [p["player"]["name"] for p in result["picks"]]
        assert "InjuredGuy" not in pick_names

    @pytest.mark.asyncio
    async def test_zero_minutes_player_ranked_low(self, mock_players, mock_fixtures):
        """Player with 0 minutes should not appear in top picks."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=3)

        pick_names = [p["player"]["name"] for p in result["picks"]]
        assert "Benchwarmer" not in pick_names

    @pytest.mark.asyncio
    async def test_pick_has_expected_fields(self, mock_players, mock_fixtures):
        """Each pick includes player, fixture, score, reasoning, and stats."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=3)

        pick = result["picks"][0]
        assert "rank" in pick
        assert "player" in pick
        assert "score" in pick
        assert "reasoning" in pick
        assert "stats" in pick

        player_info = pick["player"]
        assert "id" in player_info
        assert "name" in player_info
        assert "team" in player_info
        assert "position" in player_info
        assert "cost" in player_info

    @pytest.mark.asyncio
    async def test_fixture_info_populated(self, mock_players, mock_fixtures):
        """Players with fixtures have fixture info; blank GW players have None."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=5)

        picks_by_name = {p["player"]["name"]: p for p in result["picks"]}

        # Salah (LIV, team=14) has a fixture
        salah = picks_by_name.get("Salah")
        if salah:
            assert salah["fixture"] is not None
            assert salah["fixture"]["gameweek"] == 30

        # InjuredGuy (EVE, team=7) has no fixture in GW30
        injured = picks_by_name.get("InjuredGuy")
        if injured:
            assert injured["fixture"] is None

    @pytest.mark.asyncio
    async def test_dgw_fixture_info(self):
        """DGW player has is_dgw=True and multiple fixture entries."""
        players = [
            _make_player(id=1, web_name="Salah", team=14, form="8.0", points_per_game="7.5"),
        ]
        fixtures = [
            _make_fixture(event=30, team_h=14, team_a=20, team_h_difficulty=2, team_a_difficulty=4),
            _make_fixture(event=30, team_h=14, team_a=7, team_h_difficulty=2, team_a_difficulty=3),
        ]
        bootstrap = _make_bootstrap(players=players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, fixtures)

            result = await get_captain_picks(gameweek=30, top_n=1)

        pick = result["picks"][0]
        assert pick["fixture"]["is_dgw"] is True
        assert len(pick["fixture"]["fixtures"]) == 2

    @pytest.mark.asyncio
    async def test_uses_next_gameweek_when_none(self, mock_players, mock_fixtures):
        """When gameweek=None, uses get_next_gameweek from bootstrap."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=None, top_n=3)

        # Next GW from our mock events is 30
        assert result["gameweek"] == 30

    @pytest.mark.asyncio
    async def test_rank_field_sequential(self, mock_players, mock_fixtures):
        """Rank field starts at 1 and increments sequentially."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=5)

        for i, pick in enumerate(result["picks"]):
            assert pick["rank"] == i + 1

    @pytest.mark.asyncio
    async def test_penalty_taker_ranked_higher(self):
        """Penalty taker should score higher than identical player without pens."""
        pen_taker = _make_player(id=1, web_name="PenTaker", team=14, penalties_order=1)
        non_pen = _make_player(id=2, web_name="NoPen", team=14, penalties_order=None)

        fixtures = [
            _make_fixture(event=30, team_h=14, team_a=20, team_h_difficulty=2, team_a_difficulty=4),
        ]
        bootstrap = _make_bootstrap(players=[pen_taker, non_pen])

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, fixtures)

            result = await get_captain_picks(gameweek=30, top_n=2)

        assert result["picks"][0]["player"]["name"] == "PenTaker"
        assert result["picks"][1]["player"]["name"] == "NoPen"

    @pytest.mark.asyncio
    async def test_stats_include_xg_xa(self, mock_players, mock_fixtures):
        """Stats block includes xg_per_90 and xa_per_90 calculations."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=5)

        picks_by_name = {p["player"]["name"]: p for p in result["picks"]}
        salah = picks_by_name.get("Salah")
        if salah:
            stats = salah["stats"]
            assert stats["xg_per_90"] > 0
            assert stats["xa_per_90"] > 0
            assert stats["penalties_order"] == 1

    @pytest.mark.asyncio
    async def test_position_mapping(self, mock_players, mock_fixtures):
        """Position is correctly mapped from element_type."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=5)

        picks_by_name = {p["player"]["name"]: p for p in result["picks"]}
        if "Salah" in picks_by_name:
            assert picks_by_name["Salah"]["player"]["position"] == "MID"
        if "Haaland" in picks_by_name:
            assert picks_by_name["Haaland"]["player"]["position"] == "FWD"
        if "Benchwarmer" in picks_by_name:
            assert picks_by_name["Benchwarmer"]["player"]["position"] == "DEF"

    @pytest.mark.asyncio
    async def test_cost_divided_by_10(self, mock_players, mock_fixtures):
        """Player cost is now_cost / 10 (FPL stores in 0.1m units)."""
        bootstrap = _make_bootstrap(players=mock_players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, mock_fixtures)

            result = await get_captain_picks(gameweek=30, top_n=5)

        picks_by_name = {p["player"]["name"]: p for p in result["picks"]}
        if "Salah" in picks_by_name:
            assert picks_by_name["Salah"]["player"]["cost"] == 13.0  # 130 / 10

    @pytest.mark.asyncio
    async def test_all_blank_gw(self):
        """All players with no fixtures still get scored (with default FDR)."""
        players = [
            _make_player(id=1, web_name="PlayerA", team=14, form="6.0"),
            _make_player(id=2, web_name="PlayerB", team=15, form="4.0"),
        ]
        # No fixtures for GW30
        fixtures = [_make_fixture(event=29, team_h=14, team_a=15)]
        bootstrap = _make_bootstrap(players=players)

        with patch("app.algorithms.captain._gather_data", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (bootstrap, fixtures)

            result = await get_captain_picks(gameweek=30, top_n=2)

        assert len(result["picks"]) == 2
        # All players should have fixture=None
        for pick in result["picks"]:
            assert pick["fixture"] is None
