import asyncio
import time
from decimal import Decimal as D

import pytest

from strategies.confluence.live import backend
from strategies.liquidity.execution import Engine, types
from strategies.liquidity.paper import broker_type
from strategies.liquidity.setup import Config


def rig(tmp_path, qty=1, **options):
    cfg = Config(max_quantity=qty, max_risk=5, max_margin=100, daily_loss=10, **options)
    Ledger, _ = types(cfg)
    s = Ledger(tmp_path / "paper.sqlite")
    s.bind()
    _, _, market, _, risk, _, _ = backend()
    p = risk.Product(contract=D(1), tick=D(".01"), maker=D(".0002"), taker=D(".0005"))
    b = market.Book()
    now = time.time()
    quote(b, 100, now)
    broker = broker_type()(p, b, s)
    e = Engine(s, broker, b, p, cfg)
    return s, b, broker, e, now


def quote(b, price, now):
    b.bids = [(D(str(price)), D(1000))]
    b.asks = [(D(str(price)) + D(".01"), D(1000))]
    b.ts = now
    b.received = now


def plan(qty=1, partial=0, stop=99):
    return {
        "entry": 100,
        "stop": stop,
        "target": 110,
        "partial_target": 101,
        "side": "buy",
        "quantity": qty,
        "leverage": 5,
        "net_risk": 4.5,
        "net_target": 10,
        "margin": 20 * qty,
        "partial_quantity": partial,
        "slippage_reserve": 0.1,
    }


def fill(broker, now, price, qty, side="sell", ident="entry"):
    broker.on_trade({"id": ident, "price": D(str(price)), "size": D(qty), "side": side, "ts": now})


def test_paper_entry_partial_target_runner_exit_and_restart(tmp_path):
    async def scenario():
        s, b, broker, e, now = rig(tmp_path, 4)
        try:
            assert await e.submit(plan(4, 2, 99.8), "setup", now)
            # Trade through plus sufficient observed queue; no touch fill.
            fill(broker, now + 0.1, 100, 2000)
            assert s.get("position")["filled"] == 0
            fill(broker, now + 0.2, 99.99, 2004, ident="through")
            await e.manage(now + 0.3)
            t = s.get("position")
            assert t["filled"] == 4 and t["partial_quantity"] == 2
            assert t["protected"] and D(t["ack_stop"]) >= D("99.8")
            quote(b, 100.3, now + 1)
            fill(broker, now + 1, 100.3, 2002, "buy", "first-target")
            await e.manage(now + 1)
            t = s.get("position")
            assert t["open_qty"] == 2 and t["partial_done"]
            assert D(t["protected_net"]) >= 0
            # New broker/engine reconstruct outstanding runner and stop from DB.
            restored = broker_type()(e.p, b, s)
            restored.restore(t)
            resumed = Engine(s, restored, b, e.p, e.cfg)
            quote(b, 110.1, now + 2)
            fill(restored, now + 2, 110.1, 2002, "buy", "runner")
            await resumed.manage(now + 2)
            assert s.get("position") is None
            assert len(s.trades()) == 1 and D(s.trades()[0]["net"]) > 0
            assert not await resumed.submit(plan(4, 2), "setup", now + 3)
        finally:
            s.close()

    asyncio.run(scenario())


def test_net_floor_trails_tighten_only_and_survives_reload(tmp_path):
    async def scenario():
        s, b, broker, e, now = rig(tmp_path)
        try:
            await e.submit(plan(), "one", now)
            fill(broker, now + 0.1, 99.99, 2001)
            t = s.get("position")
            t["liquidation"] = "80"
            s.set("position", t)
            quote(b, 103, now + 1)
            await e.manage(now + 1)
            first = s.get("position")
            stop = D(first["ack_stop"])
            assert D(first["peak"]) > 2 and D(first["protected_net"]) >= D("1.5")
            quote(b, 104, now + 2)
            await e.manage(now + 2)
            second = s.get("position")
            assert D(second["ack_stop"]) > stop
            quote(b, 103.8, now + 3)
            await e.manage(now + 3)
            assert D(s.get("position")["ack_stop"]) == D(second["ack_stop"])
            assert s.get("position")["partial_quantity"] == 0
        finally:
            s.close()

    asyncio.run(scenario())


