"""Offline contracts for completed-candle option paper trading.

Fixtures describe fills and price paths independently of the engine. No broker
clients or application fixtures are imported.
"""

import importlib
import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest


def engine():
    try:
        return importlib.import_module("services.research.ema_3m_paper")
    except ModuleNotFoundError as exc:
        if exc.name == "services.research.ema_3m_paper":
            pytest.fail("The local 3-minute paper engine is not implemented")
        raise


def costs(**overrides):
    return {
        "schedule_id": "explicit-test-assumptions",
        "source": "deterministic fixture; not a broker tariff",
        "effective_from": "2026-09-01",
        "effective_to": "2026-10-31",
        "brokerage_per_order": 0,
        "exchange_rate": 0,
        "sebi_rate": 0,
        "gst_rate": 0,
        "stamp_buy_rate": 0,
        "stt_sell_rate": 0,
        "slippage_bps": 0,
    } | overrides


def minutes(n=12, start="2026-10-01 09:30", price=200):
    index = pd.date_range(start, periods=n, freq="min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price, "volume": 100},
        index=index,
        dtype=float,
    )


def signals(frame, locations=(0,), stop=197):
    return pd.DataFrame(
        {
            "stop": [stop] * len(locations),
            "ema9": [199] * len(locations),
            "ema20": [198] * len(locations),
        },
        index=frame.index[list(locations)],
    )


def three_minute_path(bars):
    """Expand declared 3m OHLC into complete 1m input with the same aggregate."""
    rows = []
    for opening, high, low, close in bars:
        rows.extend([(opening, high, low, close, 100)] * 3)
    index = pd.date_range("2026-10-01 09:15", periods=len(rows), freq="min", tz="Asia/Kolkata")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index)


def pullback_path():
    bars = [(100, 100.2, 99.8, 100)] * 30
    bars += [(c, c + 0.2, c - 0.2, c) for c in np.arange(100.5, 108, 0.5)]
    bars += [
        (106.5, 106.7, 104.8, 105.6),  # EMA touch; setup high 106.7
        (105.6, 107.2, 105.5, 107),  # bullish reclaim
        (108, 108.2, 107.8, 108),
        (107, 107.2, 105.8, 106.5),  # new setup, same bullish trend
        (106.5, 108.7, 106.3, 108.5),
    ]
    return three_minute_path(bars)


def test_fixed_signal_stop_and_tick_exact_three_r_target():
    e = engine()
    frame = minutes(price=200.03)
    frame.loc[frame.index[1], "high"] = 210
    result = e.simulate(frame, signals(frame, stop=197.03), e.PaperConfig(65, 0.05), costs())
    trade = result["trades"][0]
    assert (trade["entry_price"], trade["stop_price"], trade["target_price"]) == (
        200.05,
        197,
        209.2,
    )
    assert trade["quantity"] == 65
    assert trade["gross_pnl"] == pytest.approx(594.75)
    assert trade["reason"] == "target"
    assert result["complete"]
    json.dumps(result, allow_nan=False)


def test_prepare_discards_forming_future_and_after_hours_minutes():
    e = engine()
    frame = minutes(3, "2026-10-01 15:38")
    ready = e.prepare_minutes(frame, pd.Timestamp("2026-10-01 15:39:30+05:30"))
    assert list(ready.index) == [frame.index[0]]
    # The 15:39 minute becomes usable when completed; 15:40 is outside RTH.
    ready = e.prepare_minutes(frame, pd.Timestamp("2026-10-01 15:41+05:30"))
    assert list(ready.index) == list(frame.index[:2])


