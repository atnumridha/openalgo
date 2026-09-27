"""Regressions for causal mixed-resolution replay and a distinct filtered hypothesis."""

import copy
from datetime import datetime, timedelta

import pytest
from test_trading_research import fees, payload

from services.research import dataset, replay


def minute_payload():
    body = payload()
    body["metadata"].update(execution_bar_minutes=1, session_open="09:15", session_close="09:45")
    body["metadata"]["contracts"][0].update(tick_size=0.05, expiry="2026-01-06")
    body["rows"] = [r for r in body["rows"] if r["symbol"] == "NIFTY"]
    start = datetime.fromisoformat("2026-01-01T09:16:00+05:30")
    for i in range(30):
        at = start + timedelta(minutes=i)
        row = {
            "symbol": "NIFTY_CE",
            "timestamp": at.isoformat(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        }
        if at.strftime("%H:%M") == "09:32":
            row.update(high=125, close=120)
        if at.strftime("%H:%M") == "09:33":
            row.update(low=75)
        body["rows"].append(row)
    return body


def test_resolution_and_tick_are_hash_bound_and_legacy_hash_stays_stable():
    body = minute_payload()
    actual = dataset.validate_dataset(body)
    assert actual["metadata"]["execution_bar_minutes"] == 1
    assert actual["metadata"]["contracts"][0]["tick_size"] == 0.05
    modified = copy.deepcopy(body)
    modified["metadata"]["contracts"][0]["tick_size"] = 0.1
    assert actual["content_hash"] != dataset.validate_dataset(modified)["content_hash"]
    legacy = dataset.validate_dataset(payload())
    assert "execution_bar_minutes" not in legacy["metadata"]


@pytest.mark.parametrize("minutes", [0, 2, 6, 1.5, True])
def test_invalid_execution_resolution_is_rejected(minutes):
    body = minute_payload()
    body["metadata"]["execution_bar_minutes"] = minutes
    with pytest.raises(ValueError, match="execution_bar_minutes"):
        dataset.validate_dataset(body)


def test_minute_target_precedes_later_stop_without_using_later_underlying_bar():
    data = dataset.validate_dataset(minute_payload())
    config = replay.validate_configuration(
        data, "trend_breakout", {"lookback": 2}, fees(slippage_bps=0)
    )
    report = replay.run_replay(data, config)
    first = report["trades"][0]
    assert first["signal_at"].endswith("09:30:00+05:30")
    assert first["entry_bar_at"].endswith("09:31:00+05:30")
    assert first["exit_at"].endswith("09:32:00+05:30")
    assert first["exit_reason"] == "target"
    assert report["metrics"]["execution_bar_minutes"] == 1
    assert report["metrics"]["ambiguous_exit_count"] == 0


def test_missing_minute_during_exposure_is_incomplete():
    body = minute_payload()
    body["rows"] = [
        r for r in body["rows"] if not (r["symbol"] == "NIFTY_CE" and "09:32:" in r["timestamp"])
    ]
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert report["metrics"]["net_pnl"] is None
    assert report["incomplete_outcomes"][0]["reason"] == "missing_option_bar_during_exposure"


def test_same_minute_ambiguity_is_disclosed_and_remains_stop_first():
    body = minute_payload()
    for r in body["rows"]:
        if r["symbol"] == "NIFTY_CE" and "09:31:" in r["timestamp"]:
            r.update(high=130, low=70)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    )
    assert report["trades"][0]["exit_reason"] == "stop_loss"
    assert report["trades"][0]["ambiguous_exit"] is True
    assert report["metrics"]["ambiguous_exit_count"] >= 1


def filtered_payload():
    body = minute_payload()
    body["metadata"]["session_close"] = "13:00"
    body["rows"] = []
    start = datetime.fromisoformat("2026-01-01T09:16:00+05:30")
    for i in range(225):
        at = start + timedelta(minutes=i)
        body["rows"].append(
            {
                "symbol": "NIFTY_CE",
                "timestamp": at.isoformat(),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 1000,
            }
        )
        if at.minute % 5 == 0:
            price = 100 + i / 5
            body["rows"].append(
                {
                    "symbol": "NIFTY",
                    "timestamp": at.isoformat(),
                    "open": price - 0.1,
                    "high": price + 0.1,
                    "low": price - 0.1,
                    "close": price,
                    "volume": None,
                }
            )
    return body


def test_independent_trend_rejects_breakout_against_previous_trend():
    closes = list(range(130, 104, -1)) + [140]
    history = [
        {"close": x, "open": x, "high": x + 0.1, "low": x - 0.1, "volume": None} for x in closes
    ]
    assert replay._signal(history, "trend_breakout", replay.DEFAULTS) == "CE"
    assert replay._signal(history, "trend_breakout_filtered", replay.DEFAULTS) is None


