"""Session-authenticated research routes. Requests only validate and enqueue."""

from flask import Blueprint, jsonify, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from database.trading_research_db import get_store
from limiter import limiter
from services.research import jobs
from services.research.dataset import MAX_BODY_BYTES
from services.research.replay import CANDIDATES
from utils.session import is_session_valid

trading_research_bp = Blueprint("trading_research", __name__, url_prefix="/strategy/api/research")
_api_limit = limiter.shared_limit("120 per minute", scope="trading_research_api")


@trading_research_bp.before_request
def authenticate():
    request.max_content_length = MAX_BODY_BYTES
    if not session.get("user") or not is_session_valid():
        return jsonify(status="error", message="Sign in to use Strategy Research."), 401


def body():
    value = request.get_json()
    if not isinstance(value, dict):
        raise ValueError("Supply a JSON object")
    return value


def success(data, code=200):
    return jsonify(status="success", data=data), code


@trading_research_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(status="error", message=str(error)), 400


@trading_research_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(status="error", message="Research dataset or run not found."), 404


@trading_research_bp.errorhandler(BadRequest)
def malformed(error):
    return jsonify(
        status="error", message="The import could not be read. Check the JSON format."
    ), 400


@trading_research_bp.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(status="error", message="The import exceeds the 20 MB size limit."), 413


@trading_research_bp.errorhandler(429)
def rate_limited(error):
    return jsonify(status="error", message="Too many research requests. Try again shortly."), 429


@trading_research_bp.get("")
@_api_limit
def overview():
    data = get_store().overview(session["user"])
    data.update(
        candidates=CANDIDATES,
        limits={
            "capital": 10000,
            "first_trade_loss": 1000,
            "later_trades_loss": 1000,
            "daily_loss": 2000,
            "drawdown_pct": 20,
            "cash_buffer_pct": 20,
        },
    )
    return success(data)


@trading_research_bp.post("/datasets")
@_api_limit
def import_dataset():
    return success(jobs.import_dataset(get_store(), session["user"], body()), 201)


@trading_research_bp.post("/runs")
@_api_limit
def queue_run():
    return success(jobs.queue_run(get_store(), session["user"], body()), 202)


@trading_research_bp.get("/runs/<int:run_id>")
@_api_limit
def run_detail(run_id):
    data = get_store().get_run(session["user"], run_id)
    if data is None:
        raise LookupError()
    return success(data)


@trading_research_bp.post("/runs/<int:run_id>/cancel")
@_api_limit
def cancel_run(run_id):
    return success(get_store().cancel_run(session["user"], run_id))


@trading_research_bp.post("/runs/<int:run_id>/freeze")
@_api_limit
def freeze_run(run_id):
    return success(get_store().freeze_run(session["user"], run_id))


@trading_research_bp.post("/runs/<int:run_id>/final-test")
@_api_limit
def final_test(run_id):
    return success(jobs.queue_final(get_store(), session["user"], run_id), 202)


@trading_research_bp.get("/runs/<int:run_id>/release")
@_api_limit
def release_status(run_id):
    return success(jobs.release_status(get_store(), session["user"], run_id))
