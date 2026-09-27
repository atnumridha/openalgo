"""Causality, conservative execution and honest denominators for EMA scalps."""

import numpy as np
import pandas as pd
import pytest
from test_trading_research import fees

from services.research.ema_scalp import (
    chart_outcome,
    indicators,
    option_outcome,
    select_itm,
    signals,
    summarize,
)


def frame(count=100):
    index = pd.date_range("2025-01-01 09:20", periods=count, freq="5min", tz="Asia/Kolkata")
    close = 100 + np.arange(count) * 0.5 + np.sin(np.arange(count))
    return pd.DataFrame(
        {"open": close - 0.4, "high": close + 0.5, "low": close - 0.8, "close": close},
        index=index,
    )


def minutes():
    index = pd.date_range("2025-01-01 11:01", periods=17, freq="min", tz="Asia/Kolkata")
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=index)


def setup(direction="CE"):
    return {
        "timestamp": "2025-01-01T11:00:00+05:30",
        "direction": direction,
        "low": 98.0,
        "high": 102.0,
        "close": 100.0,
    }


def test_features_and_signals_do_not_change_when_future_is_appended():
    f = frame()
    a, b = indicators(f.iloc[:90]), indicators(f)
    pd.testing.assert_frame_equal(a, b.iloc[:90])
    pd.testing.assert_frame_equal(
        signals(a, a, slope=0.1, confirm=True), signals(b, b, slope=0.1, confirm=True).iloc[:90]
    )


def test_bullish_pin_rejection_mirrors_bearish_and_missing_confirmation_blocks():
    f = pd.DataFrame(
        [
            {
                "open": 103.0,
                "high": 105.0,
                "low": 100.0,
                "close": 104.5,
                "ema9": 102.0,
                "ema15": 101.0,
                "slope9": 0.3,
                "slope15": 0.2,
                "atr": 2.0,
                "prior_atr": 2.0,
                "prior_high": 110.0,
                "prior_low": 90.0,
                "ready": True,
            }
        ],
        index=pd.DatetimeIndex([setup()["timestamp"]]),
    )
    assert signals(f, f, slope=0.1, confirm=True).iloc[0].direction == "CE"
    missing = f.iloc[:0]
    assert signals(f, missing, slope=0.1, confirm=True).iloc[0].direction == ""
    blocked = f.copy()
    blocked["prior_high"] = 105.0
    assert signals(f, blocked, slope=0.1, confirm=True).iloc[0].direction == ""
    reflected = f.copy()
    for a, b in (
        ("open", "open"),
        ("close", "close"),
        ("high", "low"),
        ("low", "high"),
        ("ema9", "ema9"),
        ("ema15", "ema15"),
        ("prior_high", "prior_low"),
        ("prior_low", "prior_high"),
    ):
        reflected[a] = 210 - f[b]
    reflected[["slope9", "slope15"]] *= -1
    assert signals(reflected, reflected, slope=0.1, confirm=True).iloc[0].direction == "PE"


def test_gap_in_signal_history_requires_new_contiguous_warmup():
    f = frame(90).drop(frame(90).index[85])
    assert not indicators(f).iloc[85:88].ready.any()


@pytest.mark.parametrize("direction", ["CE", "PE"])
def test_two_r_target_and_stop_first_ambiguity(direction):
    f = minutes()
    f.loc[f.index[1], ["high", "low"]] = [105, 95]
    result = chart_outcome(setup(direction), f, 15)
    assert result["reason"] == "sl" and result["ambiguous"]
    assert result["r"] == pytest.approx(-1)
    f.loc[f.index[1], ["high", "low"]] = [104, 99] if direction == "CE" else [101, 96]
    result = chart_outcome(setup(direction), f, 15)
    assert result["reason"] == "target" and result["r"] == pytest.approx(2)


def test_time_deadline_missing_minute_and_gap_stop():
    f = minutes()
    f.loc[f.index[15], "high"] = 110
    result = chart_outcome(setup(), f, 15)
    assert result["reason"] == "time" and result["exit_at"].endswith("11:15:00+05:30")
    assert chart_outcome(setup(), f.drop(f.index[3]), 15)["reason"] == "missing_minute"
    f.loc[f.index[1], ["open", "high", "low", "close"]] = [97, 99, 96, 98]
    assert chart_outcome(setup(), f, 15)["r"] == pytest.approx(-1.5)


def test_itm_selection_uses_observed_quotes_and_historical_lots_not_affordability():
    quotes = pd.DataFrame(
        [
            {
                "expiry": "2025-01-02",
                "strike": 100.0,
                "option_type": "CE",
                "volume": 1000,
                "close": 80.0,
            },
            {
                "expiry": "2025-01-02",
                "strike": 95.0,
                "option_type": "CE",
                "volume": 1000,
                "close": 200.0,
            },
            {
                "expiry": "2025-01-03",
                "strike": 99.0,
                "option_type": "CE",
                "volume": 1000,
                "close": 50.0,
            },
        ]
    )
    listing = {(r.expiry, r.strike, r.option_type): {"lot_size": 75} for r in quotes.itertuples()}
    selected = select_itm(quotes, listing, spot=100, direction="CE", day="2025-01-01")
    assert selected["strike"] == 95 and selected["lot_size"] == 75
    assert select_itm(quotes, {}, spot=100, direction="CE", day="2025-01-01") is None


