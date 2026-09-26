"""Connection-scoped MCX candles observed on Kotak's live Quote stream.

The broker does not offer historical MCX bars through its history API. These
rows are observations, not reconstructed exchange history: an interrupted
subscription, missing native trade time, volume reset or missing minute leaves
the affected interval unavailable for a trading signal.
"""

from __future__ import annotations

import atexit
import math
import queue
import re
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    select,
    text,
)

from database.engine_factory import create_db_engine
from utils import real_threading as _real_threading
from utils.logging import get_logger

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
metadata = MetaData()
states = Table(
    "kotak_mcx_stream_state", metadata,
    Column("connection_id", String(36), primary_key=True),
    Column("symbol", String(90), primary_key=True),
    Column("last_trade_at", Integer),
    Column("last_arrival_at", Integer),
    Column("last_volume", Float),
    Column("coverage_from", Integer),
    Column("last_error", String(80)),
)
bars = Table(
    "kotak_mcx_candle_1m", metadata,
    Column("connection_id", String(36), primary_key=True),
    Column("symbol", String(90), primary_key=True),
    Column("minute_start", Integer, primary_key=True),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=False),
    Column("first_trade_at", Integer, nullable=False),
    Column("last_trade_at", Integer, nullable=False),
    Column("first_arrival_at", Integer, nullable=False),
    Column("last_arrival_at", Integer, nullable=False),
    Column("complete", Boolean, nullable=False, default=False),
    Column("quality", String(32), nullable=False),
)


