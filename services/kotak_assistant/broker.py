"""Explicit account/mode routing to the existing Kotak and analyzer adapters."""

import hashlib
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta

from .analysis import IST, number

_FEED_PROCESS = uuid.uuid4().hex


def account_key(user):
    # Kotak login uses the configured UCC. Never persist the UCC or token.
    ucc = os.getenv("BROKER_API_KEY", "")
    if not ucc:
        raise ValueError("Kotak account identity unavailable")
    return hashlib.sha256((user + "\0" + ucc).encode()).hexdigest()[:24]


def unwrap(result):
    ok, response, code = result
    if not ok or response.get("status") != "success":
        raise ValueError(response.get("message", "Broker data unavailable"))
    return response.get("data", response)


def submission_response(http_status, raw, orderid=None):
    """Preserve Kotak's rejection evidence without treating a timeout as rejection."""
    if orderid:
        return {"state": "accepted", "orderid": str(orderid)}
    raw = raw if isinstance(raw, dict) else {}
    definitive = raw.get("stat") == "Not_Ok" and (http_status is None or http_status < 500)
    error = next(
        (
            raw[k].strip()
            for k in ("errMsg", "emsg", "error", "message")
            if isinstance(raw.get(k), str) and raw[k].strip()
        ),
        "",
    )
    code = raw.get("stCode")
    evidence = []
    if http_status is not None:
        evidence.append(f"HTTP {http_status}")
    if code is not None:
        evidence.append(f"code {code}")
    message = "Kotak rejected order" if definitive else "Broker submission outcome unknown"
    if error:
        message += f": {error}"
    if evidence:
        message += f" ({' · '.join(evidence)})"
    if definitive and str(code) == "100008":
        message += (
            ". Connection IP is not whitelisted for orders. Check Kotak Trade API > Add IP, "
            "then reconnect from the registered static IP."
        )
    elif definitive and str(code) == "1037":
        message += (
            ". Session was created from a different IP. Reconnect from the registered static IP."
        )
    return {
        "state": "rejected" if definitive else "unknown",
        "message": message,
        "http_status": http_status,
        "broker_code": code,
        "broker_error": error,
    }


