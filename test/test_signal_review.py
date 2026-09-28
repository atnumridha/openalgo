"""Diagnostic recording must not change signal decisions or submit orders."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from services.strategy_module import scalping


def frames():
    index = pd.date_range("2026-09-15 09:20", periods=700, freq="5min", tz="Asia/Kolkata")
    close = 25000 + np.sin(np.arange(700) / 7) * 80 + np.arange(700) * 0.2
    five = pd.DataFrame(
        {"open": close - 2, "high": close + 8, "low": close - 8, "close": close}, index=index
    )
    minute = five.resample("1min").ffill()
    daily = pd.DataFrame(
        {"open": 24990.0, "high": 25010.0, "low": 24980.0, "close": 25000.0},
        index=pd.date_range("2025-01-01", periods=650, tz="Asia/Kolkata"),
    )
    return {"five": five, "bank": five * 2, "minute": minute, "daily": daily}


@pytest.mark.parametrize(
    "profile", ["ema915", "macd200", "ema5", "regime50200", "box15", "sma_macd", "bollinger"]
)
def test_review_contains_exact_decision_and_serializable_indicators(profile):
    from services.strategy_module.signal_review import explain

    inputs = frames()
    result = scalping.signals_for_profile(profile, **inputs)
    expected = inputs["minute" if profile in {"box15", "ema5"} else "five"].index[-1]
    review = explain(profile, inputs, result, expected)
    actual = result.loc[expected, "direction"] if expected in result.index else ""
    assert review["direction"] == actual
    assert len(review["rules"]) >= 2
    assert review["checks"]
    assert review["metrics"]
    assert review["bar_at"] == expected.isoformat()
    json.dumps(review, allow_nan=False)


def test_missing_expected_candle_is_unknown_not_a_failed_setup():
    from services.strategy_module.signal_review import explain

    inputs = frames()
    result = scalping.signals_for_profile("ema915", **inputs)
    expected = inputs["five"].index[-1] + pd.Timedelta(minutes=5)
    review = explain("ema915", inputs, result, expected)
    assert review["data_ready"] is False
    assert not review["metrics"]
    assert review["direction"] is None


def test_latest_signal_captures_expired_signal_and_history_without_reusing_it(monkeypatch):
    from services import indicator_service as history

    now = datetime(2026, 9, 28, 10, 1, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    bars = frames()["five"]
    at = pd.Timestamp("2026-09-28 10:00", tz="Asia/Kolkata")
    monkeypatch.setattr(
        history,
        "current_completed_bar_start",
        lambda *a: at.to_pydatetime() - pd.Timedelta(minutes=5),
    )
    monkeypatch.setattr(
        history, "fetch_history_cached", lambda *a, **k: {"status": "success", "data": []}
    )
    monkeypatch.setattr(scalping, "closed_frame", lambda *a: bars)
    monkeypatch.setattr(
        scalping,
        "signals_for_profile",
        lambda *a, **k: pd.DataFrame({"direction": ["CE"]}, index=[at]),
    )
    audit = {}
    with pytest.raises(scalping.WaitingForSignal, match="expired"):
        scalping.latest_signal("sma_macd", object(), now, audit=audit)
    assert audit["expected_bar_at"] == at.isoformat()
    assert audit["history"][0]["candles"] == len(bars)
    assert audit["signal_age_seconds"] == 70
