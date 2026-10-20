from scripts.research.video_reversal.expiry_rupees import premium_plan, replay


def test_net_two_r_includes_zero_brokerage_taxes():
    def fee(buy, sell):
        return 10

    p = premium_plan(100, 2, 65, 0.05, 2, fee)
    assert p["stop"] < p["entry"] < p["target"]
    assert p["risk_rupees"] > (p["entry"] - p["stop"]) * 65
    assert (p["target"] - p["entry"]) * 65 - 10 >= 2 * p["risk_rupees"]


def test_same_bar_is_stop_first_and_gaps_are_adverse():
    plan = {"entry": 100, "stop": 95, "target": 110, "risk_rupees": 335}
    both = {"timestamp": 60, "open": 100, "high": 115, "low": 90, "close": 105, "volume": 10}
    t = replay([both], 60, 120, plan, 65, lambda b, s: 10, 0.05)
    assert t["reason"] == "stop" and t["exit"] == 94.9 and t["net"] < 0
    gap = dict(both, open=90, high=95, low=89, close=92)
    t = replay([gap], 60, 120, plan, 65, lambda b, s: 10, 0.05)
    assert t["exit"] == 89.9


def test_missing_and_zero_volume_bars_never_become_profit():
    p = {"entry": 100, "stop": 95, "target": 110, "risk_rupees": 335}
    b = {"timestamp": 60, "open": 100, "high": 105, "low": 99, "close": 104, "volume": 10}
    t = replay([b], 60, 240, p, 65, lambda b, s: 10, 0.05)
    assert t["net"] is None and t["reason"] == "missing_or_invalid_bar"
    t = replay([dict(b, volume=0)], 60, 120, p, 65, lambda b, s: 10, 0.05)
    assert t["net"] is None


def test_expiry_cutoff_closes_and_contract_units_scale_pnl():
    p = {"entry": 100, "stop": 95, "target": 110, "risk_rupees": 335}
    b = {"timestamp": 60, "open": 100, "high": 105, "low": 99, "close": 104, "volume": 10}
    t = replay([b], 60, 120, p, 65, lambda b, s: 10, 0.05)
    assert t["exit"] == 103.9 and abs(t["net"] - 243.5) < 1e-8


def test_option_atr_cannot_use_current_or_future_bar():
    from scripts.research.video_reversal.expiry_rupees import atr_before

    rows = [
        {"timestamp": i * 60, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}
        for i in range(15)
    ]
    assert atr_before(rows, 900) == 2
    assert (
        atr_before(
            rows
            + [{"timestamp": 900, "open": 100, "high": 900, "low": 1, "close": 500, "volume": 999}],
            900,
        )
        == 2
    )
    assert atr_before(rows[:-1], 900) is None


def test_higher_reward_caps_remain_at_or_below_selected_multiple():
    for reward in [5, 10]:
        p = premium_plan(100.03, 2.13, 65, 0.05, reward, lambda b, s: 10)
        assert 2 <= p["planned_net_reward_r"] <= reward


def test_trailing_uses_completed_close_and_only_applies_next_bar():
    plan = {"entry": 100, "stop": 95, "target": 130, "risk_rupees": 5}
    rows = [
        {"timestamp": 60, "open": 100, "high": 120, "low": 96, "close": 110, "volume": 10},
        {"timestamp": 120, "open": 110, "high": 112, "low": 104, "close": 106, "volume": 10},
    ]
    t = replay(rows, 60, 180, plan, 1, lambda b, s: 0, 0.05, trailing=True)
    assert t["reason"] == "trailing_stop"
    assert t["exit_time"] == 180
    assert t["net"] >= 4.9 - 1e-9
    assert t["stop_updates"][0]["effective_from"] == 120


def test_trailing_holds_on_pullback_and_never_widens():
    plan = {"entry": 100, "stop": 95, "target": 150, "risk_rupees": 5}
    rows = [
        {
            "timestamp": 60 + i * 60,
            "open": v,
            "high": v + 1,
            "low": v - 0.1,
            "close": v,
            "volume": 10,
        }
        for i, v in enumerate([106, 105, 110, 109])
    ]
    t = replay(rows, 60, 300, plan, 1, lambda b, s: 0, 0.05, trailing=True)
    stops = [u["stop"] for u in t["stop_updates"]]
    assert stops == sorted(stops)
    assert len(stops) == 2


def test_trailing_fee_adjusted_breakeven_and_gap_risk():
    plan = {"entry": 100, "stop": 95, "target": 200, "risk_rupees": 7}
    rows = [
        {"timestamp": 60, "open": 100, "high": 112, "low": 96, "close": 110, "volume": 10},
        {"timestamp": 120, "open": 99, "high": 102, "low": 98, "close": 100, "volume": 10},
    ]
    t = replay(rows, 60, 180, plan, 1, lambda b, s: 2, 0.05, trailing=True)
    assert t["stop_updates"][0]["protected_net"] >= 0
    assert t["net"] < 0  # gaps can exceed the planned floor
