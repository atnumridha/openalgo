"""Authenticated ML Signals research/training API.

Long downloads/search/training jobs are single-flight background jobs. The
frontend can poll status without blocking Flask workers.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, jsonify, request

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)
ml_signals_bp = Blueprint("ml_signals_bp", __name__, url_prefix="/ml/api")
_LIVE_INTERVALS = ("1m", "3m", "5m", "15m")

_JOB_LOCK = threading.Lock()
_JOB: dict[str, Any] = {
    "busy": False,
    "job": None,
    "progress": 0.0,
    "message": "idle",
    "error": None,
    "started_at": None,
    "finished_at": None,
}


def _snapshot() -> dict[str, Any]:
    with _JOB_LOCK:
        return dict(_JOB)


def _update(**values: Any) -> None:
    with _JOB_LOCK:
        _JOB.update(values)


def _run_job(job: str, callback) -> None:
    _update(
        busy=True,
        job=job,
        progress=0.0,
        message="starting",
        error=None,
        started_at=datetime.now(UTC).isoformat(),
        finished_at=None,
    )
    try:
        result = callback()
        _update(
            busy=False,
            progress=1.0,
            message="complete",
            result=result,
            finished_at=datetime.now(UTC).isoformat(),
        )
    except Exception:
        logger.exception("ML job %s failed", job)
        _update(
            busy=False,
            message="failed",
            error="This job stopped with an error. Details are in the error log.",
            finished_at=datetime.now(UTC).isoformat(),
        )


def _start(job: str, callback) -> bool:
    with _JOB_LOCK:
        if _JOB["busy"]:
            return False
        _JOB.update(
            busy=True,
            job=job,
            progress=0.0,
            message="starting",
            error=None,
            result=None,
            started_at=datetime.now(UTC).isoformat(),
            finished_at=None,
        )
    thread = threading.Thread(target=_run_job, args=(job, callback), daemon=True, name=f"ml-{job}")
    thread.start()
    return True


def _core_module(name: str):
    return __import__(f"ml_signals.{name}", fromlist=[name])


def _json_error(message: str, code: int = 400):
    return jsonify({"status": "error", "message": message}), code


def _symbol() -> str | None:
    value = request.args.get("symbol")
    if value is None:
        return None
    value = value.strip()
    return value or None


@ml_signals_bp.route("/status", methods=["GET"])
@check_session_validity
def status():
    payload = _snapshot()
    try:
        from ml_signals.worker_store import read_status

        payload["worker"] = read_status()
    except Exception:
        payload["worker"] = None
    try:
        from services.ml_worker_manager import status as worker_status

        payload["worker_process"] = worker_status()
    except Exception:
        payload["worker_process"] = None
    return jsonify({"status": "success", "data": payload})


@ml_signals_bp.route("/coverage", methods=["GET"])
@check_session_validity
def coverage():
    symbol = _symbol()
    try:
        report = _core_module("data").coverage_report(symbol=symbol)
        return jsonify({"status": "success", "data": {"sources": report}})
    except Exception as exc:
        logger.exception("ML coverage failed")
        return _json_error(str(exc), 500)


@ml_signals_bp.route("/data/refresh", methods=["POST"])
@check_session_validity
def refresh():
    payload = request.get_json(silent=True) or {}
    symbol = payload.get("symbol") if isinstance(payload, dict) else None

    def callback():
        data_module = _core_module("data")
        source_names = tuple(data_module.sources_for(symbol))
        total_sources = max(1, len(source_names))
        completed_sources = 0

        def progress(source: str, page: int, total_pages: int) -> None:
            page_fraction = page / max(1, total_pages)
            _update(
                progress=min(0.99, (completed_sources + page_fraction) / total_sources),
                message=f"refreshing {source} · page {page}/{total_pages}",
            )

        def refresh_source(source: str) -> dict[str, Any]:
            nonlocal completed_sources
            result = data_module.download_source(source, days=365, progress=progress, symbol=symbol)
            completed_sources += 1
            _update(
                progress=completed_sources / total_sources,
                message=f"refreshed {source}",
            )
            return result

        return {source: refresh_source(source) for source in source_names}

    if not _start("data_refresh", callback):
        return _json_error("Another ML job is already running", 409)
    return jsonify({"status": "success", "message": "ML data refresh started"}), 202


@ml_signals_bp.route("/sentiment", methods=["GET"])
@check_session_validity
def sentiment():
    interval = request.args.get("interval", "15m")
    symbol = _symbol()
    if interval not in _LIVE_INTERVALS:
        return _json_error("Choose a 1m, 3m, 5m or 15m interval.")
    try:
        value = _core_module("predict").current_sentiment(interval, symbol=symbol)
        return jsonify({"status": "success", "data": value})
    except Exception as exc:
        return _json_error(str(exc), 500)


@ml_signals_bp.route("/settings", methods=["GET"])
@check_session_validity
def get_settings():
    from database.ml_settings_db import get_settings as read
    from database.ml_settings_db import public_settings

    return jsonify({"status": "success", "data": public_settings(read())})


@ml_signals_bp.route("/settings", methods=["POST"])
@check_session_validity
def save_settings():
    from database.ml_settings_db import public_settings, update_settings

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_error("Send the settings as an object.")
    settings, problems = update_settings(payload)
    if problems:
        return jsonify(
            {"status": "error", "message": " ".join(problems), "data": public_settings(settings)}
        ), 400
    return jsonify({"status": "success", "data": public_settings(settings)})


@ml_signals_bp.route("/live", methods=["GET"])
@check_session_validity
def live():
    interval = request.args.get("interval", "15m")
    symbol = _symbol()
    if interval not in _LIVE_INTERVALS:
        return _json_error("Choose a 1m, 3m, 5m or 15m interval.")
    try:
        from ml_signals import data as data_module
        from ml_signals.worker_store import read_live_snapshot

        symbol_name = data_module.normalize_symbol(symbol)
        value = read_live_snapshot(symbol_name, interval)
        if value is None:
            value = {
                "state": "starting",
                "symbol": symbol_name,
                "interval": interval,
                "feed": "Waiting for the ML worker to publish snapshots.",
                "server_time": time.time(),
                "sources": {},
            }
        return jsonify({"status": "success", "data": value})
    except Exception:
        logger.exception("ML live signal request failed")
        return _json_error(
            "The live signal is unavailable right now. Details are in the error log.",
            500,
        )


@ml_signals_bp.route("/labels/preview", methods=["GET"])
@check_session_validity
def label_preview():
    symbol = _symbol()
    try:
        stop = min(0.2, max(0.01, float(request.args.get("stop_pct", 0.2))))
        target = min(2.0, max(0.05, float(request.args.get("target_pct", 0.6))))
        hold = min(28, max(1, int(request.args.get("hold_minutes", 28))))
        value = _core_module("predict").label_preview(stop, target, hold, symbol=symbol)
        return jsonify({"status": "success", "data": value})
    except (TypeError, ValueError) as exc:
        return _json_error(str(exc))
    except Exception as exc:
        return _json_error(str(exc), 500)


@ml_signals_bp.route("/search", methods=["POST"])
@check_session_validity
def search():
    payload = request.get_json(silent=True) or {}
    symbol = payload.get("symbol") if isinstance(payload, dict) else None

    if not _start("rule_search", lambda: _core_module("predict").run_rule_search(symbol=symbol)):
        return _json_error("Another ML job is already running", 409)
    return jsonify({"status": "success", "message": "ML rule search started"}), 202


@ml_signals_bp.route("/train", methods=["POST"])
@check_session_validity
def train():
    payload = request.get_json(silent=True) or {}
    symbol = payload.get("symbol") if isinstance(payload, dict) else None
    try:
        config = _core_module("train").TrainConfig(
            stop_pct=min(0.2, max(0.01, float(payload.get("stop_pct", 0.2)))),
            target_pct=min(2.0, max(0.05, float(payload.get("target_pct", 0.6)))),
            hold_minutes=min(28, max(1, int(payload.get("hold_minutes", 28)))),
            fee_plan=str(payload.get("fee_plan", "scalper+diwali")),
            minimum_probability=min(
                0.99,
                max(0.34, float(payload.get("minimum_probability", 0.55))),
            ),
            sentiment_enabled=bool(payload.get("sentiment_enabled", True)),
        )
    except (TypeError, ValueError) as exc:
        return _json_error(str(exc))

    def callback():
        return _core_module("predict").run_training(config, _update, symbol=symbol)

    if not _start("training", callback):
        return _json_error("Another ML job is already running", 409)
    return jsonify({"status": "success", "message": "ML training started"}), 202


@ml_signals_bp.route("/models", methods=["GET"])
@check_session_validity
def models():
    symbol = _symbol()
    try:
        models_list = _core_module("train").list_models(symbol=symbol)
        return jsonify({"status": "success", "data": {"models": models_list}})
    except Exception as exc:
        return _json_error(str(exc), 500)


@ml_signals_bp.route("/models/<version>/activate", methods=["POST"])
@check_session_validity
def activate(version: str):
    payload = request.get_json(silent=True) or {}
    symbol = payload.get("symbol") if isinstance(payload, dict) else None
    try:
        value = _core_module("train").activate_model(version, symbol=symbol)
        return jsonify({"status": "success", "data": value})
    except FileNotFoundError:
        return _json_error("Model version not found", 404)
    except Exception as exc:
        return _json_error(str(exc), 500)


@ml_signals_bp.route("/predict", methods=["GET"])
@check_session_validity
def predict_api():
    interval = request.args.get("interval", "15m")
    symbol = _symbol()
    try:
        from_time = int(request.args["from"]) if request.args.get("from") else None
        to_time = int(request.args["to"]) if request.args.get("to") else None
        value = _core_module("predict").predict(
            interval,
            from_time,
            to_time,
            symbol=symbol,
        )
        return jsonify({"status": "success", "data": value})
    except Exception as exc:
        return _json_error(str(exc), 500)


def _mode() -> str:
    value = (request.args.get("mode") or "sandbox").lower()
    return value if value in ("sandbox", "live") else "sandbox"


@ml_signals_bp.route("/suggestions", methods=["GET"])
@check_session_validity
def suggestions():
    """A sized suggestion per shortlist symbol for one interval and mode."""
    from flask import session

    from database.ml_settings_db import get_settings
    from services.ml_trade_service import suggestion

    interval = request.args.get("interval", "5m")
    if interval not in _LIVE_INTERVALS:
        return _json_error("Choose a 1m, 3m, 5m or 15m interval.")
    use = "forming" if request.args.get("use") == "forming" else "closed"
    mode = _mode()
    try:
        values = [
            suggestion(symbol, interval, mode=mode, user_id=session.get("user"), use=use)
            for symbol in get_settings().get("symbols") or []
        ]
        return jsonify({"status": "success", "data": values})
    except Exception:
        logger.exception("ML suggestions failed")
        return _json_error(
            "Suggestions are unavailable right now. Details are in the error log.", 500
        )


@ml_signals_bp.route("/trade", methods=["POST"])
@check_session_validity
def trade():
    """Open the suggested trade now, in Sandbox or Live."""
    from flask import session

    from services.ml_trade_service import place_trade

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_error("Send the trade as an object.")
    user_id = session.get("user")
    if not user_id:
        return _json_error("Log in again to trade.", 401)
    mode = str(payload.get("mode") or "").lower()
    interval = str(payload.get("interval") or "")
    action = str(payload.get("action") or "").upper()
    if mode not in ("sandbox", "live"):
        return _json_error("Choose Sandbox or Live.")
    if interval not in _LIVE_INTERVALS:
        return _json_error("Choose a 1m, 3m, 5m or 15m interval.")
    if action not in ("LONG", "SHORT"):
        return _json_error("Only a LONG or SHORT suggestion can be traded.")
    try:
        expected = payload.get("contracts")
        expected = int(expected) if expected is not None else None
    except (TypeError, ValueError):
        return _json_error("The contract count must be a whole number.")
    try:
        result = place_trade(
            user_id=user_id,
            symbol=str(payload.get("symbol") or ""),
            interval=interval,
            mode=mode,
            expected_action=action,
            expected_contracts=expected,
        )
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception:
        logger.exception("ML trade failed")
        return _json_error("The trade could not be placed. Details are in the error log.", 500)
    status = "success" if result["ok"] else "error"
    return jsonify({"status": status, "message": result["message"], "data": result}), (
        200 if result["ok"] else 409
    )


@ml_signals_bp.route("/trades", methods=["GET"])
@check_session_validity
def trades():
    """Open ML trades with live net P&L, and the latest closed ones."""
    from flask import session

    from services.ml_trade_service import open_trades, recent_closed

    user_id = session.get("user")
    try:
        return jsonify(
            {
                "status": "success",
                "data": {"open": open_trades(user_id), "closed": recent_closed(user_id)},
            }
        )
    except Exception:
        logger.exception("ML trades listing failed")
        return _json_error(
            "Open trades are unavailable right now. Details are in the error log.", 500
        )


@ml_signals_bp.route("/trades/<int:run_id>/<leg_id>/close", methods=["POST"])
@check_session_validity
def close_trade_api(run_id: int, leg_id: str):
    from flask import session

    from services.ml_trade_service import close_trade

    result = close_trade(session.get("user"), run_id, leg_id)
    return jsonify(
        {"status": "success" if result["ok"] else "error", "message": result["message"]}
    ), (200 if result["ok"] else 409)


@ml_signals_bp.route("/retrain", methods=["POST"])
@check_session_validity
def retrain_now():
    """Ask the worker to save history and retrain now, for one symbol or the shortlist."""
    from database.ml_settings_db import get_settings
    from ml_signals import data as data_module
    from ml_signals.worker_store import request_retrain

    payload = request.get_json(silent=True) or {}
    raw = payload.get("symbol") if isinstance(payload, dict) else None
    try:
        symbols = (
            [data_module.normalize_symbol(raw)]
            if raw
            else [data_module.normalize_symbol(s) for s in get_settings().get("symbols") or []]
        )
    except ValueError as exc:
        return _json_error(str(exc))
    request_retrain(symbols)
    return jsonify(
        {
            "status": "success",
            "message": f"Saving history and retraining {', '.join(symbols)} in the background.",
        }
    ), 202


# ---------------------------------------------------------------------------
# Worker-only endpoints: loopback, and the secret the worker was started with
# ---------------------------------------------------------------------------


def _worker_allowed() -> bool:
    from services.ml_worker_manager import check_worker_secret

    if request.remote_addr not in ("127.0.0.1", "::1"):
        return False
    return check_worker_secret(request.headers.get("X-ML-Worker-Secret"))


def _ml_owner() -> str | None:
    """The single user the ML strategies belong to."""
    from database import strategy_module_db as store
    from database.ml_settings_db import get_settings

    settings = get_settings()
    for key in ("sandbox_strategy_id", "live_strategy_id"):
        strategy_id = settings.get(key)
        if strategy_id:
            row = store.get_strategy_unscoped(int(strategy_id))
            if row is not None:
                return str(row.user_id)
    return None


@ml_signals_bp.route("/worker/trades", methods=["GET"])
def worker_trades():
    if not _worker_allowed():
        return _json_error("Not found", 404)
    from services.ml_trade_service import open_trades

    owner = _ml_owner()
    return jsonify({"status": "success", "data": open_trades(owner) if owner else []})


@ml_signals_bp.route("/worker/reconcile", methods=["POST"])
def worker_reconcile():
    """Mark closed any Live ML leg that Delta no longer holds."""
    if not _worker_allowed():
        return _json_error("Not found", 404)
    from services.ml_trade_service import reconcile_live

    owner = _ml_owner()
    settled = reconcile_live(owner) if owner else []
    return jsonify({"status": "success", "data": settled})


@ml_signals_bp.route("/worker/exit", methods=["POST"])
def worker_exit():
    """Send a smart exit through the strategy's own webhook, so it is audited like any signal."""
    if not _worker_allowed():
        return _json_error("Not found", 404)
    from database import strategy_module_db as store
    from database.ml_settings_db import get_settings
    from services.ml_trade_service import webhook_token
    from services.strategy_module import state
    from services.strategy_module.webhook import handle_webhook

    payload = request.get_json(silent=True) or {}
    try:
        run_id = int(payload.get("run_id"))
    except (TypeError, ValueError):
        return _json_error("run_id is required")
    leg_id = payload.get("leg_id")
    run = store.get_run(run_id)
    settings = get_settings()
    if run is None or run.strategy_id not in {
        settings.get("sandbox_strategy_id"),
        settings.get("live_strategy_id"),
    }:
        return _json_error("That is not an ML trade.", 404)
    snapshot = state.get_run_state(run_id) or {}
    leg = (snapshot.get("legs") or {}).get(str(leg_id))
    if not leg or leg.get("status") != "open":
        return _json_error("That trade is not open.", 409)
    strategy = store.get_strategy_unscoped(int(run.strategy_id))
    token = webhook_token(str(strategy.user_id), int(strategy.id))
    if not token:
        return _json_error("The ML strategy has no webhook token.", 500)
    action = "long_exit" if leg.get("position") == "B" else "short_exit"
    store.record_event(
        int(strategy.id),
        str(strategy.user_id),
        "ml_smart_exit",
        f"Smart exit on leg {leg_id}: {str(payload.get('detail') or '')[:300]}",
        run_id=run_id,
        leg_id=leg_id,
    )
    outcome = handle_webhook(
        token,
        {"action": action, "leg_id": leg_id},
        ip="127.0.0.1",
        user_agent="openalgo-ml-worker",
    )
    body = outcome.body if hasattr(outcome, "body") else {}
    ok = bool(getattr(outcome, "ok", False))
    return jsonify({"status": "success" if ok else "error", "data": body}), (200 if ok else 409)
