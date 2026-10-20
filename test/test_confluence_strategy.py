"""All scenarios are synthetic; no orders or account connections."""

import math

import numpy as np
import pandas as pd
import pytest

from strategies.confluence.indicators import indicators, option_analysis, pivots, volume_profile
from strategies.confluence.strategy import Config, decide, manage_position

NOW = 1791288000.0


def bars(n=300, side=1, start=85000):
    close = start + side * np.arange(n) * 0.3 + np.sin(np.arange(n)) * 1.2
    return pd.DataFrame(
        {
            "time": NOW - n * 60 + np.arange(n) * 60,
            "open": close - 0.1 * side,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": np.ones(n) * 10,
        }
    )


def test_pivots_reorder_cpr_and_camarilla_is_symmetric():
    p = pivots(110, 90, 92)
    assert p["bc"] <= p["pivot"] <= p["tc"]
    assert p["r3"] == pytest.approx(97.5) and p["s3"] == pytest.approx(86.5)
    assert p["r4"] == pytest.approx(103) and p["s4"] == pytest.approx(81)


def test_volume_profile_conserves_volume_and_marks_estimate():
    b = bars(50)
    p = volume_profile(b, bins=20)
    assert sum(p["volumes"]) == pytest.approx(b.volume.sum())
    assert p["val"] <= p["poc"] <= p["vah"] and p["coverage"] >= 0.7
    assert "estimate" in p["method"]


@pytest.mark.parametrize("side", [1, -1])
def test_wilder_indicators_and_vwma(side):
    b = bars(side=side)
    v = indicators(b)
    assert 0 <= v["rsi"] <= 100 and 0 <= v["adx"] <= 100
    assert (v["plus_di"] > v["minus_di"]) == (side == 1)
    expected = (b.close.iloc[-20:] * b.volume.iloc[-20:]).sum() / b.volume.iloc[-20:].sum()
    assert v["vwma"] == pytest.approx(expected)
    assert all(math.isfinite(x) for x in v.values())


def chain(skew=-0.02):
    return [
        {
            "side": side,
            "strike": strike,
            "expiry": NOW + 86400,
            "timestamp": NOW,
            "bid": 10,
            "ask": 11,
            "iv": 0.5 + (skew if side == "PUT" else 0),
            "oi_contracts": 100,
            "delta": (-0.25 if side == "PUT" else 0.25),
        }
        for strike in [84000, 85000, 86000]
        for side in ["CALL", "PUT"]
    ]


def test_chain_pairs_same_expiry_uses_contract_oi_and_skew():
    c = option_analysis(chain(), 85000, NOW)
    assert c["put_call_ratio"] == 1 and c["skew_25d"] == pytest.approx(-0.02)
    assert c["vote"] == 1 and c["paired_strikes"] == 3
    with pytest.raises(ValueError):
        option_analysis([{**x, "timestamp": NOW - 61} for x in chain()], 85000, NOW)
    with pytest.raises(ValueError):
        option_analysis([x for x in chain() if x["side"] == "CALL"], 85000, NOW)
    with pytest.raises(ValueError):
        option_analysis([{**x, "expiry": NOW + 20} for x in chain()], 85000, NOW)


def snapshot(side=1):
    b = bars(side=side)
    entry = float(b.close.iloc[-1])
    prior = bars(1440, side=1, start=entry - 200 if side == 1 else entry + 200)
    # A complete prior IST session, independent of intraday direction.
    start = math.floor((NOW + 19800) / 86400) * 86400 - 19800 - 86400
    prior["time"] = start + np.arange(1440) * 60
    p = {
        "symbol": "BTCUSD",
        "contract_value": "0.001",
        "tick_size": ".5",
        "maker_commission_rate": ".0002",
        "taker_commission_rate": ".0005",
        "maintenance_margin": ".25",
        "initial_margin": ".5",
        "contract_type": "perpetual_futures",
        "state": "live",
        "trading_status": "operational",
    }
    return {
        "bars": b.to_dict("records"),
        "previous_session": prior.to_dict("records"),
        "product": p,
        "bid": math.floor(entry * 2) / 2,
        "ask": math.floor(entry * 2) / 2 + 0.5,
        "quote_time": NOW,
        "options": chain(-0.02 if side == 1 else 0.02),
        "next_funding": NOW + 7200,
    }


def test_stale_or_missing_inputs_fail_closed():
    s = snapshot()
    s["quote_time"] = NOW - 11
    assert decide(s, Config(), NOW)["action"] == "HOLD"
    s = snapshot()
    s["options"] = []
    assert decide(s, Config(), NOW)["action"] == "HOLD"
    s = snapshot()
    s["bars"].pop(-2)
    assert decide(s, Config(), NOW)["action"] == "HOLD"
    s = snapshot()
    s["previous_session"].pop(0)
    assert decide(s, Config(), NOW)["action"] == "HOLD"


