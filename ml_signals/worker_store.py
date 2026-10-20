"""File-backed ML worker state shared with Flask APIs."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ml_signals import data

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "db" / "ml_signals" / "worker"
LIVE_DIR = WORKER_DIR / "live"
STATUS_FILE = WORKER_DIR / "status.json"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def status_path() -> Path:
    return STATUS_FILE


def write_status(value: dict[str, Any]) -> None:
    payload = dict(value)
    payload.setdefault("updated_at", time.time())
    _atomic_json(STATUS_FILE, payload)


def read_status() -> dict[str, Any] | None:
    return _read_json(STATUS_FILE)


def live_snapshot_path(symbol: str | None, interval: str) -> Path:
    symbol_name = data.normalize_symbol(symbol)
    return LIVE_DIR / symbol_name / f"{interval}.json"


def write_live_snapshot(symbol: str | None, interval: str, value: dict[str, Any]) -> None:
    _atomic_json(live_snapshot_path(symbol, interval), value)


def read_live_snapshot(symbol: str | None, interval: str) -> dict[str, Any] | None:
    return _read_json(live_snapshot_path(symbol, interval))


def train_result_path(symbol: str | None) -> Path:
    return WORKER_DIR / "train" / f"{data.normalize_symbol(symbol)}.json"


def write_train_result(symbol: str | None, value: dict[str, Any]) -> None:
    _atomic_json(train_result_path(symbol), value)


def read_train_result(symbol: str | None) -> dict[str, Any] | None:
    return _read_json(train_result_path(symbol))


def request_path() -> Path:
    return WORKER_DIR / "requests.json"


def request_retrain(symbols: list[str]) -> None:
    """Ask the worker to save history and retrain these symbols now."""
    current = _read_json(request_path()) or {}
    wanted = list(dict.fromkeys([*(current.get("retrain") or []), *symbols]))
    _atomic_json(request_path(), {"retrain": wanted, "updated_at": time.time()})


def take_requests() -> list[str]:
    """The symbols asked for since the last call, emptying the request file."""
    value = _read_json(request_path())
    if not value:
        return []
    try:
        request_path().unlink()
    except FileNotFoundError:
        pass
    return [str(s) for s in value.get("retrain") or []]


def suggestion_path(symbol: str | None, interval: str) -> Path:
    return WORKER_DIR / "suggestions" / data.normalize_symbol(symbol) / f"{interval}.json"


def trades_path() -> Path:
    return WORKER_DIR / "trades.json"


def read_trades() -> dict[str, Any]:
    """Open ML trades by ``run_id:leg_id``: what the smart exit needs about each."""
    return _read_json(trades_path()) or {}


def update_trades(change) -> dict[str, Any]:
    """Apply ``change(trades) -> trades`` under a lock both processes honour.

    Flask adds a trade and the worker removes closed ones; without the lock
    one process's write could drop the other's.
    """
    path = trades_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a+") as lock_file:
        _lock(lock_file)
        try:
            value = change(read_trades())
            _atomic_json(path, value)
            return value
        finally:
            _unlock(lock_file)


def _lock(handle, timeout: float = 5.0) -> None:
    """Take the lock without blocking inside C, so an eventlet hub keeps running.

    The other holder only reads and rewrites a small JSON file, so the wait is
    milliseconds; it is polled with a sleep that yields rather than waited on.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError("the ML trades file stayed locked") from None
            time.sleep(0.01)


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def exits_path() -> Path:
    return WORKER_DIR / "exits.json"


def write_exits(value: dict[str, Any]) -> None:
    _atomic_json(exits_path(), value)


def read_exits() -> dict[str, Any] | None:
    return _read_json(exits_path())