class Gateway:
    def __init__(self, user, mode):
        if mode not in ("live", "analyze"):
            raise ValueError("Invalid execution mode")
        self.user = user
        self.mode = mode
        self.account = account_key(user)
        self.scope = f"{user}:{self.account}:{mode}"
        self._cache = {}
        self._flights = {}
        self._lock = threading.RLock()
        self._ticks = {}
        self._watched = set()
        self._ws = None
        self._setup_events = deque(maxlen=10000)
        self._setup_sequence = 0
        self._setup_epoch = uuid.uuid4().hex
        self._setup_connection = f"rest:{_FEED_PROCESS}:{self.account}"
        self._setup_dropped = 0

    def credentials(self):
        from database.auth_db import get_api_key_for_tradingview, get_auth_token_broker

        key = get_api_key_for_tradingview(self.user)
        if not key:
            raise ValueError("Generate an OpenAlgo API key first")
        token, broker = get_auth_token_broker(key)
        if broker != "kotak" or not token or account_key(self.user) != self.account:
            raise ValueError("Kotak session expired or account changed")
        return key, token

    def cached(self, key, ttl, loader):
        # I/O serializes only identical reads. A cold history request cannot
        # hold the live tick lock or delay protective-stop/exit quote reads.
        with self._lock:
            item = self._cache.get(key)
            if item and time.time() - item[0] < ttl:
                return item[1]
            flight = self._flights.setdefault(key, threading.Lock())
        with flight:
            with self._lock:
                item = self._cache.get(key)
                if item and time.time() - item[0] < ttl:
                    return item[1]
            value = loader()
            with self._lock:
                if len(self._cache) > 256:
                    self._cache = {k: v for k, v in self._cache.items() if time.time() - v[0] < 120}
                self._cache[key] = (time.time(), value)
                if len(self._flights) > 512:
                    for old, gate in list(self._flights.items()):
                        if old not in self._cache and gate.acquire(blocking=False):
                            gate.release()
                            self._flights.pop(old, None)
            return value

    def metadata(self, symbol, exchange):
        from database.qty_freeze_db import get_freeze_qty_for_option
        from database.token_db import get_symbol_info

        info = get_symbol_info(symbol, exchange)
        contract = re.fullmatch(r"(NIFTY|BANKNIFTY|SENSEX)\d{2}[A-Z]{3}\d{2}\d+(CE|PE)", symbol)
        if not info or info.instrumenttype not in ("CE", "PE") or not contract:
            raise ValueError("Unsupported option contract")
        underlying = contract.group(1)
        if exchange != ("BFO" if underlying == "SENSEX" else "NFO"):
            raise ValueError("Contract exchange mismatch")
        expiry = None
        for fmt in ("%d-%b-%y", "%d%b%y", "%d-%b-%Y", "%Y-%m-%d"):
            try:
                expiry = datetime.strptime(info.expiry.upper(), fmt).date().isoformat()
                break
            except (ValueError, AttributeError):
                pass
        if not expiry:
            raise ValueError("Expiry metadata unavailable")
        lot = number(info.lotsize)
        tick = number(info.tick_size)
        freeze = int(get_freeze_qty_for_option(symbol, exchange) or 0)
        if lot <= 0 or int(lot) != lot or tick <= 0 or freeze <= 0:
            raise ValueError("Lot/tick/freeze metadata unavailable")
        return {
            "lot": int(lot),
            "tick": tick,
            "freeze": (freeze // int(lot)) * int(lot),
            "underlying": underlying,
            "expiry": expiry,
        }

    def session_open(self, exchange, cutoff):
        from database.market_calendar_db import get_effective_session_window

        now = datetime.now(IST)
        session = get_effective_session_window(now.date(), exchange)
        return bool(
            session
            and session["start_ms"] <= now.timestamp() * 1000 < session["end_ms"]
            and now.strftime("%H:%M") < cutoff
        )

    def other_controller(self, symbol, exchange, product):
        from database.scalping_db import get_active_sl_states

        scalping_owned = any(
            s.get("symbol") == symbol
            and s.get("exchange") == exchange
            and s.get("product") == product
            for s in get_active_sl_states(mode=self.mode)
        )
        if scalping_owned:
            return True
        # Native Neo desk and the strategy runner also own durable broker legs.
        # Never let the new desk acquire a position while either still manages it.
        from sqlalchemy import inspect

        from database import strategy_module_db as sm

        if not inspect(sm.engine).has_table("sm_strategy_run"):
            return False
        return (
            sm.db_session.query(sm.SmStrategyOrder.id)
            .join(sm.SmStrategyRun, sm.SmStrategyRun.id == sm.SmStrategyOrder.run_id)
            .filter(
                sm.SmStrategyRun.stopped_at.is_(None),
                sm.SmStrategyRun.broker == "kotak",
                sm.SmStrategyRun.mode == self.mode,
                sm.SmStrategyOrder.symbol == symbol,
                sm.SmStrategyOrder.exchange == exchange,
                sm.SmStrategyOrder.product == product,
            )
            .first()
            is not None
        )

    def _tick(self, event):
        if not isinstance(event, dict):
            return
        symbol, exchange = event.get("symbol"), event.get("exchange")
        data = event.get("data") or {}
        if (symbol, exchange) not in self._watched or not isinstance(data, dict):
            return
        ltp = data.get("ltp", data.get("last_price"))
        if not ltp:
            return
        received = time.time()
        # Exchange timestamps, where supplied, are stronger evidence than a
        # fresh HTTP receipt. An old last trade must not arm a new setup.
        observed = received
        stamp = data.get("timestamp", data.get("exchange_timestamp"))
        if stamp not in (None, ""):
            try:
                observed = float(stamp)
                if observed > 1e12:
                    observed /= 1000
            except (ValueError, TypeError):
                try:
                    observed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError):
                    return
            if not -3 <= received - observed <= 10:
                return
        q = {
            **data,
            "ltp": ltp,
            "bid": data.get("bid", data.get("bid_price")),
            "ask": data.get("ask", data.get("ask_price")),
            "time": received,
            "observed_time": observed,
            "source": "Live feed",
        }
        depth = data.get("depth") or {}
        if not q["bid"] and depth.get("buy"):
            q["bid"] = depth["buy"][0].get("price")
        if not q["ask"] and depth.get("sell"):
            q["ask"] = depth["sell"][0].get("price")
        if exchange not in ("NSE_INDEX", "BSE_INDEX") and (not q["bid"] or not q["ask"]):
            return  # Never renew two-sided quote age from an LTP-only tick.
        with self._lock:
            self._ticks[(symbol, exchange)] = q
            if exchange in ("NSE_INDEX", "BSE_INDEX"):
                self._setup_sequence += 1
                if len(self._setup_events) == self._setup_events.maxlen:
                    self._setup_dropped += 1
                self._setup_events.append(
                    {
                        "id": f"{self._setup_epoch}:{self._setup_sequence:012d}",
                        "symbol": symbol,
                        "exchange": exchange,
                        "time": observed,
                        "received": received,
                        "price": float(ltp),
                        "source": "Live feed",
                        "time_basis": "exchange" if stamp not in (None, "") else "receipt",
                        "connection": getattr(self, "_setup_connection", self._setup_epoch),
                    }
                )

    def drain_setup_events(self, symbol, exchange):
        """Copy all observed crossings; never do DB/network work in this lock."""
        with self._lock:
            events = [
                e for e in self._setup_events if (e["symbol"], e["exchange"]) == (symbol, exchange)
            ]
            remaining = [
                e for e in self._setup_events if (e["symbol"], e["exchange"]) != (symbol, exchange)
            ]
            self._setup_events.clear()
            self._setup_events.extend(remaining)
            dropped, self._setup_dropped = self._setup_dropped, 0
            return {
                "events": events,
                "dropped": dropped,
                "connection": getattr(self, "_setup_connection", self._setup_epoch),
            }

    def restore_setup_events(self, events):
        with self._lock:
            for event in reversed(events):
                if len(self._setup_events) == self._setup_events.maxlen:
                    self._setup_dropped += 1
                self._setup_events.appendleft(event)

    def watch(self, symbol, exchange):
        if (symbol, exchange) in self._watched and getattr(self._ws, "alive", False):
            return
        key, _ = self.credentials()
        try:
            from services.websocket_client import get_websocket_client

            ws = get_websocket_client(key)
            if ws is not self._ws:
                if callable(getattr(self._ws, "unregister_callback", None)):
                    self._ws.unregister_callback("market_data", self._tick)
                self._ws = ws
                self._watched = set()
                with self._lock:
                    self._setup_epoch = uuid.uuid4().hex
                    # Live and Paper gateways consume the same actual index
                    # connection. A mode switch is not a feed interruption.
                    self._setup_connection = f"ws:{_FEED_PROCESS}:{id(ws)}"
                    self._ticks = {}
                    pending = getattr(self, "_setup_events", None)
                    if pending is not None:
                        self._setup_dropped += len(pending)
                        pending.clear()
                ws.register_callback("market_data", self._tick)
            r = ws.subscribe(
                [{"symbol": symbol, "exchange": exchange}],
                mode="LTP" if exchange in ("NSE_INDEX", "BSE_INDEX") else "Depth",
            )
            if r.get("status") == "success":
                self._watched.add((symbol, exchange))
        except Exception:
            pass  # REST fallback remains age-labelled.

    def quote(self, symbol, exchange):
        self.watch(symbol, exchange)
        with self._lock:
            live = self._ticks.get((symbol, exchange))
        if (
            live
            and time.time() - live["time"] <= 3
            and time.time() - live.get("observed_time", live["time"]) <= 5
        ):
            return dict(live)

        def load():
            from services.quotes_service import get_quotes_with_auth

            _, token = self.credentials()
            q = unwrap(get_quotes_with_auth(token, None, "kotak", symbol, exchange))
            if not isinstance(q, dict) or number(q.get("ltp", 0)) <= 0:
                raise ValueError("Quote unavailable")
            return {**q, "time": time.time(), "source": "Broker snapshot"}

        return self.cached(("quote", symbol, exchange), 2, load)

    def tracking_metadata(self, symbol, exchange):
        from database.token_db import get_symbol_info

        info = get_symbol_info(symbol, exchange)
        if not info:
            return {}
        return {
            k: value
            for k, value in {
                "lot": int(info.lotsize or 0),
                "tick": float(info.tick_size or 0),
            }.items()
            if value > 0
        }

    def books(self, include_cash=True):
        key, token = self.credentials()
        if self.mode == "analyze":
            from services import sandbox_service as sb

            data = {"apikey": key}
            orders = unwrap(sb.sandbox_get_orderbook(key, data))
            positions = unwrap(sb.sandbox_get_positions(key, data))
            fills = unwrap(sb.sandbox_get_tradebook(key, data))
            cash = unwrap(sb.sandbox_get_funds(key, data)) if include_cash else None
            orders = orders["orders"] if isinstance(orders, dict) else orders
            for f in fills:
                f["tradeid"] = f.get("tradeid", f.get("trade_id"))
                f["average_price"] = f.get("average_price", f.get("price"))
            # Sandbox persists strategy as the correlation field.
            orders = [{**o, "order_tag": o.get("strategy", "")} for o in orders]
        else:
            from broker.kotak.api import order_api as api
            from broker.kotak.mapping import order_data as mapping

            def checked(raw):
                # Some Kotak report endpoints return lowercase ok with stCode
                # 200. Canonicalize only that explicit, structurally valid success.
                if (
                    isinstance(raw, dict)
                    and raw.get("stat") == "ok"
                    and raw.get("stCode") == 200
                    and isinstance(raw.get("data"), list)
                    and not raw.get("error")
                    and not raw.get("errMsg")
                ):
                    raw = {**raw, "stat": "Ok"}
                # Kotak documents 5203 as an empty report, not a transport or
                # authentication failure. All other failed/malformed reads stay blocked.
                if (
                    isinstance(raw, dict)
                    and raw.get("stat") == "Not_Ok"
                    and raw.get("stCode") == 5203
                    and str(raw.get("errMsg", "")).strip().casefold() == "no data"
                    and str(raw.get("desc", "")).strip().casefold() == "data not found"
                    and raw.get("data") in (None, [])
                    and not raw.get("error")
                ):
                    return {"stat": "Ok", "data": []}
                if (
                    not isinstance(raw, dict)
                    or raw.get("stat") != "Ok"
                    or not isinstance(raw.get("data"), list)
                ):
                    raise ValueError("Kotak book read failed; account state is unknown")
                return raw

            raw_orders = checked(api.get_order_book(token))
            raw_positions = checked(api.get_positions(token))
            raw_fills = checked(api.get_trade_book(token))
            mapped = mapping.map_order_data(raw_orders)
            orders = mapping.transform_order_data(mapped)
            for o, raw in zip(orders, mapped, strict=False):
                o["action"] = {"B": "BUY", "S": "SELL"}.get(o["action"], o["action"])
                if raw.get("fldQty") is not None:
                    o["filled_quantity"] = int(raw["fldQty"])
                o["message"] = raw.get("rejRsn", raw.get("rmk", ""))
            positions = mapping.transform_positions_data(mapping.map_position_data(raw_positions))
            fills = mapping.transform_tradebook_data(mapping.map_trade_data(raw_fills))

            def read_cash():
                from services.funds_service import get_funds_with_auth

                return unwrap(get_funds_with_auth(token, "kotak"))

            cash = self.cached("funds", 5, read_cash) if include_cash else None
        if not all(isinstance(v, list) for v in (orders, positions, fills)) or (
            include_cash and (not isinstance(cash, dict) or cash.get("availablecash") is None)
        ):
            raise ValueError("Incomplete account snapshot")
        return {
            "orders": orders,
            "positions": positions,
            "fills": fills,
            **({"cash": number(cash["availablecash"])} if include_cash else {}),
            "time": time.time(),
        }

    def stop_limit(self, symbol, exchange, trigger):
        from broker.kotak.mapping.transform_data import _slm_protected_price

        return _slm_protected_price(symbol, exchange, "SELL", trigger)

    def submit(self, data):
        key, token = self.credentials()
        if data["action"] == "BUY":
            from database.settings_db import get_analyze_mode

            if ("analyze" if get_analyze_mode() else "live") != self.mode:
                return {
                    "state": "rejected",
                    "message": "Execution mode changed before entry submission",
                }
        if self.mode == "analyze":
            from services.sandbox_service import sandbox_place_order

            ok, r, code = sandbox_place_order(
                {**data, "strategy": data["tag"]}, key, {"apikey": key}
            )
            return {
                "state": "accepted" if ok and r.get("orderid") else "rejected",
                "orderid": r.get("orderid"),
                "message": r.get("message", ""),
            }
        from broker.kotak.api.order_api import place_order_api

        response, r, oid = place_order_api({**data, "_kotak_assistant_tag": data["tag"]}, token)
        return submission_response(response.status_code if response is not None else None, r, oid)

    def cancel(self, oid):
        key, token = self.credentials()
        if self.mode == "analyze":
            from services.sandbox_service import sandbox_cancel_order

            ok, r, code = sandbox_cancel_order({"orderid": oid}, key, {"apikey": key})
        else:
            from broker.kotak.api.order_api import cancel_order

            r, code = cancel_order(oid, token)
            ok = r.get("status") == "success"
        return {
            "state": "accepted" if ok else "rejected" if code < 500 else "unknown",
            "message": r.get("message", ""),
        }

    def history(self, symbol, exchange, interval):
        def load():
            from services.history_service import get_history

            _, token = self.credentials()
            now = datetime.now(IST)
            rows = unwrap(
                get_history(
                    symbol,
                    exchange,
                    interval,
                    (now - timedelta(days=10)).date().isoformat(),
                    now.date().isoformat(),
                    auth_token=token,
                    broker="kotak",
                    background=True,
                )
            )
            return rows

        return self.cached(
            ("history", symbol, exchange, interval, int(time.time() // 60)), 60, load
        )

    def history_range(self, symbol, exchange, interval, start, end):
        """Read actual broker history, without upsampling missing resolutions."""
        first, last = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
        if first > last or (last - first).days > 40:
            raise ValueError("Choose a historical range of at most 40 days")

        def load():
            from services.history_service import get_history

            _, token = self.credentials()
            return unwrap(
                get_history(
                    symbol,
                    exchange,
                    interval,
                    start,
                    end,
                    auth_token=token,
                    broker="kotak",
                    background=True,
                )
            )

        return self.cached(("setup_history", symbol, exchange, interval, start, end), 300, load)

    def ladder(self, underlying, expiry, count):
        from services.option_chain_service import get_option_chain

        key, _ = self.credentials()
        exchange = "BSE_INDEX" if underlying == "SENSEX" else "NSE_INDEX"
        return self.cached(
            ("chain", underlying, expiry, count),
            5,
            lambda: unwrap(
                get_option_chain(underlying, exchange, expiry, count, key, with_quotes=True)
            ),
        )
