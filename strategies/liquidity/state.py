"""Owner-specific local state paths and short-lived UI database connections."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from .setup import Config

ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = ROOT / "db" / "liquidity"


def identifier(user):
    return "liquidity_" + hashlib.sha256(user.encode()).hexdigest()[:16]


def directory(sid):
    if not re.fullmatch(r"liquidity_[a-f0-9]{16}", sid):
        raise ValueError("Invalid strategy identity")
    return STATE_ROOT / sid


def settings(sid):
    path = directory(sid) / "config.json"
    return Config(**json.loads(path.read_text())) if path.exists() else Config()


def snapshot(sid, mode):
    if mode not in ("paper", "live"):
        raise ValueError("Invalid mode")
    path = directory(sid) / (mode + ".sqlite")
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        values = {
            k: json.loads(v)
            for k, v in db.execute(
                "SELECT key,value FROM kv WHERE key IN ('view','position','paused','pause_reason','command','consumed')"
            )
        }
        values["trades"] = [
            json.loads(v)
            for (v,) in db.execute("SELECT value FROM trades ORDER BY closed_at DESC LIMIT 10")
        ]
        values["unresolved"] = db.execute(
            "SELECT COUNT(*) FROM intents WHERE status IN ('pending','unknown')"
        ).fetchone()[0]
        return values


def plan_revision(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode()).hexdigest()[
        :24
    ]


def command(sid, mode, action, setup_id=None, revision=None):
    import time

    if action not in ("approve", "pause", "resume", "close"):
        raise ValueError("Invalid control")
    if mode not in ("paper", "live"):
        raise ValueError("Invalid mode")
    path = directory(sid) / (mode + ".sqlite")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=2)) as db:
        db.execute("BEGIN IMMEDIATE")
        raw = db.execute("SELECT value FROM kv WHERE key='view'").fetchone()
        view = json.loads(raw[0]) if raw else {}
        if action == "approve" and (
            time.time() - view.get("asof", 0) > 5
            or not setup_id
            or view.get("plan", {}).get("setup_id") != setup_id
            or view.get("plan", {}).get("blocked")
            or revision != plan_revision(view.get("plan", {}))
        ):
            raise ValueError("Setup changed or expired; wait for a fresh entry preview")
        old = db.execute("SELECT value FROM kv WHERE key='command'").fetchone()
        if old and json.loads(old[0]):
            raise ValueError("A control is already pending")
        db.execute(
            "INSERT OR REPLACE INTO kv VALUES (?,?)",
            (
                "command",
                json.dumps(
                    {
                        "action": action,
                        "setup_id": setup_id,
                        "approved_plan": view.get("plan") if action == "approve" else None,
                        "at": time.time(),
                    }
                ),
            ),
        )
        db.commit()


def save_settings(sid, cfg):
    folder = directory(sid)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest = folder / "config.json"
    temp = folder / "config.tmp"
    temp.write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    temp.replace(dest)
