"""Tests for app/algorithms/compare.py — fuzzy matching and player comparison."""

from unittest.mock import AsyncMock, patch

import pytest

from app.algorithms.compare import (
    _build_verdict,
    _calc_home_away_form,
    _fuzzy_match_player,
    compare_players,
)

# ---------------------------------------------------------------------------
# Realistic mock data
# ---------------------------------------------------------------------------

MOCK_TEAMS = [
    {"id": 1, "short_name": "ARS"},
    {"id": 2, "short_name": "AVL"},
    {"id": 3, "short_name": "BOU"},
    {"id": 6, "short_name": "CHE"},
    {"id": 11, "short_name": "LIV"},
    {"id": 13, "short_name": "MCI"},
]

MOCK_ELEMENTS = [
    {
        "id": 100,
        "web_name": "Salah",
        "first_name": "Mohamed",
        "second_name": "Salah",
        "team": 11,
        "element_type": 3,
        "now_cost": 130,
        "form": "8.5",
        "points_per_game": "7.2",
        "total_points": 180,
        "selected_by_percent": "55.0",
        "ict_index": "210.0",
        "expected_goals": "12.0",
        "expected_assists": "8.0",
        "expected_goal_involvements": "20.0",
        "minutes": 2250,
        "bonus": 25,
        "starts": 25,
        "penalties_order": 1,
        "status": "a",
        "chance_of_playing_next_round": None,
        "transfers_in_event": 100_000,
        "transfers_out_event": 20_000,
    },
    {
        "id": 200,
        "web_name": "Haaland",
        "first_name": "Erling",
        "second_name": "Haaland",
        "team": 13,
        "element_type": 4,
        "now_cost": 145,
        "form": "7.0",
        "points_per_game": "6.5",
        "total_points": 160,
        "selected_by_percent": "60.0",
        "ict_index": "180.0",
        "expected_goals": "15.0",
        "expected_assists": "3.0",
        "expected_goal_involvements": "18.0",
        "minutes": 2100,
        "bonus": 20,
        "starts": 23,
        "penalties_order": None,
        "status": "a",
        "chance_of_playing_next_round": None,
        "transfers_in_event": 50_000,
        "transfers_out_event": 30_000,
    },
    {
        "id": 300,
        "web_name": "Palmer",
        "first_name": "Cole",
        "second_name": "Palmer",
        "team": 6,
        "element_type": 3,
        "now_cost": 110,
        "form": "6.0",
        "points_per_game": "5.8",
        "total_points": 140,
        "selected_by_percent": "30.0",
        "ict_index": "150.0",
        "expected_goals": "8.0",
        "expected_assists": "6.0",
        "expected_goal_involvements": "14.0",
        "minutes": 2000,
        "bonus": 15,
        "starts": 22,
        "penalties_order": 1,
        "status": "a",
        "chance_of_playing_next_round": None,
        "transfers_in_event": 40_000,
        "transfers_out_event": 10_000,
    },
    {
        "id": 400,
        "web_name": "Saka",
        "first_name": "Bukayo",
        "second_name": "Saka",
        "team": 1,
        "element_type": 3,
        "now_cost": 105,
        "form": "5.5",
        "points_per_game": "5.2",
        "total_points": 130,
        "selected_by_percent": "25.0",
        "ict_index": "140.0",
        "expected_goals": "5.0",
        "expected_assists": "9.0",
        "expected_goal_involvements": "14.0",
        "minutes": 2100,
        "bonus": 12,
        "starts": 23,
        "penalties_order": None,
        "status": "a",
        "chance_of_playing_next_round": None,
        "transfers_in_event": 20_000,
        "transfers_out_event": 15_000,
    },
]

MOCK_EVENTS = [{"id": gw, "is_current": gw == 25, "is_next": gw == 26, "finished": gw < 25} for gw in range(1, 39)]

MOCK_BOOTSTRAP = {
    "events": MOCK_EVENTS,
    "elements": MOCK_ELEMENTS,
    "teams": MOCK_TEAMS,
}


def _make_mock_summary(player_id: int) -> dict:
    """Generate a mock element-summary with home/away history for a player."""
    history = []
    for gw in range(1, 26):
        history.append(
            {
                "round": gw,
                "was_home": gw % 2 == 1,  # odd GWs at home
                "total_points": 8 if gw % 2 == 1 else 4,  # better at home
                "minutes": 90,
            }
        )
    # Override for specific players to create variety
    if player_id == 200:  # Haaland — better away
        for m in history:
            if m["was_home"]:
                m["total_points"] = 3
            else:
                m["total_points"] = 9
    if player_id == 300:  # Palmer — balanced
        for m in history:
            m["total_points"] = 6
    return {"history": history, "fixtures": []}


