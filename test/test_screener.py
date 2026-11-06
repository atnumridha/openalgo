"""Screener ownership, revision, input and market-data truth contracts."""

import copy
import time
from datetime import UTC, datetime, timezone
from threading import Event

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from database import screener_db as db
from services import screener as svc


def definition():
    return {
        "version": 1,
        "name": "Close above EMA",
        "interval": "5m",
        "universe": {"kind": "stored"},
        "intent": "observe",
        "rule": {
            "type": "group",
            "id": "root",
            "op": "all",
            "children": [
                {
                    "type": "condition",
                    "id": "c",
                    "left": {"field": "close"},
                    "op": "gt",
                    "right": {"field": "ema", "period": 20},
                }
            ],
        },
    }


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path}/screens.db", connect_args={"check_same_thread": False}
    )
    sessions = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(db, "db_session", sessions)
    db.Base.metadata.create_all(engine)
    svc.reset_runtime()
    yield
    svc.reset_runtime()
    sessions.remove()
    engine.dispose()


def test_ownership_revision_and_deletion():
    row = db.save_screen("alice", definition())
    assert db.list_screens("bob") == []
    with pytest.raises(db.NotFound):
        db.save_screen("bob", definition(), row["id"], 1)
    changed = definition()
    changed["name"] = "Changed"
    assert db.save_screen("alice", changed, row["id"], 1)["revision"] == 2
    with pytest.raises(db.Conflict):
        db.save_screen("alice", definition(), row["id"], 1)
    with pytest.raises(db.NotFound):
        db.delete_screen("bob", row["id"])
    db.delete_screen("alice", row["id"])
    assert db.list_screens("alice") == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(version=2),
        lambda d: d.update(name=" " * 3),
        lambda d: d["rule"]["children"][0]["right"].update(period=501),
        lambda d: d["rule"]["children"][0].update(op="eval"),
        lambda d: d["rule"]["children"][0].update(right=float("nan")),
        lambda d: d["rule"].update(children=d["rule"]["children"] * 25),
        lambda d: d["universe"].update(items=[{"symbol": "A", "exchange": "NSE"}] * 501),
    ],
)
def test_rejects_invalid_definition(mutate):
    value = definition()
    mutate(value)
    with pytest.raises(ValueError):
        svc.validate_definition(value)


def test_depth_limit_and_supported_patterns():
    value = definition()
    node = value["rule"]
    for i in range(4):
        node["children"] = [{"type": "group", "id": str(i), "op": "all", "children": []}]
        node = node["children"][0]
    with pytest.raises(ValueError):
        svc.validate_definition(value)
    value = definition()
    value["rule"]["children"][0]["left"] = {"field": "candle_pattern", "pattern": "made-up"}
    with pytest.raises(ValueError):
        svc.validate_definition(value)


def test_events_are_idempotent_owner_revision_and_mode_scoped():
    screen = db.save_screen("alice", definition())
    now = int(time.time())
    event = {
        "symbol": "TCS",
        "exchange": "NSE",
        "time": now - 300,
        "direction": "MATCH",
        "source": "broker",
        "observedAt": now,
    }
    assert len(db.add_events("alice", screen["id"], 1, "live", [event])) == 1
    assert db.add_events("alice", screen["id"], 1, "live", [event]) == []
    assert len(db.add_events("alice", screen["id"], 1, "analyzer", [event])) == 1
    with pytest.raises(db.NotFound):
        db.get_events("bob", screen["id"])
    db.save_screen("alice", definition(), screen["id"], 1)
    with pytest.raises(db.Conflict):
        db.add_events("alice", screen["id"], 1, "live", [event])


def test_stored_snapshot_keeps_download_observation_and_raw_utc(monkeypatch):
    import pandas as pd

    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(
        svc,
        "read_catalog",
        lambda: [{"symbol": "TCS", "exchange": "NSE", "interval": "1m", "last_download_at": stamp}],
    )
    monkeypatch.setattr(
        svc,
        "read_bars",
        lambda *a, **k: pd.DataFrame(
            [{"timestamp": 1735689600, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 20}]
        ),
    )
    monkeypatch.setattr(svc, "metadata", lambda *a: {})
    data = svc.stored_dataset("alice", "live", {"symbol": "TCS", "exchange": "NSE"}, "5m")
    assert data["observedAt"] == 1735689600
    assert data["candles"][0]["time"] == 1735689600
    assert data["daily"] == []  # no verified daily download observation
    assert data["source"] == "historify"


