from scripts.research.video_reversal.kotak import completed_sessions, previous_daily


def test_invalid_or_missing_bar_excludes_session_and_daily_is_causal():
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    start = int(datetime(2026, 10, 14, 9, 15, tzinfo=ist).timestamp())
    rows = [
        {
            "timestamp": start + i * 60,
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 0,
        }
        for i in range(360)
    ]
    assert len(completed_sessions(rows, "2026-10-14", "2026-10-14")[0]) == 1
    rows[10]["high"] = 90
    good, audit = completed_sessions(rows, "2026-10-14", "2026-10-14")
    assert good == {} and audit["excluded_sessions"] == ["2026-10-14"]
    daily = {"2026-10-13": {"high": 110}, "2026-10-14": {"high": 999}}
    assert previous_daily(daily, "2026-10-14")["high"] == 110


def test_invalid_previous_daily_is_not_replaced_by_an_older_reference():
    daily = {"2026-10-12": {"high": 110}, "2026-10-13": None, "2026-10-14": {"high": 999}}
    assert previous_daily(daily, "2026-10-14") is None


def test_gap_entry_uses_observed_adverse_price_not_an_unavailable_trigger():
    from datetime import datetime, timedelta, timezone

    from scripts.research.video_reversal.kotak import simulate_session

    ist = timezone(timedelta(hours=5, minutes=30))
    start = int(datetime(2026, 10, 14, 9, 15, tzinfo=ist).timestamp())
    bars = [
        {"time": start + i * 60, "open": 110, "high": 110, "low": 110, "close": 110}
        for i in range(360)
    ]
    c = {
        "id": "gap",
        "side": "long",
        "known": start,
        "expires": start + 60,
        "trigger": 100,
        "stop": 90,
        "target": 120,
    }
    trades, _ = simulate_session(bars, {start: [c]}, "low-first")
    assert trades[0]["entry"] == 110 and trades[0]["points"] == 0


def test_requested_month_window_excludes_previous_month_boundary_day():
    from datetime import datetime, timedelta, timezone

    timezone(timedelta(hours=5, minutes=30))
    rows = []
    for day in ["2026-09-18", "2026-09-21"]:
        start = int(datetime.fromisoformat(day + "T09:15:00+05:30").timestamp())
        rows += [
            {"timestamp": start + i * 60, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 0}
            for i in range(360)
        ]
    sessions, audit = completed_sessions(rows, "2026-09-19", "2026-10-18")
    assert list(sessions) == ["2026-09-21"]
    assert audit["observed_sessions"] == 1