def test_option_fill_waits_for_observed_index_exit_and_uses_costs_and_whole_lots():
    f = minutes()
    f["volume"] = 1000
    f.loc[f.index[5], ["open", "high", "close"]] = [102, 103, 102]
    trade = chart_outcome(setup(), minutes(), 5)
    contract = {"lot_size": 75, "multiplier": 1, "tick_size": 0.05}
    result = option_outcome(trade, f, contract, fees(slippage_bps=0))
    assert result["exit_price"] == 102
    assert result["exit_fill_at"].endswith("11:05:00+05:30")
    assert result["gross_pnl"] == 150 and result["net_pnl"] < 150
    assert result["affordable"]
    f.loc[f.index[3], "volume"] = 0
    assert option_outcome(trade, f, contract, fees())["reason"] == "missing_or_untradeable_minute"


def test_summary_counts_timeouts_and_unresolved_without_inflating_accuracy():
    records = [
        {"reason": "target", "r": 2.0, "points": 4.0, "day": "2025-01-01", "ambiguous": False},
        {"reason": "time", "r": 0.5, "points": 1.0, "day": "2025-01-01", "ambiguous": False},
        {"reason": "sl", "r": -1.0, "points": -2.0, "day": "2025-01-02", "ambiguous": True},
        {
            "reason": "missing_minute",
            "r": None,
            "points": None,
            "day": "2025-01-02",
            "ambiguous": False,
        },
    ]
    result = summarize(records)
    assert result["completed"] == 3 and result["unresolved"] == 1
    assert result["win_rate"] == pytest.approx(2 / 3)
    assert result["target_rate"] == pytest.approx(1 / 3)
    assert result["wins_over_all_attempts"] == 0.5


def test_screening_rejects_conflicts_invalid_prices_and_reserved_rows(tmp_path):
    import json

    from scripts.research_ema_scalp import screen_broker

    path = tmp_path / "candles.json"
    rows = [
        ["2025-01-01T09:15:00+05:30", 100, 102, 99, 101, 0],
        ["2025-01-01T09:15:00+05:30", 100, 102, 99, 101, 0],
        ["2025-01-01T09:16:00+05:30", 100, 102, 99, 101, 0],
        ["2025-01-01T09:16:00+05:30", 101, 103, 99, 102, 0],
        ["2025-01-01T09:17:00+05:30", 100, 99, 98, 101, 0],
        ["2026-04-24T09:15:00+05:30", 100, 102, 99, 101, 0],
    ]
    path.write_text(json.dumps({"raw_candles": rows}))
    bars, audit = screen_broker([path], 1)
    assert len(bars) == 1 and bars.index[0].strftime("%H:%M") == "09:16"
    assert audit["identical_duplicates_removed"] == 1 and audit["rejected"] == 3
    assert audit["raw_rows"] == 5


def test_serial_study_cannot_open_overlapping_positions_or_exceed_daily_cap():
    from scripts.research_ema_scalp import run_variant

    index = pd.date_range("2025-01-01 11:00", periods=10, freq="5min", tz="Asia/Kolkata")
    signal_frame = pd.DataFrame(
        {"direction": "CE", "low": 98, "high": 102, "close": 100}, index=index
    )
    minute_index = pd.date_range("2025-01-01 11:01", periods=70, freq="min", tz="Asia/Kolkata")
    quotes = pd.DataFrame({"open": 100, "high": 101, "low": 99, "close": 100}, index=minute_index)
    trades, skipped = run_variant(signal_frame, quotes, 15)
    assert len(trades) == 3
    assert [t["timestamp"][11:16] for t in trades] == ["11:00", "11:15", "11:30"]
    assert skipped == {"position_open": 6, "daily_three_entry_cap": 1}


def test_option_quote_duplicates_fail_and_entry_cost_can_make_lot_unaffordable():
    f = minutes()
    f["volume"] = 1000
    trade = chart_outcome(setup(), f, 5)
    contract = {"lot_size": 80, "multiplier": 1, "tick_size": 0.05}
    result = option_outcome(trade, f, contract, fees(slippage_bps=0))
    assert not result["affordable"] and result["premium_with_entry_fees"] > 8000
    duplicate = pd.concat([f.iloc[:1], f]).sort_index()
    assert (
        option_outcome(trade, duplicate, contract, fees())["reason"]
        == "missing_or_untradeable_minute"
    )


def test_option_audit_retains_unresolved_index_attempts_in_its_denominator(tmp_path):
    from scripts.research_ema_scalp import audit_options

    trade = setup() | {"r": None, "reason": "missing_minute"}
    results = audit_options([trade], tmp_path, "test-manifest", fees())
    for scenario in ("base", "stress"):
        assert results[scenario]["attempts"] == 1
        assert results[scenario]["unavailable"] == {"unresolved_index_exit": 1}
        assert results[scenario]["all_priced"]["count"] == 0


def test_tiny_samples_do_not_get_zero_width_confidence_intervals():
    result = summarize(
        [{"reason": "target", "r": 2.0, "points": 4.0, "day": "2025-01-01", "ambiguous": False}]
    )
    assert result["win_rate"] == 1
    assert result["win_rate_day_block_95"] is None


def test_25k_capital_changes_affordability_but_never_prices_or_returns():
    f = minutes()
    f["volume"] = 1000
    trade = chart_outcome(setup(), f, 5)
    contract = {"lot_size": 150, "multiplier": 1, "tick_size": 0.05}
    small = option_outcome(trade, f, contract, fees(), capital=10000)
    larger = option_outcome(trade, f, contract, fees(), capital=25000)
    assert not small["affordable"] and larger["affordable"]
    assert {k: v for k, v in small.items() if k != "affordable"} == {
        k: v for k, v in larger.items() if k != "affordable"
    }
    with pytest.raises(ValueError):
        option_outcome(trade, f, contract, fees(), capital=-1)
