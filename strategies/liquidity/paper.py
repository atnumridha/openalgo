"""Conservative paper broker with two targets, using observed trade-through."""

from decimal import Decimal as D

from strategies.confluence.live import backend


def broker_type():
    backend()
    from delta_scalper.paper import PaperBroker, PaperOrder
    from delta_scalper.risk import fee

    class Broker(PaperBroker):
        def on_trade(self, x):
            t = self.trade
            if not t:
                return
            if self.pending and t.get("entry_open"):
                # Resting maker orders require a later trade THROUGH the price.
                through = (
                    x["price"] < self.pending.price
                    if t["side"] == "buy"
                    else x["price"] > self.pending.price
                )
                n = (
                    self.pending.consume(x["id"], x["price"], x["size"], x["side"], x["ts"])
                    if through
                    else 0
                )
                if n:
                    t["filled"] += n
                    t["open_qty"] += n
                    t.setdefault("opened_at", x["ts"])
                    t["entry_fees"] = str(
                        D(t["entry_fees"]) + fee(D(t["entry"]), n, self.p.contract, self.p.maker)
                    )
                    t["entry_open"] = t["filled"] < t["qty"]
            if self.tp and t["open_qty"]:
                through = (
                    x["price"] > self.tp.price if t["side"] == "buy" else x["price"] < self.tp.price
                )
                n = (
                    self.tp.consume(x["id"], x["price"], x["size"], x["side"], x["ts"])
                    if through
                    else 0
                )
                if n:
                    self._fill_exit(
                        t,
                        n,
                        self.tp.price,
                        True,
                        "partial_target" if t.get("target_phase") == "partial" else "runner_target",
                        x["ts"],
                    )
            self.save()

        async def target(self, t):
            partial = t.get("partial_quantity", 0)
            if self.tp:
                if self.tp.filled < self.tp.qty:
                    return
                if t.get("target_phase") == "partial":
                    t["partial_done"] = True
                self.tp = None
            if not t["open_qty"]:
                return
            phase = "partial" if partial and not t.get("partial_done") else "runner"
            size = partial if phase == "partial" else t["open_qty"]
            price = D(t["partial_target"] if phase == "partial" else t["target"])
            side = "sell" if t["side"] == "buy" else "buy"
            t["target_phase"] = phase
            if (side == "sell" and self.book.bid >= price) or (
                side == "buy" and self.book.ask <= price
            ):
                # Simulated taker slice; depth and fees applied, never a fictitious limit fill.
                from delta_scalper.risk import depth_exit

                px, _ = depth_exit(
                    t["side"], size, self.book.bids if side == "sell" else self.book.asks, self.p
                )
                self._fill_exit(t, size, px, False, phase + "_target", self.book.ts)
                if phase == "partial":
                    t["partial_done"] = True
            else:
                levels = self.book.asks if side == "sell" else self.book.bids
                self.tp = PaperOrder(
                    side, price, size, sum(q for px, q in levels if px == price), self.book.ts, None
                )
            self.save()

    return Broker
