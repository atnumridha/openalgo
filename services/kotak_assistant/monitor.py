"""Read-only broker observation. Never adopts exposure or calls an execution path."""

import copy
import time
from datetime import datetime

from .analysis import DEFAULTS, IST, fill_time, journal, number
from .discipline import (
    advance as advance_discipline,
)
from .discipline import (
    liquidation,
    merge_checkpoints,
    order_evidence,
)


def identity(row):
    return tuple(row.get(k) for k in ("symbol", "exchange", "product"))


def open_basis(fills, position, day):
    """Rebuild the remaining weighted basis, including short/partial/reopened legs."""
    quantity = 0
    basis = 0
    try:
        ordered = []
        for fill in fills:
            if identity(fill) != identity(position):
                continue
            epoch = fill_time(fill["timestamp"])
            if datetime.fromtimestamp(epoch, IST).date().isoformat() == day:
                ordered.append((epoch, str(fill["tradeid"]), fill))
        sides = {}
        for epoch, _, fill in ordered:
            sides.setdefault(epoch, set()).add(fill["action"])
        if any(len(group) > 1 for group in sides.values()):
            # Trade IDs identify fills but do not establish exchange sequence.
            # Opposite-side fills in one timestamp can change the open basis.
            return None
        for _, _, fill in sorted(ordered, key=lambda row: (row[0], row[1])):
            q, p = number(fill["quantity"]), number(fill["average_price"])
            if q <= 0 or int(q) != q or p <= 0 or fill["action"] not in ("BUY", "SELL"):
                return None
            signed = int(q) * (1 if fill["action"] == "BUY" else -1)
            if quantity == 0 or quantity * signed > 0:
                basis += abs(signed) * p
            else:
                basis -= min(abs(quantity), abs(signed)) * basis / abs(quantity)
                if abs(signed) > abs(quantity):
                    basis = (abs(signed) - abs(quantity)) * p
            quantity += signed
        if quantity and quantity == position["quantity"]:
            return basis / abs(quantity)
    except (ValueError, TypeError, KeyError):
        pass
    return None


