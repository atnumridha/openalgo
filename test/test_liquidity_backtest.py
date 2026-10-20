from scripts.research.liquidity.backtest import (
    exit_price,
    maker_fill,
    net_pnl,
    pivot_references,
    reference_snapshot,
)


def bar(t, high, low):
    return {
        "time": t,
        "open": (high + low) / 2,
        "close": (high + low) / 2,
        "high": high,
        "low": low,
    }


def test_pivot_needs_two_right_candles_and_does_not_use_future_touch():
    rows = [
        bar(i * 3600, high, low)
        for i, (high, low) in enumerate([(10, 8), (11, 7), (14, 5), (12, 6), (11, 7), (15, 4)])
    ]
    refs = pivot_references(rows[:5], 3600, "1H", [])
    assert {r["known"] for r in refs} == {18000}
    assert pivot_references(rows[:4], 3600, "1H", []) == []
    assert reference_snapshot(refs, 18000) == reference_snapshot(
        pivot_references(rows, 3600, "1H", []), 18000
    )


def test_maker_requires_later_strict_trade_through_within_deadline():
    p = {"side": "buy", "entry": 100, "submitted": 10}
    assert not maker_fill(p, 99, 10)
    assert not maker_fill(p, 100, 11)
    assert maker_fill(p, 99.99, 11)
    assert not maker_fill(p, 99, 25)
    assert maker_fill(dict(p, side="sell"), 101, 11)


def test_costs_and_gaps_are_adverse():
    product = {
        "contract_value": "0.001",
        "maker_commission_rate": "0.0001",
        "taker_commission_rate": "0.0001",
        "tick_size": ".01",
    }
    assert abs(net_pnl("buy", 4000, 4100, 1, product, 0.1) - (-0.0009558)) < 1e-8
    assert exit_price("buy", 95, 99) == 95
    assert exit_price("sell", 105, 101) == 105


def test_blocked_trigger_is_rechecked_then_submitted_only_once(monkeypatch):
    from scripts.research.liquidity import backtest
    from strategies.liquidity.setup import Config

    calls = []

    def advance(state, bars, refs, quote, cfg, now):
        if "candidate" not in state:
            state["candidate"] = {
                "id": "retry",
                "stage": "TRIGGERED",
                "direction": "LONG",
                "triggered_at": now,
                "target": 110,
                "extreme": 99,
                "trigger": 100,
            }
        return state

    def plan(c, q, product, cfg, now, collateral):
        calls.append(now)
        if len(calls) == 1:
            return {"blocked": "Transient quote"}
        return {
            "setup_id": "retry",
            "side": "buy",
            "entry": 100,
            "stop": 99,
            "target": 110,
            "quantity": 1,
            "net_risk": 0.2,
        }

    monkeypatch.setattr(backtest, "advance", advance)
    monkeypatch.setattr(backtest, "plan_order", plan)
    minutes = [
        {"time": i * 60, "open": 100, "high": 100, "low": 100, "close": 100} for i in range(20)
    ]
    product = {
        "contract_value": ".001",
        "tick_size": ".01",
        "maker_commission_rate": ".0001",
        "taker_commission_rate": ".0001",
        "product_specs": {"rate_exchange_interval": 14400},
    }
    result = backtest.simulate(minutes, [], product, Config(leverage=2), 900, 1200, "low-first")
    assert calls == [900, 901]
    assert result["stats"]["signals"] == 1
    assert result["stats"]["entry_attempts"] == 1
    assert result["stats"]["unfilled_entries"] == 1
    assert result["blocked"] == {}


def test_gap_resets_history_instead_of_using_discontinuous_candles(monkeypatch):
    from scripts.research.liquidity import backtest
    from strategies.liquidity.setup import Config

    lengths = []

    def advance(state, bars, *args):
        lengths.append(len(bars))

    monkeypatch.setattr(backtest, "advance", advance)
    minutes = [
        {"time": i * 60, "open": 100, "high": 100, "low": 100, "close": 100}
        for i in range(20)
        if i != 16
    ]
    product = {"tick_size": ".01"}
    result = backtest.simulate(minutes, [], product, Config(), 0, 1200, "low-first")
    assert result["stats"]["data_gaps"] == 1
    assert lengths == [15]
    assert result["trade_count"] == 0


def test_fixed_quantity_research_keeps_5000_and_preserves_live_config_limit():
    from dataclasses import asdict
    from types import SimpleNamespace

    import pytest

    from scripts.research.liquidity.fixed_quantity import exact_plan
    from strategies.liquidity.setup import Config

    base = Config(leverage=2)
    cfg = SimpleNamespace(**dict(asdict(base), max_quantity=5000))
    product = {"contract_value": ".001", "tick_size": ".01"}
    c = {"stage": "TRIGGERED", "direction": "LONG"}
    result = exact_plan(c, {"bid": 4300, "ask": 4300.02}, product, cfg, 0, 1e6)
    assert result["blocked"] == "Exact quantity exceeds margin and/or notional limits"
    assert cfg.max_quantity == 5000
    assert Config().max_quantity == 1
    with pytest.raises(ValueError, match="max_quantity"):
        Config(max_quantity=5000)