MOCK_FIXTURES = [
    # GW26 fixtures
    {
        "event": 26,
        "team_h": 11,
        "team_a": 3,
        "team_h_difficulty": 2,
        "team_a_difficulty": 5,
    },
    {
        "event": 26,
        "team_h": 6,
        "team_a": 13,
        "team_h_difficulty": 4,
        "team_a_difficulty": 4,
    },
    {
        "event": 26,
        "team_h": 1,
        "team_a": 2,
        "team_h_difficulty": 2,
        "team_a_difficulty": 4,
    },
    # GW27 fixtures
    {
        "event": 27,
        "team_h": 13,
        "team_a": 11,
        "team_h_difficulty": 4,
        "team_a_difficulty": 4,
    },
    {
        "event": 27,
        "team_h": 2,
        "team_a": 6,
        "team_h_difficulty": 4,
        "team_a_difficulty": 3,
    },
    {
        "event": 27,
        "team_h": 3,
        "team_a": 1,
        "team_h_difficulty": 4,
        "team_a_difficulty": 3,
    },
]


# ---------------------------------------------------------------------------
# _fuzzy_match_player
# ---------------------------------------------------------------------------


class TestFuzzyMatchPlayer:
    def test_exact_match(self):
        result = _fuzzy_match_player("Salah", MOCK_ELEMENTS)
        assert result is not None
        assert result["id"] == 100

    def test_exact_match_case_insensitive(self):
        result = _fuzzy_match_player("salah", MOCK_ELEMENTS)
        assert result is not None
        assert result["id"] == 100

    def test_partial_starts_with(self):
        result = _fuzzy_match_player("Sal", MOCK_ELEMENTS)
        assert result is not None
        assert result["id"] == 100

    def test_partial_contains(self):
        result = _fuzzy_match_player("aal", MOCK_ELEMENTS)
        assert result is not None
        assert result["id"] == 200  # Haaland

    def test_full_name_match(self):
        result = _fuzzy_match_player("Mohamed", MOCK_ELEMENTS)
        assert result is not None
        assert result["id"] == 100

    def test_full_name_match_case_insensitive(self):
        result = _fuzzy_match_player("erling", MOCK_ELEMENTS)
        assert result is not None
        assert result["id"] == 200

    def test_not_found_returns_none(self):
        result = _fuzzy_match_player("Nonexistent", MOCK_ELEMENTS)
        assert result is None

    def test_empty_query_returns_none(self):
        result = _fuzzy_match_player("", MOCK_ELEMENTS)
        assert result is None

    def test_whitespace_query_returns_none(self):
        result = _fuzzy_match_player("   ", MOCK_ELEMENTS)
        assert result is None


# ---------------------------------------------------------------------------
# compare_players — integration (with mocked HTTP)
# ---------------------------------------------------------------------------


class TestComparePlayers:
    @pytest.fixture(autouse=True)
    def _patch_fpl(self):
        with (
            patch("app.algorithms.compare.get_bootstrap", new_callable=AsyncMock) as mock_bs,
            patch("app.algorithms.compare.get_fixtures", new_callable=AsyncMock) as mock_fix,
            patch("app.algorithms.compare.get_player_summary", new_callable=AsyncMock) as mock_summary,
        ):
            mock_bs.return_value = MOCK_BOOTSTRAP
            mock_fix.return_value = MOCK_FIXTURES
            mock_summary.side_effect = lambda pid: _make_mock_summary(pid)
            yield

    async def test_player_not_found_returns_error(self):
        result = await compare_players(["Salah", "FakePlayer123"])
        assert "error" in result
        assert "Could not match all player names" in result["error"]
        assert len(result["details"]) == 1
        assert "FakePlayer123" in result["details"][0]

    async def test_two_player_comparison(self):
        result = await compare_players(["Salah", "Haaland"])
        assert "error" not in result
        assert len(result["players"]) == 2
        names = {p["name"] for p in result["players"]}
        assert names == {"Salah", "Haaland"}
        assert result["gameweek"] == 26
        assert "verdict" in result

    async def test_four_player_comparison(self):
        result = await compare_players(["Salah", "Haaland", "Palmer", "Saka"])
        assert "error" not in result
        assert len(result["players"]) == 4
        names = {p["name"] for p in result["players"]}
        assert names == {"Salah", "Haaland", "Palmer", "Saka"}

    async def test_too_few_players(self):
        result = await compare_players(["Salah"])
        assert "error" in result
        assert "at least 2" in result["error"]

    async def test_too_many_players(self):
        result = await compare_players(["a", "b", "c", "d", "e"])
        assert "error" in result
        assert "at most 4" in result["error"]

    async def test_profiles_have_expected_fields(self):
        result = await compare_players(["Salah", "Palmer"])
        player = result["players"][0]
        assert "captain_score" in player
        assert "cost" in player
        assert "form" in player
        assert "upcoming_fixtures" in player
        assert "value_score" in player
        assert "xg_per_90" in player

    async def test_upcoming_fixtures_populated(self):
        result = await compare_players(["Salah", "Palmer"], gameweeks_ahead=2)
        for p in result["players"]:
            assert len(p["upcoming_fixtures"]) > 0

    async def test_home_away_form_fields_present(self):
        result = await compare_players(["Salah", "Haaland"])
        for p in result["players"]:
            assert "home_form" in p
            assert "away_form" in p
            assert "home_away_insight" in p

    async def test_home_away_form_values(self):
        result = await compare_players(["Salah", "Haaland"])
        salah = next(p for p in result["players"] if p["name"] == "Salah")
        haaland = next(p for p in result["players"] if p["name"] == "Haaland")
        # Salah: home=8, away=4 from mock data
        assert salah["home_form"] == 8.0
        assert salah["away_form"] == 4.0
        assert "home" in salah["home_away_insight"].lower()
        # Haaland: home=3, away=9 from mock data
        assert haaland["home_form"] == 3.0
        assert haaland["away_form"] == 9.0
        assert "away" in haaland["home_away_insight"].lower()


