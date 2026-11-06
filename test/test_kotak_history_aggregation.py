import importlib
import importlib.util
from types import SimpleNamespace

import pandas as pd
import pytest

BASE = 1792640700  # 22Oct2026 09:15IST
NOW = 1792720500  # 23Oct2026 before session


def minute_rows(count=10):
    return [
        {
            "timestamp": BASE + i * 60,
            "open": 100 + i,
            "high": 102 + i,
            "low": 99 + i,
            "close": 101 + i,
            "volume": 10,
            "oi": i,
        }
        for i in range(count)
    ]


def helper():
    assert importlib.util.find_spec("services.history_resample") is not None, (
        "Canonical minute aggregation not implemented"
    )
    return importlib.import_module("services.history_resample").aggregate_history_minutes


def test_each_five_minute_candle_uses_only_its_own_minutes():
    rows = helper()(minute_rows(), "5m", NOW)
    assert rows[0] == {
        "timestamp": BASE,
        "open": 100,
        "high": 106,
        "low": 99,
        "close": 105,
        "volume": 50,
        "oi": 4,
    }
    assert rows[1] == {
        "timestamp": BASE + 300,
        "open": 105,
        "high": 111,
        "low": 104,
        "close": 110,
        "volume": 50,
        "oi": 9,
    }
    altered = minute_rows()
    altered[9].update(high=500, close=400)
    assert helper()(altered, "5m", NOW)[0] == rows[0]


def test_historical_gaps_invalid_minutes_and_closing_partial_bucket_are_not_filled():
    agg = helper()
    rows = minute_rows(11)
    assert len(agg(rows, "5m", NOW)) == 2
    missing = rows[:2] + rows[3:]
    assert [b["timestamp"] for b in agg(missing, "5m", NOW)] == [BASE + 300]
    for edit in [{"repaired": True}, {"low": 200}, {"close": float("nan")}]:
        broken = [dict(r) for r in rows]
        broken[2].update(edit)
        assert [b["timestamp"] for b in agg(broken, "5m", NOW)] == [BASE + 300]


def test_fifteen_minute_ohlc_volume_and_current_forming_bar_are_causal():
    agg = helper()
    rows = minute_rows(16)
    result = agg(rows, "15m", NOW)
    assert len(result) == 1 and result[0]["close"] == 115 and result[0]["volume"] == 150
    forming = agg(rows, "5m", BASE + 90)
    assert len(forming) == 1 and forming[0]["close"] == 102 and forming[0]["high"] == 103
    assert len(agg(rows, "5m", BASE + 90)) == 1  # future source rows never appear
    zero = [dict(b, volume=0) for b in rows]
    assert agg(zero, "15m", NOW)[0]["volume"] == 0


@pytest.mark.parametrize(
    "broker,interval,requested",
    [("kotak", "5m", "1m"), ("kotak", "15m", "1m"), ("kotak", "1m", "1m"), ("other", "5m", "5m")],
)
def test_history_service_uses_minute_source_only_for_affected_kotak_timeframes(
    monkeypatch, broker, interval, requested
):
    from services import history_service as s

    calls = []

    class Provider:
        def __init__(self, token):
            pass

        def get_history(self, symbol, exchange, tf, start, end):
            calls.append(tf)
            return pd.DataFrame(minute_rows(15))

    monkeypatch.setattr(s, "validate_symbol_exchange", lambda *a: (True, None))
    monkeypatch.setattr(
        s, "import_broker_module", lambda name: SimpleNamespace(BrokerData=Provider)
    )
    monkeypatch.setenv("NEO_SAVED_LOGIN", "false")
    ok, response, status = s.get_history_with_auth(
        "fixture", None, broker, "NIFTY", "NSE_INDEX", interval, "2026-10-22", "2026-10-22"
    )
    assert ok and status == 200 and calls == [requested]
    if broker == "kotak" and interval == "5m":
        assert [b["close"] for b in response["data"]] == [105, 110, 115]
    if broker == "kotak" and interval == "15m":
        assert response["data"][0]["close"] == 115 and len(response["data"]) == 1