@pytest.mark.parametrize("breakage", ["naive", "duplicate", "unordered", "zero", "nan", "ohlc"])
def test_invalid_closed_candles_fail_closed(breakage):
    e = engine()
    frame = minutes(3)
    if breakage == "naive":
        frame.index = frame.index.tz_localize(None)
    elif breakage == "duplicate":
        frame.index = pd.DatetimeIndex([frame.index[0], frame.index[0], frame.index[2]])
    elif breakage == "unordered":
        frame = frame.iloc[::-1]
    elif breakage == "zero":
        frame.iloc[0, 0] = 0
    elif breakage == "nan":
        frame.iloc[0, 0] = np.nan
    else:
        frame.iloc[0, 1] = 100
    with pytest.raises(ValueError):
        e.prepare_minutes(frame, pd.Timestamp("2026-10-01 10:00+05:30"))


def test_aggregation_is_session_anchored_and_never_fills_missing_minutes():
    e = engine()
    frame = minutes(7, "2026-10-01 09:15", price=100)
    frame.loc[frame.index[2], ["open", "high", "low", "close", "volume"]] = (101, 103, 99, 102, 200)
    bars = e.aggregate_3m(frame.drop(frame.index[4]))
    assert list(bars.index) == [pd.Timestamp("2026-10-01 09:18+05:30")]
    assert tuple(bars.iloc[0][["open", "high", "low", "close", "volume"]]) == (
        100,
        103,
        99,
        102,
        400,
    )


def test_real_sdk_crossover_is_causal_and_requires_completed_warmup():
    e = engine()
    bars = [(100, 100.2, 99.8, 100)] * 30
    bars += [(102, 102.2, 101.8, 102), (103, 103.2, 102.8, 103)]
    frame = three_minute_path(bars)
    result = e.make_signals(frame, "crossover")
    assert list(result.index) == [pd.Timestamp("2026-10-01 10:48+05:30")]
    assert result.iloc[0]["stop"] < 102
    assert e.make_signals(frame.iloc[: 19 * 3], "crossover").empty
    prefix = e.make_signals(frame.iloc[:-3], "crossover")
    pd.testing.assert_frame_equal(result, prefix)


def test_real_sdk_pullback_repeats_without_a_new_supertrend_flip():
    e = engine()
    result = e.make_signals(pullback_path(), "pullback")
    assert list(result.index) == [
        pd.Timestamp("2026-10-01 11:36+05:30"),
        pd.Timestamp("2026-10-01 11:45+05:30"),
    ]
    assert (result["direction"] == -1).all()
    assert e.make_signals(pullback_path().iloc[: 46 * 3], "pullback").empty


def test_intraday_gap_resets_indicator_warmup_and_pullback_setup():
    e = engine()
    frame = pullback_path()
    # Removing one minute invalidates a bucket immediately before both reclaims.
    result = e.make_signals(frame.drop(frame.index[45 * 3 + 1]), "pullback")
    assert result.empty


def test_run_paper_cannot_use_a_forming_confirmation_bar():
    e = engine()
    frame = pullback_path().iloc[: 47 * 3]
    result = e.run_paper(
        frame,
        pd.Timestamp("2026-10-01 11:35:30+05:30"),
        "pullback",
        e.PaperConfig(65, 0.05),
        costs(),
    )
    assert result["summary"]["trade_count"] == 0
    assert not result["unresolved"]


@pytest.mark.parametrize(
    "stop,fee,reason", [(192.3, 0, "trade_risk_cap"), (192.35, 1.5, "trade_risk_cap")]
)
def test_risk_admission_counts_fees_without_squeezing_the_technical_stop(stop, fee, reason):
    e = engine()
    frame = minutes()
    result = e.simulate(
        frame, signals(frame, stop=stop), e.PaperConfig(65, 0.05), costs(brokerage_per_order=fee)
    )
    assert not result["trades"] and not result["unresolved"]
    assert result["rejected"][0]["reason"] == reason


def test_gap_up_at_next_open_is_rechecked_against_frozen_stop():
    e = engine()
    frame = minutes(price=205)
    result = e.simulate(frame, signals(frame, stop=197), e.PaperConfig(65, 0.05), costs())
    assert result["rejected"][0]["reason"] == "trade_risk_cap"


