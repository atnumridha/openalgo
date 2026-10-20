"""Single controller for user-clicked entries and explicitly authorized exits.

Every network mutation has a durable prepared operation before I/O. Unknown
submissions can be found by their unique broker tag, but never blindly retried.
"""

import copy
import time
import uuid
from datetime import datetime

from .analysis import DEFAULTS, IST, fees, journal, number, plan, snap, validate_settings
from .discipline import (
    advance as advance_discipline,
)
from .discipline import (
    liquidation,
    merge_checkpoints,
    merge_fills,
    order_evidence,
)
from .risk_policy import plan_cash, reconcile_cash, validated_cash_policy

TERMINAL = {"complete", "completed", "cancelled", "canceled", "rejected"}
ACTIVE = {
    "open",
    "pending",
    "trigger pending",
    "validation pending",
    "put order req received",
    "modify pending",
    "cancel pending",
    "after market order req received",
    "partially filled",
}


def same(row, t):
    return all(row.get(k) == t.get(k) for k in ("symbol", "exchange", "product"))


def status(o):
    return str(o.get("order_status", "")).strip().lower()


def is_terminal(o):
    return status(o) in TERMINAL


def filled(books, oid):
    seen = set()
    qty = 0
    value = 0
    for f in books["fills"]:
        if str(f.get("orderid")) != str(oid):
            continue
        ident = str(f.get("tradeid", ""))
        if not ident:
            raise ValueError("Broker fill has no stable identity")
        if ident in seen:
            continue
        seen.add(ident)
        q = number(f["quantity"])
        p = number(f["average_price"])
        if q <= 0 or int(q) != q or p <= 0:
            raise ValueError("Invalid broker fill")
        qty += int(q)
        value += q * p
    return qty, value


