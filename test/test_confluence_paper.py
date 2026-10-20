"""Isolated synthetic paper execution, never connected to an account."""

import copy

import pytest

from strategies.confluence.paper import Ledger, PaperBook, wallet_seed
from strategies.confluence.strategy import Config

NOW = 1791288000.0


def quote(now=NOW, bid=85000, ask=85000.5, trades=None):
    return {
        "bid": bid,
        "ask": ask,
        "quote_time": now,
        "bids": [[bid, 1]],
        "asks": [[ask, 1]],
        "trades": trades or [],
    }


def signal(side=1):
    return {
        "action": "LONG" if side == 1 else "SHORT",
        "candle_closed": NOW,
        "asof": NOW,
        "selected_plan": {
            "entry": 85000 if side == 1 else 85000.5,
            "stop": 84900 if side == 1 else 85100.5,
            "target": 86500 if side == 1 else 83500,
            "quantity": 1,
            "contract_value": 0.001,
            "tick": 0.5,
            "maker_rate": 0.0002,
            "taker_rate": 0.0005,
            "margin": 3.4,
            "net_risk": 0.28,
            "fits_risk": True,
        },
    }


def trade(now=NOW + 1, price=84999, side="sell", size=5):
    return {"timestamp": now, "price": price, "side": side, "size": size}


@pytest.mark.parametrize("side", [1, -1])
def test_touch_does_not_fill_then_trade_through_fills_once(side):
    p = PaperBook.fresh(20, NOW, Config())
    s = signal(side)
    price = s["selected_plan"]["entry"]
    aggressor = "sell" if side == 1 else "buy"
    p.step(quote(), s, NOW)
    p.step(quote(NOW + 1, trades=[trade(price=price, side=aggressor)]), None, NOW + 1)
    assert p.state["pending"] and not p.state["position"]
    q = quote(NOW + 2, trades=[trade(NOW + 2, price - side, aggressor)])
    p.step(q, None, NOW + 2)
    assert p.state["position"]["quantity"] == 1 and not p.state["pending"]
    state = copy.deepcopy(p.state)
    p.step(q, None, NOW + 2)
    assert p.state["position"] == state["position"]


def test_repeated_tape_cannot_drain_queue_twice():
    p = PaperBook.fresh(20, NOW, Config())
    q = quote()
    q["bids"] = [[85000, 20]]
    p.step(q, signal(), NOW)
    q = quote(NOW + 1, trades=[trade(size=10)])
    p.step(q, None, NOW + 1)
    p.step(q, None, NOW + 2)
    assert p.state["pending"]["queue_remaining"] == 11


def test_timeout_no_reentry_same_candle_and_disconnect_cancels():
    p = PaperBook.fresh(20, NOW, Config())
    p.step(quote(), signal(), NOW)
    p.step(quote(NOW + 16), signal(), NOW + 16)
    assert not p.state["pending"] and p.state["submitted"] == 1
    p = PaperBook.fresh(20, NOW, Config())
    p.step(quote(), signal(), NOW)
    p.disconnect(NOW + 1)
    assert not p.state["pending"]


def filled():
    p = PaperBook.fresh(20, NOW, Config())
    p.step(quote(), signal(), NOW)
    p.step(quote(NOW + 1, trades=[trade()]), None, NOW + 1)
    return p


def test_stop_fees_gst_once_and_cash_reconciles():
    p = filled()
    p.step(quote(NOW + 2, 84890, 84890.5), None, NOW + 2)
    t = p.trades[-1]
    assert t["reason"] == "stop" and t["exit_role"] == "taker"
    assert t["gross_usd"] == pytest.approx(-0.11)
    assert t["fees_usd"] == pytest.approx((85000 * 0.0002 + 84890 * 0.0005) * 0.001 * 1.18)
    assert t["net_usd"] == pytest.approx(t["gross_usd"] - t["fees_usd"] - 0.1)
    assert p.state["cash"] == pytest.approx(20 + t["net_usd"])


def test_target_touch_not_fill_and_stop_wins_race():
    p = filled()
    p.state["position"]["target"] = 85500
    p.step(quote(NOW + 2, 85499, 85499.5, [trade(NOW + 2, 85500, "buy")]), None, NOW + 2)
    assert p.state["position"]
    p.step(quote(NOW + 3, 84800, 84800.5, [trade(NOW + 3, 85501, "buy")]), None, NOW + 3)
    assert p.trades[-1]["reason"] == "stop"


def test_target_charges_maker_and_deadline_forces_taker():
    p = filled()
    p.state["position"]["target"] = 85500
    p.step(quote(NOW + 2, 85501, 85501.5, [trade(NOW + 2, 85501, "buy")]), None, NOW + 2)
    assert p.trades[-1]["exit_role"] == "maker"
    p = filled()
    p.step(quote(NOW + 1741), None, NOW + 1741)
    assert p.trades[-1]["reason"] == "time_limit"


def test_halt_persists_across_days_until_explicit_resume():
    p = filled()
    p.state["loss_streak"] = 2
    p.step(quote(NOW + 2, 84800, 84800.5), None, NOW + 2)
    with pytest.raises(ValueError):
        p.resume(NOW + 3)
    p.step(quote(NOW + 86400), signal(), NOW + 86400)
    assert p.state["halt_day"] is not None and not p.state["pending"]
    p.resume(NOW + 86400)
    assert p.state["halt_day"] is None


def test_ledger_restart_preserves_stop_and_single_instance(tmp_path):
    path = tmp_path / "paper.sqlite"
    with Ledger(path) as db:
        p = filled()
        db.save(p)
        with pytest.raises(RuntimeError):
            with Ledger(path):
                pass
    with Ledger(path) as db:
        p = db.load(Config())
        assert p.state["position"]["stop"] == 84900
        p.stop(quote(NOW + 2), NOW + 2)
        db.save(p)
    with Ledger(path) as db:
        p = db.load(Config())
        assert p.state["position"] is None and db.report()["trade_count"] == 1


def test_wallet_seed_is_fresh_usd_and_never_guessed():
    s = {
        "environment": "india_prod",
        "captured_at": NOW,
        "result": [{"asset_symbol": "USD", "available_balance": "12.3"}],
    }
    assert wallet_seed(s, NOW) == 12.3
    with pytest.raises(ValueError):
        wallet_seed(s, NOW + 601)
    with pytest.raises(ValueError):
        wallet_seed({**s, "environment": "other"}, NOW)


def test_stale_shutdown_keeps_unresolved_position():
    p = filled()
    p.stop(quote(), NOW + 20)
    assert p.state["position"] and p.state["paused"] and "unresolved" in p.state["status"]
