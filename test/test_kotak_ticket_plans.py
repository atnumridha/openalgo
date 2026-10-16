from services.kotak_assistant import ticket_plans
from services.kotak_assistant.analysis import DEFAULTS


def test_option_stop_uses_lower_of_atr_or_confirmed_swing():
    bars = [{"time": 60 * i, "open": 95, "high": 100, "low": 92, "close": 96} for i in range(20)]
    bars[15]["low"] = 75
    p = ticket_plans.trend_plan(100, bars, 65, 0.05, 65, "NFO", DEFAULTS, 2, "2026-10-16")
    assert p["sl"] <= 74.95
    assert p["target"] == round(100 + 2 * (100 - p["sl"]), 2)


def test_missing_option_atr_does_not_manufacture_stop():
    p = ticket_plans.trend_plan(100, [], 65, 0.05, 65, "NFO", DEFAULTS, 2, "2026-10-16")
    assert not p["fits"] and "ATR" in p["reason"]
