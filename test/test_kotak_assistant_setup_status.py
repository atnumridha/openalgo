from datetime import datetime

import pytest

from services.kotak_assistant.analysis import IST, analyse

NOW = datetime(2026, 10, 15, 13, 0, tzinfo=IST).timestamp()


def candles(*, target=120, trigger=True):
    five = [
        {
            "time": NOW - (40 - i) * 300,
            "open": 90 + i / 2,
            "high": 91 + i / 2,
            "low": 89 + i / 2,
            "close": 90.25 + i / 2,
        }
        for i in range(40)
    ]
    # Two confirmed historical resistance pivots, both known before the trigger.
    five[10]["high"] = 110
    five[20]["high"] = target
    one = [
        {"time": NOW - (60 - i) * 60, "open": 106, "high": 107, "low": 105, "close": 106}
        for i in range(60)
    ]
    if trigger:
        one[-3].update(open=109, high=112, low=108, close=111)
        one[-2].update(open=111, high=112, low=110, close=111)
        one[-1].update(open=111, high=113, low=110, close=112)
    return one, five


def test_missing_target_is_explained_without_confirming_an_entry():
    one, five = candles(target=111)
    result = analyse(one, five, NOW)
    assert result["action"] == "WAIT"
    assert result["checks"]["state"] == "no_target"
    assert result["checks"]["trend"] == "CALL"
    assert result["checks"]["pattern_confirmed"] is True
    assert result["checks"]["target_available"] is False
    assert "resistance above" in result["reason"]
    assert "setup_id" not in result


def test_downtrend_reports_missing_support_instead_of_missing_resistance():
    one, five = candles(target=111)
    for bars in (one, five):
        for b in bars:
            b.update(
                open=200 - b["open"],
                close=200 - b["close"],
                high=200 - b["low"],
                low=200 - b["high"],
            )
    result = analyse(one, five, NOW)
    assert result["action"] == "WAIT"
    assert result["checks"]["state"] == "no_target"
    assert result["checks"]["trend"] == "PUT"
    assert "support below" in result["reason"]


def test_new_completed_trigger_changes_waiting_status_to_confirmed():
    one, five = candles(trigger=False)
    waiting = analyse(one, five, NOW)
    assert waiting["action"] == "WAIT"
    assert waiting["checks"]["state"] == "waiting_trigger"
    assert waiting["checks"]["pattern_confirmed"] is False
    one, five = candles()
    confirmed = analyse(one, five, NOW)
    assert confirmed["action"] == "CALL"
    assert confirmed["checks"]["state"] == "confirmed"
    assert confirmed["checks"]["reward_risk"] >= 2
    assert confirmed["checks"]["checked_at"] == NOW
    assert confirmed["checks"]["one_closed_at"] == NOW
    assert confirmed["checks"]["five_closed_at"] == NOW


def test_target_below_required_reward_is_distinguished_from_missing_trigger():
    one, five = candles(target=113)
    result = analyse(one, five, NOW)
    assert result["action"] == "WAIT"
    assert result["checks"]["state"] == "low_reward"
    assert result["checks"]["pattern_confirmed"] is True
    assert 0 < result["checks"]["reward_risk"] < 2


@pytest.mark.parametrize("offset,state", [(0, "confirmed"), (126, "stale_history")])
def test_fresh_quotes_cannot_hide_stale_setup_candles(offset, state):
    one, five = candles()
    result = analyse(one, five, NOW + offset)
    assert result["checks"]["state"] == state
    assert result["checks"]["history"] == ("fresh" if offset == 0 else "stale")
    if offset:
        assert result["action"] == "WAIT"


def test_insufficient_history_reports_candle_progress():
    one, five = candles()
    result = analyse(one[:20], five[:20], NOW)
    assert result["checks"]["history"] == "insufficient"
    assert result["checks"]["state"] == "waiting_history"
