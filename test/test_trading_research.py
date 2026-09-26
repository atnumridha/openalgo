"""Deterministic replay must refuse missing evidence and avoid future fills."""

import copy
from datetime import datetime, timedelta, timezone

import pytest

from services.research import dataset, replay


def payload(days=1):
    metadata = {
        "underlying_symbol": "NIFTY",
        "timezone": "Asia/Kolkata",
        "bar_minutes": 5,
        "timestamp_convention": "bar_close",
        "session_close": "15:25",
        "source_reference": "fixture supplied by tester",
        "contracts": [
            {
                "symbol": "NIFTY_CE",
                "underlying": "NIFTY",
                "exchange": "NFO",
                "option_type": "CE",
                "strike": 100,
                "expiry": "2026-12-31",
                "lot_size": 25,
                "multiplier": 1,
                "segment": "index",
            }
        ],
    }
    rows = []
    for day in range(days):
        for index, price in enumerate([100, 101, 103, 105, 107, 109]):
            at = datetime(
                2026, 1, 1, 9, 20, tzinfo=timezone(timedelta(hours=5, minutes=30))
            ) + timedelta(days=day, minutes=5 * index)
            rows.append(
                {
                    "symbol": "NIFTY",
                    "timestamp": at.isoformat(),
                    "open": price - 1,
                    "high": price + 0.5,
                    "low": price - 1,
                    "close": price,
                    "volume": 100,
                }
            )
            rows.append(
                {
                    "symbol": "NIFTY_CE",
                    "timestamp": at.isoformat(),
                    "open": 100,
                    "high": 125,
                    "low": 75,
                    "close": 101,
                    "volume": 100,
                }
            )
    return {"name": "fixture", "provider": "test", "metadata": metadata, "rows": rows}


def fees(**overrides):
    value = {
        "schedule_id": "test-2026",
        "source": "explicit test schedule",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "brokerage_per_order": 10,
        "exchange_rate": 0.0001,
        "sebi_rate": 0.000001,
        "gst_rate": 0.18,
        "stamp_buy_rate": 0.00003,
        "stt_sell_rate": 0.001,
        "slippage_bps": 10,
    }
    return value | overrides


def test_import_has_stable_content_hash_and_preserves_missing_volume():
    body = payload()
    body["rows"][0].pop("volume")
    first = dataset.validate_dataset(body)
    body["name"] = "same contents renamed"
    assert dataset.validate_dataset(body)["content_hash"] == first["content_hash"]
    assert first["rows"][0]["volume"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("close", float("nan")),
        ("high", 1),
        ("timestamp", "2030-01-01T09:20:00+05:30"),
        ("timestamp", "2026-01-01T09:20:00"),
    ],
)
def test_invalid_market_data_is_refused(field, value):
    body = payload()
    body["rows"][0][field] = value
    with pytest.raises(ValueError):
        dataset.validate_dataset(body)


