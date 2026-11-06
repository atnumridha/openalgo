"""Kotak's read-only snapshots use an independent HTTP/1.1 pool.

The shared HTTP/2 connection has remained unusable after Neo closed streams,
blocking unrelated quotes and history together. HTTP/1.1 avoids multiplexing
them on that failed session. Known account-book and funds reads share this
pool. Trading mutations keep their existing transport and are never retried
or interrupted by read-only recovery.
"""

import atexit

import httpx

from utils.lazy import LazyInit


def _build_client() -> httpx.Client:
    return httpx.Client(
        http1=True,
        http2=False,
        verify=True,
        timeout=httpx.Timeout(15.0, connect=5.0, pool=5.0),
        limits=httpx.Limits(
            max_connections=16,
            max_keepalive_connections=8,
            keepalive_expiry=15.0,
        ),
    )


_client = LazyInit(_build_client, name="kotak-market-data-http")


def get_httpx_client() -> httpx.Client:
    return _client.get()


def _close_client() -> None:
    _client.reset(close=lambda client: client.close())


atexit.register(_close_client)
