"""Read-only terminal plans. ML inference runs exclusively in the ML worker.

No account credentials or order services enter this module. Public market data
is checked again before presenting a plan. A recommendation never arms trading.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import time

from services.crypto_fees import ContractFees, net_target_plan
from utils.thread_safe_cache import LockedTTLCache, MISSING

ROOT = Path(__file__).resolve().parents[1]
_ticker = LockedTTLCache(maxsize=1, ttl=1)
_product = LockedTTLCache(maxsize=1, ttl=3600)


def _number(value):
    v = float(value)
    if not math.isfinite(v):
        raise ValueError("Invalid numeric data")
    return v


def build_plan(*, snapshot, ticker, product, quantity, leverage, now):
    result = {
        **snapshot,
        "symbol": "BTCUSDFUT",
        "quantity": quantity,
        "leverage": leverage,
        "action": "HOLD",
        "plans": [],
        "live_ready": False,
        "quote_time": None,
        "server_time": now,
        "execution": "research_only",
    }
    try:
        cfg = snapshot["config"]
        if not 0 <= now - _number(snapshot["updated_at"]) <= 15:
            raise ValueError("ML worker is stale. Waiting for a fresh snapshot.")
        if not 0 <= now - _number(snapshot["signal_time"]) <= 90:
            raise ValueError("Completed candle is stale. Waiting for the next signal.")
        if quantity != cfg["quantity"] or leverage != cfg["leverage"]:
            raise ValueError(
                f"Model tested at {cfg['quantity']} contract(s), {cfg['leverage']}×. Selected settings do not match."
            )
        if quantity < 1 or int(quantity) != quantity or not 1 <= leverage <= 200:
            raise ValueError("Invalid quantity or leverage")
        cv, tick, maker, taker = [
            _number(product[k])
            for k in (
                "contract_value",
                "tick_size",
                "maker_commission_rate",
                "taker_commission_rate",
            )
        ]
        if (
            product["contract_type"] != "perpetual_futures"
            or product["state"] != "live"
            or product["trading_status"] != "operational"
        ):
            raise ValueError("Contract is not operational")
        if any(
            not math.isclose(value, _number(cfg[key]), rel_tol=1e-9)
            for value, key in (
                (cv, "contract_value"),
                (tick, "tick"),
                (maker, "maker_rate"),
                (taker, "taker_rate"),
            )
        ):
            raise ValueError("Product specifications or fees changed. Retraining is required.")
        if min(cv, tick) <= 0:
            raise ValueError("Invalid product size")
        qt = _number(ticker["timestamp"]) / 1_000_000
        result["quote_time"] = qt
        if not 0 <= now - qt <= 10:
            raise ValueError("Public order-book quote is stale")
        bid = _number(ticker["quotes"]["best_bid"])
        ask = _number(ticker["quotes"]["best_ask"])
        if not 0 < bid < ask:
            raise ValueError("Invalid bid/ask spread")
        p = [_number(v) for v in snapshot["probabilities"]]
        ev = [_number(v) for v in snapshot["expected_net_usd"]]
        if len(p) != 2 or len(ev) != 2 or any(not 0 <= v <= 1 for v in p):
            raise ValueError("Invalid probability estimates")
        threshold = max(0.65, _number(snapshot["threshold"]))
        atr = _number(snapshot["atr"])
        if atr <= 0:
            raise ValueError("Invalid volatility estimate")
        if (
            max(abs(bid - snapshot["reference_price"]), abs(ask - snapshot["reference_price"]))
            > 0.5 * atr
        ):
            raise ValueError(
                "Price moved away from the model context. Waiting for a new completed candle."
            )
        contract = ContractFees("BTCUSD", maker_rate=maker, taker_rate=taker)
        for i, side in enumerate((1, -1)):
            name = "LONG" if side == 1 else "SHORT"
            entry = (math.floor(bid / tick) if side == 1 else math.ceil(ask / tick)) * tick
            buffer = max(2 * tick, 0.25 * atr)
            stop = (
                _number(snapshot["low5"]) - buffer
                if side == 1
                else _number(snapshot["high5"]) + buffer
            )
            stop = (math.floor(stop / tick) if side == 1 else math.ceil(stop / tick)) * tick
            base = {"side": name, "probability": p[i], "expected_net_usd": ev[i], "eligible": False}
            try:
                plan = net_target_plan(
                    side=side,
                    entry=entry,
                    stop=stop,
                    quantity=quantity,
                    contract_value=cv,
                    tick=tick,
                    contract=contract,
                    net_rr=3,
                    minimum_profit=1,
                    slippage=0.1,
                    gst_pct=18,
                )
                notional = entry * quantity * cv
                margin = notional / leverage
                fits = plan["net_risk"] <= 1 and margin <= 5 and notional <= 1000
                qualified = snapshot.get("research_qualified") is True
                eligible = fits and qualified and p[i] >= threshold and ev[i] > 0
                reason = (
                    "Within research criteria"
                    if eligible
                    else "Exceeds $1 risk / $5 margin / $1,000 notional limits"
                    if not fits
                    else "Model has not passed validation"
                    if not qualified
                    else "Probability or expected net return is below threshold"
                )
                result["plans"].append(
                    {
                        **base,
                        **plan,
                        "margin": margin,
                        "notional": notional,
                        "target_fees": plan["entry_fee"] + plan["target_fee"],
                        "stop_fees": plan["entry_fee"] + plan["stop_fee"],
                        "eligible": eligible,
                        "fits_risk": fits,
                        "reason": reason,
                    }
                )
            except ValueError:
                result["plans"].append(
                    {**base, "reason": "No valid stop/target fits the current entry"}
                )
        allowed = [v for v in result["plans"] if v["eligible"]]
        if allowed:
            result["action"] = max(allowed, key=lambda v: v["expected_net_usd"])["side"]
            result["reason"] = "Research plan passed probability, net-return and risk checks."
        elif snapshot.get("research_qualified"):
            result["reason"] = "Neither side meets the current risk and probability criteria."
        result["quantity"] = quantity
        result["leverage"] = leverage
        return result
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        result["reason"] = (
            str(exc) if isinstance(exc, ValueError) else "Model or market inputs are incomplete."
        )
        result["plans"] = []
        return result


def _public(path, cache):
    cached = cache.get(path, MISSING)
    if cached is not MISSING:
        return cached
    from utils.httpx_client import get_httpx_client

    generation = cache.generation
    response = get_httpx_client().get("https://api.india.delta.exchange/v2/" + path, timeout=3)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success") or not isinstance(payload.get("result"), dict):
        raise ValueError("Public market data unavailable")
    cache.fill(path, payload["result"], generation)
    return payload["result"]


def get_plan(symbol, quantity, leverage):
    hold = {
        "action": "HOLD",
        "reason": "Fee-aware ML worker is warming up.",
        "plans": [],
        "live_ready": False,
        "execution": "research_only",
        "server_time": time.time(),
    }
    if symbol != "BTCUSDFUT":
        return {**hold, "reason": "The fee-aware model is currently trained for BTCUSD only."}
    path = ROOT / "db/ml_signals/worker/live/BTCUSD/1m.json"
    try:
        snapshot = json.loads(path.read_text()).get("fee_algo")
        if not snapshot:
            return hold
        if not snapshot.get("config"):
            return {**hold, "reason": snapshot.get("reason", hold["reason"])}
        # Read-only public REST; never imports the model into Flask.
        product = _public("products/BTCUSD", _product)
        ticker = _public("tickers/BTCUSD", _ticker)
        return build_plan(
            snapshot=snapshot,
            ticker=ticker,
            product=product,
            quantity=quantity,
            leverage=leverage,
            now=time.time(),
        )
    except Exception:
        return {**hold, "reason": "Research snapshot or public market data unavailable."}


def validate_ticket(symbol, quantity, leverage, action, mode, stamp):
    """Bind a paper submission to the current server-generated plan.

    No live execution is enabled by prefilling the terminal. Never trust client
    probabilities, qualification flags or client-provided protection distances.
    """
    if mode != "analyze":
        raise ValueError("ML defaults cannot submit live orders; live qualification is required")
    return _matching_ticket(symbol, quantity, leverage, action, stamp, model_approval=True)


def validate_manual_defaults(symbol, quantity, leverage, action, mode, stamp):
    """Validate the user's manual order defaults independently of the ML opinion."""
    if mode not in ("live", "analyze"):
        raise ValueError("Unknown trading mode")
    return _matching_ticket(symbol, quantity, leverage, action, stamp, model_approval=False)


