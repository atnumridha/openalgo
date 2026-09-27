"""Official NSE daily observations, deliberately separate from intraday replay."""

import csv
import gzip
import hashlib
import io
import json
import math
import os
import time
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

START = date(2020, 4, 13)
ROOT = Path(__file__).resolve().parents[2] / "data" / "research" / "nse-daily"
SOURCE = "https://www.nseindia.com/all-reports-derivatives"
MAX_ZIP = 20 * 1024 * 1024
MAX_CSV = 64 * 1024 * 1024
VERSION = 2


def today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def archive_url(day):
    if day < date(2024, 7, 8):
        return (
            "https://archives.nseindia.com/content/historical/DERIVATIVES/"
            f"{day:%Y}/{day:%b}/fo{day:%d%b%Y}bhav.csv.zip"
        ).replace(day.strftime("%b"), day.strftime("%b").upper())
    return f"https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"


def _number(value, *, signed=False, optional=False):
    if optional and value in (None, ""):
        return None
    value = float(value)
    if not math.isfinite(value) or (not signed and value < 0):
        raise ValueError("Invalid numeric observation in NSE file")
    return value


def parse_archive(raw, day):
    """Preserve daily prices including untraded contracts; never invent observations."""
    if len(raw) > MAX_ZIP:
        raise ValueError("NSE archive exceeds the download size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = archive.infolist()
            if len(files) != 1 or not files[0].filename.lower().endswith(".csv"):
                raise ValueError("NSE archive must contain one CSV")
            if files[0].file_size > MAX_CSV:
                raise ValueError("NSE CSV exceeds the size limit")
            content = archive.read(files[0]).decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeError) as error:
        raise ValueError("NSE did not return a readable data archive") from error
    reader = csv.DictReader(io.StringIO(content))
    modern = "TradDt" in (reader.fieldnames or [])
    required = (
        {
            "TradDt",
            "Sgmt",
            "Src",
            "FinInstrmTp",
            "TckrSymb",
            "XpryDt",
            "StrkPric",
            "OptnTp",
            "OpnPric",
            "HghPric",
            "LwPric",
            "ClsPric",
            "SttlmPric",
            "TtlTradgVol",
            "OpnIntrst",
            "ChngInOpnIntrst",
        }
        if modern
        else {
            "TIMESTAMP",
            "INSTRUMENT",
            "SYMBOL",
            "EXPIRY_DT",
            "STRIKE_PR",
            "OPTION_TYP",
            "OPEN",
            "HIGH",
            "LOW",
            "CLOSE",
            "SETTLE_PR",
            "CONTRACTS",
            "OPEN_INT",
            "CHG_IN_OI",
        }
    )
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("NSE file has an unsupported format")
    rows, seen, source_rows = [], set(), 0
    for record in reader:
        source_rows += 1
        if source_rows > 250000:
            raise ValueError("NSE file exceeds the row limit")
        trade_date = (
            date.fromisoformat(record["TradDt"])
            if modern
            else datetime.strptime(record["TIMESTAMP"], "%d-%b-%Y").date()
        )
        if trade_date != day or (modern and (record["Sgmt"] != "FO" or record["Src"] != "NSE")):
            raise ValueError("NSE file date or market does not match the request")
        kind = record["FinInstrmTp" if modern else "INSTRUMENT"]
        if kind not in ("IDO", "STO", "OPTIDX", "OPTSTK"):
            continue
        option_type = record["OptnTp" if modern else "OPTION_TYP"]
        expiry = (
            date.fromisoformat(record.get("FininstrmActlXpryDt") or record["XpryDt"])
            if modern
            else datetime.strptime(record["EXPIRY_DT"], "%d-%b-%Y").date()
        )
        symbol = record["TckrSymb" if modern else "SYMBOL"].strip()
        strike = _number(record["StrkPric" if modern else "STRIKE_PR"])
        if option_type not in ("CE", "PE") or not symbol or strike <= 0 or expiry < day:
            raise ValueError("Invalid NSE option contract identity")
        scheduled_expiry = date.fromisoformat(record["XpryDt"]) if modern else expiry
        instrument_id = record.get("FinInstrmId") if modern else None
        key = (
            (instrument_id, record.get("SsnId", "F1"))
            if instrument_id
            else (symbol, scheduled_expiry, strike, option_type)
        )
        if key in seen:
            raise ValueError("Duplicate NSE option contract")
        seen.add(key)
        prices = {
            key: _number(record[field])
            for key, field in zip(
                ("open", "high", "low", "close", "settlement"),
                ("OpnPric", "HghPric", "LwPric", "ClsPric", "SttlmPric")
                if modern
                else ("OPEN", "HIGH", "LOW", "CLOSE", "SETTLE_PR"),
                strict=True,
            )
        }
        volume = _number(record["TtlTradgVol" if modern else "CONTRACTS"])
        if volume != int(volume):
            raise ValueError("Invalid NSE traded-contract count")
        valid_ohlc = (
            0
            < prices["low"]
            <= min(prices["open"], prices["close"])
            <= max(prices["open"], prices["close"])
            <= prices["high"]
        )
        if volume > 0 and not valid_ohlc:
            raise ValueError("Traded NSE contract has inconsistent OHLC")
        lot = _number(record.get("NewBrdLotQty"), optional=True) if modern else None
        if lot is not None and (lot <= 0 or lot != int(lot)):
            raise ValueError("Invalid NSE lot size")
        rows.append(
            {
                "session": day.isoformat(),
                "underlying": symbol,
                "expiry": expiry.isoformat(),
                "strike": strike,
                "option_type": option_type,
                "scheduled_expiry": scheduled_expiry.isoformat(),
                "instrument_id": instrument_id,
                "instrument_name": record.get("FinInstrmNm") if modern else None,
                **prices,
                "traded_contracts": int(volume),
                "open_interest_units": _number(record["OpnIntrst" if modern else "OPEN_INT"]),
                "oi_change_units": _number(
                    record["ChngInOpnIntrst" if modern else "CHG_IN_OI"], signed=True
                ),
                "lot_size": int(lot) if lot else None,
                "underlying_close": _number(record.get("UndrlygPric"), optional=True)
                if modern
                else None,
                "observed_trade": volume > 0 and valid_ohlc,
            }
        )
    if not rows:
        raise ValueError("NSE file contains no option observations")
    return rows, {
        "quality": "daily_observations_only",
        "intraday_eligible": False,
        "source_rows": source_rows,
        "option_rows": len(rows),
        "untraded_rows": sum(not row["observed_trade"] for row in rows),
        "format": "udiff" if modern else "legacy",
    }


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("wb") as output:
            output.write(raw)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _save(path, value):
    _atomic(path, json.dumps(value, allow_nan=False, separators=(",", ":")).encode())


