"""Durable, explicitly POST-driven management of one reviewed maker entry."""

import fcntl
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

_HELD = threading.local()

TERMINAL = {"blocked", "completed", "cancelled", "rejected"}


class ManagedPlans:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        with self.store.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_plan_profit_peaks (plan_id TEXT PRIMARY KEY,peak_inr TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_managed_plans (id TEXT PRIMARY KEY,user TEXT,account TEXT,symbol TEXT,pid TEXT,parent_id TEXT,payload TEXT,status TEXT,message TEXT,entry_order_id TEXT,stop_order_id TEXT,target_order_id TEXT,close_order_id TEXT,position_version TEXT,entry_price TEXT,stop TEXT,UNIQUE(user,parent_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_plan_stop_migrations (plan_id TEXT PRIMARY KEY,old_id TEXT,old_version TEXT,new_id TEXT,stop_price TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_plan_timing (plan_id TEXT PRIMARY KEY,placed_at REAL,source TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_plan_level_overrides (plan_id TEXT PRIMARY KEY,target TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_plan_fill_timing (plan_id TEXT PRIMARY KEY, first_fill_at REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_plan_trailing_observations (plan_id TEXT PRIMARY KEY, observed_at REAL NOT NULL, position_version TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS delta_plan_operations (plan_id TEXT,kind TEXT,payload TEXT,PRIMARY KEY(plan_id,kind))"
            )

    @contextmanager
    def lock(self, user, account, symbol):
        """Reentrant process-safe lock, released by the OS on worker death.

        All plan reads/decisions and every account/product action share this lock.
        It deliberately spans broker preflight and mutation, without a SQLite transaction.
        """
        from .service import Rejected

        key = hashlib.sha256(
            (user + "\0" + str(account) + "\0" + str(symbol)).encode()
        ).hexdigest()
        held = getattr(_HELD, "keys", None)
        if held is None:
            held = _HELD.keys = set()
        if key in held:
            yield
            return
        directory = self.store.path.parent / (self.store.path.name + ".locks")
        directory.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(
            directory / key, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        deadline = time.monotonic() + 15
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise Rejected(
                            "Another account/product decision is in progress; refresh before retrying"
                        ) from None
                    time.sleep(0.025)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
        finally:
            os.close(descriptor)

    def assert_close_ready(self, user, account, symbol):
        from .service import Rejected, number

        client, actual = self.service.client(user)
        if actual != account:
            raise Rejected("Account changed; refresh before closing")
        with self.store.db() as db:
            rows = db.execute(
                "SELECT * FROM delta_managed_plans WHERE user=? AND account=? AND symbol=? AND status NOT IN ('completed','cancelled','rejected')",
                (user, account, symbol),
            ).fetchall()
        for row in rows:
            plan = dict(row)
            if json.loads(plan["payload"]).get("action") == "adopt":
                continue
            if not plan["entry_order_id"]:
                raise Rejected("Entry outcome is unresolved; reconcile before closing")
            parent = client.request("GET", "/v2/orders/" + plan["entry_order_id"])
            if not self.owned_order(plan, parent, "entry"):
                raise Rejected("Entry ownership cannot be proven; no close submitted")
            if (
                parent.get("state") in ("open", "pending")
                and number(parent.get("unfilled_size")) > 0
            ):
                raise Rejected(
                    "Cancel remainder first; the owned entry can still add exposure"
                )

    def get(self, user, identity):
        from .service import Rejected

        with self.store.db() as db:
            row = db.execute(
                "SELECT * FROM delta_managed_plans WHERE id=? AND user=?",
                (identity, user),
            ).fetchone()
        if not row:
            raise Rejected("Managed plan not found for this user")
        return dict(row)

    def update(self, identity, **values):
        allowed = {
            "status",
            "message",
            "entry_order_id",
            "stop_order_id",
            "target_order_id",
            "close_order_id",
            "position_version",
            "entry_price",
            "stop",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid managed plan update")
        with self.store.db() as db:
            db.execute(
                "UPDATE delta_managed_plans SET "
                + ",".join(key + "=?" for key in values)
                + " WHERE id=?",
                (*values.values(), identity),
            )

    def record_placement(self, identity, value, source="broker"):
        from .service import Rejected, fill_timestamp

        try:
            placed = float(fill_timestamp(value))
            if placed <= 0 or placed > time.time() + 5:
                return
        except (Rejected, TypeError, ValueError):
            return
        with self.store.db() as db:
            if source == "broker":
                db.execute(
                    "INSERT INTO delta_plan_timing VALUES(?,?,?) ON CONFLICT(plan_id) DO UPDATE SET placed_at=excluded.placed_at,source=excluded.source",
                    (identity, placed, source),
                )
            else:
                db.execute(
                    "INSERT OR IGNORE INTO delta_plan_timing VALUES(?,?,?)",
                    (identity, placed, source),
                )

    def record_first_fill(self, plan, fills, complete):
        from .fill_timing import first_entry_fill_time

        stamp = first_entry_fill_time(
            plan, json.loads(plan["payload"]), fills, complete, time.time()
        )
        if stamp is not None:
            with self.store.db() as db:
                db.execute(
                    "INSERT INTO delta_plan_fill_timing VALUES(?,?) ON CONFLICT(plan_id) DO UPDATE SET first_fill_at=MIN(first_fill_at,excluded.first_fill_at)",
                    (plan["id"], stamp),
                )

    def list(self, user, symbol, fills=None, fills_complete=False):
        from .fill_timing import first_entry_fill_time

        with self.store.db() as db:
            rows = db.execute(
                "SELECT * FROM delta_managed_plans WHERE user=? AND symbol=? ORDER BY rowid DESC LIMIT 20",
                (user, symbol),
            ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            levels = self.levels(dict(row))
            with self.store.db() as db:
                timing = db.execute(
                    "SELECT placed_at FROM delta_plan_timing WHERE plan_id=?",
                    (row["id"],),
                ).fetchone()
                peak_row = db.execute(
                    "SELECT peak_inr FROM delta_plan_profit_peaks WHERE plan_id=?",
                    (row["id"],),
                ).fetchone()
                fill_timing = db.execute(
                    "SELECT first_fill_at FROM delta_plan_fill_timing WHERE plan_id=?",
                    (row["id"],),
                ).fetchone()
                trailing_observation = db.execute(
                    "SELECT observed_at FROM delta_plan_trailing_observations WHERE plan_id=?",
                    (row["id"],),
                ).fetchone()
            result.append(
                {
                    "id": row["id"],
                    "status": row["status"],
                    "message": row["message"],
                    "side": payload["side"],
                    "manual_entry": payload.get("entry_mode") == "manual",
                    "target_mode": payload.get("target_mode", "fixed"),
                    "strategy_id": payload.get("strategy_id", "ema"),
                    "setup_id": payload.get("setup_id"),
                    "setup_time": payload.get("setup_time"),
                    "entry_trend_direction": payload.get("entry_trend_direction"),
                    "smart_profit_tracking": payload.get("smart_profit_tracking")
                    is True,
                    "peak_net_inr": float(peak_row[0]) if peak_row else None,
                    "entry_order_id": row["entry_order_id"],
                    "entry_request_id": row["parent_id"],
                    "stop_order_id": row["stop_order_id"],
                    "target_order_id": row["target_order_id"],
                    "first_fill_at": fill_timing["first_fill_at"]
                    if fill_timing
                    else first_entry_fill_time(
                        dict(row), payload, fills, fills_complete, time.time()
                    ),
                    "trailing_observed_at": trailing_observation["observed_at"] if trailing_observation else None,
                    "placed_at": timing["placed_at"] if timing else None,
                    "stop": float(row["stop"]),
                    "initial_stop": levels["stop"],
                    "target": levels["target"],
                    "source_time": levels["source_time"],
                    "interval_seconds": levels["interval_seconds"],
                    "entry_price": float(row["entry_price"])
                    if row["entry_price"] is not None
                    else None,
                }
            )
        return result

    @staticmethod
    def source(source, interval, original=None):
        from .service import Rejected, number

        stamp = number(source, True)
        span = number(interval, True)
        now = Decimal(str(time.time()))
        if (
            stamp != stamp.to_integral_value()
            or span != span.to_integral_value()
            or span > 86400
        ):
            raise Rejected("Invalid closed candle timestamp or interval")
        if original is not None and stamp < number(original):
            raise Rejected("Management evidence predates reviewed entry")
        if stamp + span > now or now - (stamp + span) > 2 * span + 10:
            raise Rejected(
                "Management requires a fresh closed candle for the reviewed interval"
            )
        return int(stamp)

    def create(self, user, account, product, data, mark):
        from .service import Rejected, number

        target_mode = data.get("target_mode", "fixed")
        backend_entry = (
            isinstance(data.get("automation_generation"), str)
            and bool(data["automation_generation"].strip())
            and data.get("entry_mode") != "manual"
        )
        if target_mode not in ("fixed", "trend"):
            raise Rejected("Unsupported managed target mode")
        if target_mode == "trend" and not (backend_entry or data.get("entry_mode") == "manual"):
            raise Rejected("Trend exits require a backend automatic or explicit manual entry")
        levels = data.get("auto_protection")
        if not isinstance(levels, dict):
            raise Rejected("Reviewed automatic protection levels are required")
        self.source(levels.get("source_time"), levels.get("interval_seconds"))
        stop = number(levels.get("stop"), True)
        target = number(levels.get("target"), True)
        entry = number(data["price"], True)
        tick = number(product["tick_size"], True)
        if stop % tick or target % tick:
            raise Rejected("Reviewed protection must match product tick size")
        if data["side"] == "buy":
            valid = stop < min(entry, mark) and target > max(entry, mark)
        else:
            valid = stop > max(entry, mark) and target < min(entry, mark)
        if not valid:
            raise Rejected(
                "Reviewed protection must be outside entry and current mark on the correct sides"
            )
        if (
            product.get("notional_type") != "vanilla"
            or (product.get("settling_asset") or {}).get("symbol") != "USD"
            or product.get("maker_commission_rate") is None
        ):
            raise Rejected("Managed entries require verified USD vanilla fee metadata")
        if (
            not isinstance(levels.get("reason"), str)
            or not 1 <= len(levels["reason"]) <= 240
        ):
            raise Rejected("A short reviewed protection reason is required")
        normalized_levels = {
            "stop": float(stop),
            "target": float(target),
            "source_time": int(number(levels["source_time"])),
            "interval_seconds": int(number(levels["interval_seconds"])),
            "reason": levels["reason"],
        }
        data = {
            key: data[key]
            for key in (
                "request_id",
                "symbol",
                "action",
                "account",
                "side",
                "size",
                "price",
                "leverage",
                "balance_fraction",
                "sizing_version",
                "entry_mode",
                "target_mode",
                "automation_generation",
                "strategy_id",
                "setup_id",
                "setup_time",
                "entry_trend_direction",
                "strategy_version",
                "daily_key",
                "auto_protection",
            )
            if key in data
        }
        data["auto_protection"] = normalized_levels
        data["target_mode"] = target_mode
        data["smart_profit_tracking"] = (
            target_mode == "trend" or backend_entry or normalized_levels["interval_seconds"] == 60
        )
        if (
            (backend_entry or normalized_levels["interval_seconds"] == 60)
            and data.get("entry_mode") != "manual"
        ):
            data["entry_ttl_seconds"] = 15
        identity = str(
            uuid5(NAMESPACE_URL, user + "\0" + account + "\0" + data["request_id"])
        )
        with self.store.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO delta_managed_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    user,
                    account,
                    data["symbol"],
                    str(product["id"]),
                    data["request_id"],
                    json.dumps(data),
                    "awaiting_entry",
                    "Reviewed maker entry awaiting broker acknowledgement",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    str(stop),
                ),
            )
        return identity

    @staticmethod
    def position_marker(pid, position, fills, complete):
        from .service import Rejected, digest, fill_timestamp, number

        if not complete or not isinstance(fills, list):
            raise Rejected(
                "Complete current fill evidence is required to adopt this position"
            )
        rows = {}
        for row in fills:
            nested = row.get("product")
            product = row.get(
                "product_id", nested.get("id") if isinstance(nested, dict) else None
            )
            if str(product) != str(pid):
                continue
            identity = str(row.get("id", ""))
            if not identity or (identity in rows and rows[identity] != row):
                raise Rejected("Position fill ownership is ambiguous")
            rows[identity] = row
        ordered = sorted(
            rows.values(),
            key=lambda row: fill_timestamp(row.get("created_at")),
            reverse=True,
        )
        if not ordered or (
            len(ordered) > 1
            and fill_timestamp(ordered[0].get("created_at"))
            == fill_timestamp(ordered[1].get("created_at"))
        ):
            raise Rejected("Latest position fill evidence is unavailable or ambiguous")
        latest = ordered[0]
        after = (latest.get("meta_data") or {}).get("new_position") or {}
        if (
            latest.get("fill_type") != "normal"
            or str(after.get("last_fill_uuid")) != str(latest["id"])
            or number(after.get("size")) != number(position.get("size"))
            or number(after.get("entry_price"), True)
            != number(position.get("entry_price"), True)
        ):
            raise Rejected("Latest fill snapshot does not match the current position")
        return digest(
            {
                "id": latest["id"],
                "created_at": latest.get("created_at"),
                "last_fill_uuid": after["last_fill_uuid"],
                "size": str(number(after["size"])),
                "entry": str(number(after["entry_price"])),
            }
        )

    def adopt(self, user, account, data):
        """Register explicit existing-position authorization; no broker mutation."""
        from .service import (
            Rejected,
            digest,
            matching_margined,
            number,
            position_version,
        )

        (
            c,
            actual,
            product,
            tick,
            cv,
            cap,
            mark,
            ticker,
            pos,
            margined,
            orders,
            fills,
            lev,
        ) = self.service.snapshot(user, data["symbol"])
        size = number(pos.get("size", 0))
        version = position_version(product["id"], pos)
        if (
            actual != account
            or not size
            or size != size.to_integral_value()
            or data.get("position_version") != version
        ):
            raise Rejected("Position changed; refresh before adopting protection")
        levels = data.get("auto_protection")
        if not isinstance(levels, dict):
            raise Rejected("Reviewed automatic protection levels are required")
        self.source(levels.get("source_time"), levels.get("interval_seconds"))
        stop = number(levels.get("stop"), True)
        target = number(levels.get("target"), True)
        entry = number(pos.get("entry_price"), True)
        if stop % tick or target % tick:
            raise Rejected("Reviewed protection must match product tick size")
        if (
            not isinstance(levels.get("reason"), str)
            or not 1 <= len(levels["reason"]) <= 240
        ):
            raise Rejected("A short reviewed protection reason is required")
        if (
            product.get("notional_type") != "vanilla"
            or (product.get("settling_asset") or {}).get("symbol") != "USD"
        ):
            raise Rejected("Adoption requires a supported USD vanilla position")
        reviewed = {}
        side = "buy" if size > 0 else "sell"
        opposite = "sell" if size > 0 else "buy"
        for name, kind in (
            ("stop", "stop_loss_order"),
            ("target", "take_profit_order"),
        ):
            selected = data.get("existing_" + name)
            candidates = [
                order for order in orders if order.get("stop_order_type") == kind
            ]
            if len(candidates) > 1:
                raise Rejected(
                    "Multiple existing protective orders require manual review"
                )
            if candidates:
                order = candidates[0]
                if (
                    not isinstance(selected, dict)
                    or str(selected.get("id")) != str(order["id"])
                    or selected.get("version") != digest(order)
                ):
                    raise Rejected(
                        "Review the exact existing protective order and version"
                    )
                if (
                    order.get("reduce_only") is not True
                    or order.get("side") != opposite
                    or number(order.get("size"), True) != abs(size)
                    or order.get("order_type") not in ("market_order", "limit_order")
                ):
                    raise Rejected(
                        "Existing protection must be an opposite-side reduce-only order for the full position"
                    )
                if name == "stop":
                    old = number(order.get("stop_price"), True)
                    if (size > 0 and stop < old) or (size < 0 and stop > old):
                        raise Rejected("Adoption cannot loosen the existing stop")
                reviewed["existing_" + name] = {
                    "id": str(order["id"]),
                    "version": digest(order),
                }
            elif selected is not None:
                raise Rejected(
                    "Reviewed existing protective order is no longer present"
                )
        if len(orders) != len(reviewed):
            raise Rejected(
                "Clear unrelated selected-product orders before adopting protection"
            )
        with self.store.db() as db:
            active = db.execute(
                "SELECT id FROM delta_managed_plans WHERE user=? AND account=? AND symbol=? AND status NOT IN ('blocked','completed','cancelled','rejected')",
                (user, account, data["symbol"]),
            ).fetchone()
        if active:
            raise Rejected("This position already has a managed plan requiring review")
        marker = self.position_marker(
            product["id"], pos, fills, product["_fills_complete"]
        )
        started = time.monotonic()
        fresh = c.request("GET", "/v2/positions", params={"product_id": product["id"]})
        current = c.request("GET", "/v2/tickers/" + data["symbol"], private=False)
        mark = number(current.get("mark_price"), True)
        fresh_fills = self.service.recent_fills(c, account, product["id"], force=True)
        if (
            self.position_marker(
                product["id"], fresh, fresh_fills, isinstance(fresh_fills, list)
            )
            != marker
        ):
            raise Rejected("Position fill ownership changed during adoption review")
        if (
            time.monotonic() - started > 5
            or position_version(product["id"], fresh) != version
        ):
            raise Rejected("Position changed during adoption preflight")
        if (size > 0 and not (stop < mark and target > max(mark, entry))) or (
            size < 0 and not (stop > mark and target < min(mark, entry))
        ):
            raise Rejected(
                "Adoption protection must be on the correct sides of current mark and target beyond entry"
            )
        liquidation = matching_margined(margined, product["id"], pos).get(
            "liquidation_price"
        )
        if (
            liquidation is not None
            and number(liquidation) > 0
            and (
                (size > 0 and stop <= number(liquidation))
                or (size < 0 and stop >= number(liquidation))
            )
        ):
            raise Rejected("Stop must remain inside the known liquidation price")
        payload = {
            "action": "adopt",
            "request_id": data["request_id"],
            "symbol": data["symbol"],
            "account": account,
            "side": side,
            "size": int(abs(size)),
            "price": str(entry),
            "adopted_position_version": version,
            "adopted_fill_marker": marker,
            "auto_protection": {
                "stop": float(stop),
                "target": float(target),
                "source_time": int(number(levels["source_time"])),
                "interval_seconds": int(number(levels["interval_seconds"])),
                "reason": levels["reason"],
            },
            **reviewed,
        }
        identity = str(
            uuid5(NAMESPACE_URL, user + "\0" + account + "\0" + data["request_id"])
        )
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                "SELECT id FROM delta_managed_plans WHERE user=? AND account=? AND symbol=? AND status NOT IN ('blocked','completed','cancelled','rejected')",
                (user, account, data["symbol"]),
            ).fetchone()
            if active:
                raise Rejected(
                    "This position already has a managed plan requiring review"
                )
            db.execute(
                "UPDATE delta_managed_plans SET status='rejected',message='Superseded by reviewed current-position protection' WHERE user=? AND account=? AND symbol=? AND status='blocked'",
                (user, account, data["symbol"]),
            )
            db.execute(
                "INSERT INTO delta_managed_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    user,
                    account,
                    data["symbol"],
                    str(product["id"]),
                    data["request_id"],
                    json.dumps(payload),
                    "placing_protection",
                    "Existing position explicitly adopted; reviewed legacy protection remains until replacement acknowledgment",
                    None,
                    None,
                    None,
                    None,
                    version,
                    str(entry),
                    str(stop),
                ),
            )
        return {
            "status": "confirmed",
            "request_id": data["request_id"],
            "plan_id": identity,
            "message": "Existing-position protection plan registered; no exchange order was submitted",
        }

    def replacement(self, plan, name):
        return json.loads(plan["payload"]).get("existing_" + name)

    def allow_replacement(self, user, account, symbol, data, order, name):
        from .service import digest

        if not data.get("managed_plan_id"):
            return False
        plan = self.get(user, data["managed_plan_id"])
        selected = self.replacement(plan, name)
        if name == "stop" and data.get("migration_stop_id"):
            migration = self.stop_migration(plan)
            if (
                migration
                and plan["account"] == account
                and plan["symbol"] == symbol
                and str(order.get("id")) == migration["old_id"]
                and str(data["migration_stop_id"]) == migration["old_id"]
                and data.get("migration_stop_version") == migration["old_version"]
                and digest(order) == migration["old_version"]
                and self.owned_order(plan, order, "stop")
            ):
                return True
        return bool(
            plan["account"] == account
            and plan["symbol"] == symbol
            and selected
            and str(order.get("id")) == selected["id"]
            and digest(order) == selected["version"]
            and str(data.get("replace_order_id")) == selected["id"]
            and data.get("replace_order_version") == selected["version"]
        )

    def stop_migration(self, plan):
        with self.store.db() as db:
            row = db.execute(
                "SELECT * FROM delta_plan_stop_migrations WHERE plan_id=?",
                (plan["id"],),
            ).fetchone()
        return dict(row) if row else None

    def migration_ack(self, plan, result):
        if result.get("order_id"):
            with self.store.db() as db:
                db.execute(
                    "UPDATE delta_plan_stop_migrations SET new_id=? WHERE plan_id=?",
                    (str(result["order_id"]), plan["id"]),
                )
            self.update(plan["id"], stop_order_id=str(result["order_id"]))

    def migrate_stop(self, plan, client, size, version):
        from .service import Rejected, digest, number

        migration = self.stop_migration(plan)
        if not migration:
            if not plan["stop_order_id"]:
                return None
            old = client.request("GET", "/v2/orders/" + plan["stop_order_id"])
            if old.get("order_type") != "limit_order":
                return None
            if (
                not self.owned_order(plan, old, "stop")
                or old.get("stop_order_type") != "stop_loss_order"
                or old.get("state") not in ("open", "pending")
                or number(old.get("size"), True) > abs(size)
            ):
                raise Rejected(
                    "Existing managed stop ownership is unverified; migration paused"
                )
            value = number(old.get("stop_price"), True)
            with self.store.db() as db:
                db.execute(
                    "INSERT OR IGNORE INTO delta_plan_stop_migrations VALUES(?,?,?,?,?)",
                    (plan["id"], str(old["id"]), digest(old), None, str(value)),
                )
            self.update(plan["id"], stop=str(value))
            migration = self.stop_migration(plan)
        if not migration["new_id"]:
            payload = {
                "action": "protect",
                "stop": migration["stop_price"],
                "position_version": version,
                "migration_stop_id": migration["old_id"],
                "migration_stop_version": migration["old_version"],
            }
            legacy = self.replacement(plan, "stop")
            if legacy:
                payload.update(
                    replace_order_id=legacy["id"],
                    replace_order_version=legacy["version"],
                )
            return self.run(plan, "market_stop", payload, "placing_protection")
        new = client.request("GET", "/v2/orders/" + migration["new_id"])
        if (
            not self.owned_order(plan, new, "stop")
            or not self.market_stop_valid(new)
            or new.get("state") not in ("open", "pending")
        ):
            return self.response(
                plan,
                "rejected",
                "Market stop replacement is not acknowledged for the full owned position; old stop retained",
                "blocked",
            )
        new_size = number(new.get("size"), True)
        if new_size < abs(size):
            return self.run(
                plan,
                "resize_migrated_stop_" + version,
                {
                    "action": "edit",
                    "order_id": migration["new_id"],
                    "version": digest(new),
                    "price": new["stop_price"],
                    "size": int(abs(size)),
                },
                "placing_protection",
            )
        if new_size != abs(size):
            return self.response(
                plan,
                "rejected",
                "Market stop replacement quantity is not the current position; old stop retained",
                "blocked",
            )
        old = client.request("GET", "/v2/orders/" + migration["old_id"])
        if old.get("state") in ("open", "pending"):
            if digest(old) != migration["old_version"] or not self.owned_order(
                plan, old, "stop"
            ):
                return self.response(
                    plan,
                    "rejected",
                    "Original managed stop changed; it has not been cancelled",
                    "blocked",
                )
            return self.run(
                plan,
                "cancel_maker_stop",
                {
                    "action": "cancel",
                    "order_id": migration["old_id"],
                    "version": digest(old),
                },
                "placing_protection",
            )
        return None

    def levels(self, plan):
        levels = dict(json.loads(plan["payload"])["auto_protection"])
        with self.store.db() as db:
            row = db.execute(
                "SELECT target FROM delta_plan_level_overrides WHERE plan_id=?",
                (plan["id"],),
            ).fetchone()
        if row:
            levels["target"] = float(row["target"])
        return levels

    def remember_tighter_stop(self, plan, value):
        """Historical operation replay must never erase a tighter broker sync."""
        from .service import number

        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload,stop FROM delta_managed_plans WHERE id=?",(plan["id"],)).fetchone()
            prior, candidate = number(row["stop"], True), number(value, True)
            long = json.loads(row["payload"])["side"] == "buy"
            if candidate > prior if long else candidate < prior:
                db.execute("UPDATE delta_managed_plans SET stop=? WHERE id=?",(str(candidate),plan["id"]))

    def acknowledged_stop_quantity(self, plan, order):
        """Latest confirmed request quantity distinguishes fills from external shrink."""
        from .service import number

        with self.store.db() as db:
            rows = db.execute(
                "SELECT i.response,e.value FROM intents i JOIN evidence e USING(user,request_id) WHERE i.user=? AND i.symbol=? AND i.pending=0 ORDER BY e.rowid DESC",
                (plan["user"],plan["symbol"]),
            ).fetchall()
        for row in rows:
            receipt, evidence = json.loads(row["response"]), json.loads(row["value"])
            payload = evidence.get("payload") or {}
            if (receipt.get("status") != "confirmed" or str(receipt.get("order_id")) != str(order["id"])
                    or evidence.get("path") != "/v2/orders" or evidence.get("method") not in ("POST","PUT")):
                continue
            matches = (str(payload.get("client_order_id")) == str(order.get("client_order_id"))
                       if evidence["method"] == "POST" else str(payload.get("id")) == str(order["id"]))
            if matches and payload.get("size") is not None:
                return number(payload["size"],True)
        return None

    def sync_exact_market_stop(self, plan, client, size, tick, mark):
        """Accept an external tightening of the same acknowledged owned SL only."""
        from .service import digest, number

        if not plan["stop_order_id"]:
            return plan, None
        order = client.request("GET", "/v2/orders/" + plan["stop_order_id"])
        if order.get("order_type") != "market_order":
            return plan, None  # Existing reviewed legacy-stop migration remains separate.
        proven = False
        for operation in self.operations(plan):
            if operation["kind"] not in ("stop", "market_stop"):
                continue
            payload = json.loads(operation["payload"])
            fingerprint = payload.pop("_ledger_fingerprint", None) or digest(payload)
            receipt = self.store.replay(plan["user"], payload["request_id"], fingerprint)
            if (receipt and receipt.get("status") == "confirmed"
                    and str(receipt.get("order_id")) == str(plan["stop_order_id"])
                    and str(order.get("client_order_id")) == UUID(payload["request_id"]).hex):
                proven = True
                break
        if (str(order.get("id")) != str(plan["stop_order_id"])
                or not proven or not self.owned_order(plan,order,"stop")
                or not self.market_stop_valid(order)
                or order.get("state") not in ("open","pending")):
            return plan, self.response(plan,"rejected","Exact owned market SL acknowledgement or full quantity changed; protection requires review","blocked")
        live_quantity = number(order.get("size"),True)
        if live_quantity != abs(size):
            acknowledged_quantity = self.acknowledged_stop_quantity(plan,order)
            if not (live_quantity == acknowledged_quantity and live_quantity < abs(size)
                    and number(order.get("stop_price"),True) == number(plan["stop"],True)):
                return plan, self.response(plan,"rejected","Exact owned market SL acknowledgement or full quantity changed; protection requires review","blocked")
            # Complete parent-owned fill proof already established the expanded
            # exposure. Keep this acknowledged SL while the existing path
            # resizes it before any profit management can proceed.
            return plan, None
        live_stop, stored = number(order.get("stop_price"),True), number(plan["stop"],True)
        if live_stop % tick:
            return plan, self.response(plan,"rejected","Broker SL no longer matches the product tick; protection requires review","blocked")
        if live_stop == stored:
            return plan, None
        if (live_stop < stored if size > 0 else live_stop > stored):
            return plan, self.response(plan,"rejected","Broker SL was widened outside the managed plan; the tighter recorded SL is retained for review","blocked")
        if (live_stop >= mark if size > 0 else live_stop <= mark):
            return plan, self.response(plan,"pending","Broker SL is through current mark; waiting for exact order and fill reconciliation","pending")
        self.remember_tighter_stop(plan,live_stop)
        return self.get(plan["user"],plan["id"]), None

    def edit_outcome(self, user, account, symbol, order_id, result, stop_price):
        if result.get("status") != "confirmed" or stop_price is None:
            return
        with self.store.db() as db:
            rows = db.execute(
                "SELECT id,stop_order_id,target_order_id FROM delta_managed_plans WHERE user=? AND account=? AND symbol=? AND status NOT IN ('completed','cancelled','rejected')",
                (user, account, symbol),
            ).fetchall()
            for row in rows:
                if str(row["stop_order_id"]) == str(order_id):
                    db.execute(
                        "UPDATE delta_managed_plans SET stop=? WHERE id=?",
                        (str(stop_price), row["id"]),
                    )
                elif str(row["target_order_id"]) == str(order_id):
                    db.execute(
                        "INSERT INTO delta_plan_level_overrides VALUES(?,?) ON CONFLICT(plan_id) DO UPDATE SET target=excluded.target",
                        (row["id"], str(stop_price)),
                    )

    def parent_outcome(self, user, rid, result):
        with self.store.db() as db:
            row = db.execute(
                "SELECT id FROM delta_managed_plans WHERE user=? AND parent_id=?",
                (user, rid),
            ).fetchone()
        if not row:
            return
        status = (
            "rejected"
            if result["status"] == "rejected"
            else "pending"
            if result["status"] == "pending"
            else "awaiting_entry"
        )
        values = {"status": status, "message": result["message"]}
        if result.get("order_id"):
            values["entry_order_id"] = str(result["order_id"])
        self.update(row["id"], **values)
        if result.get("status") == "confirmed" and result.get("placed_at") is not None:
            self.record_placement(
                row["id"],
                result["placed_at"],
                result.get("placement_time_source", "ack"),
            )

    def close_intent(self, user, account, symbol, data):
        from .service import digest

        with self.store.db() as db:
            rows = db.execute(
                "SELECT id FROM delta_managed_plans WHERE user=? AND account=? AND symbol=? AND status NOT IN ('completed','cancelled','rejected')",
                (user, account, symbol),
            ).fetchall()
            allowed = (
                "request_id",
                "account",
                "symbol",
                "action",
                "price",
                "size",
                "side",
                "position_version",
            )
            payload = {key: data[key] for key in allowed if key in data}
            payload["_ledger_fingerprint"] = digest(data)
            for row in rows:
                db.execute(
                    "INSERT OR IGNORE INTO delta_plan_operations VALUES(?,?,?)",
                    (
                        row["id"],
                        "manual_exit_" + data["request_id"],
                        json.dumps(payload),
                    ),
                )
                db.execute(
                    "UPDATE delta_managed_plans SET status='closing',message='Explicit market close is in progress; automatic new protection and trailing are paused' WHERE id=?",
                    (row["id"],),
                )

    def close_outcome(self, user, rid, result):
        with self.store.db() as db:
            rows = db.execute(
                "SELECT p.id FROM delta_managed_plans p JOIN delta_plan_operations o ON p.id=o.plan_id WHERE p.user=? AND o.kind=?",
                (user, "manual_exit_" + rid),
            ).fetchall()
        for row in rows:
            if result["status"] == "rejected":
                self.update(
                    row["id"],
                    status="placing_protection",
                    message="Explicit market close rejected; reviewed fixed protection will continue. "
                    + result["message"],
                )
            elif result["status"] == "confirmed" and result.get("order_id"):
                self.update(
                    row["id"],
                    status="closing",
                    close_order_id=str(result["order_id"]),
                    message="Explicit market close acknowledged; automatic new protection and trailing are paused",
                )
            else:
                self.update(
                    row["id"],
                    status="pending",
                    message="Explicit market close outcome is unknown; reconciliation required",
                )

    def response(self, plan, status, message, state=None, order_id=None):
        self.update(plan["id"], status=state or plan["status"], message=message)
        result = {
            "status": status,
            "message": message,
            "plan_id": plan["id"],
            "plan_status": state or plan["status"],
        }
        if order_id is not None:
            result["order_id"] = str(order_id)
        return result

    def operations(self, plan):
        with self.store.db() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM delta_plan_operations WHERE plan_id=? ORDER BY rowid",
                    (plan["id"],),
                )
            ]

    def acknowledge_let_run(self, plan, target_id):
        """Commit the policy switch only after the exact target cancel is proven."""
        from .service import Rejected

        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload,target_order_id FROM delta_managed_plans WHERE id=?",
                (plan["id"],),
            ).fetchone()
            payload = json.loads(row["payload"])
            if payload.get("target_mode") == "trend" and row["target_order_id"] is None:
                return
            if str(row["target_order_id"]) != str(target_id):
                raise Rejected("The reviewed target changed; trend conversion requires review")
            payload.update(target_mode="trend", smart_profit_tracking=True)
            db.execute(
                "UPDATE delta_managed_plans SET payload=?,target_order_id=NULL WHERE id=?",
                (json.dumps(payload), plan["id"]),
            )

    def reconcile_let_run_target(self, plan, target_id, reviewed_target_size=None):
        """An accepted DELETE is not proof that the TP stopped executing."""
        from .service import number

        current = self.get(plan["user"], plan["id"])
        entry = json.loads(current["payload"])
        if entry.get("target_mode") == "trend" and current["target_order_id"] is None:
            return None
        if str(current["target_order_id"]) != str(target_id):
            return self.response(current, "rejected", "The reviewed target link changed; conversion requires review", "blocked")
        client, account = self.service.client(plan["user"])
        if account != plan["account"]:
            return self.response(current, "rejected", "Managed account changed; conversion is paused", "blocked")
        # New intents bind the exact quantity reviewed against owned exposure.
        # Older intents retain their original-size check and fail closed if a
        # partial entry lacks that durable quantity proof.
        expected_size = number(reviewed_target_size if reviewed_target_size is not None else entry["size"], True)
        order = client.request("GET", "/v2/orders/" + str(target_id))
        if (
            not isinstance(order, dict)
            or str(order.get("id")) != str(target_id)
            or not self.owned_order(current, order, "target")
            or order.get("stop_order_type") != "take_profit_order"
            or order.get("order_type") != "limit_order"
            or number(order.get("size"), True) != expected_size
            or not self.service.maker_verified(plan["user"], order)
        ):
            return self.response(current, "rejected", "Exact owned target inactivity cannot be proven; conversion is paused", "blocked")
        if order.get("state") not in ("cancelled", "closed"):
            return self.response(current, "pending", "Target cancel is acknowledged; waiting for the exact owned target to become inactive", "pending")
        self.acknowledge_let_run(current, target_id)
        return None

    def apply_operations(self, plan):
        from .service import digest

        for operation in self.operations(plan):
            payload = json.loads(operation["payload"])
            fingerprint = payload.pop("_ledger_fingerprint", None) or digest(payload)
            result = self.store.replay(plan["user"], payload["request_id"], fingerprint)
            if result and result["status"] == "pending":
                return self.response(
                    plan,
                    "pending",
                    "An owned action has an unknown outcome; reconciliation is required before another mutation",
                    "pending",
                )
            if result and result["status"] == "confirmed":
                kind = operation["kind"]
                values = {}
                if kind == "let_run_cancel_target":
                    if str(result.get("order_id")) != str(payload["order_id"]):
                        return self.response(plan, "rejected", "Target cancellation acknowledgement does not match", "blocked")
                    waiting = self.reconcile_let_run_target(plan, payload["order_id"], payload.get("reviewed_target_size"))
                    if waiting is not None:
                        return waiting
                if kind == "market_stop":
                    self.migration_ack(plan, result)
                if kind in ("stop", "target") and result.get("order_id"):
                    # A historical TP creation acknowledgement cannot resurrect
                    # the target link after a proven let-run conversion.
                    if kind != "target" or json.loads(plan["payload"]).get("target_mode") != "trend":
                        values[kind + "_order_id"] = str(result["order_id"])
                elif kind.startswith(("exit_", "manual_exit_")) and result.get(
                    "order_id"
                ):
                    values["close_order_id"] = str(result["order_id"])
                elif kind.startswith("trail_"):
                    self.remember_tighter_stop(plan,payload["price"])
                if values:
                    self.update(plan["id"], **values)
            elif (
                result
                and result["status"] == "rejected"
                and operation["kind"] in ("stop", "target", "market_stop")
            ):
                return self.response(plan, "rejected", result["message"], "blocked")
        return None

    def run(self, plan, kind, payload, next_state):
        from .service import Rejected

        payload = dict(
            payload,
            request_id=str(uuid5(UUID(plan["id"]), kind)),
            account=plan["account"],
            symbol=plan["symbol"],
            managed_plan_id=plan["id"],
        )
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM delta_plan_operations WHERE plan_id=? AND kind=?",
                (plan["id"], kind),
            ).fetchone()
            if row:
                previous = json.loads(row["payload"])
                if kind.startswith("trail_") and previous.get("price") != payload.get(
                    "price"
                ):
                    raise Rejected(
                        "This candle already owns a different trailing decision"
                    )
                payload = previous
            else:
                db.execute(
                    "INSERT INTO delta_plan_operations VALUES(?,?,?)",
                    (plan["id"], kind, json.dumps(payload)),
                )
        try:
            result = self.service.action(plan["user"], payload)
        except Rejected as exc:
            return self.response(
                plan,
                "rejected",
                str(exc),
                "blocked"
                if kind in ("stop", "target", "market_stop") or kind.startswith("exit_")
                else plan["status"],
            )
        if result["status"] == "pending":
            return self.response(plan, "pending", result["message"], "pending")
        if result["status"] == "rejected":
            return self.response(
                plan,
                "rejected",
                result["message"],
                "blocked"
                if kind in ("stop", "target", "market_stop")
                or kind.startswith(("exit_", "resize_"))
                else plan["status"],
            )
        values = {}
        if kind == "let_run_cancel_target":
            if str(result.get("order_id")) != str(payload["order_id"]):
                return self.response(plan, "rejected", "Target cancellation acknowledgement does not match", "blocked")
            waiting = self.reconcile_let_run_target(plan, payload["order_id"], payload.get("reviewed_target_size"))
            if waiting is not None:
                return waiting
        if kind == "market_stop":
            self.migration_ack(plan, result)
        if kind in ("stop", "target") and result.get("order_id"):
            values[kind + "_order_id"] = str(result["order_id"])
        if kind.startswith("exit_") and result.get("order_id"):
            values["close_order_id"] = str(result["order_id"])
        if kind.startswith("trail_"):
            self.remember_tighter_stop(plan,payload["price"])
        if values:
            self.update(plan["id"], **values)
        return self.response(
            plan, "confirmed", result["message"], next_state, result.get("order_id")
        )

    def flat_after_entry(self, plan, fills, complete, filled_quantity):
        """Prove an owned entry-to-flat lifecycle; a flat position alone can lag."""
        from .service import Rejected, fill_timestamp, number

        if not complete or not isinstance(fills, list):
            return False
        try:
            payload = json.loads(plan["payload"])
            direction = Decimal(1) if payload["side"] == "buy" else Decimal(-1)
            rows = {}
            for row in fills:
                nested = row.get("product")
                pid = row.get(
                    "product_id", nested.get("id") if isinstance(nested, dict) else None
                )
                if str(pid) != plan["pid"]:
                    continue
                identity = str(row.get("id", ""))
                if not identity or (identity in rows and rows[identity] != row):
                    return False
                rows[identity] = row
            expected = Decimal(0)
            entered = Decimal(0)
            exited = Decimal(0)
            newer = None
            for row in sorted(
                rows.values(),
                key=lambda row: fill_timestamp(row.get("created_at")),
                reverse=True,
            ):
                stamp = fill_timestamp(row.get("created_at"))
                if newer is not None and stamp >= newer:
                    return False
                newer = stamp
                after = (row.get("meta_data") or {}).get("new_position") or {}
                if (
                    row.get("fill_type") not in ("normal", "liquidation")
                    or number(after.get("size")) != expected
                    or str(after.get("last_fill_uuid")) != str(row["id"])
                ):
                    return False
                quantity = number(row.get("size"), True)
                if quantity != quantity.to_integral_value() or row.get("side") not in (
                    "buy",
                    "sell",
                ):
                    return False
                signed = quantity if row["side"] == "buy" else -quantity
                previous = expected - signed
                if (
                    previous * direction < 0
                    or expected * direction < 0
                    or max(abs(previous), abs(expected)) > filled_quantity
                ):
                    return False
                if signed * direction > 0:
                    if (
                        row.get("fill_type") != "normal"
                        or str(row.get("order_id")) != plan["entry_order_id"]
                    ):
                        return False
                    entered += quantity
                else:
                    exited += quantity
                expected = previous
                if expected == 0:
                    return entered == exited == filled_quantity and entered > 0
            return False
        except (Rejected, KeyError, TypeError, ValueError):
            return False

    def owned_position(self, plan, position, fills, filled_quantity=None):
        from .service import Rejected, fill_timestamp, number

        try:
            payload = json.loads(plan["payload"])
            expected = number(position["size"])
            side = payload["side"]
            entry = number(position["entry_price"], True)
            allowed = (
                number(payload["size"]) if filled_quantity is None else filled_quantity
            )
            if allowed <= 0 or allowed > number(payload["size"]):
                return False
            if expected != (allowed if side == "buy" else -allowed):
                return False
            rows = {}
            for row in fills or []:
                nested = row.get("product")
                pid = row.get(
                    "product_id", nested.get("id") if isinstance(nested, dict) else None
                )
                if str(pid) != plan["pid"]:
                    continue
                identity = str(row.get("id", ""))
                if not identity or (identity in rows and rows[identity] != row):
                    return False
                rows[identity] = row
            weighted = Decimal(0)
            contracts = Decimal(0)
            newer = None
            latest = True
            for row in sorted(
                rows.values(),
                key=lambda row: fill_timestamp(row.get("created_at")),
                reverse=True,
            ):
                stamp = fill_timestamp(row.get("created_at"))
                if newer is not None and stamp >= newer:
                    return False
                newer = stamp
                meta = row.get("meta_data") or {}
                new = meta.get("new_position") or {}
                if (
                    row.get("fill_type") != "normal"
                    or str(row.get("order_id")) != plan["entry_order_id"]
                    or row.get("side") != side
                    or number(new.get("size")) != expected
                    or str(new.get("last_fill_uuid")) != str(row["id"])
                ):
                    return False
                if latest and abs(
                    number(new.get("entry_price"), True) - entry
                ) > Decimal(".00000001"):
                    return False
                latest = False
                quantity = number(row["size"], True)
                if quantity != quantity.to_integral_value():
                    return False
                weighted += number(row["price"], True) * quantity
                contracts += quantity
                expected -= quantity if side == "buy" else -quantity
                if expected == 0:
                    return contracts == abs(number(position["size"])) and abs(
                        weighted / contracts - entry
                    ) <= Decimal(".00000001")
            return False
        except (Rejected, KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def market_stop_valid(order):
        return (
            order.get("order_type") == "market_order"
            and order.get("stop_order_type") == "stop_loss_order"
            and order.get("reduce_only") is True
            and order.get("stop_trigger_method") == "mark_price"
        )

    def owned_order(self, plan, order, kind):
        from .service import number

        payload = json.loads(plan["payload"])
        if str(order.get("product_id")) != plan["pid"]:
            return False
        if kind == "entry":
            return (
                str(order.get("client_order_id")) == UUID(plan["parent_id"]).hex
                and order.get("side") == payload["side"]
                and number(order.get("size")) == number(payload["size"])
            )
        candidates = [
            json.loads(operation["payload"]) for operation in self.operations(plan)
        ]
        return (
            any(
                str(order.get("client_order_id")) == UUID(operation["request_id"]).hex
                for operation in candidates
            )
            and order.get("reduce_only") is True
            and order.get("side") == ("sell" if payload["side"] == "buy" else "buy")
        )

    def manage(self, user, data, protection_only=False):
        from .service import Rejected

        plan = self.get(user, data.get("plan_id") if isinstance(data, dict) else None)
        try:
            with self.lock(user, plan["account"], plan["symbol"]):
                return self._manage(user, data, protection_only)
        except Rejected:
            raise
        except Exception:
            plan = self.get(
                user, data.get("plan_id") if isinstance(data, dict) else None
            )
            return self.response(
                plan,
                "pending",
                "Broker observation or outcome unavailable; no financial mutation will be blindly retried",
                "pending",
            )

    @staticmethod
    def trailing_candles(client, plan, interval):
        """Read public OHLC outside ledger transactions; failed reads retain SL."""
        resolutions = {60:'1m',180:'3m',300:'5m',900:'15m',1800:'30m',3600:'1h',14400:'4h',86400:'1d'}
        observed = time.time()
        resolution = resolutions.get(interval)
        if resolution is None:
            return [], observed
        try:
            bars = client.request(
                "GET", "/v2/history/candles",
                params={"symbol":plan["symbol"], "resolution":resolution,
                        "start":int(observed)-32*interval, "end":int(observed)},
                private=False,
            )
            return bars, observed
        except Exception:
            return [], observed

    def _manage(self, user, data, protection_only=False):
        from .service import (
            Rejected,
            build_accounting,
            digest,
            number,
            position_version,
        )

        if not isinstance(data, dict):
            raise Rejected("Management JSON object required")
        plan = self.get(user, data.get("plan_id"))
        levels = self.levels(plan)
        trend_exit = json.loads(plan["payload"]).get("target_mode") == "trend"
        decision = data.get("decision")
        if decision not in ("sync", "cancel_entry", "trail", "reduce_risk", "exit", "let_run"):
            raise Rejected("Unsupported managed decision")
        if protection_only:
            if decision != "sync":
                raise Rejected(
                    "Background management is limited to reviewed fixed protection"
                )
            stamp = levels["source_time"]
        else:
            stamp = self.source(
                data.get("source_time"),
                levels["interval_seconds"],
                levels["source_time"],
            )
        _, account = self.service.client(user)
        if account != plan["account"]:
            return self.response(
                plan,
                "rejected",
                "Managed account changed; no action submitted",
                "blocked",
            )
        recovering_maker = (
            plan["status"] == "blocked"
            and plan["message"]
            == "Owned protective order no longer satisfies the reviewed plan"
            and decision == "sync"
        )
        recovering_unseen = (
            plan["status"] == "completed"
            and plan["message"]
            == "Owned position is flat and owned sibling exits are no longer active"
            and plan["position_version"] is None
            and plan["entry_price"] is None
            and all(
                plan[field] is None
                for field in ("stop_order_id", "target_order_id", "close_order_id")
            )
            and decision == "sync"
        )
        if plan["status"] in TERMINAL and not (recovering_maker or recovering_unseen):
            return {
                "status": "rejected",
                "message": plan["message"],
                "plan_id": plan["id"],
                "plan_status": plan["status"],
            }
        c, a, p, t, cv, cap, mark, ticker, pos, margined, orders, fills, lev = (
            self.service.snapshot(user, plan["symbol"])
        )
        if a != plan["account"] or str(p["id"]) != plan["pid"]:
            return self.response(
                plan, "rejected", "Managed product/account binding changed", "blocked"
            )
        self.service.reconcile(user, plan["symbol"], c, p["id"])
        pending = self.apply_operations(plan)
        if pending:
            return pending
        plan = self.get(user, plan["id"])
        trend_exit = json.loads(plan["payload"]).get("target_mode") == "trend"
        if plan["status"] == "closing" and not plan["close_order_id"]:
            return self.response(
                plan,
                "pending",
                "Explicit market close intent is still in progress; no new protection submitted",
                "closing",
            )
        adopted = json.loads(plan["payload"]).get("action") == "adopt"
        parent = (
            {"state": "closed", "unfilled_size": 0}
            if adopted
            else (
                c.request("GET", "/v2/orders/" + plan["entry_order_id"])
                if plan["entry_order_id"]
                else c.request(
                    "GET", "/v2/orders/client_order_id/" + UUID(plan["parent_id"]).hex
                )
            )
        )
        if not isinstance(parent, dict) or (
            not adopted and not self.owned_order(plan, parent, "entry")
        ):
            return self.response(
                plan, "rejected", "Entry ownership cannot be proven", "blocked"
            )
        if not adopted and not plan["entry_order_id"]:
            self.update(plan["id"], entry_order_id=str(parent["id"]))
            plan = self.get(user, plan["id"])
        if not adopted and parent.get("created_at") is not None:
            self.record_placement(plan["id"], parent["created_at"])
        size = number(pos.get("size", 0))
        unfilled = number(parent.get("unfilled_size"), False)
        quantity = number(json.loads(plan["payload"])["size"])
        resting = parent.get("state") in ("open", "pending")
        filled_quantity = quantity - unfilled
        if not 0 <= filled_quantity <= quantity:
            return self.response(
                plan, "rejected", "Invalid parent filled quantity", "blocked"
            )
        if resting and filled_quantity == 0:
            if size:
                return self.response(
                    plan,
                    "rejected",
                    "Foreign exposure appeared before owned entry fills",
                    "blocked",
                )
            entry_payload = json.loads(plan["payload"])
            ttl = entry_payload.get("entry_ttl_seconds")
            if (
                ttl is None
                and levels["interval_seconds"] == 60
                and entry_payload.get("entry_mode") != "manual"
            ):
                ttl = 15
            with self.store.db() as db:
                timing = db.execute(
                    "SELECT placed_at FROM delta_plan_timing WHERE plan_id=?",
                    (plan["id"],),
                ).fetchone()
            expired = (
                ttl == 15
                and timing is not None
                and time.time() - timing["placed_at"] >= ttl
            )
            if decision == "cancel_entry" or expired:
                return self.run(
                    plan,
                    "cancel_entry",
                    {
                        "action": "cancel",
                        "order_id": plan["entry_order_id"],
                        "version": digest(parent),
                    },
                    "awaiting_entry",
                )
            return self.response(
                plan,
                "pending",
                "Owned maker entry is resting; each verified fill requires maker stop protection",
                "awaiting_entry",
            )
        if not size:
            if not adopted and filled_quantity > 0:
                fills = self.service.recent_fills(c, a, p["id"], force=True)
                p["_fills_complete"] = isinstance(fills, list)
            if resting and unfilled > 0:
                return self.run(
                    plan,
                    "cancel_entry",
                    {
                        "action": "cancel",
                        "order_id": plan["entry_order_id"],
                        "version": digest(parent),
                    },
                    "cleanup",
                )
            if (
                not adopted
                and filled_quantity > 0
                and not self.flat_after_entry(
                    plan, fills, p["_fills_complete"], filled_quantity
                )
            ):
                if recovering_unseen:
                    return {
                        "status": "pending",
                        "message": "No current owned exposure is proven; completed-plan recovery is waiting for consistent broker evidence",
                        "plan_id": plan["id"],
                        "plan_status": "completed",
                    }
                return self.response(
                    plan,
                    "pending",
                    "Owned entry filled; waiting for consistent position or proven entry-to-flat fill evidence before protection can advance",
                    "pending",
                )
            for field in ("stop_order_id", "target_order_id", "close_order_id"):
                if not plan[field]:
                    continue
                order = c.request("GET", "/v2/orders/" + plan[field])
                if order.get("state") in ("open", "pending"):
                    if not self.owned_order(plan, order, field):
                        return self.response(
                            plan,
                            "rejected",
                            "Sibling ownership cannot be proven",
                            "blocked",
                        )
                    return self.run(
                        plan,
                        "cleanup_" + plan[field],
                        {
                            "action": "cancel",
                            "order_id": plan[field],
                            "version": digest(order),
                        },
                        "cleanup",
                    )
            migration = self.stop_migration(plan)
            if migration:
                old = c.request("GET", "/v2/orders/" + migration["old_id"])
                if old.get("state") in ("open", "pending"):
                    if digest(old) != migration["old_version"] or not self.owned_order(
                        plan, old, "stop"
                    ):
                        return self.response(
                            plan,
                            "rejected",
                            "Original migration stop changed; cleanup requires review",
                            "blocked",
                        )
                    return self.run(
                        plan,
                        "cleanup_migrated_stop",
                        {
                            "action": "cancel",
                            "order_id": migration["old_id"],
                            "version": digest(old),
                        },
                        "cleanup",
                    )
            if adopted:
                for name in ("stop", "target"):
                    legacy = self.replacement(plan, name)
                    if legacy:
                        order = c.request("GET", "/v2/orders/" + legacy["id"])
                        if order.get("state") in ("open", "pending"):
                            if digest(order) != legacy["version"]:
                                return self.response(
                                    plan,
                                    "rejected",
                                    "Reviewed legacy order changed; cleanup requires review",
                                    "blocked",
                                )
                            return self.run(
                                plan,
                                "cleanup_legacy_" + name,
                                {
                                    "action": "cancel",
                                    "order_id": legacy["id"],
                                    "version": digest(order),
                                },
                                "cleanup",
                            )
            return self.response(
                plan,
                "confirmed",
                "Owned entry lifecycle is confirmed flat and owned sibling exits are no longer active",
                "cancelled" if parent.get("state") == "cancelled" else "completed",
            )
        if plan["close_order_id"]:
            close = c.request("GET", "/v2/orders/" + plan["close_order_id"])
            if self.owned_order(plan, close, "close") and close.get("state") in (
                "open",
                "pending",
            ):
                return self.response(
                    plan,
                    "pending",
                    "Owned market close is acknowledged; waiting for fill reconciliation without another close",
                    "closing",
                )
            return self.response(
                plan,
                "rejected",
                "Close outcome or remaining position requires manual review",
                "blocked",
            )
        if (
            parent.get("state") not in ("closed", "cancelled", "open", "pending")
            or filled_quantity == 0
        ):
            return self.response(
                plan, "rejected", "Parent entry fill is not confirmed", "blocked"
            )
        gross = (mark - number(pos["entry_price"], True)) * size * cv
        accounting = build_accounting(
            p, p["_wallet"], pos, mark, gross, fills, p["_fills_complete"]
        )
        if (
            adopted
            and position_version(p["id"], pos)
            != json.loads(plan["payload"])["adopted_position_version"]
        ):
            return self.response(
                plan,
                "rejected",
                "Adopted position changed; explicit review is required",
                "blocked",
            )
        if adopted:
            try:
                marker = self.position_marker(p["id"], pos, fills, p["_fills_complete"])
            except Rejected as exc:
                return self.response(plan, "rejected", str(exc), "blocked")
            if marker != json.loads(plan["payload"])["adopted_fill_marker"]:
                return self.response(
                    plan,
                    "rejected",
                    "Adopted position fill ownership changed; explicit review is required",
                    "blocked",
                )
        if not adopted and (
            not p["_fills_complete"]
            or not self.owned_position(plan, pos, fills, filled_quantity)
        ):
            if recovering_unseen:
                return {
                    "status": "rejected",
                    "message": "Completed-plan recovery cannot prove current exposure belongs to the original entry",
                    "plan_id": plan["id"],
                    "plan_status": "completed",
                }
            return self.response(
                plan,
                "pending",
                "Open-position ownership evidence is unverified; no managed mutation submitted",
                "pending",
            )
        if not adopted:
            self.record_first_fill(plan, fills, p["_fills_complete"])
        current_version = position_version(p["id"], pos)
        self.update(
            plan["id"],
            position_version=current_version,
            entry_price=str(pos["entry_price"]),
        )
        plan = self.get(user, plan["id"])
        if recovering_unseen:
            if (
                parent.get("state") != "closed"
                or unfilled != 0
                or filled_quantity != quantity
            ):
                return self.response(
                    plan,
                    "rejected",
                    "Completed entry is not fully filled; recovery requires review",
                    "blocked",
                )
            return self.response(
                plan,
                "confirmed",
                "Original fully filled entry exposure verified; reviewed fixed protection can continue",
                "placing_protection",
            )
        if not resting and not recovering_maker and decision != "exit":
            plan, stop_sync = self.sync_exact_market_stop(plan,c,size,t,mark)
            if stop_sync is not None:
                return stop_sync
        if decision == "let_run":
            # Do not migrate, resize, create or alter an SL as a side effect of
            # removing a TP. The exact owned market SL must already cover it.
            if not plan["stop_order_id"]:
                return self.response(plan, "rejected", "An acknowledged owned market stop is required before letting the trade run")
            stop_order = c.request("GET", "/v2/orders/" + plan["stop_order_id"])
            if (
                not self.owned_order(plan, stop_order, "stop")
                or not self.market_stop_valid(stop_order)
                or stop_order.get("state") not in ("open", "pending")
                or number(stop_order.get("size"), True) != abs(size)
                or number(stop_order.get("stop_price"), True) != number(plan["stop"], True)
                or (number(stop_order["stop_price"]) >= mark if size > 0 else number(stop_order["stop_price"]) <= mark)
            ):
                return self.response(plan, "rejected", "The exact owned market stop must be live and cover the current exposure")
            if trend_exit:
                return self.response(plan, "confirmed", "Trend exit policy is already active", "active")
            if plan["status"] != "active" or resting or not plan["target_order_id"]:
                return self.response(plan, "rejected", "A fully reconciled active fixed-target plan is required")
            target_order = c.request("GET", "/v2/orders/" + plan["target_order_id"])
            if (
                str(target_order.get("id")) != str(plan["target_order_id"])
                or not self.owned_order(plan, target_order, "target")
                or target_order.get("stop_order_type") != "take_profit_order"
                or target_order.get("order_type") != "limit_order"
                or number(target_order.get("size"), True) != abs(size)
                or not self.service.maker_verified(user, target_order)
            ):
                return self.response(plan, "rejected", "Exact owned maker-target provenance is required; no order was cancelled")
            if target_order.get("state") in ("cancelled", "closed"):
                self.acknowledge_let_run(plan, plan["target_order_id"])
                return self.response(plan, "confirmed", "Owned target is inactive; market stop retained and trend exits enabled", "active")
            if target_order.get("state") not in ("open", "pending"):
                return self.response(plan, "pending", "Target state is unknown; no cancellation submitted")
            return self.run(
                plan,
                "let_run_cancel_target",
                {"action": "cancel", "order_id": plan["target_order_id"], "version": digest(target_order),
                 "reviewed_target_size": int(number(target_order["size"], True))},
                "active",
            )
        if not recovering_maker and decision != "exit":
            migration_result = self.migrate_stop(plan, c, size, current_version)
            if migration_result is not None:
                return migration_result
            plan = self.get(user, plan["id"])
        # Any proven partial fill receives its SL before another entry decision.
        # New fills are rebound only after the complete parent-owned fill chain above.
        if resting and unfilled > 0:
            if not plan["stop_order_id"]:
                return self.run(
                    plan,
                    "stop",
                    {
                        "action": "protect",
                        "stop": plan["stop"],
                        "position_version": current_version,
                    },
                    "partial_fill",
                )
            stop_order = c.request("GET", "/v2/orders/" + plan["stop_order_id"])
            if (
                not self.owned_order(plan, stop_order, "stop")
                or stop_order.get("state") not in ("open", "pending")
                or not self.market_stop_valid(stop_order)
            ):
                return self.response(
                    plan,
                    "rejected",
                    "Owned partial-fill stop is unavailable; review protection immediately",
                    "blocked",
                )
            live_stop = number(stop_order.get("stop_price"), True)
            if number(stop_order.get("size"), True) != abs(size):
                return self.run(
                    plan,
                    "resize_" + current_version,
                    {
                        "action": "edit",
                        "order_id": plan["stop_order_id"],
                        "version": digest(stop_order),
                        "price": str(live_stop),
                        "size": int(abs(size)),
                    },
                    "partial_fill",
                )
            return self.run(
                plan,
                "cancel_entry",
                {
                    "action": "cancel",
                    "order_id": plan["entry_order_id"],
                    "version": digest(parent),
                },
                "placing_protection",
            )
        if recovering_maker:
            if not plan["stop_order_id"]:
                return self.response(plan, "rejected", plan["message"], "blocked")
            observed = c.request("GET", "/v2/orders/" + plan["stop_order_id"])
            if (
                not self.owned_order(plan, observed, "stop")
                or observed.get("state") not in ("open", "pending")
                or not self.service.maker_verified(user, observed)
                or number(observed.get("size"), True) != abs(size)
            ):
                return self.response(plan, "rejected", plan["message"], "blocked")
            return self.response(
                plan,
                "confirmed",
                "Maker stop confirmed from exact acknowledged request provenance; reviewed fixed protection can continue",
                "placing_protection",
            )
        if decision == "cancel_entry":
            raise Rejected("A filled entry cannot be cancelled")
        # Trend exits have no TP acknowledgement. Verify the owned market SL
        # itself before recording peaks or making profit-management decisions.
        trend_stop_ready = False
        if trend_exit and plan["stop_order_id"]:
            acknowledged_stop = c.request("GET", "/v2/orders/" + plan["stop_order_id"])
            trend_stop_ready = (
                self.owned_order(plan, acknowledged_stop, "stop")
                and acknowledged_stop.get("state") in ("open", "pending")
                and self.market_stop_valid(acknowledged_stop)
                and number(acknowledged_stop.get("size"), True) == abs(size)
            )
        # Adoption has no entry order and must never invent first-fill timing.
        # Its separate conservative boundary starts only after this fresh owned
        # exposure and exact live market SL have both been verified.
        if adopted and trend_exit and trend_stop_ready:
            observed_now = time.time()
            asof = p.get("_snapshot_asof")
            stop_value = number(acknowledged_stop["stop_price"],True)
            if (asof is not None and 0 <= observed_now-float(number(asof,True)) <= 10
                    and (stop_value < mark if size > 0 else stop_value > mark)):
                with self.store.db() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO delta_plan_trailing_observations VALUES(?,?,?)",
                        (plan["id"],observed_now,current_version),
                    )
        adaptive_message = None
        if (
            json.loads(plan["payload"]).get("smart_profit_tracking") is True
            and plan["stop_order_id"]
            and (trend_stop_ready if trend_exit else plan["target_order_id"])
            and (decision == "sync" if trend_exit else decision != "exit")
            and accounting["fee_status"] == "verified"
            and accounting["estimated_exit_fee"] is not None
        ):
            from .scalp_policy import adaptive_profit_protection, profit_protection

            trailing_bars, trailing_observed = (self.trailing_candles(c, plan, levels["interval_seconds"])
                                               if trend_exit else (None,None))
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                prior = db.execute(
                    "SELECT peak_inr FROM delta_plan_profit_peaks WHERE plan_id=?",
                    (plan["id"],),
                ).fetchone()
                peak = number(prior[0]) if prior else Decimal(0)
                waived = (
                    accounting.get("scalper_fee_valid_until")
                    and time.time() < accounting["scalper_fee_valid_until"]
                )
                rate = (
                    Decimal(0)
                    if waived
                    else number(p["taker_commission_rate"]) * Decimal("1.18")
                )
                policy_args = (
                    number(pos["entry_price"], True), mark, size, cv, t,
                    number(accounting["position_entry_fees"]), rate, peak,
                )
                if trend_exit:
                    broker_stop = number(acknowledged_stop["stop_price"], True)
                    tightest_stop = (max(number(plan["stop"], True),broker_stop) if size > 0
                                     else min(number(plan["stop"], True),broker_stop))
                    first_fill = db.execute(
                        "SELECT first_fill_at FROM delta_plan_fill_timing WHERE plan_id=?",
                        (plan["id"],),
                    ).fetchone()
                    observation = db.execute(
                        "SELECT observed_at FROM delta_plan_trailing_observations WHERE plan_id=? AND position_version=?",
                        (plan["id"],current_version),
                    ).fetchone() if adopted and not first_fill else None
                    # The pure policy accepts a conservative structure cutoff.
                    # Only the separate observation field uses this fallback;
                    # first_fill_at and its UI timer remain entirely unchanged.
                    structure_after = (first_fill["first_fill_at"] if first_fill else
                                       observation["observed_at"] if observation else None)
                    peak, floor, candidate, crossed, adaptive_message = adaptive_profit_protection(
                        *policy_args, trailing_bars, levels["interval_seconds"],
                        trailing_observed, time.time(), tightest_stop,
                        first_fill_at=structure_after,
                    )
                    if observation is not None:
                        adaptive_message = adaptive_message.replace('post-fill','post-observation')
                else:
                    peak, floor, candidate, crossed = profit_protection(*policy_args)
                db.execute(
                    "INSERT INTO delta_plan_profit_peaks VALUES(?,?) ON CONFLICT(plan_id) DO UPDATE SET peak_inr=excluded.peak_inr",
                    (plan["id"], str(peak)),
                )
            if not trend_exit and floor is None and decision == "sync":
                from decimal import ROUND_FLOOR, ROUND_CEILING

                risk = abs(
                    number(pos["entry_price"], True) - number(levels["stop"], True)
                )
                gain = (mark - number(pos["entry_price"], True)) * (
                    1 if size > 0 else -1
                )
                half = number(pos["entry_price"], True) + (
                    risk / 2 if size < 0 else -risk / 2
                )
                reduced = (half / t).to_integral_value(
                    rounding=ROUND_FLOOR if size > 0 else ROUND_CEILING
                ) * t
                if gain >= max(risk / 3, t * 4) and (
                    reduced > number(plan["stop"])
                    if size > 0
                    else reduced < number(plan["stop"])
                ):
                    decision = "reduce_risk"
                    data = dict(data, stop=str(reduced))
            if crossed:
                decision = "exit"
            elif candidate is not None and (
                candidate > number(plan["stop"])
                if size > 0
                else candidate < number(plan["stop"])
            ):
                decision = "structural_trail" if trend_exit else "trail"
                data = dict(data, stop=str(candidate))
        if decision == "exit":
            return self.run(
                plan,
                "exit_" + str(stamp),
                {"action": "close", "position_version": current_version},
                "closing",
            )
        if decision in ("trail", "reduce_risk", "structural_trail"):
            if (
                accounting["fee_status"] != "verified"
                or accounting["estimated_exit_fee"] is None
            ):
                return self.response(
                    plan,
                    "pending",
                    "Fee-aware trailing is paused until actual entry fee evidence is verified",
                    "pending",
                )
            stop = number(data.get("stop"), True)
            old = number(plan["stop"], True)
            if stop == old:
                return self.response(
                    plan, "confirmed", "Stop is already at the reviewed level", "active"
                )
            if (size > 0 and stop < old) or (size < 0 and stop > old):
                raise Rejected("Managed stop can only tighten")
            coin_amount = abs(size) * cv
            costs_per_coin = (
                number(accounting["position_entry_fees"])
                + number(accounting["estimated_exit_fee"])
            ) / coin_amount
            entry_price = number(pos["entry_price"], True)
            # The browser rounds its nominal two-tick buffer toward entry.
            # Preserve at least one full tick beyond actual fees server-side.
            required = (
                entry_price + costs_per_coin + t
                if size > 0
                else entry_price - costs_per_coin - t
            )
            if decision == "reduce_risk":
                risk = abs(entry_price - number(levels["stop"], True))
                profit = (mark - entry_price) * (1 if size > 0 else -1)
                half = entry_price - risk / 2 if size > 0 else entry_price + risk / 2
                if (
                    risk <= 0
                    or profit < max(risk / 3, t * 4)
                    or (size > 0 and not half - t < stop < entry_price)
                    or (size < 0 and not entry_price < stop < half + t)
                ):
                    raise Rejected(
                        "Early risk reduction requires a favorable move and a half-risk stop below break-even"
                    )
            elif decision != "structural_trail" and ((size > 0 and stop < required) or (size < 0 and stop > required)):
                raise Rejected(
                    "Automatic trail must cover actual entry fees, estimated taker exit fees and at least one full tick of profit"
                )
            if not plan["stop_order_id"]:
                raise Rejected(
                    "Initial market stop must be acknowledged before trailing"
                )
            order = c.request("GET", "/v2/orders/" + plan["stop_order_id"])
            if not self.owned_order(plan, order, "stop") or order.get("state") not in (
                "open",
                "pending",
            ):
                return self.response(
                    plan,
                    "rejected",
                    "Owned market stop is no longer editable",
                    "blocked",
                )
            live_stop = number(order.get("stop_price"), True)
            if (size > 0 and stop < live_stop) or (size < 0 and stop > live_stop):
                raise Rejected("Managed stop cannot loosen the current broker stop")
            return self.run(
                plan,
                "trail_"
                + ("risk_" if decision == "reduce_risk" else "structure_" if decision == "structural_trail" else "")
                + str(stamp)
                + "_"
                + str(stop),
                {
                    "action": "edit",
                    "order_id": plan["stop_order_id"],
                    "version": digest(order),
                    "price": str(stop),
                },
                "active",
            )
        protection_orders = (("stop", "stop"),) if trend_exit else (("stop", "stop"), ("target", "target"))
        for kind, name in protection_orders:
            if not plan[kind + "_order_id"]:
                value = plan["stop"] if kind == "stop" else levels["target"]
                return self.run(
                    plan,
                    kind,
                    {
                        "action": "protect",
                        name: value,
                        "position_version": current_version,
                        **(
                            {
                                "managed_plan_id": plan["id"],
                                "replace_order_id": self.replacement(plan, name)["id"],
                                "replace_order_version": self.replacement(plan, name)[
                                    "version"
                                ],
                            }
                            if self.replacement(plan, name)
                            else {}
                        ),
                    },
                    "placing_protection",
                )
            order = c.request("GET", "/v2/orders/" + plan[kind + "_order_id"])
            if (
                kind == "stop"
                and self.owned_order(plan, order, kind)
                and order.get("state") in ("open", "pending")
                and number(order.get("size"), True) < abs(size)
            ):
                return self.run(
                    plan,
                    "resize_" + current_version,
                    {
                        "action": "edit",
                        "order_id": plan["stop_order_id"],
                        "version": digest(order),
                        "price": str(order["stop_price"]),
                        "size": int(abs(size)),
                    },
                    "placing_protection",
                )
            if (
                not self.owned_order(plan, order, kind)
                or order.get("state") not in ("open", "pending")
                or (
                    not self.market_stop_valid(order)
                    if kind == "stop"
                    else not self.service.maker_verified(user, order)
                )
            ):
                return self.response(
                    plan,
                    "rejected",
                    "Owned protective order no longer satisfies the reviewed plan",
                    "blocked",
                )
            if number(order.get("size"), True) != abs(size):
                return self.response(
                    plan,
                    "rejected",
                    "Maker replacement quantity does not match the adopted position",
                    "blocked",
                )
            legacy = self.replacement(plan, name)
            if legacy:
                old_order = c.request("GET", "/v2/orders/" + legacy["id"])
                if old_order.get("state") in ("open", "pending"):
                    if digest(old_order) != legacy["version"]:
                        return self.response(
                            plan,
                            "rejected",
                            "Reviewed legacy protection changed; it has not been cancelled",
                            "blocked",
                        )
                    return self.run(
                        plan,
                        "replace_legacy_" + name,
                        {
                            "action": "cancel",
                            "order_id": legacy["id"],
                            "version": digest(old_order),
                        },
                        "placing_protection",
                    )
        return self.response(
            plan,
            "confirmed",
            (adaptive_message or "Owned market stop is acknowledged; trend exit and fee-aware trailing are active"
             if trend_exit else
             "Owned market stop and maker target are acknowledged; market execution may slip and is not guaranteed"),
            "active",
        )
