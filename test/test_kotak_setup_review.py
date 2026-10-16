"""Replay evidence, honest coverage and fee-aware historical review contracts."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from test_kotak_setup_engines import START, bar, event, seed


def observed_tape():
    return [event(t, 22620) for t in range(610, 661, 10)] + [event(662, 22607)]


def test_replay_uses_only_events_and_candles_known_at_cursor_and_never_allows_entry():
    from services.kotak_assistant.setup_review import evaluate_replay

    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    tape = observed_tape()
    before = evaluate_replay(
        bars, [], tape, START + 650, START, "2026-10-16", "opening_reversal", "literal"
    )
    assert before["directions"]["PE"]["stage"] == "waiting_signal"
    assert before["signal_candle"] is None and before["triggered_at"] is None
    after = evaluate_replay(
        bars, [], tape, START + 662, START, "2026-10-16", "opening_reversal", "literal"
    )
    assert after["stage"] == "triggered" and after["index_entry"] == 22607
    assert after["historical_eligible"] and not after["eligible"] and after["read_only"]
    assert not after["directions"]["PE"]["eligible"]


def test_ohlc_alone_cannot_invent_an_opening_break_or_intrabar_trigger():
    from services.kotak_assistant.setup_review import evaluate_replay

    bars = seed() + [bar(10, 22625, 22630, 22608, 22612), bar(11, 22612, 22620, 22580, 22590)]
    result = evaluate_replay(
        bars, [], [], START + 720, START, "2026-10-16", "opening_reversal", "literal"
    )
    assert result["directions"]["PE"]["stage"] == "waiting_break"
    assert result["replay"]["intrabar_basis"] == "unavailable"
    assert any("OHLC" in text for text in result["replay"]["limitations"])


def test_replay_discloses_rest_sampling_instead_of_claiming_full_tick_fidelity():
    from services.kotak_assistant.setup_review import evaluate_replay

    result = evaluate_replay(
        seed(),
        [],
        [event(610, 22620, source="rest_snapshot")],
        START + 620,
        START,
        "2026-10-16",
        "opening_reversal",
        "literal",
    )
    assert result["replay"]["intrabar_basis"] == "sampled_snapshots"
    assert not result["replay"]["complete_tick_coverage"]


def test_coverage_counts_completed_bars_and_intraday_gaps_without_overnight_fill():
    from services.kotak_assistant.setup_review import coverage_report

    rows = seed()
    previous = [dict(rows[0], time=START - 86400)]
    future = [bar(20, 1, 2, 1, 1)]
    result = coverage_report(previous + rows[:3] + rows[4:] + future, [], [], START + 600)
    assert result["one_minute"]["count"] == 10
    assert result["one_minute"]["gaps"] == [
        {"after": START + 120, "before": START + 240, "missing": 1}
    ]
    assert not result["warmup"]["trend_ready"]
    assert result["option_history"]["count"] == 0
    assert not result["financial_metrics_available"]


def roundtrip(day, entry, exit_price, **overrides):
    time = datetime.fromisoformat(day).replace(hour=10, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    return {
        "entry": entry,
        "exit": exit_price,
        "quantity": 65,
        "exchange": "NFO",
        "entry_time": time,
        "exit_time": time + 60,
        "day": day,
        "strategy": "trend",
        "mode": "confirmed",
        "provenance": "broker_fills",
        **overrides,
    }


def test_metrics_subtract_fees_and_compute_chronological_drawdown_and_expectancy():
    from services.kotak_assistant.setup_review import trade_metrics

    # Chronological gross outcomes +650, -650, +325. Independently calculated
    # NFO premium-turnover charges are 16.66, 14.16 and 16.03.
    result = trade_metrics(
        [
            roundtrip("2026-10-16", 100, 105),
            roundtrip("2026-10-14", 100, 110),
            roundtrip("2026-10-15", 100, 90),
        ]
    )
    assert result["sample_count"] == 3
    assert result["gross"] == 325
    assert result["fees"] == 46.85
    assert result["net"] == 278.15
    assert result["expectancy"] == 92.72
    assert result["max_drawdown"] == 664.16
    assert result["profit_factor"] == 1.4188


def test_index_signals_do_not_become_fabricated_option_profit_samples():
    from services.kotak_assistant.setup_review import review_setups

    rows = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    result = review_setups(rows, [], observed_tape(), START + 662, START, "2026-10-16")
    group = result["groups"]["opening_reversal:literal"]
    assert group["index_signal_count"] == 1
    assert group["metrics"]["sample_count"] == 0
    assert group["metrics"]["net"] is None
    assert group["metrics"]["status"] == "unavailable"
    assert set(result["groups"]) == {"trend:confirmed", "trend:early", "opening_reversal:literal"}


def test_chronological_holdout_keeps_entire_days_out_of_training():
    from services.kotak_assistant.setup_review import chronological_holdout

    rows = [roundtrip(f"2026-10-{day:02}", 100, 101) for day in range(5, 15)]
    rows.append(roundtrip("2026-10-12", 100, 99))
    result = chronological_holdout(list(reversed(rows)))
    assert result["training_dates"] == [f"2026-10-{day:02}" for day in range(5, 12)]
    assert result["holdout_dates"] == ["2026-10-12", "2026-10-13", "2026-10-14"]
    assert len(result["training"]) == 7 and len(result["holdout"]) == 4


def test_same_minute_stop_and_target_uses_stop_first_and_requires_real_option_quote():
    from services.kotak_assistant.setup_review import option_bar_trade

    plan = {"entry_time": START + 610, "sl": 90, "target": 120, "quantity": 65}
    bars = [
        dict(bar(10, 100, 125, 85, 105), symbol="NIFTYCE", exchange="NFO", source="broker_history")
    ]
    quotes = [
        {
            "time": START + 610,
            "symbol": "NIFTYCE",
            "exchange": "NFO",
            "bid": 99.95,
            "ask": 100,
            "source": "websocket",
        }
    ]
    result = option_bar_trade(plan, bars, quotes, START + 660, "NIFTYCE", "NFO")
    assert result["exit"] == 90 and result["outcome"] == "stop"
    assert result["intrabar_uncertain"]
    assert result["entry"] == 100 and result["provenance"] == "historical_option_ohlc"
    assert option_bar_trade(plan, bars, [], START + 660, "NIFTYCE", "NFO") is None


def test_metrics_refuse_invalid_prices_instead_of_reporting_imaginary_profit():
    from services.kotak_assistant.setup_review import trade_metrics

    with pytest.raises(ValueError):
        trade_metrics([roundtrip("2026-10-16", float("nan"), 100)])


def test_partial_entry_minute_high_cannot_invent_a_winning_exit():
    from services.kotak_assistant.setup_review import option_bar_trade

    plan = {"entry_time": START + 610, "sl": 90, "target": 120, "quantity": 65}
    bars = [
        dict(bar(10, 100, 125, 95, 105), symbol="NIFTYCE", exchange="NFO", source="broker_history")
    ]
    quotes = [
        {
            "time": START + 610,
            "symbol": "NIFTYCE",
            "exchange": "NFO",
            "bid": 99.95,
            "ask": 100,
            "source": "websocket",
        }
    ]
    assert option_bar_trade(plan, bars, quotes, START + 660, "NIFTYCE", "NFO") is None


def test_option_quote_received_after_entry_is_unavailable_at_entry_time():
    from services.kotak_assistant.setup_review import option_bar_trade

    plan = {"entry_time": START + 610, "sl": 90, "target": 120, "quantity": 65}
    bars = [
        dict(bar(10, 100, 125, 85, 105), symbol="NIFTYCE", exchange="NFO", source="broker_history")
    ]
    quotes = [
        {
            "time": START + 610,
            "received_at": START + 620,
            "symbol": "NIFTYCE",
            "exchange": "NFO",
            "bid": 99.95,
            "ask": 100,
            "source": "websocket",
        }
    ]
    assert option_bar_trade(plan, bars, quotes, START + 660, "NIFTYCE", "NFO") is None


def test_gap_in_option_history_cannot_be_skipped_to_claim_later_profit():
    from services.kotak_assistant.setup_review import option_bar_trade

    plan = {"entry_time": START + 600, "sl": 90, "target": 120, "quantity": 65}
    bars = [
        dict(bar(i, 100, high, 95, 105), symbol="NIFTYCE", exchange="NFO", source="broker_history")
        for i, high in ((10, 105), (12, 125))
    ]
    quotes = [
        {
            "time": START + 600,
            "symbol": "NIFTYCE",
            "exchange": "NFO",
            "bid": 99.95,
            "ask": 100,
            "source": "websocket",
        }
    ]
    assert option_bar_trade(plan, bars, quotes, START + 780, "NIFTYCE", "NFO") is None


def test_scenario_label_without_contract_data_does_not_create_review_profit():
    from services.kotak_assistant.setup_review import review_setups

    scenario = roundtrip("2026-10-16", 100, 150, provenance="historical_option_ohlc")
    result = review_setups([], [], [], START + 3600, START, "2026-10-16", roundtrips=[scenario])
    assert result["groups"]["trend:confirmed"]["metrics"]["sample_count"] == 0


def test_coverage_warmup_count_does_not_claim_stale_candles_are_ready():
    from services.kotak_assistant.setup_review import coverage_report

    one = [bar(i, 100, 110, 90, 100) for i in range(60)]
    five = [bar(i, 100, 110, 90, 100, seconds=300) for i in range(250)]
    result = coverage_report(one, five, [], START + 100000)
    assert result["one_minute"]["count"] == 60 and result["five_minute"]["count"] == 250
    assert not result["warmup"]["trend_ready"]


def test_coverage_does_not_match_a_quote_to_another_options_history():
    from services.kotak_assistant.setup_review import coverage_report

    bars = [
        dict(
            bar(10, 100, 125, 95, 105), symbol="CONTRACT_A", exchange="NFO", source="broker_history"
        )
    ]
    quotes = [
        {
            "time": START + 610,
            "symbol": "CONTRACT_B",
            "exchange": "NFO",
            "bid": 99.95,
            "ask": 100,
            "source": "websocket",
        }
    ]
    result = coverage_report([], [], quotes, START + 660, option_history=bars)
    assert not result["financial_metrics_available"]


def test_recorded_observation_reset_preserves_live_gap_rejection_in_replay():
    from services.kotak_assistant.setup_review import evaluate_replay

    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    tape = [
        event(610, 22620),
        {"time": START + 650, "id": "feed-gap", "kind": "observation_gap"},
        event(662, 22607),
    ]
    result = evaluate_replay(
        bars, [], tape, START + 662, START, "2026-10-16", "opening_reversal", "literal"
    )
    assert result["directions"]["PE"]["stage"] != "triggered"
    assert not result["historical_eligible"]


def test_review_cli_reads_bounded_json_without_accounts_and_returns_unavailable_metrics(
    tmp_path, capsys
):
    import json

    from scripts.kotak_assistant.review_setups import main

    path = tmp_path / "observations.json"
    path.write_text(
        json.dumps(
            {
                "one": [],
                "five": [],
                "events": [],
                "now": START,
                "session_start": START,
                "session_id": "2026-10-16",
            }
        )
    )
    assert main([str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["read_only"]
    assert result["groups"]["trend:confirmed"]["metrics"]["sample_count"] == 0