# ---------------------------------------------------------------------------
# _build_verdict — unit tests
# ---------------------------------------------------------------------------


class TestBuildVerdict:
    def test_verdict_picks_highest_captain_score(self):
        profiles = [
            {
                "name": "Salah",
                "captain_score": 20.0,
                "form": 8.0,
                "value_score": 5.0,
                "cost": 13.0,
                "xg_per_90": 0.5,
                "upcoming_fixtures": [],
            },
            {
                "name": "Haaland",
                "captain_score": 15.0,
                "form": 7.0,
                "value_score": 4.0,
                "cost": 14.5,
                "xg_per_90": 0.6,
                "upcoming_fixtures": [],
            },
        ]
        verdict = _build_verdict(profiles)
        assert "Salah" in verdict
        assert "clear pick" in verdict

    def test_verdict_close_race(self):
        profiles = [
            {
                "name": "Salah",
                "captain_score": 15.5,
                "form": 8.0,
                "value_score": 5.0,
                "cost": 13.0,
                "xg_per_90": 0.5,
                "upcoming_fixtures": [],
            },
            {
                "name": "Haaland",
                "captain_score": 15.0,
                "form": 7.0,
                "value_score": 4.0,
                "cost": 14.5,
                "xg_per_90": 0.6,
                "upcoming_fixtures": [],
            },
        ]
        verdict = _build_verdict(profiles)
        assert "narrowly" in verdict or "viable alternative" in verdict

    def test_verdict_empty_profiles(self):
        verdict = _build_verdict([])
        assert "No players" in verdict


# ---------------------------------------------------------------------------
# _calc_home_away_form — unit tests
# ---------------------------------------------------------------------------


class TestCalcHomeAwayForm:
    def test_stronger_at_home(self):
        summary = _make_mock_summary(100)  # Salah mock: home=8, away=4
        result = _calc_home_away_form(summary)
        assert result["home_form"] == 8.0
        assert result["away_form"] == 4.0
        assert "Stronger at home" in result["home_away_insight"]

    def test_stronger_away(self):
        summary = _make_mock_summary(200)  # Haaland mock: home=3, away=9
        result = _calc_home_away_form(summary)
        assert result["home_form"] == 3.0
        assert result["away_form"] == 9.0
        assert "Stronger away" in result["home_away_insight"]

    def test_balanced_form(self):
        summary = _make_mock_summary(300)  # Palmer mock: all 6
        result = _calc_home_away_form(summary)
        assert result["home_form"] == 6.0
        assert result["away_form"] == 6.0
        assert "Similar" in result["home_away_insight"]

    def test_empty_history(self):
        result = _calc_home_away_form({"history": []})
        assert result["home_form"] == 0.0
        assert result["away_form"] == 0.0

    def test_skips_zero_minute_appearances(self):
        summary = {
            "history": [
                {"was_home": True, "total_points": 0, "minutes": 0},
                {"was_home": True, "total_points": 10, "minutes": 90},
                {"was_home": False, "total_points": 5, "minutes": 45},
            ]
        }
        result = _calc_home_away_form(summary)
        assert result["home_form"] == 10.0
        assert result["away_form"] == 5.0
