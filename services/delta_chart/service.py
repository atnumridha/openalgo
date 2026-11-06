"""Owner-bound manual Delta India trading. No automatic mutation retries."""

import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID

import requests


class Rejected(ValueError):
    pass


class DeltaError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


SAFE_ERRORS = {
    "immediate_execution_post_only": "Maker-only order rejected because it would fill immediately. Choose another limit price.",
    "ip_not_whitelisted_for_api_key": "Delta rejected this server IP. Add this server’s public IP to your Delta API key whitelist.",
    "invalid_api_key": "Delta API key is invalid. Check your India production connection.",
    "invalid_signature": "Delta could not verify the signature. Check the saved API key and secret.",
    "signature_mismatch": "Delta could not verify the signature. Check the saved API key and secret.",
    "permission_denied": "Delta API key does not have permission for this action.",
    "unauthorized": "Delta API key does not have permission for this action.",
    "insufficient_margin": "Delta rejected the action because available margin is insufficient.",
    "insufficient_wallet_balance": "Delta rejected the action because available balance is insufficient.",
}


def exchange_error(data):
    error = data.get("error") if isinstance(data, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and code in SAFE_ERRORS:
        message = SAFE_ERRORS[code]
        context = error.get("context")
        if code == "ip_not_whitelisted_for_api_key" and isinstance(context, dict):
            candidate = context.get("client_ip")
            if isinstance(candidate, str):
                try:
                    verified_ip = str(ipaddress.ip_address(candidate))
                    message = f"Delta rejected server IP {verified_ip}. Add this public IP to your Delta API key whitelist."
                except ValueError:
                    pass
        return DeltaError(message, code)
    return DeltaError("Delta rejected the request; refresh account state")


def number(value, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Rejected("Invalid numeric value") from None
    if not result.is_finite() or (positive and result <= 0):
        raise Rejected("A finite positive value is required")
    return result


def matching_margined(rows, pid, position):
    """Risk/accounting fields are valid only for the same real-time exposure."""
    matches = []
    for row in rows or []:
        try:
            if (
                str(row.get("product_id")) == str(pid)
                and number(row.get("size")) == number(position.get("size", 0))
                and number(row.get("entry_price"), True)
                == number(position.get("entry_price"), True)
            ):
                matches.append(row)
        except (Rejected, TypeError, AttributeError):
            continue
    return matches[0] if len(matches) == 1 else {}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def symbol_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{3,20}USD", value):
        raise Rejected("Select a USD perpetual symbol")
    return value


def position_version(pid, position):
    return digest(
        {
            "product_id": str(pid),
            "size": str(number(position.get("size", 0))),
            "entry": str(position.get("entry_price")),
            "created_at": position.get("created_at"),
        }
    )


# Delta India fees page verified 2026-11-01: 18% GST on trading fees.
SIZING_FEE_TAX_RATE = Decimal("0.18")
SIZING_BALANCE_BUFFER = Decimal("0.99")
BALANCE_FRACTIONS = frozenset(
    (Decimal(".1"), Decimal(".25"), Decimal(".5"), Decimal(".75"), Decimal("1"))
)


def build_sizing(product, wallet, account):
    """Expose only verified USD available collateral and fractional fee rates."""
    try:
        if not isinstance(product, dict):
            return None
        asset = product.get("settling_asset") or {}
        if not isinstance(asset, dict):
            return None
        if (
            product.get("contract_type") != "perpetual_futures"
            or product.get("notional_type") != "vanilla"
            or asset.get("symbol") != "USD"
            or asset.get("id") is None
            or not isinstance(wallet, list)
        ):
            return None
        rows = [
            row
            for row in wallet
            if isinstance(row, dict)
            and str(row.get("asset_id")) == str(asset["id"])
            and row.get("asset_symbol") == "USD"
        ]
        if len(rows) != 1 or rows[0].get("available_balance") is None:
            return None
        available = number(rows[0]["available_balance"])
        maker = number(product.get("maker_commission_rate"))
        try:
            taker = number(product.get("taker_commission_rate"))
            if taker < 0 or taker > 1 or not math.isfinite(float(taker)):
                taker = None
        except Rejected:
            taker = None
        cv = number(product.get("contract_value"), True)
        margin = number(product.get("initial_margin"), True)
        if available < 0 or maker < 0 or maker > 1:
            return None
        if not all(
            math.isfinite(float(value)) for value in (available, maker, cv, margin)
        ):
            return None
        version = digest(
            {
                "account": account,
                "product_id": str(product["id"]),
                "asset_id": str(asset["id"]),
                "currency": "USD",
                "available": str(available.normalize()),
                "maker": str(maker.normalize()),
                "taker": str(taker.normalize()) if taker is not None else None,
                "fee_tax_rate": str(SIZING_FEE_TAX_RATE),
                "contract_value": str(cv.normalize()),
                "initial_margin": str(margin.normalize()),
                "balance_buffer": str(SIZING_BALANCE_BUFFER),
            }
        )
        return {
            "available_balance": float(available),
            "currency": "USD",
            "maker_fee_rate": float(maker),
            "taker_fee_rate": float(taker) if taker is not None else None,
            "fee_tax_rate": float(SIZING_FEE_TAX_RATE),
            "version": version,
        }
    except (Rejected, KeyError, TypeError, ValueError, OverflowError):
        return None


def affordable_contracts(sizing, price, contract_value, leverage, fraction):
    fraction = number(fraction, True)
    if fraction not in BALANCE_FRACTIONS:
        raise Rejected("Choose 10%, 25%, 50%, 75% or 100% of available balance")
    available = number(sizing["available_balance"])
    maker = number(sizing["maker_fee_rate"])
    tax = number(sizing["fee_tax_rate"])
    cost = (
        number(price, True)
        * number(contract_value, True)
        * (Decimal(1) / number(leverage, True) + maker * (1 + tax))
    )
    return int(fraction * available * SIZING_BALANCE_BUFFER / cost)


def sizing_cost_price(reviewed_price, ticker):
    values = [number(reviewed_price, True), number(ticker.get("mark_price"), True)]
    quotes = ticker.get("quotes")
    if isinstance(quotes, dict):
        for key in ("best_bid", "best_ask"):
            try:
                candidate = number(quotes.get(key), True)
                if math.isfinite(float(candidate)):
                    values.append(candidate)
            except (Rejected, ValueError, OverflowError):
                pass
    return max(values)


def finite_value(value):
    try:
        result = float(number(value))
        return result if math.isfinite(result) else None
    except (Rejected, ValueError, OverflowError):
        return None


def fill_timestamp(value):
    try:
        stamp = number(value, True)
        if stamp > Decimal("1e14"):
            return stamp / 1000000
        if stamp > Decimal("1e11"):
            return stamp / 1000
        return stamp
    except Rejected:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise Rejected("Fill timestamp lacks timezone") from None
        return Decimal(str(parsed.timestamp()))


def actual_fill_fee(row):
    """Use reported all-in cost once; verify its credit and GST provenance."""
    try:
        meta = row.get("meta_data")
        if not isinstance(meta, dict) or row.get("settling_asset_symbol") != "USD":
            return None
        total = number(meta.get("total_commission_in_settling_asset"))
        cash = number(row.get("commission"))
        credit_value = meta.get(
            "tfc_used_for_commission", meta.get("trading_fee_credits_used")
        )
        credit = number(credit_value) if credit_value is not None else Decimal(0)
        if credit < 0 or abs(cash + credit - total) > Decimal(".00000001"):
            return None
        # The live India payload explicitly distinguishes rack commission before GST.
        # Promotions may change the actual total, so do not add GST to total again.
        before_gst = number(meta.get("rack_commission_without_gst"))
        rack = number(meta.get("rack_commision"))
        if abs(rack - before_gst * (1 + SIZING_FEE_TAX_RATE)) > Decimal(".00000001"):
            return None
        return total
    except (Rejected, TypeError, ValueError):
        return None


def position_entry_fees(product, position, fills, complete, *, entry_time=False):
    """Only a complete, unreduced flat-to-current entry chain is attributable."""
    try:
        if not complete or not isinstance(fills, list):
            return None
        current = number(position.get("size"))
        entry = number(position.get("entry_price"), True)
        by_id = {}
        for row in fills:
            if not isinstance(row, dict):
                return None
            nested_product = row.get("product")
            row_pid = row.get(
                "product_id",
                nested_product.get("id") if isinstance(nested_product, dict) else None,
            )
            if row_pid is None:
                return None
            if str(row_pid) != str(product["id"]):
                continue
            identity = row.get("id")
            if identity is None or not str(identity):
                return None
            identity = str(identity)
            if identity in by_id and by_id[identity] != row:
                return None
            by_id[identity] = row
        ordered = sorted(
            by_id.values(), key=lambda row: fill_timestamp(row.get("created_at"))
        )
        expected = current
        cost = Decimal(0)
        weighted = Decimal(0)
        contracts = Decimal(0)
        newer_time = None
        latest = None
        for row in reversed(ordered):
            stamp = fill_timestamp(row.get("created_at"))
            if newer_time is not None and stamp >= newer_time:
                return None
            newer_time = stamp
            meta = row.get("meta_data")
            new = meta.get("new_position") if isinstance(meta, dict) else None
            if (
                row.get("fill_type") != "normal"
                or not isinstance(new, dict)
                or number(new.get("size")) != expected
            ):
                return None
            if str(new.get("last_fill_uuid")) != str(row["id"]):
                return None
            if row.get("side") != ("buy" if current > 0 else "sell"):
                return None
            quantity = number(row.get("size"), True)
            if quantity != quantity.to_integral_value():
                return None
            signed = quantity if current > 0 else -quantity
            previous = expected - signed
            if previous and (previous > 0) != (current > 0):
                return None
            fee = actual_fill_fee(row)
            if fee is None:
                return None
            if latest is None:
                latest = new
                if abs(number(new.get("entry_price"), True) - entry) > Decimal(
                    ".00000001"
                ):
                    return None
            cost += fee
            contracts += quantity
            weighted += number(row.get("price"), True) * quantity
            if not previous:
                if contracts != abs(current) or abs(
                    weighted / contracts - entry
                ) > Decimal(".00000001"):
                    return None
                if abs(number(latest.get("total_commission_paid")) - cost) > Decimal(
                    ".00000001"
                ):
                    return None
                return stamp if entry_time else cost
            expected = previous
        return None
    except (Rejected, KeyError, TypeError, ValueError, OverflowError):
        return None


def build_accounting(product, wallet, position, mark, gross_pnl, fills, complete=False):
    """Read-only USD wallet plus current-exposure costs, never realized-wallet P&L."""
    result = {
        "currency": "USD",
        "balance": None,
        "available_balance": None,
        "position_gross_pnl": None,
        "position_entry_fees": None,
        "estimated_maker_exit_fee": None,
        "estimated_exit_fee": None,
        "exit_fee_basis": "taker",
        "position_net_after_fees": None,
        "fee_status": "unavailable",
        "message": "USD balance or position accounting unavailable.",
    }
    asset = product.get("settling_asset") or {}
    if (
        isinstance(asset, dict)
        and asset.get("symbol") == "USD"
        and asset.get("id") is not None
        and isinstance(wallet, list)
    ):
        rows = [
            row
            for row in wallet
            if isinstance(row, dict)
            and str(row.get("asset_id")) == str(asset["id"])
            and row.get("asset_symbol") == "USD"
        ]
        if len(rows) == 1:
            result["balance"] = finite_value(rows[0].get("balance"))
            result["available_balance"] = finite_value(rows[0].get("available_balance"))
    try:
        size = number(position.get("size"))
    except Rejected:
        return result
    if not size:
        result.update(
            position_gross_pnl=0,
            position_entry_fees=0,
            estimated_maker_exit_fee=0,
            estimated_exit_fee=0,
            position_net_after_fees=0,
            fee_status="flat",
            message="No open position. Zero position costs do not represent historical trading fees; wallet balances are reported directly by Delta.",
        )
        return result
    result["position_gross_pnl"] = finite_value(gross_pnl)
    if (
        product.get("notional_type") != "vanilla"
        or not isinstance(asset, dict)
        or asset.get("symbol") != "USD"
    ):
        result["message"] = (
            "Open-position fee accounting requires a verified USD-settled vanilla contract. Funding and realized results are excluded."
        )
        return result
    try:
        maker = number(product.get("maker_commission_rate"))
        if maker < 0 or maker > 1:
            raise Rejected("Unsupported maker fee")
        estimate = (
            abs(size)
            * number(product.get("contract_value"), True)
            * number(mark, True)
            * maker
            * (1 + SIZING_FEE_TAX_RATE)
        )
        result["estimated_maker_exit_fee"] = finite_value(estimate)
    except Rejected:
        pass
    try:
        taker = number(product.get("taker_commission_rate"))
        if taker < 0 or taker > 1:
            raise Rejected("Unsupported taker fee")
        result["estimated_exit_fee"] = finite_value(
            abs(size)
            * number(product.get("contract_value"), True)
            * number(mark, True)
            * taker
            * (1 + SIZING_FEE_TAX_RATE)
        )
    except Rejected:
        pass
    fees = position_entry_fees(product, position, fills, complete)
    if fees is None:
        result.update(
            fee_status="incomplete",
            message="Open-position entry fees are unverified: a complete unreduced flat-to-current fill lifecycle with all-in fee/GST evidence is required. Estimated closing fee is separate; funding and realized results are excluded.",
        )
        return result
    result["standard_exit_fee"] = result["estimated_exit_fee"]
    result["scalper_fee_valid_until"] = None
    if product.get("_scalper_enabled") is True and product.get("symbol") in (
        "BTCUSD",
        "ETHUSD",
    ):
        first = position_entry_fees(product, position, fills, complete, entry_time=True)
        deadline = float(first) + 1740 if first is not None else 0
        if time.time() < deadline and first <= Decimal(str(time.time())):
            result["scalper_fee_valid_until"] = deadline
            result["estimated_exit_fee"] = 0
    result["position_entry_fees"] = finite_value(fees)
    result["fee_status"] = "verified"
    result["message"] = (
        "Actual entry fees include reported GST and fee-credit costs once. Closing market/taker fee incl. GST is estimated at mark; funding and realized results are excluded. Wallet balances already include booked costs."
    )
    if result["scalper_fee_valid_until"]:
        result["message"] = (
            "Scalper offer verified enabled: closing fee estimated at zero inside the eligible window; standard taker fee resumes 60 seconds early. Final fee depends on Delta's fill. Opening fee vouchers are separate from cash profit."
        )
    if (
        result["position_gross_pnl"] is not None
        and result["position_entry_fees"] is not None
        and result["estimated_exit_fee"] is not None
    ):
        result["position_net_after_fees"] = finite_value(
            number(result["position_gross_pnl"])
            - fees
            - number(result["estimated_exit_fee"])
        )
    return result


class Client:
    HOST = "https://api.india.delta.exchange"

    def __init__(self, key, secret):
        self.key = key
        self.secret = secret

    def request(self, method, path, params=None, payload=None, private=True):
        query = ("?" + urlencode(params)) if params else ""
        body = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "OpenAlgo-DeltaChart/1.0",
        }
        if private:
            stamp = str(int(time.time()))
            signed = method + stamp + path + query + body
            headers.update(
                {
                    "api-key": self.key,
                    "timestamp": stamp,
                    "signature": hmac.new(
                        self.secret.encode(), signed.encode(), hashlib.sha256
                    ).hexdigest(),
                }
            )
        response = requests.request(
            method,
            self.HOST + path + query,
            headers=headers,
            data=body or None,
            timeout=(3, 8),
            allow_redirects=False,
        )
        if response.status_code >= 500:
            raise TimeoutError("Exchange response unknown")
        try:
            data = response.json()
        except ValueError:
            raise TimeoutError("Exchange response unknown") from None
        if not response.ok or not data.get("success"):
            raise exchange_error(data)
        return data.get("result", {})

    def pages(self, path, params):
        rows = []
        params = dict(params, page_size=100)
        seen = set()
        started = time.monotonic()
        for _ in range(100):
            if time.monotonic() - started > 8:
                raise DeltaError("Incomplete Delta pagination within freshness window")
            # Pagination must retain metadata, unlike ordinary request().
            query = "?" + urlencode(params)
            stamp = str(int(time.time()))
            signature = hmac.new(
                self.secret.encode(),
                ("GET" + stamp + path + query).encode(),
                hashlib.sha256,
            ).hexdigest()
            response = requests.get(
                self.HOST + path + query,
                headers={
                    "api-key": self.key,
                    "timestamp": stamp,
                    "signature": signature,
                    "User-Agent": "OpenAlgo-DeltaChart/1.0",
                },
                timeout=(3, 8),
                allow_redirects=False,
            )
            try:
                data = response.json()
            except ValueError:
                raise DeltaError(
                    "Cannot refresh complete Delta order history"
                ) from None
            if not response.ok:
                raise exchange_error(data)
            if not data.get("success") or not isinstance(data.get("result"), list):
                raise DeltaError("Invalid Delta history response")
            rows.extend(data["result"])
            cursor = (data.get("meta") or {}).get("after")
            if not cursor:
                return rows
            if cursor in seen:
                raise DeltaError("Incomplete Delta pagination")
            seen.add(cursor)
            params["after"] = cursor
        raise DeltaError("Delta history exceeds safe pagination limit")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS evidence (user TEXT, request_id TEXT, value TEXT, PRIMARY KEY(user,request_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS credentials (user TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS intents (user TEXT, request_id TEXT, fingerprint TEXT, account TEXT, symbol TEXT, action TEXT, response TEXT, pending INTEGER, PRIMARY KEY(user,request_id))"
            )
        os.chmod(self.path, 0o600)

    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def pending(self, user, symbol):
        with self.db() as db:
            return [
                json.loads(r["response"]) | {"action": r["action"]}
                for r in db.execute(
                    "SELECT * FROM intents WHERE user=? AND symbol=? AND pending=1",
                    (user, symbol),
                )
            ]

    def replay(self, user, rid, fingerprint):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM intents WHERE user=? AND request_id=?", (user, rid)
            ).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise Rejected("Request ID already belongs to a different action")
            return json.loads(row["response"])

    def claim(self, user, data, fingerprint, lock_account=None):
        response = {
            "status": "pending",
            "message": "Outcome awaiting reconciliation; do not resubmit",
            "request_id": data["request_id"],
        }
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT * FROM intents WHERE user=? AND request_id=?",
                (user, data["request_id"]),
            ).fetchone()
            if replay:
                if replay["fingerprint"] != fingerprint:
                    raise Rejected("Request ID already belongs to a different action")
                return json.loads(replay["response"])
            gate_sql = "SELECT 1 FROM intents WHERE account=? AND pending=1"
            gate_args = (lock_account or data["account"],)
            if data["action"] != "entry":
                gate_sql += " AND symbol=?"
                gate_args += (data["symbol"],)
            if db.execute(gate_sql, gate_args).fetchone():
                raise Rejected(
                    "An earlier action is awaiting reconciliation for this product"
                )
            db.execute(
                "INSERT INTO intents VALUES(?,?,?,?,?,?,?,1)",
                (
                    user,
                    data["request_id"],
                    fingerprint,
                    lock_account or data["account"],
                    data["symbol"],
                    data["action"],
                    json.dumps(response),
                ),
            )
        return None

    def receipts(self, user, symbol):
        with self.db() as db:
            rows = db.execute(
                "SELECT response FROM intents WHERE user=? AND symbol=? AND pending=0 ORDER BY rowid DESC LIMIT 20",
                (user, symbol),
            ).fetchall()
        return [json.loads(r["response"]) for r in rows]

    def evidence(self, user, rid, value):
        with self.db() as db:
            db.execute(
                "INSERT OR REPLACE INTO evidence VALUES(?,?,?)",
                (user, rid, json.dumps(value)),
            )

    def unresolved(self, user, symbol):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT i.*,e.value FROM intents i JOIN evidence e USING(user,request_id) WHERE i.user=? AND i.symbol=? AND pending=1",
                    (user, symbol),
                )
            ]

    def finish(self, user, rid, response):
        with self.db() as db:
            db.execute(
                "UPDATE intents SET response=?,pending=? WHERE user=? AND request_id=?",
                (json.dumps(response), int(response["status"] == "pending"), user, rid),
            )