def test_filtered_requires_minute_execution_and_ticks():
    data = dataset.validate_dataset(payload())
    with pytest.raises(ValueError, match="one-minute"):
        replay.validate_configuration(data, "trend_breakout_filtered", {}, fees())
    body = filtered_payload()
    del body["metadata"]["contracts"][0]["tick_size"]
    with pytest.raises(ValueError, match="tick_size"):
        replay.validate_configuration(
            dataset.validate_dataset(body), "trend_breakout_filtered", {}, fees()
        )


@pytest.mark.parametrize(
    "change,reason",
    [
        ("expiry", "expiry_filter"),
        ("liquidity", "liquidity_filter"),
        ("premium", "premium_filter"),
        ("volatility", "volatility_filter"),
    ],
)
def test_filtered_refuses_ineligible_contracts(change, reason):
    body = filtered_payload()
    if change == "expiry":
        body["metadata"]["contracts"][0]["expiry"] = "2026-01-01"
    for r in body["rows"]:
        if r["symbol"] != "NIFTY_CE":
            continue
        if change == "liquidity":
            r["volume"] = 0
        if change == "premium":
            r.update(open=150, high=151, low=149, close=150)
        if change == "volatility":
            r.update(high=140, low=60)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout_filtered", {}, fees())
    )
    assert report["trades"] == []
    assert report["rejections"][reason] > 0


def test_filtered_cooldown_and_daily_cap_limit_reentries():
    body = filtered_payload()
    # Smooth observed history, then three separated target bars. No future ATR is used.
    for r in body["rows"]:
        if r["symbol"] == "NIFTY_CE" and r["timestamp"][11:16] in (
            "11:31",
            "11:51",
            "12:11",
            "12:31",
        ):
            r.update(high=125, close=120)
    data = dataset.validate_dataset(body)
    config = replay.validate_configuration(
        data, "trend_breakout_filtered", {}, fees(slippage_bps=0)
    )
    report = replay.run_replay(data, config)
    assert len(report["trades"]) == 3
    assert report["rejections"]["cooldown"] > 0
    assert report["rejections"]["daily_trade_cap"] > 0
    assert all(
        t["entry_price"] % 0.05 == pytest.approx(0, abs=1e-9)
        or t["entry_price"] % 0.05 == pytest.approx(0.05)
        for t in report["trades"]
    )
    for previous, following in zip(report["trades"], report["trades"][1:], strict=False):
        assert datetime.fromisoformat(following["signal_at"]) - datetime.fromisoformat(
            previous["exit_at"]
        ) >= timedelta(minutes=15)


def test_filtered_only_selects_observed_affordable_contract_and_uses_past_atr():
    body = filtered_payload()
    missing = copy.deepcopy(body["metadata"]["contracts"][0])
    missing.update(symbol="UNOBSERVED_CE", strike=126, expiry="2026-01-02")
    body["metadata"]["contracts"].append(missing)
    # Future high volatility must not change the first entry's stop or sizing.
    for r in body["rows"]:
        if r["symbol"] == "NIFTY_CE" and r["timestamp"][11:16] == "11:31":
            r.update(open=100.03, high=130, low=70)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data,
        replay.validate_configuration(data, "trend_breakout_filtered", {}, fees(slippage_bps=0)),
    )
    first = report["trades"][0]
    assert first["symbol"] == "NIFTY_CE"
    assert first["entry_price"] == 100.05
    assert first["stop_price"] == 90.0
    assert first["target_price"] == 120.15
    assert first["planned_risk"] <= 1000
    assert first["entry_price"] * first["quantity"] < 8000


def test_filtered_rejects_unaffordable_quote_before_pending_entry():
    body = filtered_payload()
    body["metadata"]["contracts"][0]["lot_size"] = 100
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data, replay.validate_configuration(data, "trend_breakout_filtered", {}, fees())
    )
    assert report["trades"] == []
    assert report["rejections"]["unaffordable_signal_quote"] > 0


def test_exact_tick_target_is_not_rounded_up_by_binary_float_noise():
    body = filtered_payload()
    for r in body["rows"]:
        if r["symbol"] != "NIFTY_CE":
            continue
        r.update(open=20.05, high=20.1, low=20.0, close=20.05)
        if r["timestamp"][11:16] == "11:31":
            r.update(high=24.15, close=24.15)
        if r["timestamp"][11:16] == "11:32":
            r.update(low=17)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data,
        replay.validate_configuration(data, "trend_breakout_filtered", {}, fees(slippage_bps=0)),
    )
    first = report["trades"][0]
    assert first["target_price"] == 24.15
    assert first["exit_reason"] == "target"
    assert first["exit_at"][11:16] == "11:31"


def test_original_candidate_retains_percentage_target_with_tick_rounding():
    body = minute_payload()
    for r in body["rows"]:
        if r["symbol"] == "NIFTY_CE" and "09:31:" in r["timestamp"]:
            r.update(open=100.03)
    data = dataset.validate_dataset(body)
    report = replay.run_replay(
        data,
        replay.validate_configuration(
            data, "trend_breakout", {"lookback": 2}, fees(slippage_bps=0)
        ),
    )
    assert report["trades"][0]["target_price"] == 120.10