class BrokerMonitor:
    def __init__(self, store, gateway, clock=time.time):
        if gateway.mode != "live":
            raise ValueError("Broker monitoring requires the live account")
        self.store, self.g, self.clock = store, gateway, clock
        self.scope = gateway.scope + ":observer"

    def snapshot(self):
        attempt = self.clock()
        prior = self.store.read(self.scope)
        if prior.get("error") and 0 <= attempt - prior.get("last_attempt", 0) < 2:
            return prior
        try:
            books = self.g.cached(
                "readonly_monitor_books", 1, lambda: self.g.books(include_cash=False)
            )
            if not all(isinstance(books.get(k), list) for k in ("positions", "orders", "fills")):
                raise ValueError("Incomplete broker books; last saved state retained")
            stamp = number(books.get("time", 0))
            if not 0 <= self.clock() - stamp <= 15:
                raise ValueError("Broker books are stale; last saved state retained")
            day = datetime.fromtimestamp(stamp, IST).date().isoformat()
            fills, seen = [], set()
            for row in books["fills"]:
                raw_ids = [row.get(k) for k in ("orderid", "tradeid")]
                if any(v is None or isinstance(v, bool) or not str(v).strip() for v in raw_ids):
                    raise ValueError("Broker fill identity unavailable; last saved state retained")
                key = tuple(str(v).strip() for v in raw_ids)
                if key in seen:
                    continue
                seen.add(key)
                fill = {
                    k: row.get(k)
                    for k in (
                        "symbol",
                        "exchange",
                        "product",
                        "action",
                        "quantity",
                        "average_price",
                        "orderid",
                        "tradeid",
                        "timestamp",
                    )
                }
                fill["orderid"], fill["tradeid"] = key
                fill["action"] = {"B": "BUY", "S": "SELL"}.get(fill["action"], fill["action"])
                if fill["action"] not in ("BUY", "SELL") or not all(
                    isinstance(fill[k], str) and fill[k] for k in ("symbol", "exchange", "product")
                ):
                    raise ValueError("Invalid broker fill")
                q, price = number(fill["quantity"]), number(fill["average_price"])
                if q <= 0 or q != int(q) or price <= 0:
                    raise ValueError("Invalid broker fill quantity or price")
                fill.update(
                    quantity=int(q), average_price=price, epoch=fill_time(fill["timestamp"])
                )
                fills.append(fill)
            positions = []
            for row in books["positions"]:
                if not all(
                    isinstance(row.get(k), str) and row[k]
                    for k in ("symbol", "exchange", "product")
                ):
                    raise ValueError("Invalid broker position identity")
                qty = number(row["quantity"])
                if int(qty) != qty:
                    raise ValueError("Invalid broker position quantity")
                p = {
                    k: row.get(k)
                    for k in (
                        "symbol",
                        "exchange",
                        "product",
                        "average_price",
                        "average_price_basis",
                        "ltp",
                        "pnl",
                    )
                }
                p["quantity"] = int(qty)
                try:
                    p.update(self.g.tracking_metadata(p["symbol"], p["exchange"]))
                except Exception:
                    pass  # Units and broker prices still work without local lot metadata.
                positions.append(p)
            orders = [
                {
                    k: row.get(k)
                    for k in (
                        "symbol",
                        "exchange",
                        "product",
                        "action",
                        "orderid",
                        "order_status",
                        "quantity",
                        "filled_quantity",
                        "price",
                        "trigger_price",
                        "pricetype",
                    )
                }
                for row in books["orders"]
            ]
            for order in orders:
                order["action"] = {"B": "BUY", "S": "SELL"}.get(order["action"], order["action"])
            with self.store.lock(self.scope) as owner:
                saved = self.store.read(self.scope)
                if stamp >= saved.get("book_time", 0):
                    days = copy.deepcopy(saved.get("days", {}))
                    for fill in fills:
                        fill_day = datetime.fromtimestamp(fill["epoch"], IST).date().isoformat()
                        archive = days.setdefault(
                            fill_day, {"day": fill_day, "positions": [], "orders": [], "fills": []}
                        )
                        previous = next(
                            (
                                f
                                for f in archive["fills"]
                                if (f["orderid"], f["tradeid"])
                                == (fill["orderid"], fill["tradeid"])
                            ),
                            None,
                        )
                        if previous:
                            immutable = (
                                "symbol",
                                "exchange",
                                "product",
                                "action",
                                "quantity",
                                "average_price",
                                "epoch",
                            )
                            if any(previous.get(k) != fill.get(k) for k in immutable):
                                raise ValueError(
                                    "Broker fill changed identity; last saved state retained"
                                )
                        else:
                            archive["fills"].append(fill)
                    merged = days.get(day, {}).get("fills", [])
                    if saved.get("day") == day:
                        for previous in saved.get("positions", []):
                            if not previous.get("quantity") or not previous.get(
                                "average_entry_verified"
                            ):
                                continue
                            actual = sum(
                                p["quantity"]
                                for p in positions
                                if identity(p) == identity(previous)
                            )
                            expected = sum(
                                f["quantity"] * (1 if f["action"] == "BUY" else -1)
                                for f in merged
                                if identity(f) == identity(previous)
                            )
                            if actual != expected:
                                # Fills are immutable observations even when a
                                # separate position report has not caught up.
                                # Preserve them now so a reduced later report
                                # cannot strand this account in stale state.
                                days[day] = {
                                    **days.get(day, {}),
                                    "positions": saved.get("positions", []),
                                    "orders": saved.get("orders", []),
                                    "fills": merged,
                                    "book_time": saved.get("book_time", 0),
                                }
                                saved = {
                                    **saved,
                                    "fills": merged,
                                    "days": days,
                                    "last_attempt": attempt,
                                    "error": "Broker positions and fills differ; last saved position retained",
                                }
                                self.store.save(self.scope, saved, owner)
                                return saved
                    for p in positions:
                        entry = open_basis(merged, p, day)
                        p.update(
                            average_entry=entry if entry is not None else p.get("average_price"),
                            average_entry_verified=entry is not None,
                            entry_basis="Today’s broker fills"
                            if entry is not None
                            else "Broker average; original fill basis unconfirmed",
                        )
                    controller = self.store.read(self.g.scope)
                    settings = controller.get("settings", DEFAULTS)
                    historical = [f for saved in days.values() for f in saved.get("fills", [])]
                    evidence = order_evidence(books["orders"], merged, day, historical)
                    ledger = journal(merged, positions, day, settings.get("brokerage", 0))
                    if not evidence["complete"]:
                        ledger.update(complete=False, reason=evidence["reason"], net_realised=None)
                    net = None
                    pnl_error = ledger["reason"]
                    if ledger["complete"]:
                        try:
                            quotes = {
                                (p["symbol"], p["exchange"]): self.g.quote(
                                    p["symbol"], p["exchange"]
                                )
                                for p in ledger["open_positions"]
                            }
                            net = round(
                                liquidation(
                                    ledger, quotes, settings.get("brokerage", 0), day, self.clock()
                                )["net"],
                                2,
                            )
                        except (ValueError, KeyError, TypeError, AttributeError):
                            pnl_error = "Fresh exit quotes unavailable for the daily net P&L"
                    discipline = advance_discipline(
                        merge_checkpoints(
                            saved.get("discipline", {}),
                            controller.get("day", {}).get("discipline", {}),
                            day,
                        ),
                        day,
                        merged,
                        stamp,
                        net,
                        known_ids=evidence["entry_ids"],
                    )
                    discipline["count_verified"] = discipline["count_verified"] and evidence["complete"]
                    discipline.update(pnl_available=net is not None, pnl_error=pnl_error)
                    observed = {
                        "day": day,
                        "book_time": stamp,
                        "positions": positions,
                        "orders": orders,
                        "fills": merged,
                    }
                    days[day] = copy.deepcopy(observed)
                    # Keep all fills for each of the last 30 observed trading days.
                    days = {key: days[key] for key in sorted(days)[-30:]}
                    saved = dict(
                        scope=self.scope,
                        mode="live",
                        user=self.g.user,
                        observer=True,
                        last_attempt=attempt,
                        error=None,
                        discipline=discipline,
                        **observed,
                        days=days,
                    )
                    self.store.save(self.scope, saved, owner)
            return saved
        except Exception as error:
            with self.store.lock(self.scope) as owner:
                saved = self.store.read(self.scope)
                if saved.get("last_attempt", 0) > attempt:
                    return saved
                saved = {
                    "scope": self.scope,
                    "mode": "live",
                    "user": self.g.user,
                    "observer": True,
                    "positions": [],
                    "orders": [],
                    "fills": [],
                    "days": {},
                    **saved,
                    "last_attempt": attempt,
                    "error": str(error),
                }
                self.store.save(self.scope, saved, owner)
            return saved
