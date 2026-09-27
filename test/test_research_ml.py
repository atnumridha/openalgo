"""ML evidence must remain causal and distinct from live order execution."""

import numpy as np
import pandas as pd
import pytest
from test_research_minute_execution import minute_payload
from test_trading_research import fees

from services.research import dataset, replay


def candles(count=140):
    index = pd.date_range("2025-01-02 09:20", periods=count, freq="5min", tz="Asia/Kolkata")
    close = 100 + np.arange(count) * 0.1 + np.sin(np.arange(count))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000,
        },
        index=index,
    )


def test_features_do_not_change_when_future_prices_change():
    from services.research.ml import technical_features

    source = candles()
    before = technical_features(source.iloc[:100])
    changed = source.copy()
    changed.iloc[100:, :4] *= 7
    after = technical_features(changed).iloc[:100]
    pd.testing.assert_frame_equal(before, after)
    assert before.iloc[-1].notna().sum() >= 20


def test_features_reject_duplicate_and_reversed_timestamps():
    from services.research.ml import technical_features

    for source in (candles().iloc[::-1], pd.concat([candles(), candles().iloc[-1:]])):
        with pytest.raises(ValueError, match="timestamp"):
            technical_features(source)


def test_option_volume_features_are_real_and_underlying_volume_is_not_invented():
    from services.research.ml import technical_features

    source = candles()
    source["volume"] = np.nan
    assert not any("volume" in key or "vwap" in key for key in technical_features(source))
    option = technical_features(candles(), include_volume=True)
    assert option.iloc[-1]["relative_volume"] == 1
    assert np.isfinite(option.iloc[-1]["vwap_distance"])


def test_research_schedule_prevents_rule_fallback_and_is_hash_bound():
    data = dataset.validate_dataset(minute_payload())
    config = replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    assert replay.run_replay(data, config)["metrics"]["trade_count"] > 0
    config["research_signal_hash"] = dataset.digest({})
    empty = replay.run_replay(data, config, research_signals={})
    assert empty["metrics"]["trade_count"] == 0
    assert empty["qualification"]["eligible_for_live"] is False
    with pytest.raises(ValueError, match="schedule"):
        replay.run_replay(data, config)
    with pytest.raises(ValueError, match="hash"):
        replay.run_replay(data, config, research_signals={"2026-01-01T09:30:00+05:30": "PE"})


def test_research_schedule_enters_after_closed_signal_and_checks_direction():
    data = dataset.validate_dataset(minute_payload())
    config = replay.validate_configuration(data, "trend_breakout", {"lookback": 200}, fees())
    schedule = {"2026-01-01T09:30:00+05:30": "CE"}
    config["research_signal_hash"] = dataset.digest(schedule)
    result = replay.run_replay(data, config, research_signals=schedule)
    assert len(result["trades"]) == 1
    assert result["trades"][0]["entry_bar_at"] == "2026-01-01T09:31:00+05:30"
    schedule[next(iter(schedule))] = "BUY"
    config["research_signal_hash"] = dataset.digest(schedule)
    with pytest.raises(ValueError, match="direction"):
        replay.run_replay(data, config, research_signals=schedule)


def test_label_uses_next_minute_and_first_exit_not_a_later_winner():
    from services.research.ml import label_option_trade

    body = minute_payload()
    contract = body["metadata"]["contracts"][0]
    rows = [r for r in body["rows"] if r["symbol"] == contract["symbol"]]
    zero = fees(
        **dict.fromkeys(
            (
                "slippage_bps",
                "brokerage_per_order",
                "exchange_rate",
                "sebi_rate",
                "gst_rate",
                "stamp_buy_rate",
                "stt_sell_rate",
            ),
            0,
        )
    )
    label = label_option_trade(rows, "2026-01-01T09:30:00+05:30", contract, 1, zero, "09:45")
    assert label["entry_at"] == "2026-01-01T09:31:00+05:30"
    assert label["exit_at"] == "2026-01-01T09:32:00+05:30"
    assert label["net_r"] == 2
    assert label["net_pnl"] == 500
    # Missing next minute must not be relabelled from the later winning candle.
    missing = [r for r in rows if not r["timestamp"].endswith("09:31:00+05:30")]
    assert (
        label_option_trade(missing, "2026-01-01T09:30:00+05:30", contract, 1, zero, "09:45") is None
    )