def test_duplicate_bars_and_invalid_contracts_are_refused():
    body = payload()
    body["rows"].append(copy.deepcopy(body["rows"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        dataset.validate_dataset(body)
    body = payload()
    body["metadata"]["contracts"][0]["lot_size"] = 0
    with pytest.raises(ValueError, match="lot_size"):
        dataset.validate_dataset(body)


def test_costs_must_be_explicit_finite_and_cover_data_dates():
    data = dataset.validate_dataset(payload())
    for costs in ({}, fees(stt_sell_rate=None), fees(effective_to="2025-12-31")):
        with pytest.raises(ValueError):
            replay.validate_configuration(data, "trend_breakout", {}, costs)


def test_closed_bar_signal_next_option_bar_stop_first_and_costs():
    data = dataset.validate_dataset(payload())
    config = replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    report = replay.run_replay(data, config)
    trade = report["trades"][0]
    assert trade["signal_at"] == "2026-01-01T09:30:00+05:30"
    assert trade["entry_bar_at"] == "2026-01-01T09:35:00+05:30"
    assert trade["exit_reason"] == "stop_loss"
    assert trade["quantity"] % 25 == 0
    assert trade["net_pnl"] < trade["gross_pnl"] < 0
    assert report["qualification"]["eligible_for_live"] is False
    assert report["metrics"]["max_drawdown_pct"] > 0


def test_missing_next_contract_bar_rejects_without_fabricating_fill():
    body = payload()
    body["rows"] = [r for r in body["rows"] if r["symbol"] == "NIFTY" or "09:20:" in r["timestamp"]]
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert report["trades"] == []
    assert report["rejections"]["missing_next_option_bar"] > 0


def test_vwap_refuses_missing_underlying_volume():
    body = payload()
    body["rows"][0].pop("volume")
    data = dataset.validate_dataset(body)
    with pytest.raises(ValueError, match="volume"):
        replay.validate_configuration(data, "vwap_pullback", {}, fees())


def test_whole_lot_affordability_and_no_profit_budget_replenishment():
    body = payload()
    body["metadata"]["contracts"][0]["lot_size"] = 1000
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert report["trades"] == []
    assert report["rejections"]["unaffordable_whole_lot"] > 0


def test_history_cannot_use_underlying_bars_across_data_gaps():
    body = payload()
    body["rows"] = [
        row
        for row in body["rows"]
        if not (row["symbol"] == "NIFTY" and "09:25:" in row["timestamp"])
    ]
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert all(trade["signal_at"] != "2026-01-01T09:35:00+05:30" for trade in report["trades"])


def test_missing_option_bar_during_exposure_does_not_jump_to_a_later_fill():
    body = payload()
    for row in body["rows"]:
        if row["symbol"] == "NIFTY_CE":
            row.update(open=100, high=101, low=99, close=100)
    body["rows"] = [
        row
        for row in body["rows"]
        if not (row["symbol"] == "NIFTY_CE" and "09:40:" in row["timestamp"])
    ]
    # A stop on a later bar cannot establish what happened during the gap.
    body["rows"][-1].update(low=50)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert report["trades"] == []
    assert report["incomplete_outcomes"][0]["reason"] == "missing_option_bar_during_exposure"
    assert report["metrics"]["ending_equity"] is None


def test_cost_calculation_applies_sell_tax_once_per_order():
    from decimal import Decimal

    from services.research.costs import order_cost, validate_cost_schedule

    schedule = validate_cost_schedule(fees())
    assert order_cost(Decimal("1000"), "BUY", schedule) == Decimal("11.95")
    assert order_cost(Decimal("1000"), "SELL", schedule) == Decimal("12.92")


def test_csv_import_matches_json_rows():
    import csv
    import io

    body = payload()
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(body["rows"][0]))
    writer.writeheader()
    writer.writerows(body["rows"])
    csv_body = {key: value for key, value in body.items() if key != "rows"}
    csv_body["csv"] = stream.getvalue()
    assert (
        dataset.validate_dataset(csv_body)["content_hash"]
        == dataset.validate_dataset(body)["content_hash"]
    )


def test_gap_loss_spends_remaining_daily_budget_and_drawdown_persists():
    body = payload(2)
    # First option entry remains at 100; its next bar gaps to 50, overrunning planned risk.
    for row in body["rows"]:
        if row["symbol"] == "NIFTY_CE":
            row.update(open=100, high=101, low=99, close=100)
            if "09:40:" in row["timestamp"]:
                row.update(open=50, high=51, low=49, close=50)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert len(report["trades"]) == 1
    assert report["trades"][0]["net_pnl"] < -2000
    assert report["rejections"]["budget_or_drawdown_limit"] > 0
    assert report["metrics"]["max_drawdown_pct"] > 20


def test_no_real_underlying_volume_is_not_treated_as_observed_zero():
    body = payload()
    for row in body["rows"]:
        row.pop("volume", None)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert report["trades"]
    with pytest.raises(ValueError, match="volume"):
        replay.validate_configuration(data, "vwap_pullback", {"lookback": 2}, fees())


def test_tiny_contract_search_is_bounded_even_when_fees_exhaust_risk(monkeypatch):
    body = payload()
    body["metadata"]["contracts"][0].update(lot_size=1, multiplier=0.000001)
    data = dataset.validate_dataset(body)
    config = replay.validate_configuration(
        data, "trend_breakout", {"lookback": 2}, fees(brokerage_per_order=1000)
    )
    calls = 0
    real_evaluate = replay.evaluate_budget

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_evaluate(*args, **kwargs)

    monkeypatch.setattr(replay, "evaluate_budget", counted)
    report = replay.run_replay(data, config)
    assert report["trades"] == []
    assert calls < 100


def test_midnight_crossing_sessions_are_explicitly_unsupported():
    body = payload()
    body["metadata"]["session_close"] = "00:30"
    with pytest.raises(ValueError, match="overnight"):
        dataset.validate_dataset(body)
    body = payload()
    body["rows"][0]["timestamp"] = "2026-01-01T00:30:00+05:30"
    with pytest.raises(ValueError, match="overnight"):
        dataset.validate_dataset(body)


@pytest.mark.parametrize(
    "gap, expected_reason, expected_price",
    [
        ({"open": 150, "high": 151, "low": 149, "close": 150}, "target", 150),
        ({"open": 50, "high": 51, "low": 49, "close": 50}, "stop_loss", 50),
        ({"open": 100, "high": 125, "low": 75, "close": 100}, "stop_loss", 90),
        # The open occurs before ambiguous later extremes: an already triggered
        # target exits there even if that candle subsequently reaches the stop.
        ({"open": 150, "high": 151, "low": 75, "close": 100}, "target", 150),
    ],
)
def test_option_exit_uses_breach_kind_and_known_open_before_ambiguous_extremes(
    gap, expected_reason, expected_price
):
    body = payload()
    for row in body["rows"]:
        if row["symbol"] == "NIFTY_CE":
            row.update(open=100, high=101, low=99, close=100)
            if row["timestamp"][11:16] > "09:35":
                row.update(gap)
    data = dataset.validate_dataset(body)
    config = replay.validate_configuration(
        data, "trend_breakout", {"lookback": 2}, fees(slippage_bps=0)
    )
    first = replay.run_replay(data, config)["trades"][0]
    assert first["exit_reason"] == expected_reason
    assert first["exit_price"] == expected_price


def test_marked_net_equity_peak_drawdown_exits_and_stays_paused_after_recovery():
    body = payload(2)
    body["metadata"]["session_close"] = "09:45"
    for row in body["rows"]:
        if row["symbol"] == "NIFTY_CE":
            if row["timestamp"][11:16] == "09:35":
                row.update(open=100, high=200, low=100, close=200)
            elif row["timestamp"][11:16] == "09:40":
                row.update(open=150, high=150, low=150, close=150)
            elif row["timestamp"][11:16] == "09:45":
                row.update(open=200, high=200, low=200, close=200)
            else:
                row.update(open=100, high=101, low=99, close=100)
    data = dataset.validate_dataset(body)
    config = replay.validate_configuration(
        data, "trend_breakout", {"lookback": 2, "target_pct": 5}, fees(slippage_bps=0)
    )
    report = replay.run_replay(data, config)
    assert len(report["trades"]) == 1
    assert report["trades"][0]["exit_reason"] == "portfolio_drawdown"
    assert report["trades"][0]["exit_price"] == 150
    assert report["metrics"]["max_drawdown_pct"] > 20
    assert report["metrics"]["drawdown_paused"] is True
    assert report["metrics"]["peak_equity"] > 17000
    assert report["rejections"]["budget_or_drawdown_limit"] > 0


def test_intrabar_drawdown_exit_uses_peak_from_previous_observed_close():
    body = payload()
    body["metadata"]["session_close"] = "09:45"
    for row in body["rows"]:
        if row["symbol"] == "NIFTY_CE":
            row.update(open=100, high=101, low=99, close=100)
            if row["timestamp"][11:16] == "09:35":
                row.update(open=100, high=200, low=100, close=200)
            elif row["timestamp"][11:16] == "09:40":
                row.update(open=200, high=210, low=120, close=200)
    data = dataset.validate_dataset(body)
    config = replay.validate_configuration(
        data, "trend_breakout", {"lookback": 2, "target_pct": 5}, fees(slippage_bps=0)
    )
    report = replay.run_replay(data, config)
    first = report["trades"][0]
    assert first["exit_reason"] == "portfolio_drawdown"
    assert 153 < first["exit_price"] < 155
    assert report["metrics"]["max_drawdown_pct"] == pytest.approx(20, abs=0.001)
    assert report["metrics"]["drawdown_paused"] is True


def test_stop_filled_before_drawdown_boundary_does_not_consume_later_candle_low():
    body = payload()
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data,
        replay.validate_configuration(
            data, "trend_breakout", {"lookback": 2}, fees(slippage_bps=0)
        ),
    )
    assert report["trades"][0]["exit_reason"] == "stop_loss"
    assert report["metrics"]["max_observed_open_drawdown_pct"] < 20


def test_incomplete_oos_suppresses_bootstrap_and_unbounded_profit_factor():
    body = payload(80)
    # A known target winner followed by a surviving position without the close
    # leaves realized wins, but no complete experiment P&L distribution.
    for row in body["rows"]:
        if row["symbol"] == "NIFTY_CE":
            if row["timestamp"][11:16] == "09:35":
                row.update(open=100, high=125, low=99, close=110)
            else:
                row.update(open=100, high=101, low=99, close=100)
    data = dataset.validate_dataset(body)
    config = replay.validate_configuration(
        data, "trend_breakout", {"lookback": 2}, fees(slippage_bps=0)
    )
    report = replay.evaluate_experiment(data, config)
    assert report["oos"]["incomplete_outcomes"]
    assert report["oos"]["trades"]
    assert report["oos"]["metrics"]["profit_factor_unbounded"] is False
    assert report["bootstrap"]["net_pnl_p05"] is None
    assert report["bootstrap"]["net_pnl_p95"] is None


def test_vwap_requires_explicit_session_open_and_preserves_it_in_provenance():
    data = dataset.validate_dataset(payload())
    with pytest.raises(ValueError, match="session_open"):
        replay.validate_configuration(data, "vwap_pullback", {"lookback": 2}, fees())
    body = payload()
    body["metadata"]["session_open"] = "09:15"
    data = dataset.validate_dataset(body)
    assert data["metadata"]["session_open"] == "09:15"
    assert (
        replay.validate_configuration(data, "vwap_pullback", {"lookback": 2}, fees())["candidate"]
        == "vwap_pullback"
    )


def test_vwap_rejects_missing_opening_underlying_bar_even_with_no_internal_gaps():
    body = payload(2)
    body["metadata"]["session_open"] = "09:15"
    body["rows"] = [
        row
        for row in body["rows"]
        if not (row["symbol"] == "NIFTY" and row["timestamp"] == "2026-01-02T09:20:00+05:30")
    ]
    data = dataset.validate_dataset(body)
    with pytest.raises(ValueError, match="Incomplete underlying session 2026-01-02"):
        replay.validate_configuration(data, "vwap_pullback", {"lookback": 2}, fees())
    # Trend lookbacks may start from a later observed window without a VWAP claim.
    assert replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())


@pytest.mark.parametrize("opening", ["tomorrow", "09:15:30", "00:30", "15:30", 915])
def test_invalid_session_open_is_rejected_on_import(opening):
    body = payload()
    body["metadata"]["session_open"] = opening
    with pytest.raises(ValueError, match="session_open"):
        dataset.validate_dataset(body)
