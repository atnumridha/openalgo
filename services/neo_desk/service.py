"""One owner-controlled provider, native execution and mode remain authoritative."""

from datetime import datetime

from database import neo_desk_db as desk
from database import strategy_module_db as native
from database.settings_db import get_analyze_mode
from utils.keyed_locks import KeyedLocks

from .entries import submit_setup
from .lifecycle import day_performance, management_ready, management_status, owner_locks
from .presets import get_preset
from .runner_host import NativeRunnerHost
from .types import IST
from .views import desk_view

host_locks = KeyedLocks(name="neo-signal-host")


class NeoDeskService:
    def __init__(self, market=None, host=None):
        from .market import NativeMarket

        self.market = market or NativeMarket()
        self.host = host or NativeRunnerHost()

    def state(self, owner_id):
        view = desk_view(owner_id, self.host)
        view["originating_mode"] = view["mode"]
        view["mode"] = "sandbox" if get_analyze_mode() else "live"
        view["management"] = management_status()
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
                or c["settings"].get("host_command")
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
        if action not in ("start", "stop"):
            raise ValueError("Choose Start or Stop entries.")
        with owner_locks.hold(owner_id):
            c = desk.view(owner_id)
            mode = "sandbox" if get_analyze_mode() else "live"
            if action == "start":
                if not management_ready():
                    raise ValueError(
                        "Owned protection jobs are unavailable. Keep entries stopped and restart the native service."
                    )
                if c["activation"] == "Active":
                    return self.state(owner_id)
                if c["settings"].get("host_command"):
                    raise ValueError(
                        "The signal process is changing state. Wait for completion before starting."
                    )
                if any(rid != c.get("run_id") for rid in desk.managed_run_ids(owner_id)):
                    raise ValueError(
                        "An older native run still needs reconciliation; keep new entries stopped."
                    )
                if c["pending"]:
                    raise ValueError(
                        "An entry outcome is uncertain. Reconcile the native run before restarting."
                    )
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
            settings = {**c["settings"], "host_command": request_id, "host_action": action}
            desk.configure(
                owner_id,
                activation="Stopped",
                settings=settings,
                status="Entries stopped; signal process changing state.",
            )
        # Serialize subprocess actions without holding the protection/control lock.
        with host_locks.hold(owner_id):
            try:
                ok, error = (
                    self.host.start(owner_id) if action == "start" else self.host.stop(owner_id)
                )
            except Exception:
                ok, error = (
                    False,
                    "Signal process transition failed. Check native logs; entries remain stopped.",
                )
            with owner_locks.hold(owner_id):
                current = desk.view(owner_id)
                if current["settings"].get("host_command") == request_id:
                    clean = {
                        k: v
                        for k, v in current["settings"].items()
                        if k not in ("host_command", "host_action")
                    }
                    enabled = (
                        action == "start"
                        and ok
                        and management_ready()
                        and mode == ("sandbox" if get_analyze_mode() else "live")
                    )
                    note = (
                        "Waiting for a fresh confirmed 15-minute setup; CE and PE buys enabled."
                        if enabled
                        else (error or "Entries stopped; owned exits remain managed.")
                    )
                    desk.configure(
                        owner_id,
                        settings=clean,
                        mode=mode if enabled else current["mode"],
                        activation="Active" if enabled else "Stopped",
                        status=note,
                    )
                # A newer Stop owns the fence; this Start must never reactivate it.
        if not ok:
            raise ValueError(error or "The native signal runner did not start.")
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
        if not management_ready():
            desk.configure(
                owner_id,
                activation="Stopped",
                status="Owned protection jobs unavailable. Entries stopped; inspect any broker exposure.",
            )
            return {"acted": False, "message": "Owned protection jobs unavailable."}
        mode = "sandbox" if get_analyze_mode() else "live"
        if mode != c["mode"]:
            desk.configure(
                owner_id,
                activation="Stopped",
                status="Execution mode changed; press Start in the selected mode.",
            )
            return {"acted": False, "message": "Execution mode changed; entries stopped."}
        p = get_preset(c["profile"])
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
