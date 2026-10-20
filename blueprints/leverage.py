# blueprints/leverage.py
# Leverage configuration for crypto brokers (Delta Exchange)
# Stores a single common leverage value in leverage_config table.

import json
import os
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, session

from database.leverage_db import get_leverage, set_leverage
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

leverage_bp = Blueprint("leverage_bp", __name__, url_prefix="/leverage")

#: Where running Python strategies publish their open trade's risk numbers.
RISK_STATE_DIR = Path("strategies") / "risk_state"

#: Delta Exchange India trading fees on perpetual futures, % of notional per
#: fill, before 18% GST. Market orders pay taker.
DELTA_FEES = {"taker_pct": 0.05, "maker_pct": 0.02, "gst_pct": 18.0}

#: Maintenance margin on BTCUSD at the default tier, % of notional.
MAINTENANCE_MARGIN_PCT = 0.25

#: A file older than this is from a strategy that has stopped or hung.
STALE_SECONDS = 180


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _read_risk_states() -> list[dict]:
    states = []
    if not RISK_STATE_DIR.is_dir():
        return states
    now = datetime.now().astimezone()
    for path in sorted(RISK_STATE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        try:
            age = (now - datetime.fromisoformat(data.get("updated_at"))).total_seconds()
        except (TypeError, ValueError):
            age = None
        data["age_seconds"] = round(age) if age is not None else None
        data["running"] = _pid_alive(data.get("pid")) and age is not None and age < STALE_SECONDS
        states.append(data)
    return states


@leverage_bp.route("/api/current", methods=["GET"])
@check_session_validity
def get_current():
    """Get the current common leverage setting."""
    return jsonify({
        "status": "success",
        "leverage": get_leverage(),
    })


@leverage_bp.route("/api/risk", methods=["GET"])
@check_session_validity
def get_risk():
    """Leverage, fee schedule and each strategy's live SL/TP, for the Positions page."""
    from services.crypto_fee_service import fee_profile, profile_dict

    leverage = float(get_leverage() or 0)
    rt = 2 * DELTA_FEES["taker_pct"] * (1 + DELTA_FEES["gst_pct"] / 100)
    profile = fee_profile()
    broker_positions, broker_error = [], None
    if session.get('broker') == 'deltaexchange':
        try:
            from services.delta_profit_gateway import Gateway
            broker_positions = Gateway().view(session['user'])
        except Exception:
            broker_error = 'Broker leverage and protection could not be verified'
        finally:
            from utils.db_sessions import remove_all_scoped_sessions
            remove_all_scoped_sessions()
    return jsonify({
        "status": "success",
        "data": {
            "leverage": int(leverage) if leverage > 0 else None,
            "liquidation_move_pct": round(100 / leverage - MAINTENANCE_MARGIN_PCT, 3) if leverage > 0 else None,
            "maintenance_margin_pct": MAINTENANCE_MARGIN_PCT,
            "fees": {
                **DELTA_FEES,
                "gst_pct": profile.gst_pct,
                "round_trip_taker_pct": round(rt, 4),
            },
            "fee_profile": profile_dict(profile),
            "strategies": _read_risk_states(),
            "broker_positions": broker_positions,
            "broker_risk_error": broker_error,
        },
    })


@leverage_bp.route("/api/update", methods=["POST"])
@check_session_validity
def update_leverage():
    """
    Set common leverage for all crypto futures orders.
    Expects JSON: {"leverage": 10}
    """
    data = request.get_json()
    if data is None or "leverage" not in data:
        return jsonify({"status": "error", "message": "Missing leverage field"}), 400

    try:
        leverage = float(data["leverage"])
        import math
        if math.isnan(leverage) or math.isinf(leverage):
            return jsonify({"status": "error", "message": "Invalid leverage value"}), 400
        if leverage < 0:
            return jsonify({"status": "error", "message": "Leverage cannot be negative"}), 400
        if not leverage.is_integer():
            return jsonify({"status": "error", "message": "Leverage must be a whole number"}), 400
        leverage = int(leverage)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid leverage value"}), 400

    set_leverage(leverage)

    label = f"{int(leverage)}x" if leverage > 0 else "Default"
    return jsonify({
        "status": "success",
        "message": f"Leverage set to {label}",
    })