def _epoch(value):
    if isinstance(value, datetime):
        return int(value.timestamp()) if value.tzinfo else None
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return int(value / 1000 if value > 1e12 else value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(parsed.timestamp()) if parsed.tzinfo else None
        except ValueError:
            try:
                return int(datetime.strptime(value, "%d/%m/%Y %H:%M:%S")
                           .replace(tzinfo=IST).timestamp())
            except ValueError:
                pass
            try:
                return _epoch(float(value))
            except ValueError:
                return None
    return None


def _minute(epoch):
    return epoch - epoch % 60


def _date_bounds(start_date, end_date):
    first = datetime.fromisoformat(str(start_date)).replace(tzinfo=IST)
    last = datetime.fromisoformat(str(end_date)).replace(tzinfo=IST) + timedelta(days=1)
    return int(first.timestamp()), int(last.timestamp())


class McxCandleStore:
    """Persist stream observations with one short database connection per call."""

    def __init__(self, database_url=None):
        self.engine = create_db_engine(database_url)
        metadata.create_all(self.engine, checkfirst=True)
        self._lock = threading.Lock()
        self._active_keys: set[tuple[str, str]] = set()

    def _problem(self, connection_id, symbol, reason):
        if not connection_id or not symbol:
            return
        if reason == "Data unavailable":
            self._active_keys.discard((connection_id, symbol))
        with self.engine.begin() as conn:
            row = conn.execute(select(states).where(and_(
                states.c.connection_id == connection_id, states.c.symbol == symbol,
            ))).mappings().first()
            if row:
                conn.execute(states.update().where(and_(
                    states.c.connection_id == connection_id, states.c.symbol == symbol,
                )).values(last_error=reason))
            else:
                conn.execute(states.insert().values(
                    connection_id=connection_id, symbol=symbol, last_error=reason,
                ))

    def mark_interrupted(self, connection_id: str, symbol: str):
        """A reconnect requires a new complete minute before bars can be used."""
        with self._lock:
            self._active_keys.discard((connection_id, symbol))
            self._problem(connection_id, symbol, "Collecting history")

    def ingest(self, connection_id: str, packet: dict, arrived_at=None) -> bool:
        if not connection_id or not isinstance(packet, dict) or packet.get("exchange") != "MCX":
            return False
        symbol = str(packet.get("symbol") or "")
        data = packet.get("data") if isinstance(packet.get("data"), dict) else {}
        native = _epoch(data.get("ltt"))
        arrival = _epoch(arrived_at) or _epoch(data.get("timestamp")) or int(datetime.now(IST).timestamp())
        try:
            price = float(data.get("ltp"))
            cumulative = float(data.get("volume"))
        except (TypeError, ValueError):
            price = cumulative = math.nan
        if (packet.get("mode") != 2 or not symbol or native is None
                or data.get("volume_fresh") is not True or not math.isfinite(price)
                or price <= 0 or not math.isfinite(cumulative) or cumulative < 0
                or native > arrival + 2 or arrival - native > 30):
            self._problem(connection_id, symbol, "Data unavailable")
            return False

        key = (connection_id, symbol)
        minute = _minute(native)
        with self._lock, self.engine.begin() as conn:
            row = conn.execute(select(states).where(and_(
                states.c.connection_id == connection_id, states.c.symbol == symbol,
            ))).mappings().first()
            if row is None:
                conn.execute(states.insert().values(
                    connection_id=connection_id, symbol=symbol,
                    last_trade_at=native, last_arrival_at=arrival,
                    last_volume=cumulative, coverage_from=minute + 60,
                    last_error="Collecting history",
                ))
                self._active_keys.add(key)
                return True
            if key not in self._active_keys or row["last_trade_at"] is None:
                conn.execute(states.update().where(and_(
                    states.c.connection_id == connection_id, states.c.symbol == symbol,
                )).values(last_trade_at=native, last_arrival_at=arrival,
                         last_volume=cumulative, coverage_from=minute + 60,
                         last_error="Collecting history"))
                self._active_keys.add(key)
                return True
            prior = row["last_trade_at"]
            if native < prior or (native == prior and cumulative <= row["last_volume"]):
                return False
            previous_minute = _minute(prior)
            reset = cumulative < row["last_volume"]
            gap = native - prior > 60 or minute > previous_minute + 60
            if reset or gap:
                conn.execute(bars.update().where(and_(
                    bars.c.connection_id == connection_id, bars.c.symbol == symbol,
                    bars.c.minute_start == previous_minute,
                )).values(quality="invalid", complete=False))
                conn.execute(states.update().where(and_(
                    states.c.connection_id == connection_id, states.c.symbol == symbol,
                )).values(last_trade_at=native, last_arrival_at=arrival,
                         last_volume=cumulative, coverage_from=minute + 60,
                         last_error="Collecting history"))
                return True

            if minute > previous_minute:
                conn.execute(bars.update().where(and_(
                    bars.c.connection_id == connection_id, bars.c.symbol == symbol,
                    bars.c.minute_start == previous_minute,
                    bars.c.quality == "forming",
                )).values(quality="complete", complete=True))
            if minute >= row["coverage_from"]:
                delta = cumulative - row["last_volume"]
                existing = conn.execute(select(bars).where(and_(
                    bars.c.connection_id == connection_id, bars.c.symbol == symbol,
                    bars.c.minute_start == minute,
                ))).mappings().first()
                if existing:
                    conn.execute(bars.update().where(and_(
                        bars.c.connection_id == connection_id, bars.c.symbol == symbol,
                        bars.c.minute_start == minute,
                    )).values(high=max(existing["high"], price), low=min(existing["low"], price),
                             close=price, volume=existing["volume"] + delta,
                             last_trade_at=native, last_arrival_at=arrival))
                else:
                    conn.execute(bars.insert().values(
                        connection_id=connection_id, symbol=symbol, minute_start=minute,
                        open=price, high=price, low=price, close=price, volume=delta,
                        first_trade_at=native, last_trade_at=native,
                        first_arrival_at=arrival, last_arrival_at=arrival,
                        complete=False, quality="forming",
                    ))
            conn.execute(states.update().where(and_(
                states.c.connection_id == connection_id, states.c.symbol == symbol,
            )).values(last_trade_at=native, last_arrival_at=arrival,
                     last_volume=cumulative, last_error="Collecting history"))
            return True

    def history(self, connection_id, symbol, interval, start_date, end_date, now=None):
        """Return only completed, contiguous observed candles for this contract."""
        if interval not in ("1m", "5m", "15m"):
            return {"status": "error", "readiness": "Data unavailable", "data": [],
                    "message": "Kotak MCX stream supports completed 1m, 5m and 15m only"}
        try:
            start, end = _date_bounds(start_date, end_date)
        except (ValueError, TypeError):
            return {"status": "error", "readiness": "Data unavailable", "data": [],
                    "message": "A valid date range is required"}
        now_epoch = _epoch(now) or int(datetime.now(IST).timestamp())
        with self.engine.connect() as conn:
            state = conn.execute(select(states).where(and_(
                states.c.connection_id == connection_id, states.c.symbol == symbol,
            ))).mappings().first()
            if state is None or state["last_trade_at"] is None:
                readiness = state["last_error"] if state else "Collecting history"
                return {"status": "error", "readiness": readiness, "data": [],
                        "message": readiness}
            if state["last_error"] == "Data unavailable":
                return {"status": "error", "readiness": "Data unavailable", "data": [],
                        "message": "Kotak MCX packet lacked trustworthy trade evidence"}
            if (connection_id, symbol) not in self._active_keys:
                return {"status": "error", "readiness": "Collecting history", "data": [],
                        "message": "Feed restarted; collecting fresh contract history"}
            if now_epoch - state["last_trade_at"] > 90:
                return {"status": "error", "readiness": "Data unavailable", "data": [],
                        "message": "Kotak MCX stream is stale"}
            rows = conn.execute(select(bars).where(and_(
                bars.c.connection_id == connection_id, bars.c.symbol == symbol,
                bars.c.minute_start >= max(start, state["coverage_from"]),
                bars.c.minute_start < end,
                bars.c.minute_start + 60 <= now_epoch,
                bars.c.complete.is_(True), bars.c.quality == "complete",
            )).order_by(bars.c.minute_start)).mappings().all()

        width = {"1m": 1, "5m": 5, "15m": 15}[interval]
        groups: dict[int, list] = {}
        for row in rows:
            bucket = row["minute_start"] - row["minute_start"] % (width * 60)
            groups.setdefault(bucket, []).append(row)
        result = []
        for bucket, group in sorted(groups.items()):
            if (len(group) != width or group[0]["minute_start"] != bucket
                    or any(item["minute_start"] != bucket + index * 60
                           for index, item in enumerate(group))
                    or bucket + width * 60 > now_epoch):
                continue
            result.append({"timestamp": bucket, "open": group[0]["open"],
                           "high": max(item["high"] for item in group),
                           "low": min(item["low"] for item in group),
                           "close": group[-1]["close"],
                           "volume": sum(item["volume"] for item in group), "oi": None})
        readiness = "Ready" if result else "Collecting history"
        return {"status": "success" if result else "error", "readiness": readiness,
                "data": result, "message": readiness, "source": "kotak_live_stream",
                "connection_id": connection_id, "symbol": symbol,
                "latest_native_trade_at": state["last_trade_at"],
                "latest_arrival_at": state["last_arrival_at"]}


def is_kotak_api_key(api_key: str) -> bool:
    """Use the API key's pinned broker, not the browser's selected session."""
    try:
        from database import auth_db

        owner = auth_db.verify_api_key(api_key)
        if not owner:
            return False
        with auth_db.engine.connect() as conn:
            broker = conn.execute(text(
                "SELECT bc.broker FROM api_keys ak JOIN broker_connections bc "
                "ON ak.broker_connection_id = bc.id "
                "WHERE ak.user_id = :owner AND bc.user_id = :owner"
            ), {"owner": owner}).scalar_one_or_none()
        return str(broker or "").lower() == "kotak"
    except Exception:
        logger.exception("Could not verify the broker assigned to the API key")
        return False


def connection_id_for_api_key(api_key: str) -> str | None:
    """Return the verified API key's durable broker pin, if present."""
    try:
        from database import auth_db

        owner = auth_db.verify_api_key(api_key)
        if not owner:
            return None
        with auth_db.engine.connect() as conn:
            return conn.execute(text(
                "SELECT broker_connection_id FROM api_keys WHERE user_id = :owner"
            ), {"owner": owner}).scalar_one_or_none()
    except Exception:
        logger.exception("Could not resolve API key broker connection")
        return None


def _verified_connection(api_key: str, connection_id: str) -> bool:
    try:
        from database import auth_db

        owner = auth_db.verify_api_key(api_key)
        if not owner or not connection_id:
            return False
        with auth_db.engine.connect() as conn:
            row = conn.execute(text(
                "SELECT bc.broker, bc.status, bc.is_revoked FROM api_keys ak "
                "JOIN broker_connections bc ON ak.broker_connection_id = bc.id "
                "WHERE ak.user_id = :owner AND bc.user_id = :owner AND bc.id = :connection_id"
            ), {"owner": owner, "connection_id": connection_id}).mappings().first()
        return bool(row and str(row["broker"]).lower() == "kotak"
                    and row["status"] in {"connected", "authenticated"}
                    and not row["is_revoked"])
    except Exception:
        logger.exception("Could not verify pinned Kotak connection")
        return False


_FUTURE_NAME = re.compile(r"^(.+?)\d{2}[A-Z]{3}\d{2}FUT$")


def _is_current_future(symbol: str) -> bool:
    match = _FUTURE_NAME.fullmatch(str(symbol or "").upper())
    if not match:
        return False
    from services.option_symbol_service import find_near_month_futures

    current = find_near_month_futures(match.group(1), "MCX")
    return bool(current and current["symbol"] == symbol)


class KotakMcxStreamCollector:
    """One bounded Quote subscription collector for one pinned connection."""

    MAX_QUEUE = 4096
    MAX_SYMBOLS = 16

    def __init__(
        self, connection_id, api_key, store: McxCandleStore, *, ws_factory=None,
        connection_check=None, current_contract=None, start_worker=True,
    ):
        self.connection_id = connection_id
        self.api_key = api_key
        self.store = store
        self._ws_factory = ws_factory
        self._connection_check = connection_check or _verified_connection
        self._current_contract = current_contract or _is_current_future
        self._ws = None
        self._symbols: set[str] = set()
        self._queue = _real_threading.Queue(maxsize=self.MAX_QUEUE)
        self._overflow = False
        self._running = True
        self._thread = None
        self._lock = threading.Lock()
        if start_worker:
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="kotak-mcx-candles")
            self._thread.start()

    def _client(self):
        if self._ws_factory is not None:
            return self._ws_factory(self.api_key)
        from services.websocket_client import get_websocket_client

        return get_websocket_client(self.api_key)

    def ensure(self, symbol: str) -> str:
        if not self._connection_check(self.api_key, self.connection_id):
            return "Risk blocked"
        if not self._current_contract(symbol):
            return "Data unavailable"
        with self._lock:
            if (symbol in self._symbols and self._ws is not None and self._ws.connected
                    and self._ws.authenticated):
                return "Collecting history"
            if symbol not in self._symbols and len(self._symbols) >= self.MAX_SYMBOLS:
                return "Risk blocked"
            try:
                ws = self._client()
                if not ws.connected or not ws.authenticated:
                    return "Data unavailable"
                if ws is not self._ws:
                    if self._ws is not None:
                        self._ws.unregister_callback("market_data", self._on_market_data)
                        self._ws.unregister_callback("auth", self._on_auth)
                        for old_symbol in self._symbols:
                            self.store.mark_interrupted(self.connection_id, old_symbol)
                    ws.register_callback("market_data", self._on_market_data)
                    ws.register_callback("auth", self._on_auth)
                    self._ws = ws
                    self._symbols.clear()
                result = ws.subscribe([{"symbol": symbol, "exchange": "MCX"}], mode="Quote")
                if result.get("status") != "success":
                    return "Data unavailable"
                self._symbols.add(symbol)
                return "Collecting history"
            except Exception:
                logger.exception("MCX quote subscription failed")
                return "Data unavailable"

    def _on_market_data(self, packet):
        # This callback may be on the asyncio real OS thread. Queue only.
        if (isinstance(packet, dict) and packet.get("exchange") == "MCX"
                and packet.get("symbol") in self._symbols and packet.get("mode") == 2):
            try:
                self._queue.put_nowait(("tick", packet))
            except queue.Full:
                self._overflow = True

    def _on_auth(self, message):
        if isinstance(message, dict) and message.get("status") == "success":
            try:
                self._queue.put_nowait(("reconnect", None))
            except queue.Full:
                self._overflow = True

    def drain_once(self):
        if self._overflow:
            self._overflow = False
            while True:
                try:
                    self._queue.get_nowait()
                except _real_threading.Empty:
                    break
            for symbol in tuple(self._symbols):
                self.store.mark_interrupted(self.connection_id, symbol)
        for _ in range(500):
            try:
                kind, packet = self._queue.get_nowait()
            except _real_threading.Empty:
                break
            if kind == "reconnect":
                for symbol in tuple(self._symbols):
                    self.store.mark_interrupted(self.connection_id, symbol)
                    if self._ws is not None:
                        self._ws.subscribe([{"symbol": symbol, "exchange": "MCX"}], mode="Quote")
            elif kind == "tick":
                self.store.ingest(self.connection_id, packet)

    def _loop(self):
        while self._running:
            try:
                self.drain_once()
            except Exception:
                logger.exception("MCX candle drain failed")
            time.sleep(0.02)

    def close(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            with self._lock:
                if self._ws is not None:
                    self._ws.unregister_callback("market_data", self._on_market_data)
                    self._ws.unregister_callback("auth", self._on_auth)
                self._ws = None
                self._symbols.clear()
        finally:
            self.store.engine.dispose()


_collectors: dict[str, KotakMcxStreamCollector] = {}
_collectors_lock = threading.Lock()


def get_kotak_mcx_history(api_key, connection_id, symbol, interval, start_date, end_date):
    """Read completed observations, starting the bounded live stream if needed."""
    if not connection_id or not _verified_connection(api_key, connection_id):
        return {"status": "risk_blocked", "readiness": "Risk blocked", "data": [],
                "message": "An active pinned Kotak broker connection is required"}
    if not _is_current_future(symbol):
        return {"status": "data_unavailable", "readiness": "Data unavailable", "data": [],
                "message": "Current MCX futures contract is unavailable"}
    with _collectors_lock:
        collector = _collectors.get(connection_id)
        if collector is not None and collector.api_key != api_key:
            collector.close()
            _collectors.pop(connection_id, None)
            collector = None
        if collector is None:
            if len(_collectors) >= 8:
                return {"status": "risk_blocked", "readiness": "Risk blocked", "data": [],
                        "message": "MCX collector connection limit reached"}
            collector = KotakMcxStreamCollector(connection_id, api_key, McxCandleStore())
            _collectors[connection_id] = collector
    readiness = collector.ensure(symbol)
    if readiness in {"Risk blocked", "Data unavailable"}:
        return {"status": "risk_blocked" if readiness == "Risk blocked" else "data_unavailable",
                "readiness": readiness, "data": [], "message": readiness,
                "connection_id": connection_id, "symbol": symbol}
    result = collector.store.history(connection_id, symbol, interval, start_date, end_date)
    if result["status"] == "error":
        result["status"] = "data_unavailable" if result["readiness"] == "Data unavailable" else "collecting_history"
    return result


def _close_collectors():
    for collector in tuple(_collectors.values()):
        collector.close()
    _collectors.clear()


atexit.register(_close_collectors)