def test_partial_entry_cancels_remainder_and_does_not_loosen_stop(tmp_path):
    async def scenario():
        s, b, broker, e, now = rig(tmp_path, 4)
        try:
            await e.submit(plan(4, 2), "partial", now)
            fill(broker, now + 0.1, 99.99, 1001)
            await e.manage(now + 0.2)
            t = s.get("position")
            assert t["filled"] == 1 and not t["entry_open"] and t["partial_quantity"] == 0
            assert D(t["ack_stop"]) >= D("99")
            fill(broker, now + 0.3, 99.98, 1000, ident="late")
            assert s.get("position")["filled"] == 1
        finally:
            s.close()

    asyncio.run(scenario())


def test_submission_timeout_is_durable_and_not_submitted_twice(tmp_path):
    async def scenario():
        s, b, broker, e, now = rig(tmp_path)
        calls = []

        async def uncertain(t):
            calls.append(t["id"])
            raise TimeoutError("synthetic unknown submission")

        broker.entry = uncertain
        try:
            with pytest.raises(TimeoutError):
                await e.submit(plan(), "unknown", now)
            assert s.get("position") and s.get("consumed") == "unknown"
            assert not await e.submit(plan(), "unknown", now + 1)
            assert len(calls) == 1 and s.daily(now)["entries"] == 1
        finally:
            s.close()

    asyncio.run(scenario())


def test_entry_timeout_uses_clock_after_slow_sync(tmp_path, monkeypatch):
    async def scenario():
        s, b, broker, e, now = rig(tmp_path)
        current = [now + 10]
        monkeypatch.setattr("strategies.liquidity.execution.time.time", lambda: current[0])
        original = broker.sync

        async def slow_sync(t):
            current[0] += 20
            await original(t)

        broker.sync = slow_sync
        try:
            await e.submit(plan(), "timeout", now)
            await e.manage()
            assert s.get("position") is None
        finally:
            s.close()

    asyncio.run(scenario())


def test_live_target_does_not_submit_after_lookup_stales_book(tmp_path):
    async def scenario():
        from unittest.mock import AsyncMock, Mock

        s, b, paper, e, now = rig(tmp_path)
        _, Broker = types(e.cfg)
        broker = object.__new__(Broker)
        broker.book = b
        broker.p = e.p
        broker.save = Mock()
        broker.rest = Mock(mutate=AsyncMock())

        async def slow_order(_):
            b.ts = b.received = time.time() - 10
            return {"state": "cancelled"}

        broker.order = slow_order
        t = {"open_qty": 1, "filled": 1, "target_id": "old", "partial_quantity": 0}
        try:
            await broker.target(t)
            broker.rest.mutate.assert_not_awaited()
            assert "target_id" not in t
        finally:
            s.close()

    asyncio.run(scenario())

@pytest.mark.parametrize("side,price", [("buy", "100"), ("sell", "100.01")])
def test_live_entries_are_post_only_with_native_stop_and_no_taker_retry(tmp_path, side, price):
    async def scenario():
        s, book, _, engine, _ = rig(tmp_path)
        _, Broker = types(engine.cfg)
        _, _, _, rest_module, _, _, _ = backend()
        calls = []

        class Rest:
            async def mutate(self, method, path, payload, ident):
                calls.append((method, path, payload.copy(), ident))
                raise rest_module.ExchangeError("post_only_order_would_execute")

        broker = Broker(Rest(), engine.p, book, s)
        trade = dict(id="maker-test", side=side, entry=price, stop="99", qty=1)
        try:
            with pytest.raises(rest_module.ExchangeError, match="post_only"):
                await broker.entry(trade)
            assert len(calls) == 1
            payload = calls[0][2]
            assert payload["post_only"] == "true"
            assert payload["order_type"] == "limit_order"
            assert payload["time_in_force"] == "gtc"
            assert payload["reduce_only"] == "false"
            assert payload["bracket_stop_loss_price"] == "99"
            assert s.get("position")["entry_execution"] == "post_only"
        finally:
            s.close()

    asyncio.run(scenario())
