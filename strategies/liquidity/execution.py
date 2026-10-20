"""Strategy-specific policy over the existing durable Delta broker adapter.

The installed adapter owns authenticated mutations, durable intents and recovery.
This module owns partial targets and the user's $2/$1.50/$0.50 net policy.
"""

import time
import uuid
from dataclasses import asdict
from decimal import Decimal as D

from strategies.confluence.live import backend

from .setup import VERSION


def types(cfg):
    _, live, market, rest, risk, safety, store = backend()
    profile = risk.RiskProfile(
        VERSION,
        D(str(cfg.max_risk)),
        D(str(cfg.max_margin)),
        D(str(cfg.max_notional)),
        D(str(cfg.daily_loss)),
        (cfg.leverage,),
    )

    class Ledger(store.Store):
        def profile(self):
            return profile

        def bind(self):
            old = self.get("liquidity_config")
            if old and old != asdict(cfg) and (self.get("position") or self.unresolved()):
                raise ValueError(
                    "Saved execution settings differ; preserve the original ledger configuration"
                )
            self.set("liquidity_config", asdict(cfg))

        def daily(self, now=None):
            stamp = now or time.time()
            today = store.day(stamp)
            boundary = int((stamp + 19800) // 86400) * 86400 - 19800
            net = D(0)
            streak = 0
            import json

            for (item,) in self.db.execute(
                "SELECT value FROM trades WHERE closed_at>=? AND closed_at<? ORDER BY closed_at,id",
                (boundary, boundary + 86400),
            ):
                n = D(json.loads(item)["net"])
                net += n
                if n < 0:
                    streak += 1
                elif n > 0:
                    streak = 0
            if net <= -profile.daily_loss or streak >= 3:
                self.set("daily_halt_day", today)
            row = {
                "day": today,
                "net": str(net),
                "loss_streak": streak,
                "halted": bool(self.get("daily_halt_day")),
                "budget": str(max(D(0), min(profile.loss, profile.daily_loss + net))),
            }
            count = self.db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='entry_attempt' AND json_extract(value,'$.day')=?",
                (today,),
            ).fetchone()[0]
            row.update(entries=count, entry_limit=cfg.max_trades)
            row["halted"] = row["halted"] or count >= cfg.max_trades
            return row

    class Broker(live.LiveBroker):
        async def entry(self, t):
            t["entry_execution"] = "post_only"
            # Parent always sends a GTC post-only limit with its native stop.
            # Propagate rejections/unknown outcomes; never retry as market/IOC.
            return await super().entry(t)

        async def preflight(self):
            from strategies.confluence.live import live_types

            # The existing adapter verifies isolated margin, no auto-top-up,
            # selected leverage, empty BTCUSD exposure and current collateral.
            _, Parent = live_types(cfg)
            return await Parent.preflight(self)

        def restore_roles(self, t):
            super().restore_roles(t)
            if t.get("target_id") in t.get("retired_targets", []):
                t.pop("target_id", None)

        async def target(self, t):
            if not t["open_qty"]:
                return
            partial = t.get("partial_quantity", 0)
            if t.get("target_id"):
                order = await self.order(t["target_id"])
                if order["state"] not in ("closed", "cancelled"):
                    return
                # A closed target must agree with reconciled fills before the
                # next target can be placed. Rejected/cancelled orders are not fills.
                if t.get("target_phase") == "partial" and t["filled"] - t["open_qty"] >= partial:
                    t["partial_done"] = True
                elif order["state"] == "closed" and t["open_qty"]:
                    raise rest.ExchangeError("target_fill_reconciliation_pending")
                t.setdefault("retired_targets", []).append(t.pop("target_id"))
                self.save(t)
            # An order lookup can outlive the executable book snapshot.
            if not self.book.fresh(time.time()):
                return
            phase = "partial" if partial and not t.get("partial_done") else "runner"
            qty = (
                min(partial - (t["filled"] - t["open_qty"]), t["open_qty"])
                if phase == "partial"
                else t["open_qty"]
            )
            if qty <= 0:
                return
            price = D(t["partial_target"] if phase == "partial" else t["target"])
            # A crossed target cannot rest post-only. Close the intended slice
            # reduce-only, keeping the native full-position stop in place.
            crossed = self.book.bid >= price if t["side"] == "buy" else self.book.ask <= price
            cid = self.intent_id(t, "tp")[:32]
            payload = {
                "product_id": self.p.id,
                "size": qty,
                "side": "sell" if t["side"] == "buy" else "buy",
                "order_type": "market_order" if crossed else "limit_order",
                "reduce_only": "true",
                "client_order_id": cid,
            }
            if not crossed:
                payload.update(limit_price=str(price), post_only="true")
            t["target_phase"] = phase
            self.save(t)
            o = await self.rest.mutate("POST", "/orders", payload, cid)
            t["target_id"] = o["id"]
            t["owned_ids"].append(o["id"])
            self.save(t)

    return Ledger, Broker


