from scripts.research.video_reversal.backtest import candidate, maker_fill, slice_pnl, trigger_hit


def test_short_uses_completed_red_and_next_candle_strict_low_break():
    b = {"time": 60, "open": 110, "high": 112, "low": 106, "close": 108}
    c = candidate(b, "short", 100, 90, 111, 0.5)
    assert c["known"] == 120 and c["expires"] == 180
    assert c["stop"] == 112.5 and c["trigger"] == 106 and c["target"] == 90
    assert not trigger_hit(c, 106, 121)
    assert trigger_hit(c, 105.5, 121)
    assert not trigger_hit(c, 105.5, 119)
    assert not trigger_hit(c, 105.5, 180)
    assert candidate(dict(b, close=110), "short", 100, 90, 111, 0.5) is None
    assert candidate(b, "short", 100, 90, 112, 0.5) is None


def test_long_mirror_and_invalid_target():
    b = {"time": 60, "open": 90, "high": 94, "low": 88, "close": 92}
    c = candidate(b, "long", 100, 110, 89, 0.5)
    assert c["stop"] == 87.5 and trigger_hit(c, 94.5, 121)
    assert not trigger_hit(c, 94, 121)
    assert candidate(b, "long", 100, 90, 89, 0.5) is None


def test_maker_fill_later_and_fees_conserve_80_20():
    p = {"side": "short", "entry": 100, "submitted": 10}
    assert not maker_fill(p, 101, 10)
    assert not maker_fill(p, 100, 11)
    assert maker_fill(p, 100.5, 11)
    assert not maker_fill(p, 101, 25)
    one = slice_pnl("short", 100, 90, 5000, 0.001, 0.0002, 0.0005)
    a = slice_pnl("short", 100, 90, 4000, 0.001, 0.0002, 0.0005)
    b = slice_pnl("short", 100, 90, 1000, 0.001, 0.0002, 0.0005)
    assert abs(one["net"] - a["net"] - b["net"]) < 1e-10
    assert one["gross"] == 50


def test_80_percent_target_keeps_original_stop_and_conserves_costs(monkeypatch):
    from scripts.research.video_reversal import backtest

    monkeypatch.setattr(
        backtest,
        "path",
        lambda b, order: iter([(120, 105), (121, 106), (122, 99), (123, 89), (124, 113)]),
    )
    signal = {"time": 60, "open": 110, "high": 112, "low": 106, "close": 108}
    c = candidate(signal, "short", 100, 100, 111, 0.5)
    product = {
        "tick_size": ".5",
        "contract_value": "1",
        "maker_commission_rate": ".0002",
        "taker_commission_rate": ".0005",
    }
    b = {"time": 120, "open": 105, "high": 113, "low": 89, "close": 113}
    r = backtest.simulate([b], {120: [c]}, product, 120, 180, 5, "low-first", 0.5)
    assert r["trade_count"] == 1
    t = r["trades"][0]
    assert t["first_target_hit"] and t["stop"] == 112.5
    assert [s["quantity"] for s in r["slices"]] == [4, 1]
    a = slice_pnl("short", t["entry"], 100.5, 4, 1, 0.0002, 0.0005)
    tail = slice_pnl("short", t["entry"], 114, 1, 1, 0.0002, 0.0005)
    assert abs(t["net"] - a["net"] - tail["net"]) < 1e-10


def test_causal_signal_pivots_ignore_future_candles():
    from scripts.research.video_reversal.backtest import signals

    day = 86400
    values = [
        (100, 102, 99, 101),
        (101, 103, 98, 102),
        (102, 104, 95, 103),
        (103, 105, 97, 104),
        (104, 106, 98, 105),
        (105, 111, 104, 110),
        (110, 113, 108, 109),
    ]
    bars = [
        {"time": day + i * 60, "open": o, "high": h, "low": low, "close": c}
        for i, (o, h, low, c) in enumerate(values)
    ]
    d = [{"time": 0, "high": 108, "low": 90, "open": 95, "close": 100}]
    early, _ = signals(bars, d, 0.5)
    future = bars + [{"time": day + 420, "open": 109, "high": 114, "low": 94, "close": 96}]
    full, _ = signals(future, d, 0.5)
    assert early
    assert all(full[k] == v for k, v in early.items())
    c = list(early.values())[-1][0]
    assert c["target"] == 95 and c["known"] == day + 420
    assert not trigger_hit(c, c["trigger"] - 0.5, c["known"] - 1)


def test_two_trade_cap_counts_fills_and_attempt_cap_is_separate_sensitivity(monkeypatch):
    from scripts.research.video_reversal import backtest

    monkeypatch.setattr(
        backtest,
        "path",
        lambda b, order: iter([(b["time"], 105), (b["time"] + 1, 104), (b["time"] + 16, 103)]),
    )
    bars = [
        {"time": t, "open": 105, "high": 106, "low": 103, "close": 103} for t in [120, 180, 240]
    ]
    cs = {
        t: [
            candidate(
                {"time": t - 60, "open": 110, "high": 112, "low": 106, "close": 108},
                "short",
                100,
                90,
                111,
                0.5,
            )
        ]
        for t in [120, 180, 240]
    }
    p = {
        "tick_size": ".5",
        "contract_value": "1",
        "maker_commission_rate": ".0002",
        "taker_commission_rate": ".0005",
    }
    filled = backtest.simulate(bars, cs, p, 120, 300, 5, "low-first", 0.5, cap_scope="fills")
    attempts = backtest.simulate(bars, cs, p, 120, 300, 5, "low-first", 0.5, cap_scope="attempts")
    assert filled["stats"]["entry_attempts"] == 3 and filled["stats"]["unfilled_entries"] == 3
    assert (
        attempts["stats"]["entry_attempts"] == 2 and attempts["stats"]["daily_cap_rejections"] == 1
    )


def test_sweep_accepts_reclaim_close_and_entry_can_remain_beyond_reference():
    b = {"time": 0, "open": 22618, "high": 22620, "low": 22608, "close": 22610}
    c = candidate(b, "short", 22590, 22520, 22619, 0.5)
    assert trigger_hit(c, 22607.5, 61)  # Still above daily liquidity reference.
    reclaimed = {"time": 0, "open": 22610, "high": 22620, "low": 22575, "close": 22585}
    c = candidate(reclaimed, "short", 22590, 22520, 22619, 0.5)
    assert c and trigger_hit(c, 22574.5, 61)
    mirrored = {"time": 0, "open": 22580, "high": 22610, "low": 22570, "close": 22600}
    assert candidate(mirrored, "long", 22590, 22650, 22575, 0.5)


def test_unfinished_daily_candle_cannot_change_previous_day_reference():
    from scripts.research.video_reversal.backtest import signals

    day = 86400
    values = [
        (100, 102, 99, 101),
        (101, 103, 98, 102),
        (102, 104, 95, 103),
        (103, 105, 97, 104),
        (104, 106, 98, 105),
        (105, 111, 104, 110),
        (110, 113, 108, 109),
    ]
    bars = [
        {"time": day + i * 60, "open": o, "high": h, "low": low, "close": c}
        for i, (o, h, low, c) in enumerate(values)
    ]
    daily = [{"time": 0, "high": 108, "low": 90, "open": 95, "close": 100}]
    a, _ = signals(bars, daily, 0.5)
    b, _ = signals(
        bars, daily + [{"time": day, "high": 10000, "low": 1, "open": 100, "close": 500}], 0.5
    )
    assert a and a == b
