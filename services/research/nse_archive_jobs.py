"""One isolated archive worker; no broker or trading services are imported."""

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from services.research import nse_archive
from utils.real_threading import Lock

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nse-archive")
_lock = Lock()
_future = None
_requested_at = 0


def _run(requested_at):
    root = nse_archive.ROOT
    root.mkdir(parents=True, exist_ok=True)
    with (root / "worker.log").open("w") as output:
        # No shell, credentials, user-selected executable or inherited terminal pipe.
        with subprocess.Popen(
            [
                sys.executable,
                "-m",
                "services.research.nse_download",
                "--requested-at",
                str(requested_at),
            ],
            cwd=Path(__file__).resolve().parents[2],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
        ) as process:
            return process.wait()


def status():
    result = nse_archive.status(nse_archive.ROOT)
    with _lock:
        current = _future
        requested_at = _requested_at
    if current is not None and not current.done():
        result["status"] = "running"
    elif current is not None and current.done():
        # A later CLI run owns its own status, even if the previous web job failed.
        updated_at = result.get("updated_at")
        updated_at = datetime.fromisoformat(updated_at).timestamp() if updated_at else 0
        if (
            updated_at <= requested_at
            and (current.exception() or current.result() != 0)
            and result["status"] not in ("blocked", "failed", "interrupted")
            and not result["error_count"]
        ):
            result.update(
                status="failed",
                message="Download could not start. Check the download log and try again.",
            )
    return result


def start():
    global _future, _requested_at
    # File ownership also detects a worker started from Finder or the terminal.
    if nse_archive.is_running(nse_archive.ROOT):
        return status()
    with _lock:
        if _future is None or _future.done():
            _requested_at = time.time()
            _future = _executor.submit(_run, _requested_at)
    return status()


def cancel():
    if status()["status"] == "running":
        nse_archive.ROOT.mkdir(parents=True, exist_ok=True)
        (nse_archive.ROOT / "cancel").touch()
    return status()