def test_premium_and_entry_fees_must_fit_available_capital():
    e = engine()
    frame = minutes(price=230)
    result = e.simulate(
        frame, signals(frame, stop=229), e.PaperConfig(65, 0.05), costs(brokerage_per_order=60)
    )
    assert result["rejected"][0]["reason"] == "capital"


def test_stop_first_on_ambiguous_candle_and_gap_stop_uses_worse_open():
    e = engine()
    frame = minutes()
    frame.loc[frame.index[1], ["high", "low"]] = (210, 196)
    result = e.simulate(frame, signals(frame), e.PaperConfig(65, 0.05), costs())
    assert result["trades"][0]["net_pnl"] == -195
    assert result["trades"][0]["ambiguous"]
    frame = minutes()
    frame.loc[frame.index[1], ["open", "high", "low", "close"]] = (190, 191, 189, 190)
    result = e.simulate(frame, signals(frame), e.PaperConfig(65, 0.05), costs())
    assert result["trades"][0]["exit_price"] == 190
    assert result["trades"][0]["net_pnl"] == -650


def test_target_gap_does_not_claim_a_better_fill_than_limit():
    e = engine()
    frame = minutes()
    frame.loc[frame.index[1], ["open", "high", "low", "close"]] = (220, 221, 219, 220)
    result = e.simulate(frame, signals(frame), e.PaperConfig(65, 0.05), costs())
    assert result["trades"][0]["exit_price"] == 209


def test_losses_apply_cooldown_but_signals_at_expiry_can_enter():
    e = engine()
    frame = minutes(15)
    frame.loc[frame.index[1], "low"] = 196
    frame.loc[frame.index[8], "high"] = 210
    result = e.simulate(frame, signals(frame, (0, 3, 7)), e.PaperConfig(65, 0.05), costs())
    assert len(result["trades"]) == 2
    assert any(r["reason"] == "cooldown" for r in result["rejected"])


def test_daily_remaining_allowance_blocks_next_trade_and_resets_next_day():
    e = engine()
    frame = minutes(15)
    for i in (1, 8):
        frame.loc[frame.index[i], "low"] = 196
    next_day = minutes(3, "2026-10-02 09:30")
    next_day.loc[next_day.index[1], "high"] = 210
    frame = pd.concat([frame, next_day])
    cfg = replace(e.PaperConfig(65, 0.05), max_daily_loss=300)
    result = e.simulate(frame, signals(frame, (0, 7, 15)), cfg, costs())
    assert len(result["trades"]) == 2
    assert any(r["reason"] == "daily_risk_cap" for r in result["rejected"])


def test_missing_minute_during_exposure_halts_and_qualifies_no_profitability():
    e = engine()
    frame = minutes().drop(pd.Timestamp("2026-10-01 09:32+05:30"))
    result = e.simulate(frame, signals(frame, (0, 5)), e.PaperConfig(65, 0.05), costs())
    assert not result["complete"]
    assert result["unresolved"][0]["reason"] == "missing_exposure_minute"
    assert result["summary"]["net_pnl"] is None
    assert not result["trades"]


def test_missing_immediate_execution_open_rejects_pending_signal():
    e = engine()
    frame = minutes().drop(pd.Timestamp("2026-10-01 09:30+05:30"))
    sig = pd.DataFrame(
        {"stop": [197]}, index=pd.DatetimeIndex([pd.Timestamp("2026-10-01 09:30+05:30")])
    )
    result = e.simulate(frame, sig, e.PaperConfig(65, 0.05), costs())
    assert result["rejected"][0]["reason"] == "missing_entry_minute"
    assert result["complete"]


def test_partial_session_open_exposure_is_unresolved_not_flat_at_last_close():
    e = engine()
    frame = minutes(3)
    result = e.simulate(frame, signals(frame), e.PaperConfig(65, 0.05), costs())
    assert not result["complete"]
    assert result["unresolved"][0]["reason"] == "end_of_data_open_position"
    assert result["summary"]["net_pnl"] is None


