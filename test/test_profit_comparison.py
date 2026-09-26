"""Sandbox-only shadow outcomes for identical admitted entries."""

from datetime import UTC, datetime, timedelta

import pytest

from services.strategy_module.profit_comparison import (
    observe_comparison,
    start_comparison,
    summarize_comparison,
)

START = datetime(2026, 9, 25, 4, 0, tzinfo=UTC)


def _started(**changes):
    params = {
        "run_id": 17,
        "position_ref": "entry-17",
        "broker_connection_id": "pinned-kotak",
        "symbol": "NIFTY29SEP2623500CE",
        "exchange": "NFO",
        "run_open_positions": 1,
        "mode": "sandbox",
        "side": "BUY",
        "entry_price": 100.0,
        "quantity": 10,
        "planned_stop_risk": 200.0,
        "overall_stop_remaining": 150.0,
        "daily_allowance_remaining": 100.0,
        "baseline_risk": {"combined_stoploss": 150.0, "combined_target": 300.0},
        "baseline_leg_state": {
            "leg_id": 1,
            "position": "B",
            "entry_avg": 100.0,
            "qty": 10,
            "sl_pts": 15,
            "target_pts": 30,
        },
        "entry_at": START,
        "cutoff_at": START + timedelta(hours=5),
    }
    params.update(changes)
    return start_comparison(**params)


def _observe(state, seconds, ltp, **changes):
    params = {
        "observed_at": START + timedelta(seconds=seconds),
        "received_at": START + timedelta(seconds=seconds),
        "ltp": ltp,
        "source": "prospective",
        "broker_connection_id": "pinned-kotak",
        "symbol": "NIFTY29SEP2623500CE",
        "exchange": "NFO",
    }
    params.update(changes)
    return observe_comparison(state, **params)


def test_entry_budget_is_frozen_at_smallest_admitted_cap():
    state = _started()
    assert state["risk_budget"] == 100.0
    _observe(state, 10, 106.0)
    assert state["risk_budget"] == 100.0
    assert state["profiles"]["early"]["lock_floor"] == pytest.approx(10.0)
    assert state["profiles"]["room"]["lock_floor"] is None


def test_replay_without_book_records_trigger_only_not_a_realized_fill():
    state = _started(daily_allowance_remaining=40.0)
    _observe(state, 10, 106.0, source="replay")
    _observe(state, 20, 104.0, source="replay")
    early = state["profiles"]["early"]
    assert early["status"] == "trigger_only"
    assert early["trigger_mark_pnl"] == pytest.approx(40.0)
    assert early["simulated_realized_pnl"] is None
    assert early["missed_fill"] is True
    assert state["profiles"]["baseline"]["status"] == "observing"


def test_prospective_exit_uses_bid_and_available_quantity_and_keeps_remainder():
    state = _started(daily_allowance_remaining=40.0)
    _observe(state, 10, 106.0)
    _observe(
        state,
        20,
        104.0,
        bid=103.5,
        ask=104.0,
        bid_qty=4,
        ask_qty=10,
        quote_at=START + timedelta(seconds=20),
    )
    early = state["profiles"]["early"]
    assert early["status"] == "partial"
    assert early["filled_qty"] == 4
    assert early["simulated_realized_pnl"] == pytest.approx(14.0)
    assert early["remaining_qty"] == 6
    assert early["trigger_quote"]["bid"] == 103.5
    assert early["trigger_quote"]["bid_qty"] == 4.0
    assert early["fill_events"][0]["quantity"] == 4
    assert early["fill_events"][0]["price"] == 103.5
    _observe(
        state,
        30,
        103.0,
        bid=102.5,
        ask=103.0,
        bid_qty=6,
        ask_qty=10,
        quote_at=START + timedelta(seconds=30),
    )
    assert early["status"] == "closed"
    assert early["filled_qty"] == 10
    assert early["simulated_realized_pnl"] == pytest.approx(29.0)


def test_stale_book_cannot_turn_protective_trigger_into_a_fill():
    state = _started(daily_allowance_remaining=40.0)
    _observe(state, 10, 106.0)
    _observe(
        state,
        20,
        104.0,
        bid=103.5,
        ask=104.0,
        bid_qty=10,
        ask_qty=10,
        quote_at=START + timedelta(seconds=10),
    )
    early = state["profiles"]["early"]
    assert early["status"] == "exit_pending"
    assert early["filled_qty"] == 0
    assert early["missed_fill"] is True


def test_invalid_modes_and_zero_risk_cannot_start_comparison():
    with pytest.raises(ValueError, match="sandbox"):
        _started(mode="live")
    with pytest.raises(ValueError, match="risk"):
        _started(planned_stop_risk=0)


