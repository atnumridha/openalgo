"""Read-only Delta India public data, with bounded caches and one HTTP pool."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timezone

import httpx
from cachetools import TTLCache


def normalize_options(rows, expiry, expiry_code):
    result = []
    for row in rows:
        try:
            if (
                row["underlying_asset_symbol"] != "BTC"
                or row["product_trading_status"] != "operational"
                or row["symbol"].rsplit("-", 1)[-1] != expiry_code
            ):
                continue
            kind = row["contract_type"]
            q = row["quotes"]
            if kind not in ("call_options", "put_options"):
                continue
            result.append(
                {
                    "side": "CALL" if kind == "call_options" else "PUT",
                    "strike": float(row["strike_price"]),
                    "expiry": expiry,
                    "timestamp": float(row["timestamp"])
                    / 1e6,  # `time` is last trade, not quote time
                    "bid": float(q["best_bid"]),
                    "ask": float(q["best_ask"]),
                    "iv": float(q["mark_iv"]),
                    "delta": float(row["greeks"]["delta"]),
                    "oi_contracts": float(row["oi_contracts"]),
                }
            )  # `oi` is base currency!
        except (KeyError, TypeError, ValueError):
            continue
    return result


class DeltaPublic:
    def __init__(self, transport=None):
        # Standalone process owns this pool; context exit closes it on every path.
        self.client = httpx.Client(
            base_url="https://api.india.delta.exchange",
            timeout=8,
            transport=transport,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
            headers={"User-Agent": "OpenAlgo-Confluence-Paper/1.0", "Cache-Control": "no-cache"},
        )
        self.products = TTLCache(maxsize=4, ttl=60)
        self.candles = TTLCache(maxsize=2, ttl=5)
        self.prior = TTLCache(maxsize=2, ttl=86400)
        self.chain = TTLCache(maxsize=1, ttl=15)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def get(self, path, params=None):
        response = self.client.get(path, params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
        if not data.get("success") or "result" not in data:
            raise ValueError("Delta public data response was unsuccessful")
        return data["result"]

    def product(self, symbol):
        if symbol not in self.products:
            self.products[symbol] = self.get("/v2/products/" + symbol)
        return self.products[symbol]

    def market(self):
        start = time.monotonic()
        book = self.get("/v2/l2orderbook/BTCUSD")
        bids = sorted([[float(x["price"]), float(x["size"])] for x in book["buy"]], reverse=True)
        asks = sorted([[float(x["price"]), float(x["size"])] for x in book["sell"]])
        if (
            not bids
            or not asks
            or any(not math.isfinite(p + q) or p <= 0 or q < 0 for p, q in bids + asks)
        ):
            raise ValueError("Delta order book is invalid")
        tape = []
        # A tape failure must not prevent a fresh book from managing existing risk.
        try:
            rows = self.get("/v2/trades/BTCUSD")
            if isinstance(rows, dict):
                rows = rows["trades"]
            for row in rows:
                if row.get("buyer_role") not in ("maker", "taker"):
                    continue
                tape.append(
                    {
                        "timestamp": float(row["timestamp"]) / 1e6,
                        "price": float(row["price"]),
                        "size": float(row["size"]),
                        "side": "sell" if row["buyer_role"] == "maker" else "buy",
                    }
                )
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            pass
        return {
            "bid": bids[0][0],
            "ask": asks[0][0],
            "bids": bids,
            "asks": asks,
            "quote_time": float(book["last_updated_at"]) / 1e6,
            "trades": tape,
            "public_poll_latency_ms": (time.monotonic() - start) * 1000,
        }

    def history(self, start, end):
        rows = {}
        for chunk in range(int(start), int(end), 500 * 60):
            stop = min(chunk + 500 * 60, int(end))
            for row in self.get(
                "/v2/history/candles",
                {"symbol": "BTCUSD", "resolution": "1m", "start": chunk, "end": stop - 1},
            ):
                stamp = int(row["time"])
                if start <= stamp < end:
                    rows[stamp] = row
        return [rows[k] for k in sorted(rows)]

    def options(self, now):
        if "rows" in self.chain:
            return self.chain["rows"]
        rows = self.get(
            "/v2/tickers",
            {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC"},
        )
        codes = {}
        for row in rows:
            try:
                code = row["symbol"].rsplit("-", 1)[-1]
                date = datetime.strptime(code, "%d%m%y").replace(tzinfo=UTC)
                if date.timestamp() + 86400 > now:
                    codes.setdefault(code, (date.timestamp(), row["symbol"]))
            except (KeyError, ValueError):
                continue
        for code, (_, symbol) in sorted(codes.items(), key=lambda x: x[1][0])[:3]:
            # Use exchange metadata for the exact expiry instant, never infer its hour.
            p = self.product(symbol)
            expiry = datetime.fromisoformat(p["settlement_time"].replace("Z", "+00:00")).timestamp()
            if expiry > now + 1800:
                result = normalize_options(rows, expiry, code)
                self.chain["rows"] = result
                return result
        raise ValueError("Eligible BTC option expiry unavailable")

    def context(self, now):
        minute = int(now // 60) * 60
        boundary = int((now + 19800) // 86400) * 86400 - 19800
        if minute not in self.candles:
            self.candles[minute] = self.history(minute - 300 * 60, minute)
        if boundary not in self.prior:
            self.prior[boundary] = self.history(boundary - 86400, boundary)
        product = self.product("BTCUSD")
        interval = int(product["product_specs"]["rate_exchange_interval"])
        # Published BTC funding grid: 00:00 / 08:00 / 16:00 UTC. Fail closed on a change.
        if interval != 28800:
            raise ValueError("BTC funding interval changed; schedule needs review")
        return {
            "bars": self.candles[minute],
            "previous_session": self.prior[boundary],
            "product": product,
            "options": self.options(now),
            "next_funding": (int(now) // interval + 1) * interval,
            "funding_source": "Delta published BTC 8-hour UTC grid, verified against product interval",
        }
