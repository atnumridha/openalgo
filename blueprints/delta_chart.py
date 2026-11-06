"""Authenticated, CSRF-protected manual Delta chart endpoints."""

import os
import threading
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, jsonify, request, session, current_app

from services.delta_chart.connection import Connections
from services.delta_chart.service import DeltaError, Rejected, Store, TradingService
from utils.session import check_session_validity

delta_chart_bp = Blueprint("delta_chart", __name__, url_prefix="/delta-chart/api")


@lru_cache(maxsize=1)
def service():
    store = Store(
        Path(
            os.getenv("DELTA_CHART_DB") or Path(__file__).resolve().parents[1] / "db/delta_chart.db"
        )
    )
    trading = TradingService(store, Connections(store))
    # This production factory is the only daemon startup point.  Constructing a
    # service in tests or tools never starts an execution worker.
    from services.delta_chart.worker import ProtectionWorker

    from services.delta_chart.automation import Automation, AutomationWorker
    app = current_app._get_current_object()
    trading.automation = Automation(trading)
    trading.enforce_server_automation = True
    trading.protection_worker = ProtectionWorker(trading, context_factory=app.app_context)
    trading.automation_worker = AutomationWorker(trading.automation, app.app_context)
    app.extensions["delta_chart_service"] = trading
    return trading


_background_lock = threading.Lock()


def start_background():
    # Called by worker startup or explicit Auto configuration POST, never GET.
    with _background_lock:
        trading = service()
        trading.protection_worker.start()
        trading.automation_worker.start()
    return trading


@delta_chart_bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@delta_chart_bp.get("/state")
@check_session_validity
def state():
    try:
        return jsonify(service().state(session["user"], request.args.get("symbol", "BTCUSD")))
    except DeltaError as exc:
        return jsonify(
            connected=False,
            environment="india_prod",
            symbol=request.args.get("symbol", "BTCUSD"),
            message=str(exc),
        )
    except Exception:
        return jsonify(
            connected=False,
            environment="india_prod",
            symbol=request.args.get("symbol", "BTCUSD"),
            message="Delta connection unavailable. Connect your India account or refresh after checking its permissions.",
        )


@delta_chart_bp.post("/connection")
@check_session_validity
def connection():
    data = request.get_json(silent=True) or {}
    try:
        trading = service()
        user = session["user"]
        with trading.plans.lock("delta-connection", user, "*"):
            trading.credentials.save(
                user,
                data.get("api_key", data.get("key")),
                data.get("api_secret", data.get("secret")),
            )
        return jsonify(status="confirmed", message="Encrypted Delta India connection saved")
    except DeltaError as exc:
        return jsonify(status="rejected", message=str(exc)), 400
    except Exception:
        return jsonify(status="rejected", message="Could not save Delta connection"), 400


@delta_chart_bp.post("/action")
@check_session_validity
def action():
    data = request.get_json(silent=True)
    try:
        if (
            isinstance(data, dict)
            and data.get("action") == "entry"
            and not isinstance(data.get("auto_protection"), dict)
        ):
            raise Rejected("Every chart entry requires a reviewed automatic stop and target plan")
        return jsonify(service().action(session["user"], data))
    except Rejected as exc:
        return jsonify(
            status="rejected",
            message=str(exc),
            request_id=data.get("request_id") if isinstance(data, dict) else None,
        ), 409
    except Exception:
        return jsonify(
            status="rejected",
            message="Delta trading unavailable; refresh account state",
        ), 503


@delta_chart_bp.post("/manage")
@check_session_validity
def manage():
    try:
        result = service().manage(session["user"], request.get_json(silent=True))
        return jsonify(result), 409 if result.get("status") == "rejected" else 200
    except Rejected as exc:
        return jsonify(status="rejected", message=str(exc)), 409
    except Exception:
        return jsonify(
            status="pending",
            message="Managed outcome unavailable; refresh state before another decision",
        ), 503


@delta_chart_bp.post("/ema")
@check_session_validity
def chart_ema():
    """Calculation only: this route never constructs the trading service."""
    from services.delta_chart.ema_chart import ema_chart_backfill

    body = request.get_json(silent=True)
    try:
        if not isinstance(body, dict):
            raise ValueError("Expected candle history")
        return jsonify(status="success", ema=ema_chart_backfill(body.get("candles"), body.get("interval_seconds"),
            allow_session_gaps=body.get("allow_session_gaps", False)))
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400


@delta_chart_bp.post("/automation")
@check_session_validity
def automation():
    try:
        value = service().automation.configure(session["user"], request.get_json(silent=True))
        if value.get("enabled"):
            start_background()
        return jsonify(status="confirmed", automation=value)
    except (Rejected, DeltaError) as exc:
        return jsonify(status="rejected", message=str(exc)), 400
    except Exception:
        return jsonify(status="rejected", message="Auto configuration could not be confirmed. Refresh backend status before trying again."), 503