class TradingService:
    def __init__(self, store, credentials, client_factory=Client):
        self.store = store
        self.credentials = credentials
        self.client_factory = client_factory
        self.fill_cache = {}
        self.fill_lock = threading.Lock()
        from .plans import ManagedPlans

        self.plans = ManagedPlans(self)

    def client(self, user):
        creds = self.credentials(user)
        if not creds:
            raise Rejected("Connect a Delta India account to enable trading")
        key, secret = creds
        return self.client_factory(key, secret), hashlib.sha256(
            (user + "\0" + key).encode()
        ).hexdigest()[:24]

    def recent_fills(self, client, account, pid, force=False):
        key = (account, pid)
        with self.fill_lock:
            cached = self.fill_cache.get(key)
            if not force and cached and time.monotonic() - cached[0] < 10:
                return cached[1]
        try:
            rows = client.pages(
                "/v2/fills",
                {
                    "product_ids": pid,
                    "start_time": int((time.time() - 86400) * 1000000),
                },
            )
        except Exception:
            return None  # Unknown history leaves fees/net unavailable.
        if not isinstance(rows, list):
            return None
        with self.fill_lock:
            self.fill_cache[key] = (time.monotonic(), rows)
        return rows

    def read_wallet(self, client):
        try:
            return client.request("GET", "/v2/wallet/balances")
        except Exception:
            return None  # Optional sizing never disables manual order management.

    def read_scalper_enabled(self, client):
        try:
            value = client.request("GET", "/v2/users/trading_preferences")
            return (
                isinstance(value, dict)
                and value.get("futures_scalper_offer_enabled") is True
            )
        except Exception:
            return False

    def snapshot(self, user, symbol):
        started = time.monotonic()
        asof = int(time.time())
        symbol = symbol_value(symbol)
        client, account = self.client(user)
        product = client.request("GET", "/v2/products/" + symbol, private=False)
        if (
            product.get("symbol") != symbol
            or product.get("contract_type") != "perpetual_futures"
            or product.get("state") != "live"
        ):
            raise Rejected("Product is not a live perpetual")
        margin = number(product.get("initial_margin"), True)
        ceiling = min(200, int(Decimal(100) / margin))
        if ceiling < 1:
            raise Rejected("Product leverage ceiling unavailable")
        tick = number(product.get("tick_size"), True)
        cv = number(product.get("contract_value"), True)
        pid = product["id"]
        with ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="delta-chart-read"
        ) as pool:
            ticker_future = pool.submit(
                client.request, "GET", "/v2/tickers/" + symbol, private=False
            )
            position_future = pool.submit(
                client.request, "GET", "/v2/positions", params={"product_id": pid}
            )
            margined_future = pool.submit(
                client.request,
                "GET",
                "/v2/positions/margined",
                params={"product_ids": pid},
            )
            orders_future = pool.submit(
                client.pages,
                "/v2/orders",
                {"product_ids": pid, "states": "open,pending"},
            )
            wallet_future = pool.submit(self.read_wallet, client)
            scalper_future = pool.submit(self.read_scalper_enabled, client)
            leverage_future = pool.submit(
                client.request, "GET", f"/v2/products/{pid}/orders/leverage"
            )
            ticker = ticker_future.result()
            position = position_future.result()
            fills_future = pool.submit(
                self.recent_fills,
                client,
                account,
                pid,
                force=bool(number(position.get("size", 0))),
            )
            margined = margined_future.result()
            orders = orders_future.result()
            fills = fills_future.result()
            leverage = leverage_future.result()
            wallet = wallet_future.result()
            product = dict(product, _scalper_enabled=scalper_future.result())
        orders = [o for o in orders if str(o.get("product_id")) == str(pid)]
        mark = number(ticker.get("mark_price"), True)
        if time.monotonic() - started > 10:
            raise Rejected("Account preflight became stale; refresh and try again")
        product = dict(
            product,
            _snapshot_asof=asof,
            _sizing=build_sizing(product, wallet, account),
            _wallet=wallet,
            _fills_complete=isinstance(fills, list),
        )
        return (
            client,
            account,
            product,
            tick,
            cv,
            ceiling,
            mark,
            ticker,
            position,
            margined,
            orders,
            fills,
            leverage,
        )

    @staticmethod
    def validate_entry_market(client, data):
        from .entry_guard import INTERVAL_RESOLUTIONS, validate_entry_candles

        levels = data.get("auto_protection") or {}
        span = number(levels.get("interval_seconds"), True)
        source = number(levels.get("source_time"), True)
        if span != span.to_integral_value() or int(span) not in INTERVAL_RESOLUTIONS:
            raise Rejected("Unsupported reviewed entry candle interval")
        now = int(time.time())
        candles = client.request(
            "GET",
            "/v2/history/candles",
            params={
                "symbol": data["symbol"],
                "resolution": INTERVAL_RESOLUTIONS[int(span)],
                "start": int(source - 20 * span),
                "end": now,
            },
            private=False,
        )
        # Structural modules have their own closed-pattern confirmation. This
        # privileged path is reached only after exact durable Auto proof checks;
        # it must not inherit EMA-specific sharp-move vetoes. OHLC/freshness and
        # the closed-breakout check remain enforced by the common validator.
        structural = data.get("automation_generation") and data.get("strategy_id") in {
            "liquidity_sweep", "fvg", "breakout_retest", "range_rsi", "double_extrema", "ema_fib"
        }
        checked = dict(data, entry_mode="manual") if structural else data
        validate_entry_candles(checked, candles, time.time())

    def maker_verified(self, user, order):
        """Delta Order omits post_only: use exact confirmed local ACK provenance.

        A missing response flag is never evidence for an unrelated order.  An
        explicit false flag or a changed server update timestamp always wins.
        """
        if order.get("order_type") != "limit_order":
            return False
        if "post_only" in order:
            return order["post_only"] is True
        if order.get("time_in_force") != "gtc":
            return False
        with self.store.db() as db:
            rows = db.execute(
                "SELECT i.response,e.value FROM intents i JOIN evidence e USING(user,request_id) WHERE i.user=? AND i.pending=0 ORDER BY i.rowid DESC LIMIT 500",
                (user,),
            ).fetchall()
        for row in rows:
            try:
                result = json.loads(row["response"])
                evidence = json.loads(row["value"])
                payload = evidence["payload"]
                if (
                    result.get("status") != "confirmed"
                    or str(result.get("order_id")) != str(order.get("id"))
                    or evidence.get("path") != "/v2/orders"
                    or evidence.get("method") not in ("POST", "PUT")
                ):
                    continue
                if payload.get("post_only") is not True or str(
                    payload.get("product_id")
                ) != str(order.get("product_id")):
                    return False
                if evidence["method"] == "POST" and (
                    payload.get("client_order_id") != order.get("client_order_id")
                    or payload.get("side") != order.get("side")
                    or payload.get("time_in_force") != "gtc"
                ):
                    return False
                if evidence["method"] == "PUT" and str(payload.get("id")) != str(
                    order.get("id")
                ):
                    return False
                for key in ("size", "limit_price", "stop_price"):
                    if key in payload and number(payload[key]) != number(
                        order.get(key)
                    ):
                        return False
                for key in ("reduce_only", "stop_order_type", "stop_trigger_method"):
                    if key in payload and payload[key] != order.get(key):
                        return False
                acknowledged_update = (evidence.get("ack") or {}).get("updated_at")
                if acknowledged_update is not None:
                    return acknowledged_update == order.get("updated_at")
                # Compatibility for already-acknowledged creates from before
                # ACK update timestamps were persisted. No edits may have occurred.
                return (
                    evidence["method"] == "POST"
                    and bool(order.get("created_at"))
                    and order.get("created_at") == order.get("updated_at")
                )
            except (Rejected, ValueError, KeyError, TypeError):
                return False
        return False

    @staticmethod
    def unfilled_cancellation(order, payload):
        if not isinstance(order, dict) or order.get("state") != "cancelled":
            return None
        try:
            size = number(order.get("size"), True)
            if size != number(payload.get("size"), True) or number(order.get("unfilled_size")) != size:
                return None
        except Rejected:
            return None
        return SAFE_ERRORS.get(order.get("cancellation_reason"),
                               "Delta cancelled the order without a fill")

    @staticmethod
    def assert_account_flat(client):
        # Account-wide, including positions/orders opened outside this chart.
        # Never interpret unavailable/malformed exposure data as a flat account.
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="delta-entry-gate") as pool:
            positions_future = pool.submit(client.request, "GET", "/v2/positions/margined")
            orders_future = pool.submit(client.pages, "/v2/orders", {"states": "open,pending"})
            positions, orders = positions_future.result(), orders_future.result()
        if time.monotonic() - started > 5 or not isinstance(positions, list) or not isinstance(orders, list):
            raise Rejected("Cannot verify the account is flat; no new entry sent")
        if any(not isinstance(row, dict) or "size" not in row for row in positions):
            raise Rejected("Cannot verify account positions; no new entry sent")
        if orders or any(number(row["size"]) != 0 for row in positions):
            raise Rejected("A Delta order or position is already running. Wait until it exits or is fully cancelled.")

    def reconcile(self, user, symbol, client, pid):
        for row in self.store.unresolved(user, symbol):
            expected = json.loads(row["value"])
            payload = expected["payload"]
            matched = False
            order_id = None
            try:
                if payload.get("client_order_id"):
                    found = client.request(
                        "GET",
                        "/v2/orders/client_order_id/" + payload["client_order_id"],
                    )
                    matched = (
                        isinstance(found, dict)
                        and found.get("client_order_id") == payload["client_order_id"]
                        and str(found.get("product_id")) == str(pid)
                    )
                    order_id = found.get("id") if isinstance(found, dict) else None
                elif expected["method"] == "DELETE":
                    found = client.request("GET", "/v2/orders/" + str(payload["id"]))
                    matched = found.get("state") in ("cancelled", "closed") and str(
                        found.get("product_id")
                    ) == str(pid)
                    order_id = payload["id"]
                elif expected["method"] == "PUT" and expected["path"] == "/v2/orders":
                    found = client.request("GET", "/v2/orders/" + str(payload["id"]))
                    matched = (
                        str(found.get("product_id")) == str(pid)
                        and found.get("state") in ("open", "pending")
                        and (
                            not payload.get("post_only")
                            or (
                                found.get("post_only") is True
                                and found.get("order_type") == "limit_order"
                            )
                        )
                        and all(
                            number(found.get(k)) == number(v)
                            for k, v in payload.items()
                            if k in ("limit_price", "stop_price", "size")
                        )
                    )
                    order_id = payload["id"]
                # Position bracket creation cannot be proven by a position disappearing.
                # Exact matching reduce-only children establish the requested live protection.
                elif expected["path"] == "/v2/orders/bracket":
                    orders = client.pages(
                        "/v2/orders", {"product_ids": pid, "states": "open,pending"}
                    )
                    legs = []
                    for name, kind in (
                        ("stop_loss_order", "stop_loss_order"),
                        ("take_profit_order", "take_profit_order"),
                    ):
                        if name in payload:
                            legs.append((kind, payload[name]["stop_price"]))
                    if not legs:
                        for field, kind in (
                            ("bracket_stop_loss_price", "stop_loss_order"),
                            ("bracket_take_profit_price", "take_profit_order"),
                        ):
                            if field in payload:
                                legs.append((kind, payload[field]))
                    matched = bool(legs) and all(
                        any(
                            str(o.get("product_id")) == str(pid)
                            and o.get("stop_order_type") == kind
                            and (
                                o.get("reduce_only") is True
                                or o.get("bracket_order") is True
                            )
                            and number(o.get("stop_price")) == number(price)
                            for o in orders
                        )
                        for kind, price in legs
                    )
                elif expected["path"].endswith("/orders/leverage"):
                    found = client.request("GET", expected["path"])
                    if number(found.get("leverage"), True) == number(
                        payload["leverage"], True
                    ):
                        self.store.finish(
                            user,
                            row["request_id"],
                            {
                                "status": "rejected",
                                "request_id": row["request_id"],
                                "message": "Leverage change reconciled; no entry was submitted. Review account before a new action.",
                            },
                        )
                    continue
                if matched:
                    result = {
                        "status": "confirmed",
                        "request_id": row["request_id"],
                        "message": "Action reconciled from read-only Delta order evidence",
                    }
                    if order_id is not None:
                        result["order_id"] = str(order_id)
                    cancellation = self.unfilled_cancellation(found, payload) if payload.get("client_order_id") else None
                    if cancellation:
                        result.update(status="rejected", message=cancellation)
                    self.store.finish(user, row["request_id"], result)
            except Exception:
                pass  # Missing evidence never authorizes a retry.

    def state(self, user, symbol):
        c, a, p, t, cv, cap, mark, ticker, pos, margined, orders, fills, lev = (
            self.snapshot(user, symbol)
        )
        self.reconcile(user, symbol, c, p["id"])
        size = number(pos.get("size", 0))
        extra = matching_margined(margined, p["id"], pos)

        def optional(v):
            return float(number(v)) if v is not None else None

        def quote(value):
            try:
                result = float(number(value, True))
                return result if math.isfinite(result) else None
            except Rejected:
                return None

        quotes = ticker.get("quotes") if isinstance(ticker.get("quotes"), dict) else {}
        pnl = None
        pnl = extra.get("unrealized_pnl")
        if (
            size
            and p.get("notional_type") == "vanilla"
            and pos.get("entry_price") is not None
        ):
            pnl = (mark - number(pos["entry_price"], True)) * size * cv
        normalized = []
        for o in orders:
            kind = {"stop_loss_order": "sl", "take_profit_order": "target"}.get(
                o.get("stop_order_type"), "entry"
            )
            if not (o.get("reduce_only") is True or o.get("bracket_order") is True):
                kind = "entry"
            normalized.append(
                {
                    "id": str(o["id"]),
                    "side": o["side"],
                    "size": float(number(o["size"])),
                    "unfilled": float(number(o.get("unfilled_size", o["size"]))),
                    "type": o["order_type"],
                    "post_only": self.maker_verified(user, o),
                    "kind": kind,
                    "price": optional(
                        o.get("stop_price") if kind != "entry" else o.get("limit_price")
                    ),
                    "reduce_only": bool(
                        o.get("reduce_only") is True or o.get("bracket_order") is True
                    ),
                    "state": o.get("state", "open"),
                    "version": digest(o),
                }
            )
        return {
            "connected": True,
            "environment": "india_prod",
            "asof": p["_snapshot_asof"],
            "symbol": symbol,
            "account": a,
            "product": {
                "id": p["id"],
                "symbol": symbol,
                "tick_size": float(t),
                "contract_value": float(cv),
                "max_leverage": cap,
            },
            "ticker": {
                "mark": float(mark),
                "last": optional(ticker.get("close")),
                "bid": quote(quotes.get("best_bid")),
                "ask": quote(quotes.get("best_ask")),
            },
            "managed_plans": self.plans.list(user, symbol, fills, p["_fills_complete"]),
            "sizing": p["_sizing"],
            "accounting": build_accounting(
                p, p["_wallet"], pos, mark, pnl, fills, p["_fills_complete"]
            ),
            "leverage": optional(lev.get("leverage")),
            "position": {
                "size": float(size),
                "version": position_version(p["id"], pos),
                "entry": optional(pos.get("entry_price")),
                "mark": float(mark),
                "pnl": optional(pnl),
                "liquidation": optional(extra.get("liquidation_price")),
            }
            if size
            else None,
            "orders": normalized,
            "fills_complete": p["_fills_complete"],
            "fills": [
                {
                    "id": str(f["id"]),
                    "side": f["side"],
                    "price": float(number(f["price"])),
                    "size": float(number(f["size"])),
                    "created_at": str(f["created_at"]),
                }
                for f in (fills or [])
                if str(f.get("product_id", (f.get("product") or {}).get("id")))
                == str(p["id"])
            ],
            "pending": self.store.pending(user, symbol),
            "receipts": self.store.receipts(user, symbol),
            **({"automation": self.automation.status(user, a, symbol)} if hasattr(self, "automation") else {}),
        }

    def manage(self, user, data):
        return self.plans.manage(user, data)

    def action(self, user, data):
        # Serialize manual close with plan observation, child action and state updates.
        account = data.get("account") if isinstance(data, dict) else None
        symbol = data.get("symbol") if isinstance(data, dict) else None
        if isinstance(data, dict) and data.get("action") == "entry":
            # Connection replacement shares the outer barrier, so its successful
            # acknowledgement follows every submission using the previous key.
            with self.plans.lock("delta-connection", user, "*"):
                # Serialize entries from different chart tabs/products for this API key.
                self.client(user)  # Validate saved credentials before deriving the lock key.
                key_account = hashlib.sha256(self.credentials(user)[0].encode()).hexdigest()
                with self.plans.lock("delta-entry", key_account, "*"):
                    with self.plans.lock(user, account, symbol):
                        return self._action(user, data)
        with self.plans.lock(user, account, symbol):
            return self._action(user, data)

    def _action(self, user, data):
        if not isinstance(data, dict):
            raise Rejected("JSON object required")
        try:
            rid = str(UUID(data.get("request_id", "")))
            fingerprint = digest(data)
        except (ValueError, TypeError, AttributeError):
            raise Rejected(
                "Valid request UUID and finite JSON values required"
            ) from None
        if rid != data.get("request_id"):
            raise Rejected("Canonical request UUID required")
        replay = self.store.replay(user, rid, fingerprint)
        if replay:
            return replay
        symbol = symbol_value(data.get("symbol"))
        client, account = self.client(user)
        if data.get("account") != account:
            raise Rejected("Account changed; refresh before trading")
        action = data.get("action")
        if action == "entry" and hasattr(self, "automation"):
            self.automation.authorize_entry(user, data)
        if action not in ("entry", "close", "protect", "edit", "cancel", "adopt"):
            raise Rejected("Unsupported action")
        if data.get("entry_mode") is not None and (
            action != "entry"
            or data["entry_mode"] != "manual"
            or not isinstance(data.get("auto_protection"), dict)
        ):
            raise Rejected(
                "Manual entry requires explicit mode and automatic SL/target protection"
            )
        if action == "entry" and data.get("order_type", "limit_order") != "limit_order":
            raise Rejected("Maker-only entries require limit orders")
        if (
            action == "close"
            and data.get("order_type", "market_order") != "market_order"
        ):
            raise Rejected("Position closes use reduce-only market orders")
        fraction = None
        if data.get("balance_fraction") is not None:
            fraction = number(data["balance_fraction"], True)
            if action != "entry" or fraction not in BALANCE_FRACTIONS:
                raise Rejected(
                    "Balance sizing requires an entry and 10%, 25%, 50%, 75% or 100%"
                )
            if (
                not isinstance(data.get("sizing_version"), str)
                or not data["sizing_version"]
            ):
                raise Rejected(
                    "Refresh available balance and review the percentage quantity"
                )
        if action == "close":
            self.plans.assert_close_ready(user, account, symbol)
        lock_account = hashlib.sha256(self.credentials(user)[0].encode()).hexdigest()
        replay = self.store.claim(user, data, fingerprint, lock_account)
        if replay:
            return replay
        if action == "adopt":
            try:
                result = self.plans.adopt(user, account, data)
            except (Rejected, DeltaError) as exc:
                self.store.finish(
                    user,
                    rid,
                    {"status": "rejected", "message": str(exc), "request_id": rid},
                )
                raise Rejected(str(exc)) from None
            except Exception:
                self.store.finish(
                    user,
                    rid,
                    {
                        "status": "rejected",
                        "message": "Fresh adoption preflight unavailable; no order submitted",
                        "request_id": rid,
                    },
                )
                raise Rejected(
                    "Fresh adoption preflight unavailable; no order submitted"
                ) from None
            self.store.finish(user, rid, result)
            return result
        mutated = False
        if action == "close":
            self.plans.close_intent(user, account, symbol, data)
        try:
            c, a, p, t, cv, cap, mark, ticker, pos, margined, orders, fills, lev = (
                self.snapshot(user, symbol)
            )
            pid = p["id"]
            size = number(pos.get("size", 0))
            if a != account:
                raise Rejected("Account connection changed during preflight")
            if action in ("close", "protect") and data.get(
                "position_version"
            ) != position_version(pid, pos):
                raise Rejected("Position changed; refresh before acting")
            if size != size.to_integral_value():
                raise Rejected("Position contract quantity is invalid")

            def price(v):
                n = number(v, True)
                if n % t:
                    raise Rejected("Price must match the product tick size")
                return str(n)

            liquidation_row = matching_margined(margined, pid, pos)

            def protections(side, include_retained=False):
                values = {}
                for name in ("stop", "target"):
                    value = data.get(name)
                    if value is None and include_retained:
                        field = (
                            "bracket_stop_loss_price"
                            if name == "stop"
                            else "bracket_take_profit_price"
                        )
                        value = order.get(field)
                        if value is not None and number(value) == 0:
                            value = None
                    if value is not None:
                        n = number(price(value), True)
                        below = (side == "buy") == (name == "stop")
                        if (below and n >= mark) or (not below and n <= mark):
                            raise Rejected(
                                "Protection must be on the correct side of current mark"
                            )
                        if action in ("protect", "edit") and size:
                            if name == "target":
                                entry_price = number(pos.get("entry_price"), True)
                                if (size > 0 and n <= entry_price) or (
                                    size < 0 and n >= entry_price
                                ):
                                    raise Rejected(
                                        "Target must remain beyond the position entry price"
                                    )
                            elif liquidation_row.get("liquidation_price") is not None:
                                liquidation = number(
                                    liquidation_row["liquidation_price"]
                                )
                                if liquidation > 0 and (
                                    (size > 0 and n <= liquidation)
                                    or (size < 0 and n >= liquidation)
                                ):
                                    raise Rejected(
                                        "Stop must remain inside the known liquidation price"
                                    )
                        reference = None
                        if (
                            action == "entry"
                            and data.get("order_type", "limit_order") == "limit_order"
                        ):
                            reference = number(price(data.get("price")), True)
                        elif (
                            action == "edit"
                            and order.get("order_type") == "limit_order"
                            and not order.get("stop_order_type")
                        ):
                            reference = number(
                                price(data.get("price", order.get("limit_price"))), True
                            )
                        if reference is not None and (
                            (below and n >= reference) or (not below and n <= reference)
                        ):
                            raise Rejected(
                                "Protection must also be on the correct side of the entry price"
                            )
                        values[name] = str(n)
                return values

            def validate_sizing(current_product, sizing, current_ticker):
                if fraction is None:
                    return
                if not sizing:
                    raise Rejected(
                        "USD available balance and fee metadata are unavailable; enter a manual quantity or refresh"
                    )
                if sizing["version"] != data["sizing_version"]:
                    raise Rejected(
                        "Available balance or fees changed; refresh and review the percentage quantity"
                    )
                if (
                    str(current_product.get("id")) != str(pid)
                    or current_product.get("symbol") != symbol
                    or current_product.get("state") != "live"
                ):
                    raise Rejected("Product changed during balance preflight")
                current_tick = number(current_product.get("tick_size"), True)
                if number(data["price"], True) % current_tick:
                    raise Rejected("Price no longer matches the product tick size")
                if leverage > min(
                    200,
                    int(
                        Decimal(100)
                        / number(current_product.get("initial_margin"), True)
                    ),
                ):
                    raise Rejected("Product leverage ceiling changed")
                maximum = affordable_contracts(
                    sizing,
                    sizing_cost_price(data["price"], current_ticker),
                    number(current_product.get("contract_value"), True),
                    leverage,
                    fraction,
                )
                if maximum < 1:
                    raise Rejected(
                        "Available balance cannot fund one contract with fees and buffer"
                    )
                if qty > maximum:
                    raise Rejected(
                        "Reviewed quantity exceeds the available balance allocation including fees and buffer"
                    )

            path = "/v2/orders"
            method = "POST"
            payload = {"product_id": pid}
            if action == "entry":
                if size or orders:
                    raise Rejected("A Delta order or position is already running. Wait until it exits or is fully cancelled.")
                self.assert_account_flat(c)
                side = data.get("side")
                order_type = data.get("order_type", "limit_order")
                if side not in ("buy", "sell") or order_type != "limit_order":
                    raise Rejected("Invalid side or order type")
                qty = number(data.get("size"), True)
                if qty != qty.to_integral_value():
                    raise Rejected("Size must be whole contracts")
                leverage = number(data.get("leverage", 5), True)
                if leverage != leverage.to_integral_value() or leverage > cap:
                    raise Rejected("Leverage exceeds product ceiling")
                payload.update(
                    side=side,
                    size=int(qty),
                    order_type=order_type,
                    reduce_only=False,
                    client_order_id=UUID(rid).hex,
                )
                payload["limit_price"] = price(data.get("price"))
                if data.get("stop") is not None or data.get("target") is not None:
                    raise Rejected(
                        "Attached bracket exits cannot be maker-only; add separate maker SL/target after the entry fills"
                    )
                validate_sizing(p, p["_sizing"], ticker)
                if data.get("auto_protection") is not None:
                    if size or orders:
                        raise Rejected(
                            "Managed entry requires a flat selected product and no existing orders"
                        )
                    levels = data["auto_protection"]
                    if levels.get("interval_seconds") == 60 or data.get("automation_generation"):
                        planned = (
                            (
                                abs(
                                    number(data["price"], True)
                                    - number(levels.get("stop"), True)
                                )
                                + number(data["price"], True)
                                * number(p.get("maker_commission_rate"))
                                * (1 + SIZING_FEE_TAX_RATE)
                                + number(levels.get("stop"), True)
                                * number(p.get("taker_commission_rate"))
                                * (1 + SIZING_FEE_TAX_RATE)
                            )
                            * cv
                            * qty
                            * 85
                        )
                        if planned > 20:
                            raise Rejected(
                                "Planned scalp loss including standard fees exceeds the ₹20 limit; reduce lots"
                            )
                    self.validate_entry_market(c, data)
                    self.plans.create(user, account, p, data, mark)
                # Changing leverage on existing exposure also changes its risk; fail closed.
                if number(lev.get("leverage"), True) != leverage:
                    if size or orders:
                        raise Rejected(
                            "Flatten position and clear orders before changing leverage"
                        )
                    leverage_started = time.monotonic()
                    with ThreadPoolExecutor(
                        max_workers=5 if fraction is not None else 2,
                        thread_name_prefix="delta-chart-leverage-check",
                    ) as pool:
                        position_future = pool.submit(
                            c.request,
                            "GET",
                            "/v2/positions",
                            params={"product_id": pid},
                        )
                        orders_future = pool.submit(
                            c.pages,
                            "/v2/orders",
                            {"product_ids": pid, "states": "open,pending"},
                        )
                        if fraction is not None:
                            wallet_future = pool.submit(self.read_wallet, c)
                            product_future = pool.submit(
                                c.request,
                                "GET",
                                "/v2/products/" + symbol,
                                private=False,
                            )
                            ticker_future = pool.submit(
                                c.request, "GET", "/v2/tickers/" + symbol, private=False
                            )
                        leverage_position = position_future.result()
                        leverage_orders = orders_future.result()
                        if fraction is not None:
                            current_product = product_future.result()
                            current_wallet = wallet_future.result()
                            current_ticker = ticker_future.result()

                    if time.monotonic() - leverage_started > 5:
                        raise Rejected("Leverage preflight exceeded freshness window")
                    if (
                        number(leverage_position.get("size", 0))
                        or leverage_orders
                        or position_version(pid, leverage_position)
                        != position_version(pid, pos)
                    ):
                        raise Rejected(
                            "Exposure changed; no leverage change was submitted"
                        )
                    if fraction is not None:
                        validate_sizing(
                            current_product,
                            build_sizing(current_product, current_wallet, account),
                            current_ticker,
                        )
                    self.store.evidence(
                        user,
                        rid,
                        {
                            "method": "POST",
                            "path": f"/v2/products/{pid}/orders/leverage",
                            "payload": {"leverage": int(leverage)},
                        },
                    )
                    mutated = True
                    c.request(
                        "POST",
                        f"/v2/products/{pid}/orders/leverage",
                        payload={"leverage": int(leverage)},
                    )
                    check = c.request("GET", f"/v2/products/{pid}/orders/leverage")
                    if number(check.get("leverage"), True) != leverage:
                        raise TimeoutError("Leverage confirmation unavailable")
            elif action == "close":
                if not size:
                    raise Rejected("No position remains to close")
                closing_side = "sell" if size > 0 else "buy"
                if data.get("size") is not None and number(data["size"], True) != abs(
                    size
                ):
                    raise Rejected("Position size changed; review before closing")
                if data.get("side") is not None and data["side"] != closing_side:
                    raise Rejected("Position direction changed; review before closing")
                payload.update(
                    side="sell" if size > 0 else "buy",
                    size=int(abs(size)),
                    order_type="market_order",
                    reduce_only=True,
                    client_order_id=UUID(rid).hex,
                )
            elif action == "protect":
                if not size:
                    raise Rejected("No position remains to protect")
                guards = protections("buy" if size > 0 else "sell")
                if len(guards) != 1:
                    raise Rejected("Submit exactly one stop or target per request")
                name, value = next(iter(guards.items()))
                kind = "stop_loss_order" if name == "stop" else "take_profit_order"
                side = "sell" if size > 0 else "buy"
                for existing in orders:
                    if (
                        existing.get("reduce_only") is True
                        or existing.get("bracket_order") is True
                    ):
                        existing_kind = existing.get("stop_order_type")
                        if existing_kind == kind and self.plans.allow_replacement(
                            user, account, symbol, data, existing, name
                        ):
                            continue
                        if (
                            existing_kind
                            not in ("stop_loss_order", "take_profit_order")
                            or existing_kind == kind
                        ):
                            raise Rejected(
                                "Existing protection must be edited individually"
                            )
                        if existing.get("side") != side or number(
                            existing.get("size"), True
                        ) > abs(size):
                            raise Rejected(
                                "Existing protection no longer matches the position"
                            )
                payload.update(
                    side=side,
                    size=int(abs(size)),
                    order_type="market_order" if name == "stop" else "limit_order",
                    stop_price=value,
                    stop_order_type=kind,
                    stop_trigger_method="mark_price",
                    reduce_only=True,
                    client_order_id=UUID(rid).hex,
                )
                if name == "target":
                    payload["limit_price"] = value
            else:
                order = next(
                    (o for o in orders if str(o["id"]) == str(data.get("order_id"))),
                    None,
                )
                if (
                    not order
                    or not data.get("version")
                    or digest(order) != data["version"]
                ):
                    raise Rejected("Order changed; refresh before editing")
                payload["id"] = order["id"]
                if action == "cancel":
                    method = "DELETE"
                else:
                    method = "PUT"
                    kind = order.get("stop_order_type")
                    market_stop = (
                        order.get("order_type") == "market_order"
                        and kind == "stop_loss_order"
                    )
                    if market_stop and (
                        order.get("reduce_only") is not True
                        or order.get("stop_trigger_method") != "mark_price"
                    ):
                        raise Rejected(
                            "Only reduce-only mark-triggered market stops can be edited"
                        )
                    if order.get("order_type") != "limit_order" and not market_stop:
                        raise Rejected(
                            "Only limit orders and reduce-only market stop-loss orders can be edited"
                        )
                    if not market_stop:
                        if order.get("time_in_force") != "gtc":
                            raise Rejected(
                                "Only existing GTC limit orders can be edited"
                            )
                        payload["post_only"] = True
                    payload["size"] = order["size"]
                    protective = kind in ("stop_loss_order", "take_profit_order")
                    if protective:
                        if not size or not (
                            order.get("reduce_only") is True
                            or order.get("bracket_order") is True
                        ):
                            raise Rejected("Protection no longer matches a position")
                        if order.get("side") != (
                            "sell" if size > 0 else "buy"
                        ) or number(order.get("size"), True) > abs(size):
                            raise Rejected(
                                "Protection no longer matches position direction or size"
                            )
                        if data.get("size") is not None:
                            edit_size = number(data["size"], True)
                            if (
                                edit_size != edit_size.to_integral_value()
                                or edit_size > abs(size)
                            ):
                                raise Rejected(
                                    "Protective quantity must be whole contracts within the current position"
                                )
                            payload["size"] = int(edit_size)
                        name = "stop" if kind == "stop_loss_order" else "target"
                        other = "target" if name == "stop" else "stop"
                        if data.get(other) is not None:
                            raise Rejected(
                                "Edit only the selected maker protection leg"
                            )
                        v = data.get(name, data.get("price"))
                        new = dict(data)
                        new[name] = v
                        old = data
                        data = new
                        try:
                            guards = protections("buy" if size > 0 else "sell")
                        finally:
                            data = old
                        payload.update(stop_price=guards[name], reduce_only=True)
                        if not market_stop:
                            payload["limit_price"] = guards[name]
                    else:
                        if order.get("order_type") != "limit_order":
                            raise Rejected("Only pending limit entries can be edited")
                        if (
                            data.get("stop") is not None
                            or data.get("target") is not None
                        ):
                            raise Rejected(
                                "Attached bracket exits cannot be maker-only; add separate maker SL/target after the entry fills"
                            )
                        for managed_entry in self.plans.list(user, symbol):
                            if (
                                managed_entry.get("entry_order_id") == str(order["id"])
                                and managed_entry.get("interval_seconds") == 60
                            ):
                                raise Rejected(
                                    "Cancel and recreate a scalp entry to recalculate its ₹20 risk limit; its resting price cannot be edited"
                                )
                        payload["limit_price"] = price(data.get("price"))
                        protections(order["side"], include_retained=True)
                        for field in (
                            "bracket_stop_loss_price",
                            "bracket_take_profit_price",
                        ):
                            value = order.get(field)
                            if value is not None and number(value) != 0:
                                raise Rejected(
                                    "Attached bracket exits cannot be maker-only; cancel and recreate as a maker-only entry, then add separate maker SL/target."
                                )
            adopted_payload = None
            if data.get("managed_plan_id") and (action != "cancel" or size):
                managed = self.plans.get(user, data["managed_plan_id"])
                if managed["account"] != account or managed["symbol"] != symbol:
                    raise Rejected("Managed action account/product binding changed")
                candidate = json.loads(managed["payload"])
                if candidate.get("action") == "adopt":
                    adopted_payload = candidate
            scalp_entry = (
                action == "entry"
                and ((data.get("auto_protection") or {}).get("interval_seconds") == 60 or data.get("automation_generation"))
            )
            fresh_started = time.monotonic()
            with ThreadPoolExecutor(
                max_workers=6,
                thread_name_prefix="delta-chart-preflight",
            ) as pool:
                price_future = pool.submit(
                    c.request, "GET", "/v2/tickers/" + symbol, private=False
                )
                position_future = pool.submit(
                    c.request, "GET", "/v2/positions", params={"product_id": pid}
                )
                if adopted_payload is not None:
                    adoption_fills_future = pool.submit(
                        self.recent_fills, c, account, pid, True
                    )
                if fraction is not None:
                    wallet_future = pool.submit(self.read_wallet, c)
                if fraction is not None or scalp_entry:
                    product_future = pool.submit(
                        c.request, "GET", "/v2/products/" + symbol, private=False
                    )
                check_liquidation = (
                    action == "protect" and data.get("stop") is not None
                ) or (
                    action == "edit"
                    and order.get("stop_order_type") == "stop_loss_order"
                )
                if check_liquidation:
                    liquidation_future = pool.submit(
                        c.request,
                        "GET",
                        "/v2/positions/margined",
                        params={"product_ids": pid},
                    )
                if action == "entry" and data.get("auto_protection") is not None:
                    entry_market_future = pool.submit(
                        self.validate_entry_market, c, data
                    )
                    managed_orders_future = pool.submit(
                        c.pages,
                        "/v2/orders",
                        {"product_ids": pid, "states": "open,pending"},
                    )
                fresh_ticker = price_future.result()
                fresh_position = position_future.result()
                if adopted_payload is not None:
                    adoption_fills = adoption_fills_future.result()
                    if (
                        self.plans.position_marker(
                            pid,
                            fresh_position,
                            adoption_fills,
                            isinstance(adoption_fills, list),
                        )
                        != adopted_payload["adopted_fill_marker"]
                    ):
                        raise Rejected(
                            "Adopted position fill ownership changed during preflight"
                        )
                if check_liquidation:
                    fresh_margined = liquidation_future.result()
                    liquidation_row = matching_margined(
                        fresh_margined, pid, fresh_position
                    )
                if action == "entry" and data.get("auto_protection") is not None:
                    entry_market_future.result()
                    if managed_orders_future.result():
                        raise Rejected(
                            "Managed product orders changed during preflight"
                        )
                if fraction is not None or scalp_entry:
                    current_product = product_future.result()
                if fraction is not None:
                    current_wallet = wallet_future.result()
            if time.monotonic() - fresh_started > 5:
                raise Rejected("Live preflight exceeded freshness window")
            if position_version(pid, fresh_position) != position_version(pid, pos):
                raise Rejected("Position changed during preflight; review again")
            if fraction is not None:
                validate_sizing(
                    current_product,
                    build_sizing(current_product, current_wallet, account),
                    fresh_ticker,
                )
            if scalp_entry:
                if (
                    str(current_product.get("id")) != str(pid)
                    or current_product.get("symbol") != symbol
                ):
                    raise Rejected("Scalp product changed during final risk preflight")
                stop_price = number(data["auto_protection"]["stop"], True)
                entry_price = number(data["price"], True)
                fresh_cv = number(current_product["contract_value"], True)
                loss = (
                    (
                        abs(entry_price - stop_price)
                        + (
                            entry_price
                            * number(current_product["maker_commission_rate"])
                            + stop_price
                            * number(current_product["taker_commission_rate"])
                        )
                        * (1 + SIZING_FEE_TAX_RATE)
                    )
                    * fresh_cv
                    * qty
                    * 85
                )
                if loss > 20:
                    raise Rejected(
                        "Fresh planned scalp loss including fees exceeds the ₹20 limit"
                    )
            mark = number(fresh_ticker.get("mark_price"), True)
            if action == "entry":
                self.assert_account_flat(c)
            if action == "entry" and data.get("auto_protection") is not None:
                self.plans.create(user, account, p, data, mark)
            if action in ("entry", "protect"):
                protections(
                    data.get("side")
                    if action == "entry"
                    else ("buy" if size > 0 else "sell")
                )
            elif action == "edit" and not order.get("stop_order_type"):
                protections(order["side"], include_retained=True)
            elif action == "edit" and order.get("stop_order_type") in (
                "stop_loss_order",
                "take_profit_order",
            ):
                check_data = dict(data)
                name = (
                    "stop"
                    if order["stop_order_type"] == "stop_loss_order"
                    else "target"
                )
                check_data[name] = payload["stop_price"]
                old = data
                data = check_data
                try:
                    protections("buy" if size > 0 else "sell")
                finally:
                    data = old
            if (
                method == "POST"
                and path == "/v2/orders"
                and payload.get("order_type") == "limit_order"
            ):
                payload.update(post_only=True, time_in_force="gtc")
            if action == "entry" and hasattr(self, "automation"):
                self.automation.authorize_entry(user, data)
            self.store.evidence(
                user, rid, {"method": method, "path": path, "payload": payload}
            )
            mutated = True
            ack = c.request(method, path, payload=payload)
            cancellation = self.unfilled_cancellation(ack, payload)
            if cancellation:
                raise DeltaError(cancellation)
            if isinstance(ack, dict) and ack.get("updated_at") is not None:
                self.store.evidence(
                    user,
                    rid,
                    {
                        "method": method,
                        "path": path,
                        "payload": payload,
                        "ack": {"id": ack.get("id"), "updated_at": ack["updated_at"]},
                    },
                )
            result = {
                "status": "confirmed",
                "message": "Delta acknowledged the action; execution may still be pending",
                "request_id": rid,
            }
            if isinstance(ack, dict) and ack.get("id") is not None:
                result["order_id"] = str(ack["id"])
            if action == "entry":
                try:
                    placed = (
                        float(fill_timestamp(ack.get("created_at")))
                        if isinstance(ack, dict)
                        else None
                    )
                    if placed is None or placed <= 0 or placed > time.time() + 5:
                        raise Rejected("Invalid placement timestamp")
                    result["placed_at"] = placed
                    result["placement_time_source"] = "broker"
                except (Rejected, TypeError, ValueError):
                    result["placed_at"] = time.time()
                    result["placement_time_source"] = "ack"
        except Rejected as exc:
            result = {
                "status": "pending" if mutated else "rejected",
                "message": str(exc),
                "request_id": rid,
            }
        except DeltaError as exc:
            result = {
                "status": "rejected",
                "message": str(exc),
                "request_id": rid,
            }
        except Exception:
            result = {
                "status": "pending" if mutated else "rejected",
                "message": "Exchange outcome requires reconciliation; do not resubmit"
                if mutated
                else "Fresh account preflight unavailable; no order submitted",
                "request_id": rid,
            }
        self.store.finish(user, rid, result)
        self.plans.parent_outcome(user, rid, result)
        if action == "close":
            self.plans.close_outcome(user, rid, result)
        elif action == "edit":
            self.plans.edit_outcome(
                user,
                account,
                symbol,
                data.get("order_id"),
                result,
                payload.get("stop_price"),
            )
        if result["status"] == "rejected":
            raise Rejected(result["message"])
        return result