def test_label_rejects_missing_exposure_bar_and_never_uses_next_session():
    from services.research.ml import label_option_trade

    body = minute_payload()
    contract = body["metadata"]["contracts"][0]
    rows = [r for r in body["rows"] if r["symbol"] == contract["symbol"]]
    rows = [r for r in rows if not r["timestamp"].endswith("09:32:00+05:30")]
    assert (
        label_option_trade(rows, "2026-01-01T09:30:00+05:30", contract, 1, fees(), "09:45") is None
    )


def test_chronological_fit_refuses_training_labels_overlapping_validation():
    from services.research.ml import assert_chronology

    train = pd.DataFrame(
        {"timestamp": ["2025-06-30T15:00:00+05:30"], "label_exit_at": ["2025-07-01T09:30:00+05:30"]}
    )
    later = pd.DataFrame({"timestamp": ["2025-07-01T09:25:00+05:30"]})
    with pytest.raises(ValueError, match="overlap"):
        assert_chronology(train, later)


def test_predictions_are_generated_without_labels_and_choose_skip_or_best_direction():
    from services.research.ml import signal_schedule

    opportunities = pd.DataFrame(
        {
            "timestamp": ["2025-01-01T10:00:00+05:30"] * 2,
            "direction": ["CE", "PE"],
            "symbol": ["CALL", "PUT"],
        }
    )
    assert signal_schedule(opportunities, [0.05, 0.08], 0.1) == {}
    assert signal_schedule(opportunities, [0.15, 0.3], 0.1) == {
        "2025-01-01T10:00:00+05:30": {"direction": "PE", "symbol": "PUT"}
    }


def test_scored_contract_cannot_be_replaced_when_stress_makes_it_unaffordable():
    from test_research_minute_execution import filtered_payload

    from services.research.ml import signal_schedule

    body = filtered_payload()
    body["metadata"]["contracts"][0]["expiry"] = "2026-01-05"
    alternative = dict(body["metadata"]["contracts"][0], symbol="ALTERNATIVE", expiry="2026-01-06")
    body["metadata"]["contracts"][0]["lot_size"] = 75
    alternative["lot_size"] = 75
    body["metadata"]["contracts"].append(alternative)
    extra = []
    for row in body["rows"]:
        if row["symbol"] == "NIFTY_CE":
            row.update(open=106.2, high=106.3, low=106.1, close=106.2)
            extra.append(dict(row, symbol="ALTERNATIVE", open=80, high=80.1, low=79.9, close=80))
    body["rows"].extend(extra)
    data = dataset.validate_dataset(body)
    table = pd.DataFrame(
        {"timestamp": ["2026-01-01T10:00:00+05:30"], "direction": ["CE"], "symbol": ["NIFTY_CE"]}
    )
    schedule = signal_schedule(table, [0.5], 0.2)
    config = replay.validate_configuration(
        data, "trend_breakout_filtered", {}, fees(slippage_bps=30, brokerage_per_order=20)
    )
    config["research_signal_hash"] = dataset.digest(schedule)
    report = replay.run_replay(data, config, research_signals=schedule)
    assert report["trades"] == []
    assert report["rejections"]["no_eligible_observed_contract"] == 1


def test_label_refuses_one_lot_whose_planned_loss_exceeds_every_budget_bucket():
    from services.research.ml import label_option_trade

    body = minute_payload()
    contract = dict(body["metadata"]["contracts"][0], lot_size=75)
    rows = [r for r in body["rows"] if r["symbol"] == contract["symbol"]]
    # 75 units * max(10% of100, 1.5*15ATR) =1687.5 before fees.
    assert (
        label_option_trade(rows, "2026-01-01T09:30:00+05:30", contract, 15, fees(), "09:45") is None
    )


def test_validation_ambiguity_cannot_pass_evidence_gate():
    from services.research.ml import validation_qualifies

    good = {"net_pnl": 100, "trade_count": 25, "ambiguous_exit_count": 0}
    assert validation_qualifies({"base": good, "stress": good}) is True
    assert (
        validation_qualifies({"base": good, "stress": dict(good, ambiguous_exit_count=1)}) is False
    )
    assert validation_qualifies({"base": dict(good, net_pnl=None), "stress": good}) is False
