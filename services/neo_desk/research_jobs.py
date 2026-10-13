"""Bounded native research jobs; pure replay never shares an order pipe."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal as D
from hashlib import sha256
from threading import BoundedSemaphore

from sqlalchemy.exc import IntegrityError

from database import neo_history_db as db
from utils.db_sessions import remove_all_scoped_sessions
from utils.logging import get_logger

from .datasets import load_dataset
from .replay import ReplayRequest, run_replay

pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neo-research")
slots = BoundedSemaphore(3)


def parse_request(body):
    required = {"request_id", "dataset", "profile", "symbol", "expiry", "start", "end", "compound"}
    if (
        not isinstance(body, dict)
        or set(body) != required
        or not isinstance(body["compound"], bool)
        or not isinstance(body["request_id"], str)
        or not 1 <= len(body["request_id"]) <= 100
    ):
        raise ValueError(
            "Choose the dataset, preset, expiry and dates; a request identity is required."
        )
    request = ReplayRequest(
        body["dataset"],
        body["profile"],
        body["symbol"],
        date.fromisoformat(body["expiry"]),
        date.fromisoformat(body["start"]),
        date.fromisoformat(body["end"]),
        compound=body["compound"],
    )
    if (
        request.symbol != "NIFTY"
        or request.end < request.start
        or (request.end - request.start).days > 366
    ):
        raise ValueError("Choose NIFTY and a date range up to one year.")
    from .presets import get_preset

    get_preset(request.profile)
    return request


def get_job(owner, identity):
    db.init_db()
    row = db.db_session.query(db.NeoResearchJob).filter_by(owner=owner, id=identity).first()
    if not row:
        raise ValueError("Research job was not found for this owner.")
    return {
        "id": row.id,
        "status": row.status,
        "request": row.request,
        "result": row.result,
        "error": row.error,
    }


def _execute(owner, identity, request):
    try:
        db.db_session.query(db.NeoResearchJob).filter_by(id=identity, owner=owner).update(
            {"status": "running"}
        )
        db.db_session.commit()
        report = run_replay(load_dataset(request.dataset), request)
        db.db_session.query(db.NeoResearchJob).filter_by(id=identity, owner=owner).update(
            {"status": "complete", "result": report}
        )
        db.db_session.commit()
    except Exception as error:
        db.db_session.rollback()
        get_logger(__name__).exception("Neo historical replay failed")
        db.db_session.query(db.NeoResearchJob).filter_by(id=identity, owner=owner).update(
            {
                "status": "failed",
                "error": public_error(error),
            }
        )
        db.db_session.commit()
    finally:
        remove_all_scoped_sessions()
        slots.release()


def submit_job(owner, body):
    from utils.runtime import worker_class

    if worker_class() == "eventlet":
        raise ValueError(
            "Native backtests require the gthread worker; replay refused to preserve protection responsiveness."
        )
    request = parse_request(body)
    db.init_db()
    identity = sha256((owner + "\0" + body["request_id"]).encode()).hexdigest()
    old = db.db_session.query(db.NeoResearchJob).filter_by(id=identity, owner=owner).first()
    if old:
        if old.request != body:
            raise ValueError("Request identity conflicts with a different replay.")
        return get_job(owner, identity)
    if not slots.acquire(blocking=False):
        raise ValueError("Research queue is full. Wait for a current replay to finish.")
    try:
        db.db_session.add(
            db.NeoResearchJob(id=identity, owner=owner, status="queued", request=body)
        )
        db.db_session.commit()
    except IntegrityError:
        db.db_session.rollback()
        slots.release()
        result = get_job(owner, identity)
        if result["request"] != body:
            raise ValueError("Request identity conflicts with a different replay.") from None
        return result
    except Exception:
        db.db_session.rollback()
        slots.release()
        raise
    try:
        pool.submit(_execute, owner, identity, request)
    except Exception:
        slots.release()
        db.db_session.query(db.NeoResearchJob).filter_by(id=identity, owner=owner).update(
            {"status": "failed", "error": "Research worker could not start."}
        )
        db.db_session.commit()
        raise
    return get_job(owner, identity)


def recover_jobs():
    db.init_db()
    db.db_session.query(db.NeoResearchJob).filter(
        db.NeoResearchJob.status.in_(["queued", "running"])
    ).update({"status": "failed", "error": "Application restarted; submit a new research request."})
    db.db_session.commit()


def public_error(error):
    text = str(error)
    if isinstance(error, ValueError):
        messages = {
            "Index 15-minute and option 1-minute observations are required.": "This archive lacks verified 15-minute NIFTY and 1-minute option observations. Choose the verified NIFTY 13-Oct archive.",
            "Dataset checksum mismatch; replay refused.": "Dataset checksum mismatch. Restore the verified archive before replaying.",
            "Choose a preserved real dataset.": "This dataset is unavailable or incompatible. Refresh the dataset list and choose a verified archive.",
            "Invalid observed OHLC.": "The archive contains invalid OHLC observations. Replay stopped; source repair is required.",
        }
        if text in messages:
            return messages[text]
    return "Replay failed; verify source checksums, coverage and native logs."