def test_summary_reports_peak_giveback_drawdown_and_unknown_fees():
    state = _started(daily_allowance_remaining=40.0)
    _observe(state, 10, 106.0)
    _observe(state, 20, 104.0, source="replay")
    result = summarize_comparison(state)
    early = result["profiles"]["early"]
    assert early["peak_profit"] == pytest.approx(60.0)
    assert early["peak_to_exit_giveback"] == pytest.approx(20.0)
    assert early["max_drawdown"] == pytest.approx(20.0)
    assert early["fees"] is None
    assert early["outcome_quality"] == "trigger_only_estimate"


def test_cutoff_uses_book_if_available_and_never_invents_an_exit_price():
    state = _started(cutoff_at=START + timedelta(seconds=30))
    _observe(state, 30, 101.0)
    assert state["profiles"]["baseline"]["status"] == "cutoff"
    assert state["profiles"]["baseline"]["simulated_realized_pnl"] is None
    assert state["profiles"]["baseline"]["reason"] == "intraday_cutoff"

    filled = _started(cutoff_at=START + timedelta(seconds=30), position_ref="filled")
    _observe(
        filled,
        30,
        101.0,
        bid=100.5,
        ask=101.0,
        bid_qty=10,
        ask_qty=10,
        quote_at=START + timedelta(seconds=30),
    )
    assert filled["profiles"]["baseline"]["status"] == "closed"
    assert filled["profiles"]["baseline"]["simulated_realized_pnl"] == pytest.approx(5.0)


def test_out_of_order_observation_cannot_move_a_profit_floor_backward():
    state = _started()
    _observe(state, 10, 106.0)
    with pytest.raises(ValueError, match="ordered"):
        _observe(state, 9, 101.0)
    assert state["profiles"]["early"]["lock_floor"] == pytest.approx(10.0)


def test_stale_prospective_market_time_cannot_advance_a_floor():
    state = _started()
    with pytest.raises(ValueError, match="stale"):
        _observe(state, 10, 106, received_at=START + timedelta(seconds=20))
    assert state["profiles"]["early"]["lock_floor"] is None


def test_summary_labels_earlier_exit_relative_to_baseline():
    state = _started(daily_allowance_remaining=40, cutoff_at=START + timedelta(seconds=30))
    _observe(state, 10, 106)
    _observe(
        state,
        20,
        104,
        bid=103.5,
        ask=104,
        bid_qty=10,
        ask_qty=10,
        quote_at=START + timedelta(seconds=20),
    )
    assert summarize_comparison(state)["profiles"]["early"]["early_exit_vs_baseline"] is None
    _observe(
        state,
        30,
        101,
        bid=100.5,
        ask=101,
        bid_qty=10,
        ask_qty=10,
        quote_at=START + timedelta(seconds=30),
    )
    result = summarize_comparison(state)
    assert result["profiles"]["early"]["early_exit_vs_baseline"] is True
    assert result["profiles"]["early"]["trigger_mark_pnl"] == pytest.approx(40.0)


def test_baseline_uses_existing_per_leg_stop_before_aggregate_stop():
    state = _started(
        baseline_leg_state={
            "leg_id": 1,
            "position": "B",
            "entry_avg": 100.0,
            "qty": 10,
            "sl_pts": 5,
            "target_pts": 30,
        }
    )
    _observe(state, 10, 94.0, source="replay")
    baseline = state["profiles"]["baseline"]
    assert baseline["status"] == "trigger_only"
    assert baseline["reason"] == "sl"
    assert state["profiles"]["early"]["status"] == "observing"


def test_baseline_leg_trail_ratchets_using_shared_risk_rules():
    state = _started(
        baseline_leg_state={
            "leg_id": 1,
            "position": "B",
            "entry_avg": 100.0,
            "qty": 10,
            "sl_pts": 5,
            "target_pts": 30,
            "trail_x": 2,
            "trail_y": 1,
        }
    )
    _observe(state, 10, 106.0)
    assert state["baseline_leg_state"]["effective_sl"] == pytest.approx(98.0)
    _observe(state, 20, 97.0, source="replay")
    assert state["profiles"]["baseline"]["reason"] == "sl"


def test_comparison_rejects_unscoped_run_or_wrong_quote_identity():
    with pytest.raises(ValueError, match="single open position"):
        _started(run_open_positions=2)
    state = _started()
    with pytest.raises(ValueError, match="identity"):
        _observe(state, 10, 106, symbol="SENSEX25SEP2680000CE")
    assert state["profiles"]["early"]["peak_profit"] == 0.0


def test_quote_after_cutoff_cannot_simulate_a_late_exit():
    state = _started(cutoff_at=START + timedelta(seconds=20))
    _observe(state, 10, 106)
    with pytest.raises(ValueError, match="cutoff"):
        _observe(
            state,
            21,
            104,
            bid=103.5,
            ask=104,
            bid_qty=10,
            ask_qty=10,
            quote_at=START + timedelta(seconds=21),
        )
    assert state["profiles"]["early"]["filled_qty"] == 0


def test_entry_records_local_confirmation_time_provenance():
    state = _started()
    assert state["entry_timestamp_source"] == "local_confirmation"
    assert summarize_comparison(state)["entry_timestamp_source"] == "local_confirmation"