def test_entry_cutoff_and_flatten_use_observed_minutes_only():
    e = engine()
    frame = minutes(22, "2026-10-01 14:59")
    result = e.simulate(frame, signals(frame, (0, 1)), e.PaperConfig(65, 0.05), costs())
    assert result["trades"][0]["reason"] == "session_flatten"
    assert result["trades"][0]["exit_at"] == "2026-10-01T15:20:00+05:30"
    assert any(r["reason"] == "entry_window" for r in result["rejected"])


def test_duplicate_signals_are_rejected_and_later_stop_cannot_trail_position():
    e = engine()
    frame = minutes(4)
    frame.loc[frame.index[2], "low"] = 197.5
    frame.loc[frame.index[3], "high"] = 210
    sig = signals(frame, (0, 1), stop=197)
    sig.iloc[1, 0] = 199
    result = e.simulate(frame, sig, e.PaperConfig(65, 0.05), costs())
    assert result["trades"][0]["stop_price"] == 197
    assert result["trades"][0]["reason"] == "target"
    assert result["rejected"][0]["reason"] == "position_open"
    with pytest.raises(ValueError, match="duplicate"):
        e.simulate(frame, pd.concat([sig, sig.iloc[:1]]), e.PaperConfig(65, 0.05), costs())


def test_cost_schedule_is_mandatory_and_must_cover_dates():
    e = engine()
    frame = minutes()
    for schedule in ({}, costs(effective_to="2026-09-30")):
        with pytest.raises(ValueError):
            e.simulate(frame, signals(frame), e.PaperConfig(65, 0.05), schedule)


def test_run_paper_refuses_empty_evidence_but_reports_observed_coverage():
    e = engine()
    with pytest.raises(ValueError, match="no usable closed minutes"):
        e.run_paper(
            minutes(0),
            pd.Timestamp("2026-10-01 10:00+05:30"),
            "pullback",
            e.PaperConfig(65, 0.05),
            costs(),
        )
    frame = minutes(4, "2026-10-01 09:15")
    result = e.run_paper(
        frame,
        pd.Timestamp("2026-10-01 09:18:30+05:30"),
        "pullback",
        e.PaperConfig(65, 0.05),
        costs(),
    )
    assert result["quality"]["closed_regular_minutes"] == 3
    assert result["quality"]["forming_or_future_minutes"] == 1
    assert result["quality"]["signal_count"] == 0
    assert result["quality"]["first_observed"] == "2026-10-01T09:15:00+05:30"
    assert result["quality"]["last_observed"] == "2026-10-01T09:17:00+05:30"


@pytest.mark.parametrize("waiting_bars,want_signals", [(2, 1), (3, 0)])
def test_pullback_confirmation_expires_after_three_subsequent_completed_bars(
    waiting_bars, want_signals
):
    e = engine()
    frame = pullback_path().iloc[: 46 * 3]
    later = [(106, 106.2, 105.8, 106)] * waiting_bars
    later += [(105.6, 107.2, 105.5, 107)]
    tail = three_minute_path(later)
    tail.index = pd.date_range(
        frame.index[-1] + pd.Timedelta(minutes=1), periods=len(tail), freq="min", tz="Asia/Kolkata"
    )
    result = e.make_signals(pd.concat([frame, tail]), "pullback")
    assert len(result) == want_signals


@pytest.mark.parametrize(
    "first_target,next_price,next_stop,want_trades",
    [
        (False, 228, 225, 1),
        (True, 235, 232, 2),
    ],
)
def test_realized_net_cash_carries_across_daily_budget_resets(
    first_target, next_price, next_stop, want_trades
):
    e = engine()
    first = minutes(3)
    first.loc[first.index[1], "high" if first_target else "low"] = 210 if first_target else 196
    second = minutes(3, "2026-10-02 09:30", price=next_price)
    second.loc[second.index[1], "high"] = next_price + 10
    frame = pd.concat([first, second])
    sig = signals(frame, (0, 3))
    sig.iloc[1, 0] = next_stop
    result = e.simulate(frame, sig, e.PaperConfig(65, 0.05), costs())
    assert len(result["trades"]) == want_trades
    if not first_target:
        assert result["rejected"][0]["reason"] == "capital"


