"""One owner-controlled provider, native execution and mode remain authoritative."""

from datetime import datetime

from database import neo_desk_db as desk
from database import strategy_module_db as native
from database.settings_db import get_analyze_mode

from .entries import submit_setup
from .lifecycle import day_performance, owner_locks
from .presets import get_preset
from .runner_host import NativeRunnerHost
from .types import IST
from .views import desk_view


class NeoDeskService:
    def __init__(self, market=None, host=None):
        from .market import NativeMarket

        self.market = market or NativeMarket()
        self.host = host or NativeRunnerHost()

    def state(self, owner_id):
        view = desk_view(owner_id, self.host)
        view["originating_mode"] = view["mode"]
        view["mode"] = "sandbox" if get_analyze_mode() else "live"
        return view

    def change_settings(self, owner_id, changes):
        if not isinstance(changes, dict) or set(changes) != {"profile"}:
            raise ValueError(
                "Choose one installed preset. Execution timing and loss guards remain fixed."
            )
        get_preset(changes["profile"])
        with owner_locks.hold(owner_id):
            c = desk.view(owner_id)
            if (
                c["run_id"]
                or c["pending"]
                or c["activation"] != "Stopped"
                or desk.managed_run_ids(owner_id)
            ):
                raise ValueError(
                    "Stop entries and wait for owned exposure to be flat before changing the preset."
                )
            desk.configure(
                owner_id, profile=changes["profile"], status="Preset saved; entries remain stopped."
            )
        return self.state(owner_id)

    def _native_strategy(self, owner, c):
        if c.get("strategy_id"):
            return c["strategy_id"]
        from datetime import time

        p = get_preset(c["profile"])
        row, error = native.create_strategy(
            owner,
            {
                "name": "Neo Desk · " + p.label,
                "underlying": "NIFTY",
                "underlying_exchange": "NSE_INDEX",
                "entry_time": time(9, 45),
                "exit_time": time(15, 29),
                "product": "NRML",
                "pricetype": "LIMIT",
                "legs": [
                    {
                        "id": 1,
                        "segment": "options",
                        "neo_provider": True,
                        "expiry": "weekly",
                        "lots": 1,
                        "position": "B",
                        "option_type": "CE",
                        "strike_mode": "atm",
                        "atm_offset": "ATM",
                    }
                ],
            },
        )
        if error:
            raise ValueError(error)
        desk.configure(owner, strategy_id=row["id"])
        return row["id"]

    def command(self, owner_id, action, request_id, confirm_live=False):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
            raise ValueError("A command identity is required.")
        with owner_locks.hold(owner_id):
            c = desk.view(owner_id)
            if action == "stop":
                desk.configure(
                    owner_id,
                    activation="Stopped",
                    status="Entries stopped; owned exits remain managed.",
                )
                ok, error = self.host.stop(owner_id)
                if not ok:
                    desk.configure(
                        owner_id,
                        status=error
                        or "Signal process could not stop; server entries are stopped.",
                    )
            elif action == "start":
                if c["activation"] == "Active":
                    return self.state(owner_id)
                if any(rid != c.get("run_id") for rid in desk.managed_run_ids(owner_id)):
                    raise ValueError(
                        "An older native run still needs reconciliation; keep new entries stopped."
                    )
                if c["pending"]:
                    raise ValueError(
                        "An entry outcome is uncertain. Reconcile the native run before restarting."
                    )
                mode = "sandbox" if get_analyze_mode() else "live"
                if mode == "live" and get_preset(c["profile"]).research_only:
                    raise ValueError("Price Break & Retest is available in Sandbox only.")
                if mode == "live" and not confirm_live:
                    raise ValueError("Confirm Start Live to allow new real orders.")
                if c["run_id"] and c["mode"] != mode:
                    raise ValueError(
                        "Owned exposure uses its originating mode. Keep entries stopped until flat."
                    )
                sid = self._native_strategy(owner_id, c)
                ok, error = native.set_live_enabled(sid, owner_id, mode == "live")
                if not ok:
                    raise ValueError(error)
                ok, error = self.host.start(owner_id)
                if not ok:
                    raise ValueError(error or "The native signal runner did not start.")
                desk.configure(
                    owner_id,
                    mode=mode,
                    activation="Active",
                    status="Waiting for a fresh confirmed 15-minute setup; CE and PE buys enabled.",
                )
            else:
                raise ValueError("Choose Start or Stop entries.")
        return self.state(owner_id)

    def poll(self, owner_id, *, now=None):
        try:
            return self._poll(owner_id, now=now)
        finally:
            from .views import publish_owner

            publish_owner(owner_id)

    def _poll(self, owner_id, *, now=None):
        now = now or datetime.now(IST)
        c = desk.view(owner_id)
        if c["activation"] != "Active" or c["pending"] or c["run_id"]:
            return {"acted": False, "message": c["status"]}
        mode = "sandbox" if get_analyze_mode() else "live"
        if mode != c["mode"]:
            desk.configure(
                owner_id,
                activation="Stopped",
                status="Execution mode changed; press Start in the selected mode.",
            )
            return {"acted": False, "message": "Execution mode changed; entries stopped."}
        p = get_preset(c["profile"])
        if p.research_only and mode == "live":
            return {"acted": False, "message": "Research preset requires Sandbox."}
        net, count = day_performance(owner_id, now.astimezone(IST).date())
        if count >= 3 or net <= -1000:
            desk.configure(
                owner_id,
                activation="Stopped",
                status="Daily entry or loss guard reached; entries stopped.",
            )
            return {"acted": False, "message": "Daily guard reached."}
        inputs = self.market.snapshot(owner_id, p, now)
        if inputs.get("error"):
            desk.configure(owner_id, status=inputs["error"])
            return {"acted": False, "message": inputs["error"]}
        setup, selection = inputs.get("setup"), inputs.get("selection")
        if not setup or not selection:
            note = inputs.get("message") or "Waiting for the next confirmed setup."
            desk.configure(owner_id, status=note)
            return {"acted": False, "message": note}
        result = submit_setup(owner_id, setup, selection, mode)
        return {
            "acted": result.ok,
            "run_id": result.run_id,
            "message": result.error or "Native entry submitted.",
        }


from utils.lazy import LazyInit

_service_init = LazyInit(NeoDeskService, name="neo-desk-service")


def get_service():
    return _service_init.get()
