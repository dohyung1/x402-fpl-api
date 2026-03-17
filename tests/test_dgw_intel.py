"""
Tests for DGW/BGW community intelligence scraper.

Covers:
- _match_team_name() — team alias resolution
- _extract_dgw_bgw_from_text() — regex extraction from article text
- merge_intel_with_api_predictions() — merging community + API data
"""

from app.algorithms.dgw_intel import (
    _extract_dgw_bgw_from_text,
    _match_team_name,
    merge_intel_with_api_predictions,
)


class TestMatchTeamName:
    def test_exact_match(self):
        assert _match_team_name("arsenal") == "ARS"
        assert _match_team_name("chelsea") == "CHE"

    def test_case_insensitive(self):
        assert _match_team_name("Arsenal") == "ARS"
        assert _match_team_name("CHELSEA") == "CHE"

    def test_alias_match(self):
        assert _match_team_name("man city") == "MCI"
        assert _match_team_name("man utd") == "MUN"
        assert _match_team_name("spurs") == "TOT"
        assert _match_team_name("wolves") == "WOL"
        assert _match_team_name("palace") == "CRY"

    def test_full_name(self):
        assert _match_team_name("manchester city") == "MCI"
        assert _match_team_name("manchester united") == "MUN"
        assert _match_team_name("crystal palace") == "CRY"
        assert _match_team_name("west ham") == "WHU"
        assert _match_team_name("nottingham forest") == "NFO"

    def test_no_match(self):
        assert _match_team_name("barcelona") is None
        assert _match_team_name("xyz") is None

    def test_whitespace_handling(self):
        assert _match_team_name("  arsenal  ") == "ARS"


class TestExtractDgwBgwFromText:
    def test_dgw_with_number(self):
        text = "The biggest Double Gameweek 33 of the season features Arsenal and Chelsea."
        result = _extract_dgw_bgw_from_text(text)
        assert "33" in result["dgws"]
        assert "ARS" in result["dgws"]["33"]["teams"]
        assert "CHE" in result["dgws"]["33"]["teams"]

    def test_dgw_shorthand(self):
        text = "DGW33 is expected to include Liverpool and Man City."
        result = _extract_dgw_bgw_from_text(text)
        assert "33" in result["dgws"]
        assert "LIV" in result["dgws"]["33"]["teams"]
        assert "MCI" in result["dgws"]["33"]["teams"]

    def test_dgw_with_space(self):
        text = "DGW 36 could see Man City play twice."
        result = _extract_dgw_bgw_from_text(text)
        assert "36" in result["dgws"]
        assert "MCI" in result["dgws"]["36"]["teams"]

    def test_bgw_extraction(self):
        text = "Blank Gameweek 34 will see Arsenal and Liverpool miss out due to FA Cup."
        result = _extract_dgw_bgw_from_text(text)
        assert "34" in result["bgws"]
        assert "ARS" in result["bgws"]["34"]["teams"]
        assert "LIV" in result["bgws"]["34"]["teams"]

    def test_bgw_shorthand(self):
        text = "BGW31 affects Arsenal and Wolves who have no fixture."
        result = _extract_dgw_bgw_from_text(text)
        assert "31" in result["bgws"]
        assert "ARS" in result["bgws"]["31"]["teams"]
        assert "WOL" in result["bgws"]["31"]["teams"]

    def test_confirmed_status(self):
        text = "Double Gameweek 26 has been confirmed with Arsenal playing twice."
        result = _extract_dgw_bgw_from_text(text)
        assert result["dgws"]["26"]["status"] == "confirmed"

    def test_predicted_status_default(self):
        text = "DGW33 is expected to be the biggest double."
        result = _extract_dgw_bgw_from_text(text)
        assert result["dgws"]["33"]["status"] == "predicted"

    def test_multiple_dgws_in_text(self):
        text = (
            "DGW33 will feature Chelsea and Arsenal playing twice. "
            "Later, DGW36 could include Man City with their rescheduled match."
        )
        result = _extract_dgw_bgw_from_text(text)
        assert "33" in result["dgws"]
        assert "36" in result["dgws"]
        assert "MCI" in result["dgws"]["36"]["teams"]

    def test_mixed_dgw_bgw(self):
        text = (
            "BGW34 will see Arsenal and Chelsea blank. "
            "Their fixtures move to DGW33 instead."
        )
        result = _extract_dgw_bgw_from_text(text)
        assert "34" in result["bgws"]
        assert "33" in result["dgws"]

    def test_no_matches(self):
        text = "This is a regular article about football with no gameweek predictions."
        result = _extract_dgw_bgw_from_text(text)
        assert result["dgws"] == {}
        assert result["bgws"] == {}

    def test_invalid_gameweek_ignored(self):
        text = "DGW0 and DGW39 and DGW99 should all be ignored."
        result = _extract_dgw_bgw_from_text(text)
        assert result["dgws"] == {}

    def test_real_article_snippet(self):
        """Simulate content from a real Premier League article."""
        text = (
            "Blank Gameweek 31 (BGW31), which takes place on the same weekend as the "
            "EFL Cup final. Arsenal and Manchester City are the finalists, so Arsenal vs "
            "Wolverhampton Wanderers and Manchester City vs Crystal Palace will be postponed. "
            "These fixtures are likely to be rescheduled into Double Gameweek 33."
        )
        result = _extract_dgw_bgw_from_text(text)
        assert "31" in result["bgws"]
        assert "ARS" in result["bgws"]["31"]["teams"]
        assert "33" in result["dgws"]


class TestMergeIntelWithApiPredictions:
    def _make_teams_by_id(self):
        return {
            1: {"short_name": "ARS"},
            2: {"short_name": "CHE"},
            3: {"short_name": "MCI"},
            4: {"short_name": "LIV"},
        }

    def test_empty_intel(self):
        api = {33: [1]}
        intel = {}
        result = merge_intel_with_api_predictions(api, intel, self._make_teams_by_id())
        assert result == {33: [1]}

    def test_adds_new_teams(self):
        api = {33: [1]}  # Arsenal
        intel = {"dgws": {"33": {"teams": ["CHE", "MCI"]}}}
        result = merge_intel_with_api_predictions(api, intel, self._make_teams_by_id())
        assert 1 in result[33]  # Arsenal still there
        assert 2 in result[33]  # Chelsea added
        assert 3 in result[33]  # Man City added

    def test_adds_new_gameweek(self):
        api = {33: [1]}
        intel = {"dgws": {"36": {"teams": ["MCI"]}}}
        result = merge_intel_with_api_predictions(api, intel, self._make_teams_by_id())
        assert 33 in result
        assert 36 in result
        assert 3 in result[36]

    def test_no_duplicates(self):
        api = {33: [1]}  # Arsenal already predicted
        intel = {"dgws": {"33": {"teams": ["ARS"]}}}  # Arsenal from community too
        result = merge_intel_with_api_predictions(api, intel, self._make_teams_by_id())
        assert result[33].count(1) == 1  # No duplicate

    def test_unknown_team_ignored(self):
        api = {}
        intel = {"dgws": {"33": {"teams": ["XYZ"]}}}
        result = merge_intel_with_api_predictions(api, intel, self._make_teams_by_id())
        assert 33 not in result  # XYZ didn't resolve to any team ID
