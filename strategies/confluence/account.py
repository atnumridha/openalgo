"""One-time GET-only wallet bootstrap within the strategy host's process limits.

Reads the existing private Delta connector configuration without modifying it.
Credentials are local to this startup request, never returned, logged or saved
in paper state. There is no order/settings transport or child process here.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import stat
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from dotenv import dotenv_values


def _connection(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, encoding="utf-8") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Delta connection file must be private and owner-controlled")
            text = file.read(16385)
            if len(text) > 16384:
                raise ValueError("Invalid Delta connection file")
        values = dotenv_values(stream=io.StringIO(text), interpolate=False)
    except (OSError, UnicodeError):
        raise ValueError(
            "Existing Delta connection is unavailable. Configure Delta or provide --wallet-snapshot."
        ) from None
    if values.get("DELTA_MCP_ENV", "india_prod") != "india_prod":
        raise ValueError("Paper account funding requires the Delta India production connection")
    key = values.get("DELTA_API_KEY")
    secret = values.get("DELTA_API_SECRET")
    if not key or not secret:
        raise ValueError("Existing Delta connection has no account credentials")
    return key, secret


def _read_error(code):
    if code == "ip_not_whitelisted_for_api_key":
        return ValueError(
            "Delta API IP allowlist blocks the wallet read. Whitelist this machine for the connected API key, then click Start again. Paper balance was not initialized."
        )
    if code in ("invalid_api_key", "invalid_signature", "unauthorized", "credentials_missing"):
        return ValueError(
            "Delta account authentication failed. Check the existing Delta connection, then retry Start. Paper balance was not initialized."
        )
    return ValueError(
        "Delta account balance is unavailable. Check connection, API permissions and IP allowlist, then retry Start. No paper balance was substituted."
    )


def read_connected_snapshot(*, config_path=None, transport=None):
    """Read one fixed endpoint. No generic method, URL or payload is accepted."""
    # Same shared file/path override as delta_exchange_mcp.store. No environment
    # credential fallback: it must be the user's existing India connection.
    path = Path(
        config_path
        or os.getenv("DELTA_MCP_CONFIG_FILE")
        or Path.home() / ".delta-exchange-mcp/config.env"
    ).expanduser()
    key, secret = _connection(path)
    timestamp = str(int(time.time()))
    route = "/v2/wallet/balances"
    signature = hmac.new(
        secret.encode(), ("GET" + timestamp + route).encode(), hashlib.sha256
    ).hexdigest()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(5, connect=3), follow_redirects=False, transport=transport
        ) as client:
            response = client.get(
                "https://api.india.delta.exchange" + route,
                headers={
                    "api-key": key,
                    "timestamp": timestamp,
                    "signature": signature,
                    "User-Agent": "OpenAlgo-Confluence-Paper/1.0",
                    "Accept": "application/json",
                },
            )
            data = response.json()
    except httpx.TimeoutException:
        raise ValueError(
            "Delta wallet read timed out. Paper balance remains uninitialized; retry Start."
        ) from None
    except (httpx.HTTPError, ValueError):
        raise _read_error(None) from None
    if not isinstance(data, dict):
        raise _read_error(None)
    if response.is_error or data.get("success") is not True:
        error = data.get("error") or {}
        raise _read_error(error.get("code") if isinstance(error, dict) else None)
    try:
        rows = [row for row in data["result"] if row.get("asset_symbol") == "USD"]
        if len(rows) != 1:
            raise ValueError("Exactly one USD wallet required")
        amount = str(rows[0]["available_balance"])
        money = Decimal(amount)
        if not money.is_finite() or money < 0:
            raise ValueError("Invalid available balance")
        return {
            "environment": "india_prod",
            "captured_at": time.time(),
            "result": [{"asset_symbol": "USD", "available_balance": amount}],
        }
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        raise _read_error(None) from None