def _matching_ticket(symbol, quantity, leverage, action, stamp, *, model_approval):
    if symbol != "BTCUSDFUT" or action not in ("BUY", "SELL") or not isinstance(stamp, dict):
        raise ValueError("Invalid ML ticket")
    current = get_plan(symbol, quantity, leverage)
    now = time.time()
    for key, max_age in (("updated_at", 15), ("signal_time", 90), ("quote_time", 10)):
        if not 0 <= now - _number(current.get(key, 0)) <= max_age:
            raise ValueError("ML plan is stale; refresh the ticket")
    side = "LONG" if action == "BUY" else "SHORT"
    if model_approval and (current.get("action") != side or current.get("research_qualified") is not True):
        raise ValueError("ML HOLD: this entry has not passed validation")
    if (current.get("symbol"), current.get("quantity"), current.get("leverage")) != (symbol, quantity, leverage):
        raise ValueError("ML ticket settings changed; refresh the ticket")
    if not current.get("model_version") or stamp.get("model_version") != current["model_version"] or stamp.get("signal_time") != current["signal_time"]:
        raise ValueError("ML model or candle changed; refresh the ticket")
    plan = next((p for p in current.get("plans", []) if p.get("side") == side), None)
    if not plan:
        raise ValueError("ML plan does not meet entry criteria")
    if model_approval and plan.get('eligible') is not True:
        raise ValueError("ML plan does not meet entry criteria")
    if not model_approval:
        risk = _number(plan.get('net_risk', 0))
        if (plan.get('fits_risk') is not True or not 0 < risk <= 1
                or not 0 < _number(plan.get('margin', 0)) <= 5
                or not 0 < _number(plan.get('notional', 0)) <= 1000
                or _number(plan.get('net_target', 0)) + 1e-9 < max(1, 3 * risk)):
            raise ValueError('Manual defaults exceed the risk or net-reward limits')
    for key in ("entry", "stop", "target"):
        if not math.isclose(_number(stamp.get(key, 0)), _number(plan[key]), rel_tol=0, abs_tol=1e-9):
            raise ValueError("ML prices changed; refresh the ticket before submitting")
    return plan