def test_invalid_candles_are_not_repaired():
    with pytest.raises(ValueError):
        svc.normalize_bars(
            [{"timestamp": 1, "open": 10, "high": 8, "low": 9, "close": 11, "volume": 0}]
        )
    assert (
        svc.normalize_bars([{"timestamp": 1, "open": 10, "high": 12, "low": 9, "close": 11}])[0][
            "volume"
        ]
        is None
    )


def test_universe_sources_fail_independently(monkeypatch):
    monkeypatch.setattr(svc, "read_catalog", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(
        svc,
        "read_watchlists",
        lambda owner: [{"id": 4, "name": "Mine", "items": [{"symbol": "TCS", "exchange": "NSE"}]}],
    )
    result = svc.universes("alice")
    assert any(u["id"] == "watchlist:4" for u in result["universes"])
    assert any(u["id"] == "crypto" for u in result["universes"])
    assert result["errors"]


def test_bounded_coalesced_owner_bound_jobs(monkeypatch):
    gate = Event()
    calls = []

    def refresh(owner, mode, item, frame, credentials):
        calls.append(item["symbol"])
        gate.wait(2)
        return {
            **item,
            "interval": frame,
            "candles": [],
            "daily": [],
            "source": "test",
            "observedAt": 1,
        }

    monkeypatch.setattr(svc, "refresh_dataset", refresh)
    items = [{"symbol": "TCS", "exchange": "NSE"}]
    first = svc.start_job("alice", "live", items, "5m", {})
    second = svc.start_job("alice", "live", items, "5m", {})
    with pytest.raises(db.NotFound):
        svc.job_result("bob", first["job_id"])
    gate.set()
    deadline = time.time() + 3
    while (
        svc.job_result("alice", second["job_id"])["status"] != "complete" and time.time() < deadline
    ):
        time.sleep(0.01)
    assert calls == ["TCS"]
    assert svc.job_result("alice", first["job_id"])["status"] == "complete"


def test_api_auth_and_csrf(monkeypatch):
    from flask import Flask
    from flask_wtf.csrf import CSRFProtect

    from blueprints.screener import screener_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(screener_bp)
    CSRFProtect(app)
    client = app.test_client()
    assert client.get("/screener/api/screens").status_code == 401
    with client.session_transaction() as session:
        session.update(user="alice", logged_in=True, login_time=datetime.now(UTC).isoformat())
    assert client.get("/screener/api/screens").status_code == 200
    assert (
        client.post("/screener/api/screens", json={"definition": definition()}).status_code == 400
    )
    app.config["WTF_CSRF_ENABLED"] = False
    created = client.post("/screener/api/screens", json={"definition": definition()})
    assert created.status_code == 201
    assert (
        client.put(
            "/screener/api/screens/" + str(created.json["screen"]["id"]),
            json={"definition": definition(), "expected_revision": 5},
        ).status_code
        == 409
    )


def test_screen_limit_and_event_retention(monkeypatch):
    monkeypatch.setattr(db, "MAX_SCREENS", 2)
    a = db.save_screen("alice", definition())
    db.save_screen("alice", definition())
    with pytest.raises(db.Conflict):
        db.save_screen("alice", definition())
    assert db.save_screen("bob", definition())
    monkeypatch.setattr(db, "MAX_EVENTS", 2)
    now = int(time.time())
    base = {
        "exchange": "NSE",
        "time": now - 300,
        "direction": "MATCH",
        "source": "broker",
        "observedAt": now,
    }
    db.add_events("alice", a["id"], 1, "live", [{**base, "symbol": str(i)} for i in range(3)])
    assert len(db.get_events("alice", a["id"])) == 2


@pytest.mark.parametrize(
    "patch",
    [
        {"observedAt": 1},
        {"time": int(time.time()) + 500},
        {"direction": "EXECUTE_BUY"},
        {"source": ""},
    ],
)
def test_rejects_stale_or_invalid_events(patch):
    now = int(time.time())
    event = {
        "symbol": "TCS",
        "exchange": "NSE",
        "time": now - 300,
        "direction": "MATCH",
        "source": "broker",
        "observedAt": now,
        **patch,
    }
    with pytest.raises(ValueError):
        svc.validate_events([event], "live")


def test_cancel_stops_queued_requests_and_keeps_other_jobs(monkeypatch):
    gate = Event()
    started = Event()
    calls = []

    def refresh(owner, mode, item, frame, credentials):
        calls.append(item["symbol"])
        if len(calls) == 2:
            started.set()
        gate.wait(3)
        return {
            **item,
            "interval": frame,
            "source": "test",
            "observedAt": 1,
            "candles": [],
            "daily": [],
        }

    monkeypatch.setattr(svc, "refresh_dataset", refresh)
    job = svc.start_job(
        "alice", "live", [{"symbol": str(i), "exchange": "NSE"} for i in range(10)], "5m", {}
    )
    assert started.wait(1)
    svc.cancel_job("alice", job["job_id"])
    gate.set()
    svc.reset_runtime()
    assert len(calls) == 2


def test_refresh_limit_and_job_expiry(monkeypatch):
    with pytest.raises(ValueError):
        svc.start_job("alice", "live", [{"symbol": "TCS", "exchange": "NSE"}] * 26, "5m", {})
    job = svc.start_job("alice", "live", [], "5m", {})
    svc._jobs[job["job_id"]]["created"] -= svc.JOB_TTL + 1
    with pytest.raises(db.NotFound):
        svc.job_result("alice", job["job_id"])


def test_refresh_captures_observation_before_broker_and_reuses_services(monkeypatch):
    from services import history_service
    from utils import db_sessions

    calls = []

    def history(symbol, exchange, interval, *args, **kwargs):
        calls.append((interval, time.time(), kwargs))
        return (
            True,
            {
                "data": [
                    {"timestamp": 1, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 0}
                ]
            },
            200,
        )

    monkeypatch.setattr(history_service, "get_history", history)
    monkeypatch.setattr(
        svc, "metadata", lambda *a: {"session": {"start": 555, "end": 930, "offset": 19800}}
    )
    monkeypatch.setattr(db_sessions, "remove_all_scoped_sessions", lambda: None)
    result = svc.refresh_dataset(
        "alice",
        "analyzer",
        {"symbol": "TCS", "exchange": "NSE"},
        "5m",
        {"auth_token": "private", "broker": "fyers"},
    )
    assert result["observedAt"] <= calls[0][1]
    assert [x[0] for x in calls] == ["5m", "1d"]
    assert all(x[2]["background"] is True and x[2]["broker"] == "fyers" for x in calls)
    assert result["source"] == "broker:fyers"


def test_cached_history_is_partitioned_by_active_broker(monkeypatch):
    monkeypatch.setattr(svc, "read_catalog", lambda: [])
    item = {"symbol": "TCS", "exchange": "NSE"}
    svc._cache[("alice", "live", "kotak", "NSE", "TCS", "5m")] = (
        time.monotonic(),
        {**item, "source": "broker:kotak", "candles": []},
    )
    assert (
        svc.stored_dataset("alice", "live", item, "5m", broker="fyers")["source"] == "unavailable"
    )
    assert (
        svc.stored_dataset("alice", "live", item, "5m", broker="kotak")["source"] == "broker:kotak"
    )


def test_cancelled_queued_instrument_can_be_requested_again(monkeypatch):
    gate = Event()
    started = Event()
    calls = []

    def refresh(owner, mode, item, frame, credentials):
        calls.append(item["symbol"])
        if len(calls) == 2:
            started.set()
        gate.wait(2)
        return {
            **item,
            "interval": frame,
            "source": "test",
            "observedAt": 1,
            "candles": [],
            "daily": [],
        }

    monkeypatch.setattr(svc, "refresh_dataset", refresh)
    first = svc.start_job(
        "alice", "live", [{"symbol": str(i), "exchange": "NSE"} for i in range(3)], "5m", {}
    )
    assert started.wait(1)
    svc.cancel_job("alice", first["job_id"])
    retry = svc.start_job("alice", "live", [{"symbol": "2", "exchange": "NSE"}], "5m", {})
    gate.set()
    deadline = time.time() + 2
    while (
        svc.job_result("alice", retry["job_id"])["status"] != "complete" and time.time() < deadline
    ):
        time.sleep(0.01)
    assert svc.job_result("alice", retry["job_id"])["status"] == "complete"
    assert "2" in calls


def test_api_payload_bounds_and_malformed_structures():
    from flask import Flask

    from blueprints.screener import screener_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(screener_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(user="alice", logged_in=True, login_time=datetime.now(UTC).isoformat())
    assert (
        client.post(
            "/screener/api/screens",
            json={"definition": definition(), "junk": "x" * svc.MAX_PAYLOAD},
        ).status_code
        == 413
    )
    assert client.post("/screener/api/screens", json=[]).status_code == 400
    assert (
        client.post(
            "/screener/api/data",
            json={
                "mode": "live",
                "interval": "5m",
                "items": [{"symbol": "TCS", "exchange": "NSE"}] * 501,
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/screener/api/screens",
            data='{"definition":' + ("[" * 1100) + ("]" * 1100) + "}",
            content_type="application/json",
        ).status_code
        == 400
    )


def test_session_metadata_uses_chart_minutes_and_exchange_precision(monkeypatch):
    from database import market_calendar_db
    from services import symbol_service

    monkeypatch.setattr(
        symbol_service,
        "get_symbol_info",
        lambda *args: (True, {"data": {"tick_size": "0.0025"}}, 200),
    )
    monkeypatch.setattr(
        market_calendar_db,
        "get_market_timing",
        lambda exchange: {"start_offset": 32400000, "end_offset": 61200000},
    )
    result = svc.metadata("USDINR", "CDS")
    assert result == {"tickSize": 0.0025, "session": {"start": 540, "end": 1020, "offset": 19800}}
    assert svc.metadata("BTCUSD", "DELTA")["session"] is None


@pytest.mark.parametrize(
    "symbol,exchange,venue", [("NIFTY", "NSE_INDEX", "NSE"), ("SENSEX", "BSE_INDEX", "BSE")]
)
def test_index_session_metadata_resolves_cash_venue(monkeypatch, symbol, exchange, venue):
    from database import market_calendar_db
    from services import symbol_service

    monkeypatch.setattr(symbol_service, "get_symbol_info", lambda *args: (False, {}, 404))

    def timing(requested):
        return {"start_offset": 33300000, "end_offset": 55800000} if requested == venue else None

    monkeypatch.setattr(market_calendar_db, "get_market_timing", timing)
    assert svc.metadata(symbol, exchange)["session"] == {"start": 555, "end": 930, "offset": 19800}


def test_snapshot_prefers_newer_scoped_broker_cache_over_old_download(monkeypatch):
    item = {"symbol": "TCS", "exchange": "NSE"}
    monkeypatch.setattr(
        svc, "read_catalog", lambda: [{**item, "interval": "1m", "last_download_at": 1000}]
    )
    monkeypatch.setattr(
        svc,
        "read_bars",
        lambda *a, **kw: [
            {"timestamp": 900, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100}
        ],
    )
    monkeypatch.setattr(
        svc, "metadata", lambda *a: {"session": {"start": 555, "end": 930, "offset": 19800}}
    )
    cached = {
        **item,
        "interval": "5m",
        "source": "broker:kotak",
        "observedAt": 2000,
        "candles": [],
        "daily": [],
    }
    svc._cache[("alice", "live", "kotak", "NSE", "TCS", "5m")] = (time.monotonic(), cached)
    assert svc.stored_dataset("alice", "live", item, "5m", broker="kotak") == cached
    assert svc.stored_dataset("bob", "live", item, "5m", broker="kotak")["source"] == "historify"
    # A newer real download can replace the broker snapshot without a new timestamp.
    monkeypatch.setattr(
        svc, "read_catalog", lambda: [{**item, "interval": "1m", "last_download_at": 3000}]
    )
    assert svc.stored_dataset("alice", "live", item, "5m", broker="kotak")["observedAt"] == 3000
