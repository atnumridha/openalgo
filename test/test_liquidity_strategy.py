import copy

from strategies.liquidity.setup import Config, advance, plan_order


def candle(t, o, h, low, c):
    return {"time": t, "open": o, "high": h, "low": low, "close": c, "volume": 1}


def run_sequence(side=1):
    bars = [candle(t, 105, 106, 104, 105) for t in range(0, 1200, 60)]
    bars += [
        candle(1200, 101, 104, 99, 103),  # first buyer: deliberately skipped
        candle(1260, 103, 104, 98, 100),  # meaningful seller below buyer's open
        candle(1320, 100, 106, 99, 105),
    ]  # renewed buyer above seller high
    refs = [
        {"id": "support", "side": "Low", "price": 100, "known": 0, "frame": "1H"},
        {"id": "target", "side": "High", "price": 130, "known": 0, "frame": "4H"},
    ]
    if side < 0:
        bars = [
            dict(
                b,
                open=210 - b["open"],
                close=210 - b["close"],
                high=210 - b["low"],
                low=210 - b["high"],
            )
            for b in bars
        ]
        refs = [
            dict(r, price=210 - r["price"], side="High" if r["side"] == "Low" else "Low")
            for r in refs
        ]
    return bars, refs


def test_extra_confirmation_skips_first_buyer_and_freezes_trigger():
    bars, refs = run_sequence()
    state = {"last_bar": 1140}
    cfg = Config()
    advance(state, bars[:21], refs, {"bid": 103, "ask": 103.5, "time": 1260}, cfg, 1260)
    assert state["candidate"]["stage"] == "COUNTERATTACK"
    state["observed_at"] = 1319  # Quotes continued between candle closes.
    advance(state, bars[:22], refs, {"bid": 100, "ask": 100.5, "time": 1320}, cfg, 1320)
    assert state["candidate"]["stage"] == "RENEWED_CONFIRMATION"
    state["observed_at"] = 1379
    advance(state, bars, refs, {"bid": 105, "ask": 105.5, "time": 1380}, cfg, 1380)
    c = state["candidate"]
    assert c["stage"] == "WATCHING" and c["trigger"] == 106 and c["extreme"] == 98
    advance(state, bars, refs, {"bid": 106, "ask": 106.5, "time": 1381}, cfg, 1381)
    assert c["stage"] == "WATCHING"
    advance(state, bars, refs, {"bid": 106.5, "ask": 107, "time": 1382}, cfg, 1382)
    assert c["stage"] == "TRIGGERED" and c["triggered_at"] == 1382
    restored = copy.deepcopy(state)
    advance(restored, bars, refs, {"bid": 107, "ask": 107.5, "time": 1383}, cfg, 1383)
    assert restored["candidate"]["id"] == c["id"]
    assert restored["candidate"]["triggered_at"] == 1382


def test_short_is_explicit_opt_in_mirror():
    bars, refs = run_sequence(-1)
    state = {"last_bar": 1140}
    advance(state, bars, refs, {"bid": 104.5, "ask": 105, "time": 1380}, Config(shorts=True), 1380)
    assert state["candidate"]["direction"] == "SHORT"
    advance(state, bars, refs, {"bid": 103, "ask": 103.5, "time": 1381}, Config(shorts=True), 1381)
    assert state["candidate"]["stage"] == "TRIGGERED"


def test_restart_gap_does_not_trigger_missed_crossing():
    bars, refs = run_sequence()
    state = {"last_bar": 1140}
    advance(state, bars, refs, {"bid": 105, "ask": 105.5, "time": 1380}, Config(), 1380)
    advance(state, bars, refs, {"bid": 107, "ask": 107.5, "time": 1400}, Config(), 1400)
    assert state["candidate"]["stage"] == "DATA_GAP"


def test_no_future_pivot_or_incomplete_candle_entry():
    bars, refs = run_sequence()
    state = {"last_bar": 1140}
    future = [dict(r, known=1800) for r in refs]
    advance(state, bars, future, {"bid": 107, "ask": 107.5, "time": 1380}, Config(), 1380)
    assert state.get("candidate") is None
    state = {"last_bar": 1140}
    advance(state, bars, refs, {"bid": 107, "ask": 107.5, "time": 1350}, Config(), 1350)
    assert state["candidate"]["stage"] == "RENEWED_CONFIRMATION"


def test_sizing_respects_whole_contracts_fees_and_no_chasing():
    c = {
        "id": "x",
        "direction": "LONG",
        "stage": "TRIGGERED",
        "trigger": 81010,
        "extreme": 80980,
        "atr": 100,
        "target": 81500,
        "triggered_at": 100,
        "expires": 600,
    }
    p = {
        "contract_value": ".001",
        "tick_size": ".5",
        "maker_commission_rate": ".0002",
        "taker_commission_rate": ".0005",
        "maintenance_margin": ".25",
        "maintenance_margin_scaling_factor": ".00000125",
        "initial_margin": ".5",
        "product_specs": {"isolated_liq_penalty_factor": ".0005"},
    }
    quote = {"bid": 81011, "ask": 81011.5, "time": 101}
    result = plan_order(c, quote, p, Config(), 101, 100)
    assert result["quantity"] == 1 and result["stop"] == 80979.5
    assert result["net_risk"] < 1 and result["partial_quantity"] == 0
    assert result["margin"] <= 25 and result["leverage"] == 5
    assert plan_order(c, dict(quote, bid=81100, ask=81100.5), p, Config(), 101, 100)["blocked"]


def test_counterattack_doji_does_not_qualify_and_expiry():
    bars, refs = run_sequence()
    bars[21] = candle(1260, 100, 104, 98, 100)
    state = {"last_bar": 1140}
    advance(state, bars, refs, {"bid": 105, "ask": 105.5, "time": 1380}, Config(), 1380)
    assert state["candidate"]["stage"] == "COUNTERATTACK"
    # A long pause abandons it even if price now crosses.
    advance(state, bars, refs, {"bid": 108, "ask": 108.5, "time": 2000}, Config(), 2000)
    assert state["candidate"]["stage"] != "TRIGGERED"
