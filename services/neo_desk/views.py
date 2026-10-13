from datetime import datetime

from database import neo_desk_db as desk
from database import strategy_module_db as native
from services.strategy_module import state

from .lifecycle import day_performance
from .presets import PRESETS
from .types import IST


def desk_view(owner, host):
    c = desk.view(owner)
    snap = state.get_run_state(c["run_id"]) if c["run_id"] else None
    net, count = day_performance(owner, datetime.now(IST).date())
    return {
        **{k: v for k, v in c.items() if k != "owner"},
        "can_edit": not c["run_id"]
        and not c["pending"]
        and not c["settings"].get("host_command")
        and c["activation"] == "Stopped"
        and not desk.managed_run_ids(owner),
        "entries_today": count,
        "day_net_estimate": str(net),
        "presets": [
            {"profile": p.profile, "label": p.label, "research_only": p.research_only}
            for p in PRESETS.values()
        ],
        "owned": {
            "run_id": c["run_id"],
            "legs": list((snap or {}).get("legs", {}).values()),
            "managed_runs": [
                {
                    "run_id": rid,
                    "protection": desk.get_run_protection(owner, rid),
                    "state": state.get_run_state(rid),
                }
                for rid in desk.managed_run_ids(owner)
            ],
        },
        "runner": host.status(owner),
        "observed_at": datetime.now(IST).isoformat(),
    }


def room_for_owner(owner):
    from hashlib import sha256

    return "neo-desk:" + sha256(owner.encode()).hexdigest()[:24]


def publish_owner(owner):
    from database.auth_db import get_auth_token
    from extensions import emit_from_any_thread
    from utils.logging import get_logger

    from .service import get_service

    try:
        if not get_auth_token(owner):
            return False
        emit_from_any_thread(
            "neo_desk_update", get_service().state(owner), to=room_for_owner(owner)
        )
        return True
    except Exception:
        get_logger(__name__).exception("Native Neo Desk state push failed")
        return False
