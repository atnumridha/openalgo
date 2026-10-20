"""The worker's two calls into the web process, over loopback.

Open strategy legs live in the web process, so the worker asks for them and
sends exits back. Both calls carry the per-run secret Flask handed the worker
in its environment; Flask refuses them from anywhere but loopback. An exit is
sent as a ``long_exit`` / ``short_exit`` signal and goes through the same path
as any other, so it is audited and claimed under the run lock.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from utils.logging import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS = 5.0
_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=TIMEOUT_SECONDS)
    return _client


def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def _headers() -> dict[str, str]:
    return {"X-ML-Worker-Secret": os.getenv("OPENALGO_ML_WORKER_SECRET", "")}


def _base() -> str:
    return os.getenv("OPENALGO_ML_LOCAL_URL", "http://127.0.0.1:5000")


def open_trades() -> list[dict[str, Any]] | None:
    """Every open ML leg, or None when the web process could not be asked."""
    if not os.getenv("OPENALGO_ML_WORKER_SECRET"):
        return None
    try:
        response = _http().get(f"{_base()}/ml/api/worker/trades", headers=_headers())
        if response.status_code != 200:
            logger.warning("ML worker could not read open trades: HTTP %s", response.status_code)
            return None
        return list((response.json() or {}).get("data") or [])
    except Exception as exc:
        logger.warning("ML worker could not reach the web process: %s", exc)
        return None


def send_exit(trade: dict[str, Any], reason: str, detail: str) -> bool:
    """Close one ML leg through its strategy's signal path. True when it was accepted."""
    try:
        response = _http().post(
            f"{_base()}/ml/api/worker/exit",
            headers=_headers(),
            json={
                "run_id": trade["run_id"],
                "leg_id": trade["leg_id"],
                "reason": reason,
                "detail": detail,
            },
        )
        if response.status_code == 200:
            return True
        logger.warning("Smart exit for %s was refused: %s", trade.get("key"), response.text[:200])
    except Exception as exc:
        logger.warning("Smart exit for %s could not be sent: %s", trade.get("key"), exc)
    return False


def reconcile() -> list[dict[str, Any]]:
    """Ask the web process to settle Live legs Delta has already closed."""
    try:
        response = _http().post(f"{_base()}/ml/api/worker/reconcile", headers=_headers())
        if response.status_code == 200:
            return list((response.json() or {}).get("data") or [])
    except Exception as exc:
        logger.warning("ML worker could not reconcile Live trades: %s", exc)
    return []
