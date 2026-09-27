"""Daily exchange observations must never become fabricated intraday evidence."""

import csv
import io
import json
import time
import zipfile
from datetime import date

import httpx
import pytest

from services.research import nse_archive as archive


def bundle(day="2026-09-25", **changes):
    row = {
        "TradDt": day,
        "Sgmt": "FO",
        "Src": "NSE",
        "FinInstrmTp": "IDO",
        "TckrSymb": "NIFTY",
        "XpryDt": "2026-09-29",
        "FininstrmActlXpryDt": "2026-09-29",
        "StrkPric": "23000",
        "OptnTp": "CE",
        "OpnPric": "100",
        "HghPric": "120",
        "LwPric": "80",
        "ClsPric": "110",
        "SttlmPric": "109",
        "TtlTradgVol": "20",
        "OpnIntrst": "1500",
        "ChngInOpnIntrst": "75",
        "NewBrdLotQty": "75",
        "UndrlygPric": "23100",
    }
    row.update(changes)
    return zipped([row])


def zipped(rows):
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as output:
        output.writestr("bhavcopy.csv", text.getvalue())
    return result.getvalue()


def test_current_daily_prices_keep_settlement_and_lot_size_distinct():
    rows, info = archive.parse_archive(bundle(), date(2026, 9, 25))
    assert rows[0]["close"] == 110
    assert rows[0]["settlement"] == 109
    assert rows[0]["lot_size"] == 75
    assert rows[0]["traded_contracts"] == 20
    assert rows[0]["open_interest_units"] == 1500
    assert rows[0]["observed_trade"] is True
    assert info["quality"] == "daily_observations_only"
    assert info["intraday_eligible"] is False


def test_untraded_contract_is_retained_but_never_marked_executable():
    rows, info = archive.parse_archive(
        bundle(OpnPric="0", HghPric="0", LwPric="0", TtlTradgVol="0"), date(2026, 9, 25)
    )
    assert rows[0]["open"] == 0
    assert rows[0]["observed_trade"] is False
    assert info["untraded_rows"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"TradDt": "2026-09-24"},
        {"Sgmt": "CM"},
        {"Src": "OTHER"},
        {"HghPric": "90"},
        {"TtlTradgVol": "-1"},
        {"ClsPric": "NaN"},
    ],
)
def test_bad_observations_are_rejected_instead_of_repaired(change):
    with pytest.raises(ValueError):
        archive.parse_archive(bundle(**change), date(2026, 9, 25))


def test_legacy_archive_preserves_unknown_lot_size():
    raw = zipped(
        [
            {
                "INSTRUMENT": "OPTIDX",
                "SYMBOL": "NIFTY",
                "EXPIRY_DT": "16-Apr-2020",
                "STRIKE_PR": "9000",
                "OPTION_TYP": "PE",
                "OPEN": "100",
                "HIGH": "120",
                "LOW": "80",
                "CLOSE": "110",
                "SETTLE_PR": "115",
                "CONTRACTS": "20",
                "OPEN_INT": "1500",
                "CHG_IN_OI": "75",
                "TIMESTAMP": "13-APR-2020",
            }
        ]
    )
    rows, _ = archive.parse_archive(raw, date(2020, 4, 13))
    assert rows[0]["expiry"] == "2020-04-16"
    assert rows[0]["lot_size"] is None


def test_duplicate_contracts_rejected():
    with zipfile.ZipFile(io.BytesIO(bundle())) as z:
        row = next(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))
    with pytest.raises(ValueError, match="Duplicate"):
        archive.parse_archive(zipped([row, row]), date(2026, 9, 25))


def test_distinct_scheduled_expiries_can_share_an_accelerated_actual_expiry():
    with zipfile.ZipFile(io.BytesIO(bundle())) as z:
        row = next(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))
    first = dict(row, FinInstrmId="100", XpryDt="2026-10-27", FininstrmActlXpryDt="2026-09-29")
    second = dict(row, FinInstrmId="101", XpryDt="2026-11-24", FininstrmActlXpryDt="2026-09-29")
    rows, _ = archive.parse_archive(zipped([first, second]), date(2026, 9, 25))
    assert len(rows) == 2
    assert {r["scheduled_expiry"] for r in rows} == {"2026-10-27", "2026-11-24"}
    assert {r["instrument_id"] for r in rows} == {"100", "101"}


