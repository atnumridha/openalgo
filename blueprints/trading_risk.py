"""Authenticated allocation status and explicit operator risk reviews."""

from decimal import Decimal

from flask import Blueprint, jsonify, request, session
from sqlalchemy.exc import SQLAlchemyError

from database import trading_risk_db as ledger
from limiter import limiter
from services.research.costs import validate_cost_schedule
from services.strategy_module import trading_budget
from utils.session import is_session_valid

trading_risk_bp = Blueprint("trading_risk", __name__, url_prefix="/strategy/api/risk")
_limit = limiter.shared_limit("60 per minute", scope="trading_risk_api")


def _json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    return value


@trading_risk_bp.before_request
def authenticate():
    request.max_content_length = 65536
    if not session.get("user") or not is_session_valid():
        return jsonify(status="error", message="Sign in to view trading risk."), 401


@trading_risk_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(status="error", message=str(error)), 400


@trading_risk_bp.errorhandler(SQLAlchemyError)
def unavailable(_error):
    return jsonify(
        status="error", message="Trading risk records are unavailable. Entries remain blocked."
    ), 503


@trading_risk_bp.get("")
@_limit
def status():
    user = session["user"]
    accounts = {}
    for mode in ("sandbox", "live"):
        trading_budget.reconcile_account(user, mode)
        accounts[mode] = ledger.status(user, mode, trading_budget.trading_day())
    return jsonify(
        status="success",
        data=_json(
            {
                "policy": ledger.policy_payload(),
                "enabled": ledger.policy_enabled(user),
                "costs": ledger.get_costs(user),
                "accounts": accounts,
            }
        ),
    )


@trading_risk_bp.put("/costs")
@_limit
def costs():
    payload = validate_cost_schedule(request.get_json())
    user = session["user"]
    if not ledger.policy_enabled(user):
        from database import strategy_module_db as store

        if any(row.get("current_run_id") for row in store.list_strategies(user)):
            raise ValueError(
                "Stop and reconcile existing Strategy Module runs before enabling the capital profile"
            )
    ledger.set_costs(user, payload)
    return jsonify(status="success", data=payload)


@trading_risk_bp.post("/resume")
@_limit
def resume():
    payload = request.get_json()
    if not isinstance(payload, dict):
        raise ValueError("Supply a JSON object")
    user, mode = session["user"], payload.get("mode")
    if mode not in {"sandbox", "live"}:
        raise ValueError("Choose sandbox or live")
    trading_budget.reconcile_account(user, mode)
    ledger.resume(
        user,
        mode,
        trading_budget.trading_day(),
        payload.get("reason"),
        reconciled=payload.get("reconciled"),
    )
    return jsonify(
        status="success", data=_json(ledger.status(user, mode, trading_budget.trading_day()))
    )