def manifest(root=ROOT):
    try:
        return json.loads((root / "manifest.json").read_text())
    except FileNotFoundError:
        return {"version": VERSION, "provider": "NSE", "source": SOURCE, "days": {}}


@contextmanager
def archive_lock(root):
    """OS ownership survives web restarts and releases on worker death."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "download.lock").open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("An NSE download is already running.") from error
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def is_running(root=ROOT):
    try:
        with archive_lock(root):
            return False
    except ValueError:
        return True


def status(root=ROOT):
    data = manifest(root)
    days = data["days"]
    available = sorted(day for day, item in days.items() if item["status"] == "available")
    result = {
        "status": data.get("status", "empty"),
        "session_count": len(available),
        "start": available[0] if available else None,
        "end": available[-1] if available else None,
        "requested_start": data.get("requested_start"),
        "requested_end": data.get("requested_end"),
        "processed_dates": data.get("processed_dates", 0),
        "total_dates": data.get("total_dates", 0),
        "unavailable_count": sum(item["status"] == "unavailable" for item in days.values()),
        "error_count": sum(item["status"] == "error" for item in days.values()),
        "option_rows": sum(
            item.get("option_rows", 0) for item in days.values() if item["status"] == "available"
        ),
        "message": data.get("message"),
        "updated_at": data.get("updated_at"),
        "source": SOURCE,
        "intraday_eligible": False,
    }
    if result["status"] == "running" and not is_running(root):
        result.update(status="interrupted", message="Download stopped. Update history to resume.")
    return result


def _cached(root, day, item):
    if item.get("status") != "available" or item.get("version") != VERSION:
        return False
    try:
        return all(
            _hash((root / folder / f"{day}{suffix}").read_bytes()) == item[key]
            for folder, suffix, key in [
                ("raw", ".zip", "sha256"),
                ("daily", ".json.gz", "daily_sha256"),
            ]
        )
    except FileNotFoundError:
        return False


def _saved_raw(root, day, item):
    if item.get("status") != "available":
        return None
    try:
        raw = (root / "raw" / f"{day}.zip").read_bytes()
        return raw if _hash(raw) == item.get("sha256") else None
    except FileNotFoundError:
        return None


def fetch(client, day):
    """Retry a transient connection/server failure twice; never retry denial or throttling."""
    for attempt in range(3):
        try:
            return _fetch_once(client, day)
        except httpx.HTTPStatusError as error:
            if error.response.status_code < 500 or attempt == 2:
                raise
        except httpx.TransportError:
            if attempt == 2:
                raise
        time.sleep(2**attempt)


def _fetch_once(client, day):
    """Only public official archives; do not retry access denials on another host."""
    with client.stream("GET", archive_url(day), timeout=30, follow_redirects=False) as response:
        if response.status_code == 404:
            return None
        if response.status_code in (401, 403, 429):
            raise PermissionError("NSE has paused or refused downloads. Try updating later.")
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_ZIP:
                raise ValueError("NSE archive exceeds the download size limit")
            chunks.append(chunk)
        return b"".join(chunks)


def sync(
    root,
    start,
    end,
    *,
    client,
    delay=0.5,
    should_stop=lambda: False,
    retry_missing=False,
    executor=None,
    requested_at=None,
):
    if start < START or end >= today() or start > end:
        raise ValueError("Choose completed dates from 13 April 2020 onward.")
    requested_at = time.time() if requested_at is None else requested_at
    with archive_lock(root):
        data = manifest(root)
        data.update(
            status="running",
            message=None,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            total_dates=(end - start).days + 1,
            processed_dates=0,
        )

        def save():
            data["updated_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
            _save(root / "manifest.json", data)

        save()
        day = end
        pending = {}

        def needs_fetch(check_day):
            key = check_day.isoformat()
            item = data["days"].get(key, {})
            negative = (
                item.get("status") == "unavailable"
                and not retry_missing
                and time.time() - item.get("checked_at", 0) < 86400
            )
            return not _cached(root, key, item) and not negative

        while day >= start:
            try:
                cancelled = (root / "cancel").stat().st_mtime >= requested_at
            except FileNotFoundError:
                cancelled = False
            if should_stop() or cancelled:
                data.update(
                    status="interrupted", message="Download paused. Update history to resume."
                )
                break
            key = day.isoformat()
            if executor:
                # At most three public archive responses in memory; never enqueue the whole range.
                for offset in range(3):
                    upcoming = day - timedelta(days=offset)
                    if (
                        upcoming >= start
                        and upcoming not in pending
                        and needs_fetch(upcoming)
                        and _saved_raw(
                            root, upcoming.isoformat(), data["days"].get(upcoming.isoformat(), {})
                        )
                        is None
                    ):
                        pending[upcoming] = executor.submit(fetch, client, upcoming)
            if needs_fetch(day):
                try:
                    raw = _saved_raw(root, key, data["days"].get(key, {}))
                    if raw is None:
                        raw = pending.pop(day).result() if day in pending else fetch(client, day)
                    if raw is None:
                        item = {
                            "status": "unavailable",
                            "checked_at": time.time(),
                            "source": archive_url(day),
                        }
                    else:
                        rows, info = parse_archive(raw, day)
                        normalized = gzip.compress(
                            json.dumps(rows, separators=(",", ":"), allow_nan=False).encode(),
                            compresslevel=1,
                            mtime=0,
                        )
                        _atomic(root / "raw" / f"{key}.zip", raw)
                        _atomic(root / "daily" / f"{key}.json.gz", normalized)
                        item = {
                            "status": "available",
                            "version": VERSION,
                            "source": archive_url(day),
                            "sha256": _hash(raw),
                            "daily_sha256": _hash(normalized),
                            **info,
                        }
                    data["days"][key] = item
                except PermissionError as error:
                    data.update(status="blocked", message=str(error))
                    break
                except httpx.HTTPError:
                    from utils.logging import get_logger

                    get_logger(__name__).exception("NSE download connection failed for %s", key)
                    data.update(
                        status="failed",
                        message="NSE history could not be downloaded. Check your connection and update history to resume.",
                    )
                    break
                except Exception:
                    from utils.logging import get_logger

                    get_logger(__name__).exception("NSE daily import failed for %s", key)
                    data["days"][key] = {"status": "error", "source": archive_url(day)}
                if delay:
                    time.sleep(delay)
            data["processed_dates"] += 1
            save()
            day -= timedelta(days=1)
        else:
            gaps = any(
                item["status"] != "available"
                for day, item in data["days"].items()
                if start.isoformat() <= day <= end.isoformat()
            )
            data["status"] = "completed_with_gaps" if gaps else "completed"
        for future in pending.values():
            future.cancel()
        save()
    return status(root)


def snapshot(root=ROOT, symbol="NIFTY", *, before=None, limit=20):
    """Strictly prior-session observations, never same-day information in past signals."""
    before = before or today()
    days = manifest(root)["days"]
    dates = sorted(
        (
            day
            for day, item in days.items()
            if item["status"] == "available" and day < before.isoformat()
        ),
        reverse=True,
    )
    if not dates:
        return {"session": None, "contracts": [], "age_calendar_days": None}
    day = dates[0]
    raw = (root / "daily" / f"{day}.json.gz").read_bytes()
    if _hash(raw) != days[day]["daily_sha256"]:
        raise ValueError(
            "The saved daily file failed its integrity check. Update history to repair it."
        )
    rows = [
        row
        for row in json.loads(gzip.decompress(raw))
        if row["underlying"] == symbol and row["observed_trade"]
    ]
    rows.sort(
        key=lambda row: (-row["traded_contracts"], row["expiry"], row["strike"], row["option_type"])
    )
    return {
        "session": day,
        "age_calendar_days": (before - date.fromisoformat(day)).days,
        "contracts": rows[:limit],
        "traded_contract_count": len(rows),
    }