def test_download_resume_verifies_cache_and_never_calls_missing_day_a_holiday(tmp_path):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        if "20260924" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, content=bundle())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = archive.sync(
            tmp_path, date(2026, 9, 24), date(2026, 9, 25), client=client, delay=0
        )
        assert result["session_count"] == 1
        assert result["unavailable_count"] == 1
        assert result["status"] == "completed_with_gaps"
        written_at = (tmp_path / "daily" / "2026-09-25.json.gz").stat().st_mtime_ns
        requested.clear()
        archive.sync(tmp_path, date(2026, 9, 24), date(2026, 9, 25), client=client, delay=0)
        assert not requested  # immutable verified data and dated missing responses are reusable
        assert (tmp_path / "daily" / "2026-09-25.json.gz").stat().st_mtime_ns == written_at
        (tmp_path / "raw" / "2026-09-25.zip").write_bytes(b"damaged")
        archive.sync(tmp_path, date(2026, 9, 24), date(2026, 9, 25), client=client, delay=0)
        assert len(requested) == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["days"]["2026-09-24"]["status"] == "unavailable"


def test_access_denial_stops_without_retrying_other_hosts(tmp_path):
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = archive.sync(
            tmp_path, date(2026, 9, 24), date(2026, 9, 25), client=client, delay=0
        )
    assert result["status"] == "blocked"
    assert result["session_count"] == 0
    assert len(calls) == 1


def test_previous_session_excludes_same_day_and_reports_staleness(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=bundle()))
    ) as client:
        archive.sync(tmp_path, date(2026, 9, 25), date(2026, 9, 25), client=client, delay=0)
    assert archive.snapshot(tmp_path, "NIFTY", before=date(2026, 9, 25))["session"] is None
    result = archive.snapshot(tmp_path, "NIFTY", before=date(2026, 9, 28))
    assert result["session"] == "2026-09-25"
    assert result["age_calendar_days"] == 3
    assert result["contracts"][0]["close"] == 110


def test_archive_schema_cannot_be_imported_as_intraday_data():
    from services.research.dataset import validate_dataset

    rows, info = archive.parse_archive(bundle(), date(2026, 9, 25))
    with pytest.raises(ValueError):
        validate_dataset({"name": "NSE daily", "provider": "NSE", "metadata": info, "rows": rows})


def test_pause_requested_before_child_start_is_not_erased(tmp_path):
    requested_at = time.time() - 1
    (tmp_path / "cancel").touch()

    def forbidden(request):
        raise AssertionError("Paused job must not fetch")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        result = archive.sync(
            tmp_path,
            date(2026, 9, 25),
            date(2026, 9, 25),
            client=client,
            delay=0,
            requested_at=requested_at,
        )
    assert result["status"] == "interrupted"
    assert result["session_count"] == 0


@pytest.mark.parametrize("failure", ["network", "server"])
def test_provider_outage_stops_batch_instead_of_marking_every_date_missing(
    tmp_path, failure, monkeypatch
):
    monkeypatch.setattr(archive.time, "sleep", lambda seconds: None)
    calls = []

    def respond(request):
        calls.append(request.url)
        if failure == "network":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = archive.sync(tmp_path, date(2026, 8, 1), date(2026, 9, 25), client=client, delay=0)
    assert result["status"] == "failed"
    assert result["unavailable_count"] == 0
    assert len(calls) == 3


def test_transient_connection_failure_recovers_with_bounded_same_source_retry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(archive.time, "sleep", lambda seconds: None)
    calls = []

    def respond(request):
        calls.append(request.url)
        if len(calls) < 3:
            raise httpx.ReadError("temporary read failure", request=request)
        return httpx.Response(200, content=bundle())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = archive.sync(
            tmp_path, date(2026, 9, 25), date(2026, 9, 25), client=client, delay=0
        )
    assert result["status"] == "completed"
    assert result["session_count"] == 1
    assert len(set(calls)) == 1
