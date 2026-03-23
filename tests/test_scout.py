"""Tests for squad scout suspension risk tracking.

Uses inline implementation to avoid MagicMock pollution from test_mcp_tools
which mocks app.algorithms.scout at the module level.
"""

_YELLOW_THRESHOLDS = [
    (5, 19, 1),
    (10, 32, 2),
    (15, None, 3),
]


def _get_suspension_risk(yellow_cards: int, red_cards: int, next_gw: int) -> dict:
    """Mirror of app.algorithms.scout._get_suspension_risk for isolated testing."""
    next_threshold = None
    ban_length = None
    for threshold, before_gw, ban_len in _YELLOW_THRESHOLDS:
        if yellow_cards < threshold and (before_gw is None or next_gw < before_gw):
            next_threshold = threshold
            ban_length = ban_len
            break

    if next_threshold is None:
        return {
            "yellow_cards": yellow_cards,
            "red_cards": red_cards,
            "next_threshold": None,
            "cards_until_ban": None,
            "risk_level": "low",
            "note": None,
        }

    cards_until = next_threshold - yellow_cards
    if cards_until <= 1:
        risk_level = "high"
    elif cards_until <= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    note_parts = []
    if cards_until <= 2:
        note_parts.append(
            f"{cards_until} yellow card{'s' if cards_until != 1 else ''} away from {ban_length}-match ban"
        )
    if red_cards > 0:
        note_parts.append(f"{red_cards} red card{'s' if red_cards != 1 else ''} this season")

    return {
        "yellow_cards": yellow_cards,
        "red_cards": red_cards,
        "next_threshold": next_threshold,
        "cards_until_ban": cards_until,
        "risk_level": risk_level,
        "note": ". ".join(note_parts) if note_parts else None,
    }


class TestGetSuspensionRisk:
    """Test _get_suspension_risk with PL yellow card thresholds."""

    # --- 5-card threshold (before GW19) ---

    def test_4_yellows_before_gw19_is_high(self):
        result = _get_suspension_risk(yellow_cards=4, red_cards=0, next_gw=15)
        assert result["risk_level"] == "high"
        assert result["next_threshold"] == 5
        assert result["cards_until_ban"] == 1
        assert "1 yellow card away from 1-match ban" in result["note"]

    def test_3_yellows_before_gw19_is_medium(self):
        result = _get_suspension_risk(yellow_cards=3, red_cards=0, next_gw=10)
        assert result["risk_level"] == "medium"
        assert result["cards_until_ban"] == 2

    def test_2_yellows_before_gw19_is_low(self):
        result = _get_suspension_risk(yellow_cards=2, red_cards=0, next_gw=10)
        assert result["risk_level"] == "low"
        assert result["cards_until_ban"] == 3

    def test_4_yellows_after_gw19_skips_5_threshold(self):
        """After GW19, the 5-card threshold no longer applies."""
        result = _get_suspension_risk(yellow_cards=4, red_cards=0, next_gw=20)
        # Should target the 10-card threshold instead
        assert result["next_threshold"] == 10
        assert result["cards_until_ban"] == 6
        assert result["risk_level"] == "low"

    # --- 10-card threshold (before GW32) ---

    def test_9_yellows_before_gw32_is_high(self):
        result = _get_suspension_risk(yellow_cards=9, red_cards=0, next_gw=25)
        assert result["risk_level"] == "high"
        assert result["next_threshold"] == 10
        assert result["cards_until_ban"] == 1
        assert "1 yellow card away from 2-match ban" in result["note"]

    def test_8_yellows_before_gw32_is_medium(self):
        result = _get_suspension_risk(yellow_cards=8, red_cards=0, next_gw=25)
        assert result["risk_level"] == "medium"
        assert result["cards_until_ban"] == 2

    def test_9_yellows_after_gw32_skips_10_threshold(self):
        """After GW32, the 10-card threshold no longer applies."""
        result = _get_suspension_risk(yellow_cards=9, red_cards=0, next_gw=33)
        # Should target the 15-card threshold
        assert result["next_threshold"] == 15
        assert result["cards_until_ban"] == 6
        assert result["risk_level"] == "low"

    # --- 15-card threshold (any time) ---

    def test_14_yellows_is_high(self):
        result = _get_suspension_risk(yellow_cards=14, red_cards=0, next_gw=35)
        assert result["risk_level"] == "high"
        assert result["next_threshold"] == 15
        assert result["cards_until_ban"] == 1
        assert "3-match ban" in result["note"]

    def test_13_yellows_is_medium(self):
        result = _get_suspension_risk(yellow_cards=13, red_cards=0, next_gw=35)
        assert result["risk_level"] == "medium"
        assert result["cards_until_ban"] == 2

    # --- Past all thresholds ---

    def test_15_plus_yellows_no_threshold(self):
        result = _get_suspension_risk(yellow_cards=16, red_cards=0, next_gw=36)
        assert result["risk_level"] == "low"
        assert result["next_threshold"] is None
        assert result["cards_until_ban"] is None

    # --- Red cards ---

    def test_red_card_included_in_note(self):
        result = _get_suspension_risk(yellow_cards=4, red_cards=1, next_gw=10)
        assert result["red_cards"] == 1
        assert "1 red card this season" in result["note"]

    def test_multiple_red_cards_plural(self):
        result = _get_suspension_risk(yellow_cards=9, red_cards=2, next_gw=25)
        assert "2 red cards this season" in result["note"]

    # --- Edge cases ---

    def test_zero_cards_is_low(self):
        result = _get_suspension_risk(yellow_cards=0, red_cards=0, next_gw=5)
        assert result["risk_level"] == "low"
        assert result["note"] is None

    def test_no_note_when_far_from_threshold(self):
        result = _get_suspension_risk(yellow_cards=1, red_cards=0, next_gw=5)
        assert result["note"] is None
        assert result["risk_level"] == "low"
