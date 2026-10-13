"""Hosted signal poller. The server owns rules, activation, orders and exits."""

import os
import time

import requests
import logging

logger = logging.getLogger(__name__)


def run():
    host = os.environ.get("OPENALGO_HOST") or os.environ.get("HOST_SERVER", "http://127.0.0.1:5001")
    key = os.environ.get("OPENALGO_API_KEY")
    if not key:
        raise RuntimeError("Native API key is not configured for the strategy owner.")
    with requests.Session() as client:
        while True:
            try:
                response = client.post(
                    host.rstrip("/") + "/api/v1/neodesk/signal", json={"apikey": key}, timeout=15
                )
                if response.status_code == 401:
                    raise RuntimeError("Native API session requires reconnection.")
                if response.status_code >= 400:
                    logger.error("Signal service did not complete; inspect the terminal status.")
            except requests.RequestException:
                logger.error(
                    "Native signal service is unavailable; no replacement order was submitted."
                )
            time.sleep(0.5)


if __name__ == "__main__":
    run()