def test_inputs_do_not_mutate_and_forming_candles_do_not_change_indicators():
    s = snapshot()
    d = decide(s, Config(), NOW)
    before = len(s["bars"])
    s["bars"].append({**s["bars"][-1], "time": NOW, "close": 1, "low": 1})
    after = decide(s, Config(), NOW)
    assert d["indicators"] == after["indicators"] and len(s["bars"]) == before + 1


@pytest.mark.parametrize("side", [1, -1])
def test_plans_include_fees_and_respect_limits(side):
    d = decide(snapshot(side), Config(), NOW)
    assert len(d["plans"]) == 2
    for p in d["plans"]:
        if p.get("fits_risk"):
            assert p["net_risk"] <= 1 and p["margin"] <= 5 and p["notional"] <= 1000
            assert p["net_target"] >= max(1, 3 * p["net_risk"]) - 1e-9
            assert p["entry_fee"] > 0 and p["stop_fee"] > 0 and p["target_fee"] > 0
    assert "probability" not in d


def test_funding_window_is_a_hold():
    s = snapshot()
    s["next_funding"] = NOW + 1200
    assert "funding" in decide(s, Config(), NOW)["reason"].lower()


@pytest.mark.parametrize("side,expected", [(1, "LONG"), (-1, "SHORT")])
def test_end_to_end_selects_both_directions(side, expected):
    s = snapshot(side)
    if side == 1:
        for bar in s["previous_session"]:
            for k in ("open", "high", "low", "close"):
                bar[k] -= 400
    d = decide(s, Config(), NOW)
    assert d["action"] == expected and len(d["votes"]) == 8
    assert d["agreement"][expected] >= 6
    assert d["selected_plan"]["net_target"] >= 1
    assert decide({**s, "available_collateral": 1}, Config(), NOW)["action"] == "HOLD"
    assert decide({**s, "daily_budget": 0.1}, Config(), NOW)["action"] == "HOLD"


@pytest.mark.parametrize("field", ["slippage", "net_rr", "min_net_profit"])
def test_nonfinite_configuration_rejected(field):
    with pytest.raises(ValueError):
        Config(**{field: float("nan")})


def test_protection_rounding_meets_net_floor_both_sides():
    for side in [1, -1]:
        p = {
            "side": side,
            "entry": 85000,
            "stop": 85000 - side * 100,
            "quantity": 1,
            "contract_value": 0.001,
            "entry_fee": 0.02006,
            "maker_rate": 0.0002,
            "taker_rate": 0.0005,
            "tick": 0.5,
            "opened_at": NOW,
            "peak_net": 3,
        }
        m = manage_position(p, 85000 + side * 3000, NOW, Config())
        net = (
            side * (m["stop"] - p["entry"]) * 0.001
            - p["entry_fee"]
            - m["stop"] * 0.001 * 0.0005 * 1.18
            - 0.1
        )
        assert net >= m["planned_floor"] - 1e-9
        m2 = manage_position(
            {**p, "stop": m["stop"], "peak_net": m["peak_net"]}, 85000, NOW + 1, Config()
        )
        assert m2["stop"] == m["stop"] and m2["exit_reason"] == "stop"


def test_depth_shortfall_prevents_sizing():
    s = snapshot()
    s.update(bids=[[s["bid"], 0.5]], asks=[[s["ask"], 0.5]])
    d = decide(s, Config(), NOW)
    assert all(not p["fits_risk"] for p in d["plans"])


@pytest.mark.parametrize("peak,floor", [(0.49, None), (0.5, -0.1), (1.5, 0.9), (3, 2.1), (5, 4)])
@pytest.mark.parametrize("side", [1, -1])
def test_net_trailing_thresholds_never_loosen(side, peak, floor):
    pos = {
        "side": side,
        "entry": 85000,
        "stop": 85000 - side * 100,
        "quantity": 1,
        "contract_value": 0.001,
        "entry_fee": 0.02006,
        "maker_rate": 0.0002,
        "taker_rate": 0.0005,
        "tick": 0.5,
        "opened_at": NOW - 10,
        "target": 85000 + side * 10000,
        "peak_net": peak,
    }
    result = manage_position(pos, 85000 + side * 6000, NOW, Config())
    assert side * (result["stop"] - pos["stop"]) >= 0
    # Test exact floor mapping independently of an executable profit peak update.
    from strategies.confluence.strategy import profit_floor

    actual = profit_floor(peak)
    assert actual is None if floor is None else actual == pytest.approx(floor)
    if floor is not None:
        assert result["planned_floor"] >= floor