class Engine:
    def __init__(self, store, broker, book, product, cfg):
        self.store, self.broker, self.book, self.p, self.cfg = store, broker, book, product, cfg

    async def submit(self, plan, candidate_id, now=None, metadata=None):
        _, _, _, _, risk, _, store_module = backend()
        now = now or time.time()
        s = self.store
        cfg = self.cfg
        if s.get("position") or s.get("paused") or s.daily(now)["halted"]:
            return False
        if candidate_id == s.get("consumed"):
            return False
        if (
            plan["quantity"] > cfg.max_quantity
            or plan["net_risk"] > min(cfg.max_risk, float(s.daily(now)["budget"]))
            or plan["margin"] > cfg.max_margin
            or plan["entry"] * plan["quantity"] * float(self.p.contract) > cfg.max_notional
        ):
            return False
        t = {k: str(plan[k]) for k in ("entry", "stop", "target", "partial_target")}
        t.update(
            id="lx" + uuid.uuid4().hex[:18],
            candidate_id=candidate_id,
            side=plan["side"],
            qty=plan["quantity"],
            leverage=cfg.leverage,
            risk=str(plan["net_risk"]),
            planned_net_target=str(plan["net_target"]),
            slippage=str(plan["slippage_reserve"]),
            profile=VERSION,
            created=now,
            filled=0,
            open_qty=0,
            peak="0",
            entry_open=True,
            intended_partial=plan["partial_quantity"],
            funding_at=(metadata or {}).get("funding_at", 0),
        )
        # All entry identities and the daily attempt counter commit together.
        with s.db:
            for key, value in [("consumed", candidate_id), ("position", t)]:
                s.db.execute(
                    "INSERT OR REPLACE INTO kv VALUES (?,?)", (key, store_module.encode(value))
                )
            s.db.execute(
                "INSERT INTO events(ts,kind,value) VALUES (?,?,?)",
                (
                    now,
                    "entry_attempt",
                    store_module.encode({"day": store_module.day(now), "setup": candidate_id}),
                ),
            )
        await self.broker.entry(t)
        s.set("position", t)
        return True

    async def manage(self, now=None):
        _, _, _, _, r, _, _ = backend()
        real_clock = now is None
        now = now or time.time()
        s = self.store
        t = s.get("position")
        if not t:
            return
        try:
            await self.broker.sync(t)
            if real_clock:
                now = time.time()
            if t.get("entry_open") and (now - t["created"] >= 15 or t["filled"] or s.get("paused")):
                await self.broker.cancel_entry(t)
                await self.broker.sync(t)
            if real_clock:
                now = time.time()
            if not t["open_qty"]:
                if t.get("entry_open"):
                    return
                if t["filled"]:
                    if not t.get("fees_final"):
                        return
                    t["net"] = str(
                        D(t.get("gross", "0"))
                        - D(t["entry_fees"])
                        - D(t["exit_fees"])
                        + D(t.get("funding", "0"))
                    )
                    t["closed_at"] = t.get("closed_at", now)
                    s.record_trade(t)
                await self.broker.cleanup(t)
                s.set("position", None)
                return
            if not t.get("protected"):
                try:
                    await self.broker.protect(t, D(t.get("ack_stop", t["stop"])))
                except Exception:
                    s.pause("protection_failure")
                    await self.broker.close(t, "protection_failure")
                    return
            if t.get("liquidation") and not r.liquidation_safe(
                t["side"], D(t["entry"]), D(t["stop"]), D(t["liquidation"])
            ):
                s.pause("liquidation_buffer_failed")
                await self.broker.close(t, "liquidation_buffer")
                return
            if real_clock:
                now = time.time()
            if now - t.get("opened_at", t["created"]) >= self.cfg.max_hold_seconds:
                await self.broker.close(t, "holding_deadline")
                return
            if not self.book.fresh(now):
                return
            entry = D(t["entry"])
            stop = D(t.get("ack_stop", t["stop"]))
            sign = 1 if t["side"] == "buy" else -1
            if "partial_quantity" not in t and not t.get("entry_open"):
                # Derive from actual filled size; a partial fill cannot increase exposure.
                qty = t["filled"] // 2 if t.get("intended_partial") else 0
                price = r.tick(entry + sign * abs(entry - D(t["stop"])), self.p.tick, up=sign > 0)
                net = (
                    r.net_at(
                        t["side"],
                        entry,
                        price,
                        qty,
                        r.fee(entry, qty, self.p.contract, self.p.taker),
                        D(t["slippage"]),
                        self.p,
                    )
                    if qty
                    else D(0)
                )
                t["partial_quantity"] = (
                    qty if net > 0 and sign * (D(t["target"]) - price) > 0 else 0
                )
                t["partial_target"] = str(price)
            price, impact = r.depth_exit(
                t["side"], t["open_qty"], self.book.bids if sign > 0 else self.book.asks, self.p
            )
            reserve = max(D(t["slippage"]), impact)
            realized = D(t.get("gross", "0")) - D(t.get("exit_fees", "0"))
            net = (
                r.net_at(
                    t["side"],
                    entry,
                    price,
                    t["open_qty"],
                    D(t["entry_fees"]),
                    reserve,
                    self.p,
                    D(t.get("funding", "0")),
                )
                + realized
            )
            peak = max(D(t["peak"]), net)
            t.update(peak=str(peak), net_estimate=str(net))
            floor = -min(D(t["risk"]), D(str(self.cfg.max_risk)))
            partial = t.get("partial_quantity", 0)
            if partial and t["filled"] - t["open_qty"] > 0:
                floor = D(0)
                if t["filled"] - t["open_qty"] >= partial:
                    t["partial_done"] = True
            if peak > D(2):
                floor = max(floor, D("1.5"), peak - D(".5"))
            t["protected_net"] = str(max(D(t.get("protected_net", floor)), floor))
            floor = D(t["protected_net"])
            s.set("position", t)
            if net <= floor:
                await self.broker.close(t, "net_floor")
                return
            proposed = r.stop_for_net(
                t["side"],
                entry,
                t["open_qty"],
                D(t["entry_fees"]),
                floor - realized,
                reserve,
                self.p,
                D(t.get("funding", "0")),
            )
            stop = max(stop, proposed) if sign > 0 else min(stop, proposed)
            if sign * (price - stop) <= 0:
                await self.broker.close(t, "stop_crossed")
                return
            if not t.get("ordinary_stop") or stop != D(t.get("ack_stop", t["stop"])):
                try:
                    await self.broker.protect(t, stop)
                    t["ordinary_stop"] = True
                except Exception:
                    s.pause("protection_failure")
                    await self.broker.close(t, "protection_failure")
                    return
            if self.book.fresh(time.time() if real_clock else now):
                await self.broker.target(t)
        finally:
            if s.get("position") is not None:
                s.set("position", t)

    async def stop(self, reason="operator_stop"):
        self.store.pause(reason)
        t = self.store.get("position")
        if t:
            await self.broker.sync(t)
            await self.broker.close(t, reason)
            self.store.set("position", t)
