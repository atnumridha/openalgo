"""Authenticated, bounded review actions; evidence arrives only from execution."""

from flask import Blueprint, jsonify, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from limiter import limiter
from services.research import qualification
from utils.session import is_session_valid

strategy_qualification_bp = Blueprint(
    "strategy_qualification", __name__, url_prefix="/strategy/api/qualification"
)
_limit = limiter.shared_limit("120 per minute", scope="strategy_qualification_api")


@strategy_qualification_bp.before_request
def authenticate():
    request.max_content_length = 65536
    if not session.get("user") or not is_session_valid():
        return jsonify(status="error", message="Sign in to review strategy qualification."), 401


def body():
    value = request.get_json()
    if not isinstance(value, dict):
        raise ValueError("Supply a JSON object")
    return value


def success(data, code=200):
    return jsonify(status="success", data=data), code


@strategy_qualification_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(status="error", message=str(error)), 400


@strategy_qualification_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(status="error", message="Qualification campaign or research run not found."), 404


@strategy_qualification_bp.errorhandler(BadRequest)
def malformed(error):
    return jsonify(status="error", message="The request must contain valid JSON."), 400


@strategy_qualification_bp.errorhandler(RequestEntityTooLarge)
def oversized(error):
    return jsonify(status="error", message="Qualification requests must be below 64 KB."), 413


@strategy_qualification_bp.errorhandler(429)
def rate_limited(error):
    return jsonify(
        status="error", message="Too many qualification requests. Try again shortly."
    ), 429


@strategy_qualification_bp.get("")
@_limit
def overview():
    return success(qualification.overview(session["user"]))


@strategy_qualification_bp.post("/campaigns")
@_limit
def create_campaign():
    return success(qualification.create_campaign(session["user"], body()), 201)


@strategy_qualification_bp.get("/campaigns/<int:campaign_id>")
@_limit
def detail(campaign_id):
    return success(qualification.detail(session["user"], campaign_id))


@strategy_qualification_bp.post("/campaigns/<int:campaign_id>/reconcile")
@_limit
def reconcile(campaign_id):
    return success(qualification.reconcile(session["user"], campaign_id, body()))


@strategy_qualification_bp.post("/campaigns/<int:campaign_id>/approve")
@_limit
def approve(campaign_id):
    return success(qualification.approve(session["user"], campaign_id, body()))


@strategy_qualification_bp.post("/campaigns/<int:campaign_id>/revoke")
@_limit
def revoke(campaign_id):
    return success(qualification.revoke(session["user"], campaign_id, body()))
