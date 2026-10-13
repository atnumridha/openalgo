"""Install and run one signal template through OpenAlgo's existing Python host."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path

from .types import IST


class NativeRunnerHost:
    def identity(self, owner):
        return "neo_desk_runner_" + sha256(owner.encode()).hexdigest()[:12]

    def install(self, owner):
        from blueprints import python_strategy as host

        sid = self.identity(owner)
        target = host.STRATEGIES_DIR / (sid + ".py")
        with host.PROCESS_LOCK:
            existing = host.STRATEGY_CONFIGS.get(sid)
            if existing:
                if existing.get("user_id") != owner:
                    raise ValueError("Native runner ownership does not match.")
                return sid
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path("strategies/templates/neo_desk_runner.py").read_bytes())
            target.chmod(0o700)
            host.STRATEGY_CONFIGS[sid] = {
                "name": "Neo Desk confirmed-signal runner",
                "file_path": str(target),
                "file_name": target.name,
                "exchange": "NFO",
                "is_running": False,
                "is_scheduled": False,
                "created_at": datetime.now(IST).isoformat(),
                "user_id": owner,
                "schedule_start": "09:00",
                "schedule_stop": "15:30",
                "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
            }
        if not host.save_configs():
            raise ValueError("Native runner configuration could not be saved.")
        return sid

    def status(self, owner):
        from blueprints import python_strategy as host

        sid = self.identity(owner)
        with host.PROCESS_LOCK:
            record = host.RUNNING_STRATEGIES.get(sid)
        return {"id": sid, "running": bool(record and host._record_is_alive(record))}

    def start(self, owner):
        from blueprints.python_strategy import start_strategy_process

        sid = self.install(owner)
        if self.status(owner)["running"]:
            return True, None
        return start_strategy_process(sid)

    def stop(self, owner):
        from blueprints.python_strategy import stop_strategy_process

        if not self.status(owner)["running"]:
            return True, None
        return stop_strategy_process(self.identity(owner))
