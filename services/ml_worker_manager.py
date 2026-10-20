"""Lifecycle control for the ML worker subprocess."""

from __future__ import annotations

import hmac
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "log" / "ml_worker.log"

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"process": None, "pid": None, "started_at": None}

#: Shared with the worker through its environment, so it can reach the two
#: worker-only endpoints. Generated per start of the web process and never
#: written to disk.
WORKER_SECRET = secrets.token_hex(32)


def check_worker_secret(presented: str | None) -> bool:
    return bool(presented) and hmac.compare_digest(str(presented), WORKER_SECRET)


def local_base_url() -> str:
    """Where the worker reaches this web process: loopback on the configured port."""
    port = os.getenv("FLASK_PORT", "5000")
    return f"http://127.0.0.1:{port}"


def _alive(process: subprocess.Popen | None) -> bool:
    return process is not None and process.poll() is None


def status() -> dict[str, Any]:
    with _LOCK:
        process = _STATE.get("process")
        alive = _alive(process)
        return {
            "running": alive,
            "pid": _STATE.get("pid") if alive else None,
            "log_file": str(LOG_FILE),
            "started_at": _STATE.get("started_at") if alive else None,
        }


def start_worker() -> bool:
    """Start the ML worker once. Idempotent while running."""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True

    with _LOCK:
        process = _STATE.get("process")
        if _alive(process):
            return True

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handle = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        handle.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        handle.flush()

        args: dict[str, Any] = {
            "cwd": str(ROOT),
            "stdout": handle,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "env": {
                **os.environ,
                "OPENALGO_ML_WORKER_SECRET": WORKER_SECRET,
                "OPENALGO_ML_LOCAL_URL": local_base_url(),
            },
        }
        if os.name == "nt":
            args["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            args["start_new_session"] = True

        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "ml_signals.worker", "run"],
                **args,
            )
        except Exception:
            handle.close()
            logger.exception("Could not start ML worker")
            return False
        finally:
            try:
                handle.close()
            except Exception:
                pass

        _STATE["process"] = process
        _STATE["pid"] = process.pid
        _STATE["started_at"] = time.time()
        logger.info("ML worker started with PID %s", process.pid)
        return True


def stop_worker(timeout_s: float = 8.0) -> None:
    """Stop the ML worker if it is running."""
    with _LOCK:
        process = _STATE.get("process")
        if not _alive(process):
            _STATE.update({"process": None, "pid": None, "started_at": None})
            return
        pid = int(process.pid)

    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        logger.exception("Could not terminate ML worker %s", pid)

    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.1)

    if process.poll() is None:
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            logger.exception("Could not kill ML worker %s", pid)

    with _LOCK:
        _STATE.update({"process": None, "pid": None, "started_at": None})
