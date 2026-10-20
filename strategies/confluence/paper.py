"""Independent paper ledger. This module cannot submit exchange orders."""

from __future__ import annotations

import fcntl
import json
import math
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .strategy import Config, manage_position


def day(now):
    return int((now + 19800) // 86400)


def wallet_seed(snapshot, now):
    """Accept the existing scalper's sanitized read-only USD wallet format."""
    try:
        rows = [r for r in snapshot["result"] if r["asset_symbol"] == "USD"]
        amount = float(rows[0]["available_balance"])
        age = now - float(snapshot["captured_at"])
        if (
            snapshot["environment"] != "india_prod"
            or len(rows) != 1
            or not 0 <= age <= 600
            or not math.isfinite(amount)
            or amount < 0
        ):
            raise ValueError("Invalid or stale account balance snapshot")
        return amount
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("A recent Delta USD wallet snapshot is required") from exc


def fresh_quote(q, now):
    try:
        return (
            all(math.isfinite(float(q[k])) for k in ("bid", "ask", "quote_time"))
            and 0 < float(q["bid"]) < float(q["ask"])
            and 0 <= now - float(q["quote_time"]) <= 10
        )
    except (KeyError, TypeError, ValueError):
        return False


class PaperBook:
    def __init__(self, state, cfg):
        self.state = state
        self.cfg = cfg
        # Unsaved records are drained after each atomic SQLite checkpoint.
        self.trades = []
        self.events = []

    @classmethod
    def fresh(cls, capital, now, cfg, source="synthetic test"):
        if not math.isfinite(capital) or capital < 0:
            raise ValueError("Nonnegative finite capital required")
        return cls(
            {
                "version": 1,
                "config": asdict(cfg),
                "initial_cash": capital,
                "cash": capital,
                "capital_source": source,
                "started_at": now,
                "pending": None,
                "position": None,
                "last_candle": 0,
                "submitted": 0,
                "filled": 0,
                "day": day(now),
                "day_net": 0.0,
                "loss_streak": 0,
                "halt_day": None,
                "paused": False,
                "status": "ready",
                "updated_at": now,
            },
            cfg,
        )

    def event(self, kind, now, **details):
        self.events.append({"kind": kind, "at": now, **details})

    def budget(self, now):
        net = self.state["day_net"] if self.state["day"] == day(now) else 0
        return max(0, min(self.cfg.max_risk, 3 + min(0, net)))

    def disconnect(self, now):
        if self.state["pending"]:
            self.event("entry_cancelled", now, reason="feed_unavailable")
        self.state["pending"] = None
        self.state["status"] = "feed unavailable; entries suspended; simulated stop retained"
        self.state["updated_at"] = now

    def resume(self, now):
        if self.state["halt_day"] is not None:
            if day(now) <= self.state["halt_day"]:
                raise ValueError("Daily halt requires explicit resume on a later India-time day")
            self.state.update(halt_day=None, loss_streak=0, day=day(now), day_net=0.0)
        self.state.update(paused=False, status="ready")
        self.event("resumed", now)

    def _close(self, price, role, reason, now):
        p = self.state["position"]
        units = p["quantity"] * p["contract_value"]
        fee = price * units * p[role + "_rate"] * (1 + self.cfg.gst_pct / 100)
        gross = p["side"] * (price - p["entry"]) * units
        reserve = p.get("slippage_reserve", self.cfg.slippage)
        fees = p["entry_fee"] + fee
        net = gross - fees - reserve
        trade = {
            **p,
            "exit": price,
            "exit_role": role,
            "reason": reason,
            "closed_at": now,
            "holding_seconds": now - p["opened_at"],
            "gross_usd": gross,
            "entry_fee_usd": p["entry_fee"],
            "exit_fee_usd": fee,
            "fees_usd": fees,
            "slippage_usd": reserve,
            "net_usd": net,
            "net_inr": net * 85,
        }
        self.trades.append(trade)
        self.state["cash"] += gross - fee - reserve  # entry fee already debited
        if self.state["day"] != day(now):
            self.state.update(day=day(now), day_net=0.0)
        self.state["day_net"] += net
        self.state["loss_streak"] = self.state["loss_streak"] + 1 if net < 0 else 0
        if self.state["day_net"] <= -3 or self.state["loss_streak"] >= 3:
            self.state["halt_day"] = day(now)
        self.state["position"] = None
        self.event("closed", now, reason=reason, net_usd=net)

    @staticmethod
    def _through(order, trades, now, target=False):
        """Conservative tape model: strict trade-through, queue ahead, no reuse.

        Delta REST trades have no unique ID. Duplicate tuples and subsequent
        prints at the same second are intentionally undercounted, never reused.
        """
        seen = set()
        fresh = []
        for t in trades:
            try:
                ts, price, size = (float(t[k]) for k in ("timestamp", "price", "size"))
                key = (ts, price, size, t["side"])
                if (
                    key in seen
                    or not all(math.isfinite(x) for x in (ts, price, size))
                    or not order["watermark"] < ts <= now
                    or size <= 0
                ):
                    continue
                seen.add(key)
                fresh.append((ts, price, size, t["side"]))
            except (KeyError, TypeError, ValueError):
                continue
        expected = "buy" if (order["side"] == -1) != target else "sell"
        level = order["target"] if target else order["entry"]
        direction = -order["side"] if target else order["side"]
        size = sum(
            size
            for ts, price, size, side in fresh
            if side == expected and direction * (price - level) < 0
        )
        if fresh:
            order["watermark"] = max(t[0] for t in fresh)
        order["queue_remaining"] = max(0, order["queue_remaining"] - size)
        return order["queue_remaining"] == 0

    def step(self, quote, decision, now):
        s = self.state
        s["updated_at"] = now
        if not fresh_quote(quote, now):
            self.disconnect(now)
            return
        s["status"] = (
            "daily halt" if s["halt_day"] is not None else "paused" if s["paused"] else "scanning"
        )
        if s["position"]:
            p = s["position"]
            price = quote["bid"] if p["side"] == 1 else quote["ask"]
            result = manage_position(p, price, now, self.cfg)
            p.update(stop=result["stop"], peak_net=result["peak_net"], unrealized_net=result["net"])
            # A restart/disconnect may miss the path; close conservatively on reconnect.
            reason = result["exit_reason"]
            if not reason and now - p.get("last_managed", now) > 10:
                reason = "feed_gap"
            p["last_managed"] = now
            if reason:
                self._close(price, "taker", reason, now)
            elif self._through(p, quote.get("trades", []), now, target=True):
                self._close(p["target"], "maker", "target", now)
            return
        if s["pending"]:
            p = s["pending"]
            if now - p["submitted_at"] >= 15:
                self.event("entry_cancelled", now, reason="15_second_timeout")
                s["pending"] = None
            elif self._through(p, quote.get("trades", []), now):
                fee = (
                    p["entry"]
                    * p["quantity"]
                    * p["contract_value"]
                    * p["maker_rate"]
                    * (1 + self.cfg.gst_pct / 100)
                )
                p.update(
                    opened_at=now,
                    last_managed=now,
                    entry_fee=fee,
                    peak_net=0.0,
                    watermark=now,
                    queue_remaining=p["quantity"],
                    entry_latency_seconds=now - p["submitted_at"],
                )
                s.update(position=p, pending=None, filled=s["filled"] + 1, cash=s["cash"] - fee)
                self.event("filled", now, side=p["side"], price=p["entry"], quantity=p["quantity"])
                # Establish and evaluate protection in the same iteration as the fill.
                self.step(quote, None, now)
            return
        if not decision or s["paused"] or s["halt_day"] is not None:
            return
        candle = decision.get("candle_closed", 0)
        if candle <= s["last_candle"]:
            return
        if decision.get("action") not in ("LONG", "SHORT"):
            # A candle may qualify later as quotes/chain refresh; HOLD never consumes it.
            return
        p = dict(decision["selected_plan"])
        side = 1 if decision["action"] == "LONG" else -1
        if (
            not p.get("fits_risk")
            or p["net_risk"] > self.budget(now)
            or p["margin"] > self.cfg.max_margin
            or p["margin"]
            + p["entry"] * p["quantity"] * p["contract_value"] * p["maker_rate"] * 1.18
            > s["cash"]
            or not 0 <= now - decision["asof"] <= 2
        ):
            return
        # Refuse a stale/crossing entry. The next scan must create a fresh plan.
        if (side == 1 and p["entry"] != quote["bid"]) or (
            side == -1 and p["entry"] != quote["ask"]
        ):
            return
        book = quote["bids"] if side == 1 else quote["asks"]
        ahead = sum(float(size) for price, size in book if float(price) == p["entry"])
        p.update(side=side, submitted_at=now, watermark=now, queue_remaining=ahead + p["quantity"])
        s.update(pending=p, last_candle=candle, submitted=s["submitted"] + 1)
        self.event("submitted", now, side=side, quantity=p["quantity"], entry=p["entry"])

    def stop(self, quote, now, reason="manual"):
        self.state.update(
            paused=True, pending=None, status="stopped", updated_at=now, stop_reason=reason
        )
        if self.state["position"]:
            if fresh_quote(quote, now):
                p = self.state["position"]
                self._close(
                    quote["bid"] if p["side"] == 1 else quote["ask"], "taker", "shutdown", now
                )
            else:
                self.state["status"] = (
                    "stopped with unresolved simulated exposure; fresh quote required"
                )
        self.event("stopped", now, unresolved=bool(self.state["position"]))


class Ledger:
    """One writer per ledger, state/events/fills committed in one transaction."""

    def __init__(self, path, readonly=False):
        self.path = Path(path)
        self.db = None
        self.lock = None
        self.readonly = readonly

    def __enter__(self):
        if self.readonly:
            self.db = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3
            )
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.lock = open(str(self.path) + ".lock", "a")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("This paper ledger already has a controller") from None
            self.db = sqlite3.connect(self.path, timeout=3)
            os.chmod(self.path, 0o600)
            self.db.executescript("""CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, body TEXT NOT NULL);""")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.db:
            self.db.close()
            self.db = None
        if self.lock:
            self.lock.close()
            self.lock = None

    def load(self, cfg):
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if not row:
            return None
        state = json.loads(row[0])
        if state["version"] != 1 or state["config"] != asdict(cfg):
            raise ValueError(
                "Ledger configuration differs; use the original settings or a separate ledger"
            )
        result = PaperBook(state, cfg)
        return result

    def save(self, paper):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO state VALUES (1,?)",
                (json.dumps(paper.state, allow_nan=False),),
            )
            self.db.executemany(
                "INSERT INTO trades(body) VALUES (?)",
                [(json.dumps(x, allow_nan=False),) for x in paper.trades],
            )
            self.db.executemany(
                "INSERT INTO events(body) VALUES (?)",
                [(json.dumps(x, allow_nan=False),) for x in paper.events],
            )
        paper.trades.clear()
        paper.events.clear()

    def report(self):
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if not row:
            return {"mode": "paper", "status": "not initialized", "trade_count": 0}
        s = json.loads(row[0])
        count = wins = losses = 0
        gross = fees = slip = net = win_total = loss_total = peak = dd = holding = latency = 0.0
        recent = []
        for row in self.db.execute("SELECT body FROM trades ORDER BY id"):
            t = json.loads(row[0])
            count += 1
            wins += t["net_usd"] > 0
            losses += t["net_usd"] < 0
            gross += t["gross_usd"]
            fees += t["fees_usd"]
            slip += t["slippage_usd"]
            net += t["net_usd"]
            win_total += max(0, t["net_usd"])
            loss_total += max(0, -t["net_usd"])
            peak = max(peak, net)
            dd = max(dd, peak - net)
            holding += t["holding_seconds"]
            latency += t["entry_latency_seconds"]
            recent.append(t)
            if len(recent) > 50:
                recent.pop(0)
        return {
            "mode": "paper",
            "state": s,
            "trade_count": count,
            "gross_usd": gross,
            "fees_usd": fees,
            "slippage_usd": slip,
            "net_usd": net,
            "gross_inr": gross * 85,
            "fees_inr": fees * 85,
            "net_inr": net * 85,
            "usd_inr": 85,
            "win_rate": wins / count if count else None,
            "expectancy_usd": net / count if count else None,
            "profit_factor": win_total / loss_total if loss_total else None,
            "realized_drawdown_usd": dd,
            "mean_holding_seconds": holding / count if count else None,
            "mean_entry_fill_latency_seconds": latency / count if count else None,
            "maker_entry_fill_rate": s["filled"] / s["submitted"] if s["submitted"] else None,
            "recent_trades": recent,
            "limitations": "Simulated tape/queue fills, full fees, reserved slippage. No exchange execution. Drawdown is realized only.",
        }
