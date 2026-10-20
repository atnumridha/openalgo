"""Fresh read-only OpenAlgo mode and authenticated host lifecycle provenance."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


class Host:
    def __init__(self, url=None, api_key=None, transport=None):
        if not url and os.getenv("STRATEGY_ID"):
            # HOST_SERVER may be an expired external webhook tunnel. A local
            # hosted process reads mode directly from its own Flask listener.
            port = int(os.getenv("FLASK_PORT", "5000"))
            if not 1 <= port <= 65535:
                raise ValueError("Invalid OpenAlgo server port")
            url = f"http://127.0.0.1:{port}"
        url = url or os.getenv("OPENALGO_HOST") or os.getenv("HOST_SERVER", "http://127.0.0.1:5050")
        parsed = urlparse(url)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid OpenAlgo host URL")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote OpenAlgo requires HTTPS")
        self.key = api_key or os.getenv("OPENALGO_API_KEY")
        if not self.key:
            raise ValueError("Auto/live mode requires the OpenAlgo host API key")
        self.http = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=httpx.Timeout(3, connect=2),
            transport=transport,
            follow_redirects=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    def mode(self):
        try:
            response = self.http.post("/api/v1/analyzer", json={"apikey": self.key})
            response.raise_for_status()
            data = response.json()
            mode = data["data"]["mode"]
            flag = data["data"]["analyze_mode"]
            if (
                data["status"] != "success"
                or type(flag) is not bool
                or mode != ("analyze" if flag else "live")
            ):
                raise ValueError()
            return "paper" if flag else "live"
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ValueError(
                "OpenAlgo mode is unavailable or inconsistent; entries blocked"
            ) from None


def shutdown_reason():
    try:
        config = json.loads(Path(os.environ["OPENALGO_STRATEGY_CONFIG"]).read_text())
        request = config[os.environ["STRATEGY_ID"]]["shutdown_request"]
        if (
            request["pid"] == os.getpid()
            and 0 <= time.time() - request["at"] < 60
            and request["reason"] in ("schedule", "server_shutdown", "manual")
        ):
            return request["reason"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "manual"


def resume_host_paper(paper, origin, now):
    s = paper.state
    if (
        s["halt_day"] is not None
        or not s["paused"]
        or s["status"] != "stopped"
        or s["position"]
        or s["pending"]
    ):
        return False
    # Explicit UI Start acknowledges a prior clean stop. Cron cannot clear a manual stop.
    if origin == "manual" or s.get("stop_reason") in ("schedule", "server_shutdown", "mode_change"):
        paper.resume(now)
        return True
    return False
