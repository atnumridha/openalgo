"""Distinct receiver rules use closed bars and buy options in either direction."""

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

IST = ZoneInfo("Asia/Kolkata")


def candles(rows, *, interval=5, end="2026-09-28 12:00"):
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close"],
        index=pd.date_range(end=end, periods=len(rows), freq=f"{interval}min", tz=IST),
    )


def reflected(frame):
    result = frame.copy()
    result["open"], result["close"] = 300 - frame.open, 300 - frame.close
    result["high"], result["low"] = 300 - frame.low, 300 - frame.high
    return result


def confirmation():
    return candles([[90, 97, 89, 95], [95, 102, 94, 100], [100, 107, 99, 105]], interval=15)


def trend_bars():
    closes = np.linspace(85, 110, 40)
    rows = [[c - 0.5, c + 0.5, c - 1, c] for c in closes]
    rows[-1] = [107, 111, 106, 110.8]
    return candles(rows)


def momentum_bars():
    return candles([[99, 101, 98, 100]] * 12 + [[100, 107, 99.8, 106.8]])


def retest_bars():
    return candles([[99, 101, 98, 100]] * 12 + [[100, 105, 99.8, 104], [103, 104, 100.8, 103.8]])


@pytest.mark.parametrize(
    "profile,builder",
    [
        ("receiver_trend", trend_bars),
        ("receiver_momentum", momentum_bars),
        ("receiver_retest", retest_bars),
    ],
)
@pytest.mark.parametrize("bearish", [False, True])
def test_each_rule_buys_ce_or_pe_without_shorting(profile, builder, bearish):
    from services.strategy_module import receiver_rules

    five, fifteen = builder(), confirmation()
    if bearish:
        five, fifteen = reflected(five), reflected(fifteen)
    result = receiver_rules.evaluate(profile, five, fifteen, five.index[-1])
    assert result["direction"] == ("PE" if bearish else "CE")
    assert result["position"] == "B"
    assert result["timestamp"] == five.index[-1].isoformat()


def test_retest_requires_a_later_closed_bar_and_cannot_repeat_on_another_bar():
    from services.strategy_module import receiver_rules

    five = retest_bars()
    at = five.index[-1]
    first = receiver_rules.evaluate(
        "receiver_retest", five.iloc[:-1], confirmation(), at - pd.Timedelta(minutes=5)
    )
    assert first["direction"] == ""
    assert first["checks"] == {"confirmation": "CE", "setup": "none"}
    assert receiver_rules.evaluate("receiver_retest", five, confirmation(), at)["direction"] == "CE"
    later = pd.concat([five, candles([[103, 104.5, 100.9, 104]], end="2026-09-28 12:05")])
    assert (
        receiver_rules.evaluate("receiver_retest", later, confirmation(), later.index[-1])[
            "direction"
        ]
        == ""
    )


@pytest.mark.parametrize("profile", ["receiver_trend", "receiver_retest", "receiver_momentum"])
def test_flat_or_contradictory_confirmation_never_creates_an_entry(profile):
    from services.strategy_module import receiver_rules

    flat = candles([[100, 101, 99, 100]] * 40)
    assert receiver_rules.evaluate(profile, flat, confirmation(), flat.index[-1])["direction"] == ""
    five = {
        "receiver_trend": trend_bars,
        "receiver_retest": retest_bars,
        "receiver_momentum": momentum_bars,
    }[profile]()
    assert (
        receiver_rules.evaluate(profile, five, reflected(confirmation()), five.index[-1])[
            "direction"
        ]
        == ""
    )


def test_future_candles_cannot_change_a_closed_signal_or_supply_confirmation():
    from services.strategy_module import receiver_rules

    five = momentum_bars()
    at = five.index[-1]
    expected = receiver_rules.evaluate("receiver_momentum", five, confirmation(), at)
    future = candles([[107, 109, 89, 90]], end="2026-09-28 12:05")
    assert (
        receiver_rules.evaluate("receiver_momentum", pd.concat([five, future]), confirmation(), at)
        == expected
    )
    assert (
        receiver_rules.evaluate(
            "receiver_momentum", five, confirmation().iloc[1:].shift(freq="15min"), at
        )["direction"]
        == ""
    )


def test_missing_bar_stale_confirmation_and_duplicate_bars_fail_closed():
    from services.strategy_module import receiver_rules

    five = momentum_bars()
    at = five.index[-1]
    assert (
        receiver_rules.evaluate("receiver_momentum", five.drop(five.index[-3]), confirmation(), at)[
            "direction"
        ]
        == ""
    )
    assert (
        receiver_rules.evaluate("receiver_momentum", five, confirmation().shift(freq="-15min"), at)[
            "direction"
        ]
        == ""
    )
    with pytest.raises(ValueError):
        receiver_rules.evaluate(
            "receiver_momentum", pd.concat([five, five.iloc[-1:]]), confirmation(), at
        )


def test_momentum_breakout_does_not_masquerade_as_a_retest_or_trend_pullback():
    from services.strategy_module import receiver_rules

    five = momentum_bars()
    at = five.index[-1]
    assert (
        receiver_rules.evaluate("receiver_momentum", five, confirmation(), at)["direction"] == "CE"
    )
    assert receiver_rules.evaluate("receiver_retest", five, confirmation(), at)["direction"] == ""
    assert receiver_rules.evaluate("receiver_trend", five, confirmation(), at)["direction"] == ""


@pytest.mark.parametrize(
    "profile,builder",
    [
        ("receiver_trend", trend_bars),
        ("receiver_retest", retest_bars),
        ("receiver_momentum", momentum_bars),
    ],
)
@pytest.mark.parametrize("bearish", [False, True])
def test_diagnostics_report_each_direction_setup_and_confirmation(profile, builder, bearish):
    from services.strategy_module import receiver_rules

    five, higher = builder(), confirmation()
    if bearish:
        five, higher = reflected(five), reflected(higher)
    signal = receiver_rules.evaluate(profile, five, higher, five.index[-1])
    diagnostic = receiver_rules.diagnostics(signal)
    assert diagnostic["data_ready"] is True
    assert len(diagnostic["checks"]) == 4
    for check in diagnostic["checks"]:
        assert check["passed"] is (check["side"] == signal["direction"])
        assert check["label"]
    conflict = receiver_rules.evaluate(profile, five, reflected(higher), five.index[-1])
    checks = receiver_rules.diagnostics(conflict)["checks"]
    for side in ("CE", "PE"):
        outcomes = [check["passed"] for check in checks if check["side"] == side]
        assert sorted(outcomes) == [False, True]


def test_diagnostics_mark_missing_warmup_unknown_instead_of_failed_setup():
    from services.strategy_module import receiver_rules

    five = momentum_bars().iloc[-5:]
    signal = receiver_rules.evaluate("receiver_momentum", five, confirmation(), five.index[-1])
    diagnostic = receiver_rules.diagnostics(signal)
    assert diagnostic["data_ready"] is False
    assert all(check["passed"] is None for check in diagnostic["checks"])