class Coordinator:
    def __init__(self, store, gateway, clock=time.time):
        self.store = store
        self.g = gateway
        self.clock = clock
        self.scope = gateway.scope

    def state(self):
        return {
            **{
                "settings": copy.deepcopy(DEFAULTS),
                "tickets": {},
                "trades": {},
                "day": {},
                "requests": {},
                "consumed": [],
                "journals": {},
                "user": self.g.user,
                "mode": self.g.mode,
            },
            **self.store.read(self.scope),
        }

    def save(self, d, owner):
        # The checkpoint and broker intent are committed together before I/O.
        # Keep lifecycle changes with the trade, independent of browser memory.
        for trade in d.get("trades", {}).values():
            checkpoint = {
                "status": trade.get("status"),
                "reason": trade.get("reason", ""),
                "filled": trade.get("entry_quantity", 0),
                "remaining": trade.get("remaining", 0),
                "sl": trade.get("current_sl"),
                "orders": [
                    {k: op.get(k) for k in ("role", "orderid", "state", "broker_status", "filled")}
                    for op in trade.get("ops", [])
                ],
            }
            history = trade.setdefault("lifecycle", [])
            previous = {k: v for k, v in history[-1].items() if k != "at"} if history else None
            if checkpoint != previous:
                history.append({"at": self.clock(), **checkpoint})
        self.store.save(self.scope, d, owner)

    def configure(self, settings):
        settings = validate_settings(settings)
        with self.store.lock(self.scope) as owner:
            d = self.state()
            d["settings"] = settings
            d["tickets"] = {}
            self.save(d, owner)
        return settings

    def books(self):
        b = self.g.books()
        if (
            not isinstance(b, dict)
            or not all(isinstance(b.get(k), list) for k in ("positions", "orders", "fills"))
            or not 0 <= self.clock() - b.get("time", 0) <= 15
        ):
            raise ValueError("Fresh account books unavailable")
        return b

    def risk(self, d, b):
        day = datetime.fromtimestamp(self.clock(), IST).date().isoformat()
        observer = self.store.read(self.scope + ":observer") if self.g.mode == "live" else {}
        archived = observer.get("days", {}).get(day, {}).get("fills", [])
        previous_fills = d.get("journals", {}).get(day, {}).get("fills", [])
        merged = merge_fills(previous_fills, archived, b["fills"])
        historical = [f for saved in d.get("journals", {}).values() for f in saved.get("fills", [])]
        evidence = order_evidence(b["orders"], merged, day, historical)
        j = journal(
            merged,
            b["positions"],
            day,
            d["settings"]["brokerage"],
        )
        prior = (
            d["day"] if d["day"].get("date") == day else {"date": day, "peak": None, "halt": None}
        )
        if not evidence["complete"]:
            j.update(complete=False, reason=evidence["reason"], net_realised=None)
        if j["complete"]:
            quotes = {
                (p["symbol"], p["exchange"]): self.g.quote(p["symbol"], p["exchange"])
                for p in j["open_positions"]
            }
            estimated = liquidation(j, quotes, d["settings"]["brokerage"], day, self.clock())
            net = estimated["net"]
            open_gross = estimated["open_gross"]
            liquidation_costs = estimated["estimated_liquidation_costs"]
            prior["peak"] = max(net, prior["peak"] if prior["peak"] is not None else net)
            s = d["settings"]
            if s["daily_loss"] and net <= -s["daily_loss"]:
                prior["halt"] = "Daily loss limit reached"
            if s["giveback"] and prior["peak"] > 0 and prior["peak"] - net >= s["giveback"]:
                prior["halt"] = "Profit giveback limit reached"
            streak = 0
            last = 0
            for cycle in reversed(j["cycles"]):
                if cycle["net"] >= 0:
                    break
                streak += 1
                last = max(last, cycle["end"])
            prior["cooldown_until"] = last + s["cooldown"] if streak >= 3 else 0
            prior.update(
                net=round(net, 2),
                open_gross=round(open_gross, 2),
                estimated_liquidation_costs=round(liquidation_costs, 2),
                observed_peak=True,
            )
        # Count broker-confirmed BUY orders once even when fills are split.
        # Day-local high-water counts survive restarts and transient book omissions.
        limits = prior.get("entry_limits", {})
        external = observer.get("discipline", {})
        known = set(external.get("entry_ids", [])) if external.get("date") == day else set()
        checkpoint = merge_checkpoints(prior.get("discipline", {}), external, day)
        discipline = advance_discipline(
            checkpoint,
            day,
            merged,
            self.clock(),
            prior.get("net") if j["complete"] else None,
            minimum_entries=limits.get("entries", 0),
            known_ids=known | evidence["entry_ids"],
        )
        discipline["count_verified"] = discipline["count_verified"] and evidence["complete"]
        prior["discipline"] = discipline
        entries = discipline["entries"]
        if j["complete"]:
            losses = sum(cycle["net"] < 0 for cycle in j["cycles"])
            limits = {
                "entries": max(entries, limits.get("entries", 0)),
                "losses": max(losses, limits.get("losses", 0)),
                "max_entries": 3,
                "max_losses": 2,
            }
            blocked = (
                "Daily loss-trade limit reached · 2 losing trades"
                if limits["losses"] >= 2
                else "Daily entry limit reached · 3 entries"
                if limits["entries"] >= 3
                else None
            )
            limits["blocked_reason"] = blocked
        if entries >= 3:
            limits.update(entries=entries, max_entries=3)
            limits["blocked_reason"] = (
                limits.get("blocked_reason") or "Daily entry limit reached · 3 entries"
            )
        prior["entry_limits"] = limits
        d["journals"][day] = j
        prior["journal"] = j
        d["day"] = prior
        return prior

    def _validate(self, t, d, b):
        now = self.clock()
        s = d["settings"]
        meta = self.g.metadata(t["symbol"], t["exchange"])
        if (
            t["exchange"] not in ("NFO", "BFO")
            or t["product"] not in ("MIS", "NRML")
            or meta["underlying"] not in ("NIFTY", "BANKNIFTY", "SENSEX")
        ):
            raise ValueError("Only NIFTY/BANKNIFTY/SENSEX long options are supported")
        if meta["expiry"] < datetime.fromtimestamp(now, IST).date().isoformat():
            raise ValueError("Contract expired")
        if not self.g.session_open(t["exchange"], s["cutoff"]):
            raise ValueError("Market closed or square-off cutoff reached")
        day = datetime.fromtimestamp(now, IST).date().isoformat()
        policy = validated_cash_policy(t)
        if policy is not None:
            p = plan_cash(
                t["entry"],
                t["quantity"],
                meta["tick"],
                t["exchange"],
                s,
                policy["loss_budget"],
                policy["target_multiple"],
                day,
                lot=meta["lot"],
            )
            if p["fits"]:
                t.update(sl=p["sl"], target=p["target"], risk_policy=p["risk_policy"])
        else:
            p = plan(
                t["entry"],
                t["sl"],
                t["target"],
                t["quantity"],
                t["exchange"],
                s,
                meta["tick"],
                meta["lot"],
                day,
            )
        if not p["fits"]:
            raise ValueError(p["reason"])
        if meta.get("freeze", 0) <= 0 or t["quantity"] > meta["freeze"]:
            raise ValueError("Entry exceeds freeze limit or freeze metadata unavailable")
        q = self.g.quote(t["symbol"], t["exchange"])
        bid = number(q.get("bid", 0))
        ask = number(q.get("ask", 0))
        if (
            not 0 <= self.clock() - q.get("time", 0) <= 5
            or not 0 < bid <= ask
            or (ask - bid) / ask * 100 > s["spread"]
        ):
            raise ValueError("Quote is stale, unavailable or spread exceeds limit")
        if ask > t["entry"] or bid <= t["sl"]:
            raise ValueError("Price moved outside the displayed entry/SL plan")
        if number(b["cash"]) < t["entry"] * t["quantity"] + p["costs"]:
            raise ValueError("Insufficient available cash")
        if any(same(x, t) and int(x["quantity"]) for x in b["positions"]):
            raise ValueError("Existing position: no averaging or overlapping entry")
        if any(same(x, t) and not is_terminal(x) for x in b["orders"]):
            raise ValueError("Existing pending order in this contract")
        if self.g.other_controller(t["symbol"], t["exchange"], t["product"]):
            raise ValueError("Another controller owns this contract")
        risk = self.risk(d, b)
        if not risk["journal"]["complete"]:
            raise ValueError(risk["journal"]["reason"])
        if risk.get("discipline", {}).get("count_verified") is False:
            raise ValueError(
                "Complete daily entry history unavailable; wait for broker synchronization"
            )
        if t.get("manual_entry") and risk.get("entry_limits", {}).get("entries", 0) >= 3:
            raise ValueError("Daily entry limit reached · 3 entries. Stop trading for today")
        if not t.get("manual_entry") and risk.get("entry_limits", {}).get("blocked_reason"):
            raise ValueError(risk["entry_limits"]["blocked_reason"])
        if risk.get("halt"):
            raise ValueError(risk["halt"])
        if not t.get("manual_entry") and now < risk.get("cooldown_until", 0):
            raise ValueError("Loss cooldown active")
        if not t.get("manual_entry") and t.get("setup_id") and t["setup_id"] in d["consumed"]:
            raise ValueError("Setup already consumed; wait for a new confirmation")
        if any(x["status"] not in ("closed", "rejected") for x in d["trades"].values()):
            raise ValueError("Manage the existing trade before another entry")
        # Any account stop problem blocks another assistant entry.
        for pos in b["positions"]:
            if int(pos["quantity"]) <= 0:
                continue
            stops = [
                o
                for o in b["orders"]
                if same(o, pos) and not is_terminal(o) and o.get("pricetype") in ("SL", "SL-M")
            ]
            if any(o.get("action") != "SELL" for o in stops) or sum(
                int(o["quantity"]) for o in stops
            ) != int(pos["quantity"]):
                raise ValueError("Existing option position has unresolved protection")
        return p, meta

    def preview(self, request):
        keys = (
            "manual_entry",
            "symbol",
            "exchange",
            "product",
            "quantity",
            "entry",
            "sl",
            "target",
            "auto_target",
            "auto_invalidation",
            "auto_risk",
            "trailing",
            "profit_activation",
            "retention",
            "underlying",
            "index_invalidation",
            "setup_id",
            "strategy",
            "strategy_version",
            "risk_policy",
        )
        t = {k: request[k] for k in keys if k in request}
        for k in ("manual_entry", "auto_target", "auto_invalidation", "auto_risk", "trailing"):
            if k in t and not isinstance(t[k], bool):
                raise ValueError("Exit policy flags must be boolean")
        policy = validated_cash_policy(t)
        for k in ("entry",) if policy is not None else ("entry", "sl", "target"):
            t[k] = number(t[k])
        if t.get("auto_invalidation") and (
            t.get("underlying") not in ("NIFTY", "BANKNIFTY", "SENSEX")
            or number(t.get("index_invalidation", 0)) <= 0
        ):
            raise ValueError("Automatic invalidation requires a confirmed index level")
        if t.get("trailing"):
            if (
                number(t.get("profit_activation", 0)) <= 0
                or not 0 < number(t.get("retention", 0)) < 1
            ):
                raise ValueError("Configure trailing activation and retention")
        with self.store.lock(self.scope) as owner:
            d = self.state()
            p, meta = self._validate(t, d, self.books())
            tid = uuid.uuid4().hex
            d["tickets"] = {k: v for k, v in d["tickets"].items() if v["expires"] >= self.clock()}
            d["tickets"][tid] = dict(
                **t,
                lot=meta["lot"],
                tick=meta["tick"],
                freeze=meta["freeze"],
                expires=self.clock() + 5,
                settings=d["settings"],
                plan=p,
            )
            self.save(d, owner)
        return {"ticket": tid, "expires": self.clock() + 5, "plan": p, "mode": self.g.mode}

    def enter(self, ticket):
        with self.store.lock(self.scope) as owner:
            d = self.state()
            if ticket in d["trades"]:
                return d["trades"][ticket]
            t = d["tickets"].get(ticket)
            if not t or t["expires"] < self.clock() or t["settings"] != d["settings"]:
                raise ValueError("Entry preview expired or settings changed; refresh it")
            self._validate(t, d, self.books())
            tr = {k: v for k, v in t.items() if k not in ("expires", "settings")}
            tr["cutoff"] = d["settings"]["cutoff"]
            if tr.get("risk_policy"):
                tr["risk_settings"] = copy.deepcopy(d["settings"])
            if tr.get("setup_id") and not tr.get("manual_entry"):
                d["consumed"].append(tr["setup_id"])
            tr.update(
                id=ticket,
                created=self.clock(),
                status="entry_pending",
                ops=[],
                exit_goal=None,
                closed_quantity=0,
                entry_quantity=0,
                remaining=0,
                peak_net=None,
                reason="Entry submission started; awaiting broker response",
                scope=self.scope,
            )
            d["trades"][ticket] = tr
            d["tickets"].pop(ticket, None)
            self._submit(d, tr, owner, "entry", tr["quantity"], "LIMIT", tr["entry"])
            return copy.deepcopy(tr)

    def _submit(self, d, t, owner, role, qty, kind, price=0, trigger=0):
        op = {
            "retry_generation": t.get("retry_generation", 0),
            "role": role,
            "id": uuid.uuid4().hex,
            "quantity": qty,
            "state": "prepared",
            "created": self.clock(),
            "orderid": None,
            "filled": 0,
            "pricetype": kind,
            "trigger_price": trigger,
            "price": price,
        }
        op["tag"] = "ka" + op["id"][:18]
        t["ops"].append(op)
        self.save(d, owner)
        payload = {k: t[k] for k in ("symbol", "exchange", "product")}
        payload.update(
            action="BUY" if role == "entry" else "SELL",
            quantity=qty,
            pricetype=kind,
            price=price,
            trigger_price=trigger,
            tag=op["tag"],
        )
        try:
            r = self.g.submit(payload)
        except Exception:
            r = {
                "state": "unknown",
                "message": "Broker submission outcome unknown; reconciling without resubmitting",
            }
        op.update(state=r["state"], orderid=r.get("orderid"), message=r.get("message", ""))
        op.update({k: r[k] for k in ("http_status", "broker_code", "broker_error") if k in r})
        if op["state"] == "unknown":
            t.update(status="unknown", reason=r.get("message", "Unknown outcome"))
        if op["state"] == "rejected":
            t["reason"] = r.get("message", "Broker rejected order")
            if role == "entry":
                t["status"] = "rejected"
            elif role == "sl":
                t["exit_goal"] = t["entry_quantity"]
                t["exit_reason"] = "Protection failed"
                t["status"] = "unprotected"
            else:
                t["status"] = "exit_rejected"
        self.save(d, owner)

    def _cancel(self, d, t, op, owner):
        if op.get("cancel_requested"):
            if op.get("cancel_result", {}).get("state") == "unknown":
                t.update(
                    status="cancel_unknown",
                    reason="Stop cancellation outcome unknown; fresh books will reconcile it. Exit can explicitly retry cancellation of this same order.",
                )
                return
            if (
                op.get("cancel_result", {}).get("state") != "rejected"
                or self.clock() - op["cancel_requested"] < 5
            ):
                return
            if op.get("cancel_attempts", 0) >= 3:
                t.update(
                    status="cancel_rejected",
                    reason="Stop cancellation rejected; retry Exit after checking broker reason",
                )
                return
        op["cancel_attempts"] = op.get("cancel_attempts", 0) + 1
        op["cancel_requested"] = self.clock()
        self.save(d, owner)
        try:
            r = self.g.cancel(op["orderid"])
        except Exception:
            r = {"state": "unknown"}
        op["cancel_result"] = r
        if r["state"] == "unknown":
            t.update(
                status="cancel_unknown",
                reason="Stop cancellation outcome unknown; awaiting broker confirmation",
            )
        self.save(d, owner)
        # Only a subsequent book's terminal state proves cancellation.

    def _sync_trade(self, t, b):
        for op in t["ops"]:
            match = next(
                (
                    o
                    for o in b["orders"]
                    if (
                        str(o["orderid"]) == str(op["orderid"])
                        if op.get("orderid")
                        else o.get("order_tag") == op["tag"]
                    )
                ),
                None,
            )
            if match:
                qty, value = filled(b, str(match["orderid"]))
                if t.get("risk_policy") and (
                    qty < op.get("filled", 0)
                    or value + 1e-7 < op.get("value", 0)
                    or (qty == op.get("filled", 0) and abs(value - op.get("value", 0)) > 1e-7)
                ):
                    raise ValueError(
                        "Confirmed broker fill quantity or cost basis changed; protection retained"
                    )
                op["orderid"] = str(match["orderid"])
                op["state"] = "accepted"
                op["broker_status"] = status(match)
                op["filled"], op["value"] = qty, value
                # Reject state cannot be inferred from an HTTP response alone.
                if status(match) == "rejected":
                    op.update(
                        state="rejected", message=match.get("message", "Broker rejected order")
                    )
                if op["filled"] != int(match.get("filled_quantity", op["filled"])):
                    raise ValueError("Broker order fills and tradebook not yet reconciled")
                if int(match["quantity"]) != op["quantity"] or match["action"] != (
                    "BUY" if op["role"] == "entry" else "SELL"
                ):
                    raise ValueError("Managed order modified outside this controller")
                if (
                    op["role"] == "sl"
                    and not is_terminal(match)
                    and abs(number(match["trigger_price"]) - op["trigger_price"]) > 1e-7
                ):
                    raise ValueError("Managed stop modified outside this controller")
            elif op.get("orderid") and op.get("broker_status") not in TERMINAL:
                raise ValueError("Managed broker order missing from fresh book")
        entry = t.get("baseline_quantity", 0) + sum(
            o["filled"] for o in t["ops"] if o["role"] == "entry"
        )
        sold = sum(
            o["filled"] - o.get("baseline_filled", 0) for o in t["ops"] if o["role"] != "entry"
        )
        t.update(entry_quantity=entry, closed_quantity=sold, remaining=entry - sold)
        if entry:
            t["average_entry"] = (
                t.get("baseline_value", 0)
                + sum(o.get("value", 0) for o in t["ops"] if o["role"] == "entry")
            ) / entry
        net = sum(int(p["quantity"]) for p in b["positions"] if same(p, t))
        if net != t["remaining"] or net < 0:
            raise ValueError("External fill or position discrepancy; automation paused")
        owned = {o.get("orderid") for o in t["ops"] if o.get("orderid")}
        if any(
            same(o, t) and not is_terminal(o) and str(o["orderid"]) not in owned
            for o in b["orders"]
        ):
            raise ValueError("Unowned pending order conflicts with this position")

    def _manage(self, d, t, b, owner):
        self._sync_trade(t, b)
        if (t.get("risk_policy") or {}).get("kind") == "cash_budget" and t["remaining"]:
            fill_plan = reconcile_cash(
                t, datetime.fromtimestamp(self.clock(), IST).date().isoformat()
            )
            t["fill_plan"] = fill_plan
            if fill_plan["fits"]:
                t.update(sl=fill_plan["sl"], target=fill_plan["target"], desired_sl=fill_plan["sl"])
            elif t.get("exit_goal") is None:
                t.update(exit_goal=t["entry_quantity"], exit_reason=fill_plan["reason"])
        unresolved = [o for o in t["ops"] if o["state"] in ("prepared", "unknown")]
        if unresolved:
            t.update(
                status="unknown", reason="Broker outcome unknown; no duplicate orders will be sent"
            )
            return
        entries = [o for o in t["ops"] if o["role"] == "entry"]
        pending = [
            o
            for o in t["ops"]
            if o["state"] == "accepted" and o.get("broker_status") not in TERMINAL
        ]
        entry_pending = [o for o in pending if o["role"] == "entry"]
        sls = [o for o in pending if o["role"] == "sl"]
        exits = [o for o in pending if o["role"] == "exit"]
        if not t["remaining"] and not entry_pending:
            if any(
                o.get("broker_status") not in TERMINAL and o["state"] != "rejected" for o in entries
            ):
                return
            for op in sls + exits:
                self._cancel(d, t, op, owner)
            if sls or exits:
                t.update(status="closing", reason="Flat; reconciling outstanding owned exits")
                return
            t.update(
                status="closed" if t["entry_quantity"] else "rejected",
                reason="Filled exits and fresh position book confirm flat",
            )
            return
        if entry_pending and (self.clock() - t["created"] >= 5 or t.get("exit_goal") is not None):
            for op in entry_pending:
                self._cancel(d, t, op, owner)
        if any(o["role"] == "sl" and o["state"] == "rejected" for o in t["ops"]):
            t["exit_goal"] = t["entry_quantity"]
            t["exit_reason"] = "Protection rejected"
            d["day"]["halt"] = "Protection failed; review account"
        try:
            q = self.g.quote(t["symbol"], t["exchange"])
        except Exception:
            q = {"time": 0, "bid": 0, "ask": 0, "source": "Unavailable"}
        fresh = 0 <= self.clock() - q.get("time", 0) <= 5
        bid = number(q.get("bid", 0))
        t.update(
            quote=q,
            gross_open=round((bid - t.get("average_entry", t["entry"])) * t["remaining"], 2)
            if fresh and bid > 0 and t.get("average_entry_verified", True)
            else None,
        )
        now = datetime.fromtimestamp(self.clock(), IST)
        cutoff = t.get("cutoff", d["settings"]["cutoff"])
        reason = None
        if (
            now.strftime("%H:%M") >= cutoff
            or now.date().isoformat() > datetime.fromtimestamp(t["created"], IST).date().isoformat()
        ):
            reason = "Intraday square-off cutoff"
        elif fresh and t.get("auto_target") and bid >= t["target"]:
            reason = "Target reached"
        elif t.get("auto_risk") and d["day"].get("halt"):
            reason = d["day"]["halt"]
        elif t.get("auto_invalidation") and t.get("exit_goal") is None:
            try:
                iq = self.g.quote(
                    t["underlying"], "NSE_INDEX" if t["exchange"] == "NFO" else "BSE_INDEX"
                )
                t["index_quote"] = iq
                if 0 <= self.clock() - iq.get("time", 0) <= 5:
                    price = number(iq.get("ltp", 0))
                    level = t["index_invalidation"]
                    if price > 0 and (
                        price <= level if t["symbol"].endswith("CE") else price >= level
                    ):
                        reason = "Index invalidation"
                    t["index_unavailable"] = price <= 0
                else:
                    t["index_unavailable"] = True
            except (ValueError, TypeError, KeyError):
                t["index_unavailable"] = True
        if reason and t.get("exit_goal") is None:
            t.update(exit_goal=t["entry_quantity"], exit_reason=reason)
        if t.get("exit_goal") is not None:
            t.update(status="closing", reason=t.get("exit_reason", "User exit"))
            if entry_pending:
                return
            for op in sls:
                self._cancel(d, t, op, owner)
            if sls or exits:
                return
            residual = min(t["remaining"], max(0, t["exit_goal"] - t["closed_quantity"]))
            if residual:
                attempts = [
                    o
                    for o in t["ops"]
                    if o["role"] == "exit"
                    and o["state"] == "rejected"
                    and o.get("retry_generation", 0) == t.get("retry_generation", 0)
                ]
                if len(attempts) >= 3 or (attempts and self.clock() - attempts[-1]["created"] < 5):
                    t.update(
                        status="exit_rejected",
                        reason="Exit rejected; inspect broker reason and retry manually",
                    )
                    return
                self._submit(d, t, owner, "exit", min(residual, t["freeze"]), "MARKET")
                return
            t["exit_goal"] = None
        if t["remaining"]:
            covered = sum(o["quantity"] - o["filled"] for o in sls)
            if covered > t["remaining"]:
                for op in sls:
                    self._cancel(d, t, op, owner)
                t.update(
                    status="unprotected", reason="Reconciling stop coverage after partial fill"
                )
                return
            if covered < t["remaining"]:
                if exits:
                    return
                if any(o.get("cancel_requested") for o in sls):
                    return
                if fresh and bid <= t["sl"]:
                    t.update(
                        exit_goal=t["entry_quantity"],
                        exit_reason="Price already through protective stop",
                        status="unprotected",
                    )
                    return
                stop = t.get("desired_sl", t["sl"])
                trigger = snap(stop, t["tick"])
                limit = self.g.stop_limit(t["symbol"], t["exchange"], trigger)
                self._submit(
                    d,
                    t,
                    owner,
                    "sl",
                    min(t["remaining"] - covered, t["freeze"]),
                    "SL",
                    limit,
                    trigger,
                )
                t.update(
                    status="protection_pending",
                    reason="Broker stop submitted; awaiting book confirmation",
                )
                return
            t["current_sl"] = max(o["trigger_price"] for o in sls) if sls else t["sl"]
            lower_stops = [o for o in sls if t.get("desired_sl", 0) > o["trigger_price"]]
            cash_policy = (t.get("risk_policy") or {}).get("kind") == "cash_budget"
            if t.get("desired_sl") and (
                lower_stops if cash_policy else t["desired_sl"] > t["current_sl"]
            ):
                for op in lower_stops if cash_policy else sls:
                    self._cancel(d, t, op, owner)
                t.update(
                    status="protection_pending",
                    reason="Replacing protection with the requested tighter stop",
                )
                return
            t.update(
                status="protected",
                reason="HOLD · initial plan remains valid"
                if fresh and not t.get("index_unavailable")
                else "DATA UNAVAILABLE · required monitoring quote stale",
            )
            if fresh and bid > 0 and t.get("average_entry_verified", True):
                charge = fees(
                    t.get("average_entry", t["entry"]) * t["remaining"],
                    bid * t["remaining"],
                    t["exchange"],
                    d["settings"]["brokerage"],
                    now.date().isoformat(),
                )["total"]
                t["net_open"] = round(t["gross_open"] - charge, 2)
                t["peak_net"] = max(t["net_open"], t["peak_net"] or t["net_open"])
                if bid >= t["target"]:
                    t["reason"] = "EXIT · target reached"
                if bid <= t["current_sl"]:
                    t["reason"] = "EXIT · broker stop triggered; monitor fill"
                if t.get("trailing") and t["peak_net"] >= t["profit_activation"]:
                    proposed = snap(
                        t["average_entry"]
                        + (t["peak_net"] * t["retention"] + charge) / t["remaining"],
                        t["tick"],
                    )
                    if t["current_sl"] < proposed < bid:
                        t["desired_sl"] = proposed
                        t["reason"] = "TIGHTEN SL · configured profit retention"

            if not t.get("average_entry_verified", True):
                t.update(
                    net_open=None,
                    gross_open=None,
                    reason="DATA UNAVAILABLE · entry cost basis unconfirmed; broker protection retained",
                )

    def reconcile(self):
        with self.store.lock(self.scope) as owner:
            d = self.state()
            b = self.books()
            try:
                self.risk(d, b)
                d["day"]["risk_available"] = bool(d["day"]["journal"]["complete"])
            except ValueError as e:
                d["day"].update(risk_available=False, risk_error=str(e))
            d["book_time"] = b["time"]
            d["positions"] = b["positions"]
            d["orders"] = b["orders"]
            for t in d["trades"].values():
                if t["status"] in ("closed", "rejected"):
                    changed = False
                    for op in t["ops"]:
                        matched = next(
                            (
                                o
                                for o in b["orders"]
                                if (
                                    str(o["orderid"]) == str(op["orderid"])
                                    if op.get("orderid")
                                    else o.get("order_tag") == op["tag"]
                                )
                            ),
                            None,
                        )
                        if matched:
                            qty, _ = filled(b, matched["orderid"])
                            if qty > op.get("filled", 0):
                                changed = True
                    if not changed:
                        continue
                    t.update(
                        status="recovering",
                        reason="Delayed fill discovered; restoring trade management",
                    )
                try:
                    self._manage(d, t, b, owner)
                except ValueError as e:
                    t.update(status="blocked", reason=str(e))
            d["heartbeat"] = self.clock()
            self.save(d, owner)
        return d

    def exit(self, trade_id, quantity=None, request_id=None):
        if not request_id or not isinstance(request_id, str) or len(request_id) > 64:
            raise ValueError("Exit request identity required")
        with self.store.lock(self.scope) as owner:
            d = self.state()
            t = d["trades"].get(trade_id)
            if not t:
                raise ValueError("Managed trade not found in this account/mode")
            if request_id in d["requests"]:
                return t
            b = self.books()
            self._sync_trade(t, b)
            qty = t["remaining"] if quantity is None else quantity
            if (
                not isinstance(qty, int)
                or isinstance(qty, bool)
                or qty < 0
                or qty > t["remaining"]
                or qty % t["lot"]
            ):
                raise ValueError("Exit must reduce the confirmed position in whole lots")
            if t.get("exit_goal") is not None:
                if t["status"] not in ("exit_rejected", "cancel_rejected", "cancel_unknown"):
                    return t
                t["retry_generation"] = t.get("retry_generation", 0) + 1
                for op in t["ops"]:
                    if op.get("cancel_result", {}).get("state") in ("rejected", "unknown"):
                        op.pop("cancel_requested", None)
                        op["cancel_attempts"] = 0
            t.update(
                exit_goal=t["closed_quantity"] + qty, exit_reason="User exit", status="closing"
            )
            # A full exit also cancels any still-pending entry even before its first fill.
            if quantity is None:
                t["exit_goal"] = t["quantity"]
            d["requests"][request_id] = trade_id
            self.save(d, owner)
            self._manage(d, t, b, owner)
            self.save(d, owner)
            return copy.deepcopy(t)

    def tighten(self, trade_id, sl):
        with self.store.lock(self.scope) as owner:
            d = self.state()
            t = d["trades"].get(trade_id)
            if not t:
                raise ValueError("Managed trade not found")
            self._sync_trade(t, self.books())
            price = snap(number(sl), t["tick"])
            q = self.g.quote(t["symbol"], t["exchange"])
            if self.clock() - q.get("time", 0) > 5 or not max(
                t["sl"], t.get("current_sl", 0), t.get("desired_sl", 0)
            ) < price < number(q["bid"]):
                raise ValueError("Stop can only tighten below a fresh bid")
            t["desired_sl"] = price
            self.save(d, owner)
            return t

    def adopt(self, request):
        """Explicitly take control of an existing long option, or close it directly.

        Pending sells are only acquired if their exact IDs were displayed and
        included in the user's click. Another controller remains a hard conflict.
        """
        with self.store.lock(self.scope) as owner:
            d = self.state()
            rid = request.get("request_id")
            if not isinstance(rid, str) or not rid or len(rid) > 64:
                raise ValueError("Request identity required")
            if rid in d["requests"]:
                return d["trades"][d["requests"][rid]]
            t = {k: request[k] for k in ("symbol", "exchange", "product")}
            b = self.books()
            matches = [p for p in b["positions"] if same(p, t) and int(p["quantity"]) > 0]
            if len(matches) != 1:
                raise ValueError("A single confirmed long position is required")
            p = matches[0]
            qty = int(p["quantity"])
            meta = self.g.metadata(t["symbol"], t["exchange"])
            if request.get("quantity") != qty or qty % meta["lot"]:
                raise ValueError("Position quantity changed; refresh before taking control")
            if self.g.other_controller(t["symbol"], t["exchange"], t["product"]):
                raise ValueError("Another controller owns this position")
            if any(
                same(x, t) and x["status"] not in ("closed", "rejected")
                for x in d["trades"].values()
            ):
                raise ValueError("Position is already managed")
            pending = [o for o in b["orders"] if same(o, t) and not is_terminal(o)]
            disclosed = request.get("order_ids", [])
            if not isinstance(disclosed, list) or set(map(str, disclosed)) != {
                str(o["orderid"]) for o in pending
            }:
                raise ValueError("Pending orders changed; review the displayed order IDs")
            if any(o["action"] != "SELL" for o in pending):
                raise ValueError("Pending BUY conflicts with adoption or exit")
            close = request.get("close", False)
            if not isinstance(close, bool):
                raise ValueError("Invalid close flag")
            entry = number(p.get("average_price") or 0)
            ledger = journal(
                b["fills"],
                b["positions"],
                datetime.fromtimestamp(self.clock(), IST).date().isoformat(),
                d["settings"]["brokerage"],
            )
            basis = (
                next((row for row in ledger.get("open_positions", []) if same(row, t)), None)
                if ledger["complete"]
                else None
            )
            if basis:
                entry = basis["average_price"]
            sl = 0 if close else number(request.get("sl", 0))
            target = 0 if close else number(request.get("target", 0))
            if not close:
                quote = self.g.quote(t["symbol"], t["exchange"])
                if not 0 <= self.clock() - quote.get("time", 0) <= 5:
                    raise ValueError("Fresh bid required to adopt protection")
                bid = number(quote.get("bid", 0))
                if (
                    not 0 < sl < bid < target
                    or abs(sl - snap(sl, meta["tick"])) > 1e-7
                    or abs(target - snap(target, meta["tick"])) > 1e-7
                ):
                    raise ValueError(
                        "Set a valid tick-aligned SL below current bid and target above current bid"
                    )
                if any(o.get("pricetype") not in ("SL", "SL-M") for o in pending):
                    raise ValueError(
                        "Take control requires only protective stops; exit can cancel disclosed targets"
                    )
                if sum(int(o["quantity"]) - filled(b, o["orderid"])[0] for o in pending) > qty:
                    raise ValueError("Overlapping exits exceed this position")
            if not close:
                sl = max([sl] + [number(o.get("trigger_price", 0)) for o in pending])
            tid = uuid.uuid4().hex
            t.update(
                id=tid,
                quantity=qty,
                lot=meta["lot"],
                tick=meta["tick"],
                freeze=meta["freeze"],
                entry=entry,
                sl=sl,
                target=target,
                created=self.clock(),
                cutoff=d["settings"]["cutoff"],
                average_entry_verified=bool(basis),
                baseline_quantity=qty,
                baseline_value=qty * entry,
                entry_quantity=qty,
                closed_quantity=0,
                remaining=qty,
                average_entry=entry,
                status="closing" if close else "unprotected",
                reason="User requested direct exit" if close else "User adopted existing position",
                exit_goal=qty if close else None,
                exit_reason="User exit",
                ops=[],
                peak_net=None,
                scope=self.scope,
            )
            if not close:
                t["desired_sl"] = sl
            for o in pending:
                t["ops"].append(
                    {
                        "role": "sl",
                        "id": uuid.uuid4().hex,
                        "quantity": int(o["quantity"]),
                        "state": "accepted",
                        "created": self.clock(),
                        "orderid": str(o["orderid"]),
                        "filled": 0,
                        "baseline_filled": filled(b, o["orderid"])[0],
                        "tag": o.get("order_tag", ""),
                        "pricetype": o.get("pricetype"),
                        "trigger_price": number(o.get("trigger_price", 0)),
                        "price": number(o.get("price", 0)),
                        "broker_status": status(o),
                    }
                )
            d["trades"][tid] = t
            d["requests"][rid] = tid
            self.save(d, owner)
            self._manage(d, t, b, owner)
            self.save(d, owner)
            return copy.deepcopy(t)