def test_rejected_risk_has_hand_checked_admission_diagnostics():
    e = engine()
    frame = minutes()
    result = e.simulate(frame, signals(frame, stop=192.3), e.PaperConfig(65, 0.05), costs())
    row = result["rejected"][0]
    assert row["entry_price"] == 200
    assert row["stop_price"] == 192.3
    assert row["target_price"] == 223.1
    assert row["quantity"] == 65
    assert row["planned_loss"] == 500.5
    assert row["max_trade_loss"] == 500
    assert row["remaining_daily_allowance"] == 1500
    assert row["required_cash"] == 13000
    assert row["available_cash"] == 15000


def test_adverse_slippage_affects_both_stop_risk_and_paper_pnl():
    e = engine()
    frame = minutes(3)
    frame.loc[frame.index[1], "low"] = 196
    result = e.simulate(frame, signals(frame), e.PaperConfig(65, 0.05), costs(slippage_bps=10))
    trade = result["trades"][0]
    assert trade["entry_price"] == 200.2
    assert trade["stop_price"] == 197
    assert trade["exit_price"] == 196.8
    assert trade["planned_loss"] == 221
    assert trade["net_pnl"] == -221


def test_entry_open_below_signal_stop_cannot_be_rescued_by_buy_slippage():
    e = engine()
    frame = minutes(3, price=196.9)
    result = e.simulate(
        frame, signals(frame, stop=197), e.PaperConfig(65, 0.05), costs(slippage_bps=10)
    )
    assert not result["trades"]
    assert not result["unresolved"]
    assert result["rejected"][0]["reason"] == "invalid_stop"


@pytest.mark.parametrize("missing_boundary", ["opening", "closing"])
def test_missing_session_boundary_cannot_carry_ready_indicators_overnight(missing_boundary):
    e = engine()
    prior = minutes(385, "2026-09-30 09:15", price=100)
    current = minutes(21, "2026-10-01 09:15", price=101)
    if missing_boundary == "opening":
        current = current.drop(current.index[0])
    else:
        prior = prior.drop(pd.Timestamp("2026-09-30 15:37+05:30"))
    result = e.make_signals(pd.concat([prior, current]), "pullback")
    features = result.attrs["features"]
    today = features.loc[features.index.date == current.index[0].date()]
    assert not today["ready"].any()
    assert result.empty


def test_intact_regular_session_boundaries_preserve_overnight_warmup():
    e = engine()
    prior = minutes(385, "2026-09-30 09:15", price=100)
    current = minutes(3, "2026-10-01 09:15", price=101)
    features = e.make_signals(pd.concat([prior, current]), "pullback").attrs["features"]
    assert features.loc[pd.Timestamp("2026-10-01 09:18+05:30"), "ready"]


def test_missing_opening_minute_cannot_create_a_paper_winner_from_old_warmup():
    e = engine()
    prior_bars = [(c, c + 0.2, c - 0.2, c) for c in 100 + np.arange(128) * 0.5]
    prior = three_minute_path(prior_bars)
    prior.index -= pd.Timedelta(days=1)
    prior = pd.concat([prior, minutes(1, "2026-09-30 15:39", price=163.5)])
    today = three_minute_path(
        [
            (164, 164.2, 163.8, 164),
            (164.5, 164.7, 164.3, 164.5),
            (165, 165.2, 164.8, 165),
            (163, 163.2, 161, 162),
            (162, 165, 161.9, 164.8),
            (164.8, 166.2, 164.7, 166),
            (166, 180, 165.8, 179),
        ]
    )
    today = today.drop(today.index[0])
    result = e.run_paper(
        pd.concat([prior, today]),
        pd.Timestamp("2026-10-01 09:36+05:30"),
        "pullback",
        e.PaperConfig(65, 0.05),
        costs(),
    )
    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["net_pnl"] == 0