def test_provider_repair_provenance_survives_into_aggregation(monkeypatch):
    from broker.kotak.api import data as module

    monkeypatch.setattr(module, "_history_clock", lambda: pd.Timestamp("2026-10-23T08:30:00+05:30"))
    provider = module.BrokerData(
        "fixture-trade:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-api"
    )
    monkeypatch.setattr(provider, "_history_segment", lambda *a: "nse_cm")
    monkeypatch.setattr(provider, "_history_neosymbols", lambda *a: ["nse_cm|fixture"])
    wire = []
    for i in range(10):
        stamp = (
            pd.Timestamp(BASE + i * 60, unit="s", tz="UTC").tz_convert("Asia/Kolkata").isoformat()
        )
        wire.append([stamp, 100, 102, 99, 101, 10, 0])
    wire[2][1:5] = [100, 90, 99, 101]
    monkeypatch.setattr(provider, "_fetch_history_chunk", lambda *a: wire)
    frame = provider.get_history("NIFTY", "NSE_INDEX", "1m", "2026-10-22", "2026-10-22")
    assert frame.iloc[2].get("repaired", False)
    result = helper()(frame.to_dict(orient="records"), "5m", NOW)
    assert len(result) == 1 and result[0]["timestamp"] == BASE + 300 and result[0]["low"] == 99


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_unusable_provider_price_does_not_fail_valid_history_archive(monkeypatch, tmp_path, bad):
    from broker.kotak.api import data as module
    from database.engine_factory import create_db_engine
    from services.neo_desk.chart_archive import ChartArchive

    monkeypatch.setattr(module, "_history_clock", lambda: pd.Timestamp("2026-10-23T10:00:00+05:30"))
    provider = module.BrokerData(
        "fixture-trade:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-api"
    )
    monkeypatch.setattr(provider, "_history_segment", lambda *a: "nse_fo")
    monkeypatch.setattr(provider, "_history_neosymbols", lambda *a: ["nse_fo|fixture"])
    wire = []
    for i in range(10):
        stamp = pd.Timestamp(BASE + i * 60, unit="s", tz="UTC").isoformat()
        wire.append([stamp, 100, 102, 99, 101, 10, 0])
    wire[2][1] = bad
    monkeypatch.setattr(provider, "_fetch_history_chunk", lambda *a: wire)
    frame = provider.get_history("NIFTY27OCT2622750CE", "NFO", "1m", "2026-10-22", "2026-10-22")
    archive = ChartArchive(create_db_engine(f"sqlite:///{tmp_path}/clean-history.db"))
    assert archive.save("NIFTY27OCT2622750CE", "NFO", "1m", frame.to_dict("records")) == 9
    assert BASE + 120 not in frame.timestamp.tolist()
    assert [r["timestamp"] for r in helper()(frame.to_dict("records"), "5m", NOW)] == [BASE + 300]


def closing_minutes():
    # NFO's configured 15:40 close leaves ten real minutes in the final 15m bucket.
    start = BASE + (15 * 60 + 30 - (9 * 60 + 15)) * 60
    return [dict(row, timestamp=start + i * 60) for i, row in enumerate(minute_rows(10))]


def test_complete_short_session_closing_candle_uses_all_real_minutes_only():
    agg = helper()
    source = closing_minutes()
    assert agg(source, "15m", NOW) == []  # Without verified close metadata, never guess.
    result = agg(source, "15m", NOW, session_end=940)
    assert result == [
        {
            "timestamp": source[0]["timestamp"],
            "open": 100,
            "high": 111,
            "low": 99,
            "close": 110,
            "volume": 100,
            "oi": 9,
        }
    ]
    assert agg(source, "15m", NOW, session_end=930) == []


@pytest.mark.parametrize("missing", [0, 4, 9])
def test_session_close_does_not_fill_a_missing_or_repaired_minute(missing):
    agg = helper()
    source = closing_minutes()
    assert agg(source[:missing] + source[missing + 1 :], "15m", NOW, session_end=940) == []
    source[missing]["repaired"] = True
    assert agg(source, "15m", NOW, session_end=940) == []


def test_session_close_does_not_read_prices_after_the_verified_close():
    source = closing_minutes()
    source.append(
        dict(
            source[-1],
            timestamp=source[-1]["timestamp"] + 60,
            open=999,
            high=1000,
            low=998,
            close=999,
            volume=999,
        )
    )
    result = helper()(source, "15m", NOW, session_end=940)
    # Contradictory post-close data does not justify dropping prices or filling
    # a truncated bucket. It must satisfy ordinary full-bucket completeness.
    assert result == []


def test_history_service_preserves_the_verified_nfo_closing_bucket(monkeypatch):
    from database import market_calendar_db as calendar
    from services import history_service as s

    class Provider:
        def __init__(self, token):
            pass

        def get_history(self, *args):
            return pd.DataFrame(closing_minutes())

    seen = []

    def timing(exchange):
        seen.append(exchange)
        return {"start_offset": 33300000, "end_offset": 56400000}

    monkeypatch.setattr(calendar, "get_market_timing", timing)
    monkeypatch.setattr(s, "validate_symbol_exchange", lambda *a: (True, None))
    monkeypatch.setattr(
        s, "import_broker_module", lambda name: SimpleNamespace(BrokerData=Provider)
    )
    monkeypatch.setenv("NEO_SAVED_LOGIN", "false")
    ok, result, code = s.get_history_with_auth(
        "fixture", None, "kotak", "NIFTY03NOV2623300CE", "NFO", "15m", "2026-10-22", "2026-10-22"
    )
    assert ok and code == 200
    assert len(result["data"]) == 1 and result["data"][0]["close"] == 110
    assert seen == ["NFO"]


def test_regular_close_metadata_does_not_delete_other_observed_session_buckets():
    source = [
        dict(row, timestamp=BASE + (18 * 60 - (9 * 60 + 15)) * 60 + i * 60)
        for i, row in enumerate(minute_rows(15))
    ]
    result = helper()(source, "15m", NOW, session_end=940)
    assert len(result) == 1 and result[0]["close"] == 115


@pytest.mark.parametrize("start_minute,regular_end", [(930, 940), (1425, 1435)])
def test_complete_observed_bucket_crossing_regular_close_is_preserved(start_minute, regular_end):
    source = [
        dict(row, timestamp=BASE + (start_minute - 555) * 60 + i * 60)
        for i, row in enumerate(minute_rows(15))
    ]
    result = helper()(source, "15m", NOW, session_end=regular_end)
    assert result == [
        {
            "timestamp": source[0]["timestamp"],
            "open": 100,
            "high": 116,
            "low": 99,
            "close": 115,
            "volume": 150,
            "oi": 14,
        }
    ]
