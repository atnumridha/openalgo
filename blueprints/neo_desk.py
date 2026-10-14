import os
from functools import wraps

from flask import Blueprint, jsonify, request, session

from services.neo_desk.lifecycle import request_owned_exit, update_protection
from services.neo_desk.service import get_service

neo_desk_bp = Blueprint("neo_desk", __name__, url_prefix="/neodesk/api")


def authenticated(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if os.environ.get("NEO_SAVED_LOGIN", "").upper() != "TRUE":
            return jsonify(status="error", message="Neo Desk is not enabled on this instance."), 404
        if (
            not session.get("user")
            or not session.get("logged_in")
            or session.get("broker") != "kotak"
        ):
            return jsonify(
                status="error", message="Connect the Kotak session to use the terminal."
            ), 401
        try:
            return fn(*a, **kw)
        except ValueError as e:
            return jsonify(status="error", message=str(e)), 400
        except Exception:
            from utils.logging import get_logger

            get_logger(__name__).exception("Neo Desk command failed")
            return jsonify(
                status="error",
                message="This request did not complete. Check the native run and retry.",
            ), 503

    return wrapped


@neo_desk_bp.get("/state")
@authenticated
def state():
    return jsonify(get_service().state(session["user"]))


@neo_desk_bp.post("/settings")
@authenticated
def settings():
    return jsonify(get_service().change_settings(session["user"], request.get_json(silent=True)))


@neo_desk_bp.post("/execution/<action>")
@authenticated
def execution(action):
    b = request.get_json(silent=True) or {}
    if set(b) - {"request_id", "confirm_live"}:
        raise ValueError("Unexpected execution controls.")
    return jsonify(
        get_service().command(
            session["user"], action, b.get("request_id"), confirm_live=b.get("confirm_live") is True
        )
    )


@neo_desk_bp.post("/position/protection")
@authenticated
def protection():
    b = request.get_json(silent=True) or {}
    return jsonify(update_protection(session["user"], b.get("trade_id"), b.get("changes")))


@neo_desk_bp.post("/position/close")
@authenticated
def close():
    b = request.get_json(silent=True) or {}
    if b.get("confirmed") is not True:
        raise ValueError("Confirm square-off of the exact terminal-owned trade.")
    result = request_owned_exit(
        session["user"], b.get("trade_id"), "Manual square-off", b.get("request_id")
    )
    return jsonify(result), 200 if result.get("ok") else 409


from flask_socketio import join_room, leave_room

from extensions import socketio
from services.neo_desk.views import room_for_owner


@socketio.on("neo_desk_subscribe")
def subscribe_desk(_data=None):
    owner = session.get("user")
    if (
        os.environ.get("NEO_SAVED_LOGIN", "").upper() != "TRUE"
        or not owner
        or not session.get("logged_in")
        or session.get("broker") != "kotak"
    ):
        return {"ok": False, "message": "Connect your Kotak session."}
    join_room(room_for_owner(owner))
    return {"ok": True}


@socketio.on("neo_desk_unsubscribe")
def unsubscribe_desk(_data=None):
    owner = session.get("user")
    if owner:
        leave_room(room_for_owner(owner))
    return {"ok": True}


@neo_desk_bp.get("/history")
@authenticated
def history():
    from services.neo_desk.history import history_page

    return jsonify(
        history_page(
            session["user"],
            request.args.get("symbol", ""),
            request.args.get("start"),
            request.args.get("end"),
            request.args.get("cursor", 0),
            request.args.get("cost_plan", "trade_free"),
            request.args.get("mode", "live"),
        )
    )


@neo_desk_bp.post("/history/import")
@authenticated
def history_import():
    from services.neo_desk.history import import_csv

    return jsonify(
        import_csv(session["user"], (request.get_json(silent=True) or {}).get("csv", ""))
    )


@neo_desk_bp.post("/history/refresh")
@authenticated
def history_refresh():
    from services.neo_desk.history import refresh_history

    return jsonify(refresh_history(session["user"]))


@neo_desk_bp.get("/history/export")
@authenticated
def history_export():
    from flask import Response

    from services.neo_desk.history import export_csv

    return Response(
        export_csv(
            session["user"],
            request.args.get("symbol", ""),
            request.args.get("start"),
            request.args.get("end"),
            request.args.get("mode", "live"),
        ),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=recorded-executions.csv"},
    )


@neo_desk_bp.get("/history/template")
@authenticated
def history_template():
    from flask import Response

    return Response(
        "fill_id,order_id,symbol,exchange,product,side,quantity,price,time,fees\n",
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=execution-template.csv"},
    )


@neo_desk_bp.get("/chart")
@authenticated
def chart():
    from services.neo_desk.chart_views import chart_view

    return jsonify(
        chart_view(
            session["user"], request.args.get("instrument", ""), request.args.get("interval", "15m")
        )
    )


@neo_desk_bp.get("/datasets")
@authenticated
def datasets():
    from services.neo_desk.datasets import list_datasets

    return jsonify(datasets=list_datasets())


@neo_desk_bp.post("/research")
@authenticated
def research():
    from services.neo_desk.research_jobs import submit_job

    return jsonify(submit_job(session["user"], request.get_json(silent=True))), 202


@neo_desk_bp.get("/research/latest")
@authenticated
def research_latest():
    from services.neo_desk.research_jobs import latest_jobs

    return jsonify(jobs=latest_jobs(session["user"]))


@neo_desk_bp.get("/research/<identity>")
@authenticated
def research_job(identity):
    from services.neo_desk.research_jobs import get_job

    return jsonify(get_job(session["user"], identity))


@neo_desk_bp.get("/overview")
@authenticated
def overview():
    from services.neo_desk.overview import live_overview

    return jsonify(live_overview(session["user"]))


@neo_desk_bp.get("/health")
@authenticated
def health():
    from services.neo_desk.health import execution_feedback

    return jsonify(execution_feedback(session["user"]))


@neo_desk_bp.get("/storage")
@authenticated
def storage():
    from services.neo_desk.persistence import storage_status
    return jsonify(storage_status(session["user"]))


@neo_desk_bp.get("/charts/saved")
@authenticated
def archived_chart():
    from services.neo_desk.persistence import saved_chart
    return jsonify(saved_chart(
        request.args.get("symbol", "NIFTY"), request.args.get("exchange", "NSE_INDEX"),
        request.args.get("interval", "15m"), request.args.get("start", ""), request.args.get("end", "")
    ))


@neo_desk_bp.get("/history/replay")
@authenticated
def history_replay():
    from services.neo_desk.trade_replay import trade_replay

    return jsonify(trade_replay(session["user"], request.args.get("trade_id"), request.args.get("mode", "live")))


@neo_desk_bp.get("/research/saved")
@authenticated
def research_saved():
    from services.neo_desk.research_jobs import saved_jobs

    return jsonify(jobs=saved_jobs(session["user"]))
