from datetime import datetime
from zoneinfo import ZoneInfo

from services.kotak_assistant import setup_data as data

IST = ZoneInfo("Asia/Kolkata")


def epoch(day, hour, minute):
    return datetime(2026, 10, day, hour, minute, tzinfo=IST).timestamp()


def window(day, exchange):
    if day.weekday() >= 5:
        return None
    return {"start_ms": epoch(day.day, 9, 15) * 1000, "end_ms": epoch(day.day, 15, 30) * 1000}


def bar(t, **kw):
    return {"time": t, "open": 100, "high": 102, "low": 99, "close": 101, **kw}


def test_history_excludes_overnight_weekend_and_unfinished_bars():
    t = epoch(16, 9, 16)
    rows = [
        bar(epoch(15, 23, 0)),
        bar(epoch(16, 9, 14)),
        bar(epoch(16, 9, 15)),
        bar(t),
        bar(epoch(17, 9, 15)),
    ]
    assert data.session_bars(rows, 60, t + 20, "NSE", window) == [rows[2]]


def test_index_volume_is_never_invented():
    rows = [bar(epoch(16, 9, 15), volume=0), bar(epoch(16, 9, 16), volume=10)]
    result = data.session_bars(rows, 60, epoch(16, 9, 18), "NSE", window)
    assert result[0].get("volume") == 0
    assert result[1]["volume"] == 10


def test_gap_detection_ignores_overnight_but_reports_missing_intraday_minute():
    rows = [bar(epoch(15, 15, 29)), bar(epoch(16, 9, 15)), bar(epoch(16, 9, 17))]
    assert data.continuity_gaps(rows, 60) == [
        {"after": epoch(16, 9, 15), "before": epoch(16, 9, 17), "missing": 1}
    ]


def test_duplicate_event_commit_and_restart_restore_are_atomic(tmp_path):
    from database.engine_factory import create_db_engine

    store = data.SetupStore(create_db_engine(f"sqlite:///{tmp_path}/setups.db"))
    event = {"id": "tick-1", "time": epoch(16, 9, 16), "price": 22608, "source": "Live feed"}
    assert store.commit("u:NIFTY", 0, {"consumed": {"PE": True}}, [event])
    assert not store.commit("u:NIFTY", 0, {"consumed": {}}, [event])
    restored = data.SetupStore(store.engine)
    state, version = restored.read("u:NIFTY")
    assert state["consumed"]["PE"] is True and version == 1
    assert restored.events("u:NIFTY", epoch(16, 9, 15), epoch(16, 9, 20)) == [event]
    assert restored.commit("u:NIFTY", version, state, [event])
    assert len(restored.events("u:NIFTY", 0, epoch(16, 10, 0))) == 1


def test_normalizes_real_broker_timestamp_and_millisecond_schema():
    t = epoch(16, 9, 15)
    a, b = bar(t), bar(t + 60)
    a["timestamp"] = a.pop("time")
    b["timestamp"] = b.pop("time") * 1000
    result = data.session_bars([a, b], 60, t + 180, "NSE", window)
    assert [row["time"] for row in result] == [t, t + 60]
