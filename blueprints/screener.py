"""Session-authenticated screener routes; global Flask-WTF CSRF stays enabled."""

from flask import Blueprint, jsonify, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from database import screener_db as db
from services import screener as service
from utils.session import is_session_valid

screener_bp = Blueprint("screener", __name__, url_prefix="/screener/api")


@screener_bp.before_request
def authorize():
    if not session.get("user") or not is_session_valid():
        return jsonify(error="Sign in to use the screener"), 401
    # Per-blueprint body limit, including chunked requests. The application
    # default permits much larger imports elsewhere.
    request.max_content_length = service.MAX_PAYLOAD


@screener_bp.errorhandler(db.NotFound)
def not_found(error):
    return jsonify(error=str(error)), 404


@screener_bp.errorhandler(db.Conflict)
def conflict(error):
    return jsonify(error=str(error)), 409


@screener_bp.errorhandler(ValueError)
@screener_bp.errorhandler(TypeError)
@screener_bp.errorhandler(BadRequest)
def invalid(error):
    return jsonify(
        error="Invalid screener request"
        if isinstance(error, (TypeError, BadRequest))
        else str(error)
    ), 400


@screener_bp.errorhandler(RequestEntityTooLarge)
def oversized(error):
    return jsonify(error="Screener request exceeds 256 KB"), 413


def payload():
    value = request.get_json()
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def credentials():
    # Tokens are read only within the authorized request, passed by value into
    # bounded tasks, and never exposed in a response or stored in a job record.
    from database.auth_db import get_auth_token, get_feed_token

    owner = session["user"]
    broker = session.get("broker")
    if not isinstance(broker, str) or not broker:
        return {}
    return {
        "auth_token": get_auth_token(owner),
        "feed_token": get_feed_token(owner),
        "broker": broker,
    }


@screener_bp.get("/universes")
def universes():
    return jsonify(service.universes(session["user"]))


@screener_bp.get("/screens")
def screens():
    return jsonify(screens=db.list_screens(session["user"]))


@screener_bp.post("/screens")
def create_screen():
    return jsonify(screen=db.save_screen(session["user"], payload().get("definition"))), 201


@screener_bp.put("/screens/<int:screen_id>")
def update_screen(screen_id):
    body = payload()
    return jsonify(
        screen=db.save_screen(
            session["user"], body.get("definition"), screen_id, body.get("expected_revision")
        )
    )


@screener_bp.delete("/screens/<int:screen_id>")
def delete_screen(screen_id):
    db.delete_screen(session["user"], screen_id)
    return jsonify(ok=True)


@screener_bp.get("/screens/<int:screen_id>/events")
def events(screen_id):
    return jsonify(events=db.get_events(session["user"], screen_id))


@screener_bp.post("/screens/<int:screen_id>/events")
def add_events(screen_id):
    body = payload()
    return jsonify(
        events=db.add_events(
            session["user"], screen_id, body.get("revision"), body.get("mode"), body.get("events")
        )
    )


@screener_bp.post("/data")
def data():
    body = payload()
    mode = body.get("mode")
    interval = body.get("interval")
    refresh = body.get("refresh", False)
    if (
        mode not in {"live", "analyzer"}
        or interval not in service.FRAMES
        or type(refresh) is not bool
    ):
        raise ValueError("Invalid mode, interval or refresh")
    items = service.validate_items(body.get("items"), 25 if refresh else 500)
    if refresh:
        return jsonify(
            service.start_job(session["user"], mode, items, interval, credentials())
        ), 202
    try:
        catalog = service.read_catalog()
    except Exception:
        catalog = []
    return jsonify(
        status="complete",
        datasets=[
            service.stored_dataset(
                session["user"], mode, item, interval, broker=session.get("broker"), catalog=catalog
            )
            for item in items
        ],
    )


@screener_bp.get("/data/<job_id>")
def job(job_id):
    return jsonify(service.job_result(session["user"], job_id))


@screener_bp.delete("/data/<job_id>")
def cancel_job(job_id):
    return jsonify(service.cancel_job(session["user"], job_id))
