"""Authenticated controls for the hosted liquidity strategy, with global CSRF."""

import time
from dataclasses import asdict
from functools import wraps

from flask import Blueprint, jsonify, request, session

from strategies.liquidity import state
from strategies.liquidity.setup import Config

liquidity_strategy_bp = Blueprint(
    "liquidity_strategy", __name__, url_prefix="/liquidity-strategy/api"
)


def guarded(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        if not session.get("user"):
            return jsonify(message="Sign in to use the strategy"), 401
        if session.get("broker") != "deltaexchange":
            return jsonify(message="Connect Delta Exchange"), 403
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            return jsonify(message=str(exc)), 409
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Liquidity control failed")
            return jsonify(
                message="Strategy control could not be confirmed. Refresh status before retrying."
            ), 503

    return call


def running(sid):
    from blueprints import python_strategy as host

    config = host.get_strategy_config(sid)
    return bool(config and config.get("is_running"))


@liquidity_strategy_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@liquidity_strategy_bp.get("/status")
@guarded
def status():
    sid = state.identifier(session["user"])
    cfg = state.settings(sid)
    return jsonify(
        status="success",
        data={
            "strategy_id": sid,
            "configured": (state.directory(sid) / "config.json").exists(),
            "running": running(sid),
            "config": asdict(cfg),
            "paper": state.snapshot(sid, "paper"),
            "live": state.snapshot(sid, "live"),
        },
    )


@liquidity_strategy_bp.post("/configure")
@guarded
def configure():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Provide strategy settings")
    try:
        cfg = Config(**data)
    except TypeError:
        raise ValueError("Unknown or invalid strategy setting") from None
    sid = state.identifier(session["user"])
    from blueprints import python_strategy as host

    # The existing host lock excludes a simultaneous start/configure request.
    with host.PROCESS_LOCK:
        if running(sid):
            raise ValueError("Stop the strategy process before changing its settings")
        for mode in ("paper", "live"):
            snap = state.snapshot(sid, mode)
            if snap.get("position") or snap.get("unresolved"):
                raise ValueError(f"Reconcile the existing {mode} trade before changing settings")
        state.save_settings(sid, cfg)
        existing = host.STRATEGY_CONFIGS.get(sid, {})
        if existing and existing.get("user_id") != session["user"]:
            raise ValueError("Strategy ownership mismatch")
        host.STRATEGY_CONFIGS[sid] = {
            **existing,
            "name": "Liquidity extra confirmation · BTCUSD",
            "file_path": str(state.ROOT / "strategies/examples/delta_liquidity_strategy.py"),
            "file_name": "delta_liquidity_strategy.py",
            "exchange": "CRYPTO",
            "user_id": session["user"],
            "is_running": False,
            "is_scheduled": False,
            "created_at": existing.get("created_at", time.time()),
        }
    host.save_configs()
    return jsonify(status="success", data={"strategy_id": sid, "config": asdict(cfg)})


@liquidity_strategy_bp.post("/start")
@guarded
def start():
    from blueprints import python_strategy as host
    from database.settings_db import get_analyze_mode

    sid = state.identifier(session["user"])
    cfg = state.settings(sid)
    data = request.get_json(silent=True) or {}
    if data.get("mode") != cfg.mode:
        raise ValueError("Review the saved execution mode before starting")
    actual = "paper" if get_analyze_mode() else "live"
    if actual != cfg.mode:
        raise ValueError(
            f"Select {'Analyze' if cfg.mode == 'paper' else 'Live'} in OpenAlgo before starting {cfg.mode}"
        )
    config = host.get_strategy_config(sid)
    if not config or config.get("user_id") != session["user"]:
        raise ValueError("Save the strategy settings first")
    result = host.start_strategy_process(sid, start_reason="manual")
    # Host returns success/message, never interpret a failed start as running.
    if not result[0]:
        raise ValueError(result[1])
    return jsonify(status="success", message=result[1])


@liquidity_strategy_bp.post("/control")
@guarded
def control():
    data = request.get_json(silent=True) or {}
    sid = state.identifier(session["user"])
    cfg = state.settings(sid)
    if data.get("mode") != cfg.mode:
        raise ValueError("Execution mode changed; refresh the screen")
    if not running(sid):
        raise ValueError("Start the strategy to process this control")
    state.command(sid, cfg.mode, data.get("action"), data.get("setup_id"), data.get("revision"))
    return jsonify(status="success", message="Control queued; waiting for server acknowledgement")


@liquidity_strategy_bp.post("/stop")
@guarded
def stop():
    from blueprints import python_strategy as host

    sid = state.identifier(session["user"])
    config = host.get_strategy_config(sid)
    if not config or config.get("user_id") != session["user"]:
        raise ValueError("Unknown strategy")
    result = host.stop_strategy_process(sid, stop_reason="manual")
    if not result[0]:
        raise ValueError(result[1])
    return jsonify(status="success", message=result[1])
