"""ML trade suggestions, and the one-click trade that follows one.

A suggestion is the worker's latest snapshot for a symbol and interval, made
concrete: the side, the entry, the stop and target prices, how many contracts
the risk budget buys, the margin, every fee, and the expected value. Nothing
here computes a model; the worker already did.

A trade is placed through the strategy module's signal mode, on one of two
strategies this module keeps: "ML Signals (Sandbox)" and "ML Signals (Live)".
That path already decides Sandbox or Live per run, claims an exit under a lock,
recovers after a restart, and hands stop and target decisions to
``services/risk/``. The entry carries its own size, stop, target and trail.
"""

from __future__ import annotations

import time
from typing import Any

from ml_signals import data
from ml_signals.decision import INTERVAL_MINUTES
from ml_signals.sizing import size_trade
from utils.logging import get_logger
from utils.thread_safe_cache import LockedTTLCache

logger = get_logger(__name__)

SANDBOX_NAME = "ML Signals (Sandbox)"
LIVE_NAME = "ML Signals (Live)"
MODES = ("sandbox", "live")
#: A snapshot older than this is too stale to trade from.
MAX_SNAPSHOT_AGE_SECONDS = 15

_balance_cache = LockedTTLCache(maxsize=8, ttl=5)


def _settings() -> dict[str, Any]:
    from database.ml_settings_db import get_settings

    return get_settings()


def openalgo_symbol(symbol: str) -> str:
    """BTCUSD to BTCUSDFUT, the perpetual's OpenAlgo symbol."""
    return f"{data.normalize_symbol(symbol)}FUT"


def balance_for(mode: str, user_id: str | None) -> tuple[float | None, str | None, str]:
    """The USD balance a trade in this mode is sized from, with where it came from.

    Live reads Delta's USD wallet, cached for a few seconds so a page polling
    suggestions does not spend Delta's private rate limit. Sandbox uses the
    USD amount in ML settings, because the sandbox's own funds are kept in
    rupees for Indian markets and sizing a dollar contract from them would be
    off by the exchange rate.
    """
    settings = _settings()
    if mode == "sandbox":
        return float(settings.get("sandbox_balance_usd", 1000.0)), None, "sandbox setting"
    if not user_id:
        return None, "Log in again to read your Delta balance.", "delta"
    from utils.thread_safe_cache import MISSING

    cached = _balance_cache.get(user_id, MISSING)
    if cached is not MISSING:
        return cached
    generation = _balance_cache.generation
    try:
        from broker.deltaexchange.api.funds import get_usd_available
        from database.auth_db import get_auth_token

        token = get_auth_token(user_id)
        if not token:
            result = (
                None,
                "Delta Exchange is not logged in, so the USD balance cannot be read.",
                "delta",
            )
        else:
            value, error = get_usd_available(token)
            result = (value, error, "delta")
    except Exception:
        logger.exception("Could not read the Delta USD balance")
        result = (
            None,
            "The Delta balance could not be read. Details are in the error log.",
            "delta",
        )
    _balance_cache.fill(user_id, result, generation)
    return result


def _signal_of(snapshot: dict[str, Any], use: str) -> dict[str, Any] | None:
    return snapshot.get("closed" if use == "closed" else "forming") or snapshot.get("closed")


def suggestion(
    symbol: str,
    interval: str,
    *,
    mode: str = "sandbox",
    user_id: str | None = None,
    use: str = "closed",
    now: float | None = None,
) -> dict[str, Any]:
    """One symbol and interval's suggestion, sized for the given mode.

    ``use`` picks the closed bar (the default: its probabilities no longer
    move) or the forming one.
    """
    from database.token_db_enhanced import get_symbol_info
    from ml_signals.worker_store import read_live_snapshot
    from services.crypto_fee_service import contract_fees, fee_profile, voucher_earned_this_month

    symbol = data.normalize_symbol(symbol)
    now = time.time() if now is None else now
    settings = _settings()
    snapshot = read_live_snapshot(symbol, interval) or {}
    signal = _signal_of(snapshot, use) or {}
    action = signal.get("action") or "WAIT"
    price = float(snapshot.get("price") or 0.0)
    age = now - float(snapshot.get("server_time") or 0.0)
    out: dict[str, Any] = {
        "symbol": symbol,
        "openalgo_symbol": openalgo_symbol(symbol),
        "interval": interval,
        "mode": mode,
        "action": action,
        "price": price,
        "snapshot_age_seconds": round(age, 1),
        "model_version": snapshot.get("model_version"),
        "model_promoted": bool(snapshot.get("model_promoted")),
        "promotion_reason": snapshot.get("promotion_reason"),
        "p_long": signal.get("p_long"),
        "p_short": signal.get("p_short"),
        "p_wait": signal.get("p_wait"),
        "ev_pct": signal.get("ev_pct"),
        "ev_long_pct": signal.get("ev_long_pct"),
        "ev_short_pct": signal.get("ev_short_pct"),
        "min_edge_pct": signal.get("min_edge_pct"),
        "stop_pct": signal.get("stop_pct"),
        "target_pct": signal.get("target_pct"),
        "hold_minutes": signal.get("hold_minutes") or int(settings.get("max_hold_minutes", 28)),
        "signal_time": signal.get("time"),
        "expires_at": (
            int(signal["time"]) + 2 * INTERVAL_MINUTES[interval] * 60
            if use == "closed" and signal.get("time") is not None
            else signal.get("closes_at")
        ),
        "message": snapshot.get("message"),
        "sizing": None,
        "tradable": False,
    }
    if not snapshot:
        out["message"] = "The ML worker has not published a signal for this symbol yet."
        return out
    if age > MAX_SNAPSHOT_AGE_SECONDS:
        out["message"] = (
            f"The signal is {int(age)} seconds old, so the live feed has stalled. "
            "It resumes on its own; check the data feeds below if it does not."
        )
        return out
    side = 1 if action == "LONG" else -1 if action == "SHORT" else 0
    if not side:
        return out

    entry = price
    out["entry_price"] = entry
    out["stop_price"] = entry * (1 - side * float(out["stop_pct"]) / 100)
    out["target_price"] = entry * (1 + side * float(out["target_pct"]) / 100)

    contract, _fallback_value = contract_fees(out["openalgo_symbol"], "CRYPTO")
    info = get_symbol_info(out["openalgo_symbol"], "CRYPTO")
    contract_value = float(getattr(info, "contract_value", 0) or 0) if info is not None else 0.0
    if contract_value <= 0:
        # Never size from a guessed contract value: a contract worth more per
        # unit than the guess would be oversized by that factor.
        out["message"] = (
            f"{symbol}'s contract size is not loaded yet. Download the master contract, or wait a "
            "moment after a restart."
        )
        return out
    balance, balance_error, source = balance_for(mode, user_id)
    out["balance"] = balance
    out["balance_source"] = source
    if balance is None:
        out["message"] = balance_error
        return out
    sized = size_trade(
        side=side,
        entry=entry,
        stop_pct=float(out["stop_pct"]),
        target_pct=float(out["target_pct"]),
        balance=float(balance),
        risk_pct=float(settings.get("risk_pct", 1.0)),
        max_leverage=float(settings.get("max_leverage", 10)),
        contract_value=float(contract_value),
        contract=contract,
        profile=fee_profile(settings),
        hold_minutes=float(out["hold_minutes"]),
        voucher_earned_this_month=voucher_earned_this_month(settings),
    )
    out["contract_value"] = contract_value
    out["sizing"] = sized.to_dict()
    out["tradable"] = sized.ok
    if not sized.ok:
        out["message"] = sized.reason
    return out


def live_gate(symbol: str, interval: str, user_id: str | None) -> str | None:
    """Why Live trading is not allowed right now, or None when it is."""
    from ml_signals.worker_store import read_live_snapshot

    snapshot = read_live_snapshot(symbol, interval) or {}
    if not snapshot.get("model_promoted"):
        reason = snapshot.get("promotion_reason") or "The model has not been promoted."
        return f"Live is locked for {symbol} {interval}: {reason}"
    _balance, error, _ = balance_for("live", user_id)
    if error:
        return error
    return None


# ---------------------------------------------------------------------------
# The two strategies trades are placed through
# ---------------------------------------------------------------------------


def _legs_for(symbols: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": index + 1,
            "symbol": openalgo_symbol(symbol),
            "exchange": "CRYPTO",
            "side": "both",
            "segment": "futures",
            "qty_mode": "units",
            "qty": 1,
            "trail": {"x": 0, "y": 0},
        }
        for index, symbol in enumerate(symbols)
    ]


def _config(name: str, symbols: list[str]) -> dict[str, Any]:
    from blueprints.strategy_module import validate_strategy_config

    config, message = validate_strategy_config(
        {
            "name": name,
            "strategy_kind": "signal",
            "direction": "both",
            "underlying": "MULTI",
            "underlying_exchange": "NSE",
            "universe_tab": "crypto",
            # Positional: a crypto trade is not squared off at an Indian
            # market's close, and its run rolls only when it is flat.
            "strategy_type": "positional",
            "product": "NRML",
            "legs": _legs_for(symbols),
        }
    )
    if message:
        raise ValueError(message)
    return config


def ensure_strategy(user_id: str, mode: str) -> tuple[Any | None, str | None]:
    """The strategy ML trades in this mode go through, created or brought up to date.

    Its legs follow the shortlist. A leg is only rewritten while the strategy
    holds nothing, so a symbol removed from the shortlist keeps its leg until
    any trade on it is closed.
    """
    from database import strategy_module_db as store
    from database.ml_settings_db import get_settings, set_internal

    settings = get_settings()
    key = "live_strategy_id" if mode == "live" else "sandbox_strategy_id"
    name = LIVE_NAME if mode == "live" else SANDBOX_NAME
    symbols = [data.normalize_symbol(s) for s in settings.get("symbols") or []]
    strategy_id = settings.get(key)
    row = store.get_strategy(int(strategy_id), user_id) if strategy_id else None
    if row is None:
        existing = [s for s in store.list_strategies(user_id) if s.get("name") == name]
        if existing:
            row = store.get_strategy(int(existing[0]["id"]), user_id)
    if row is None:
        created, error = store.create_strategy(user_id, _config(name, symbols))
        if not created:
            return None, error or "The ML strategy could not be created."
        row = store.get_strategy(int(created["id"]), user_id)
        store.record_event(row.id, user_id, "strategy_created", f"Strategy '{name}' created")
    if row.id != strategy_id:
        set_internal(**{key: int(row.id)})

    wanted = {openalgo_symbol(s) for s in symbols}
    have = {str(leg.get("symbol")) for leg in row.legs or []}
    if not wanted <= have:
        legs = list(row.legs or [])
        next_id = max([int(leg.get("id") or 0) for leg in legs] or [0]) + 1
        for symbol in symbols:
            if openalgo_symbol(symbol) in have:
                continue
            leg = _legs_for([symbol])[0]
            leg["id"] = next_id
            next_id += 1
            legs.append(leg)
        row.legs = legs
        store.db_session.commit()
    if mode == "live" and not row.live_enabled:
        if row.status == "running":
            return None, "Close the open ML Sandbox trades before switching this strategy to Live."
        ok, error = store.set_live_enabled(row.id, user_id, True)
        if not ok:
            return None, error
        row = store.get_strategy(row.id, user_id)
    return row, None


def leg_for(strategy: Any, symbol: str) -> dict[str, Any] | None:
    wanted = openalgo_symbol(symbol)
    for leg in strategy.legs or []:
        if str(leg.get("symbol")) == wanted:
            return leg
    return None


def webhook_token(user_id: str, strategy_id: int) -> str | None:
    """The token the ML worker uses to send exits through this strategy's webhook.

    The strategy module keeps only a hash of each token, so the first call
    rotates the token and keeps the new one encrypted with the app's own key.
    These strategies are managed here, not by an outside alert service, so no
    sender loses a token it was given.
    """
    from database import strategy_module_db as store
    from database.auth_db import decrypt_token, encrypt_token
    from database.ml_settings_db import get_settings, set_internal

    key = f"webhook_{strategy_id}"
    stored = (get_settings().get("webhook_tokens") or {}).get(key)
    if stored:
        token = decrypt_token(stored)
        row = store.get_strategy_by_webhook_token(token) if token else None
        if row is not None and int(row.id) == int(strategy_id):
            return token
    token, error = store.rotate_webhook_token(int(strategy_id), user_id)
    if not token:
        logger.error("Could not issue a webhook token for ML strategy %s: %s", strategy_id, error)
        return None
    tokens = dict(get_settings().get("webhook_tokens") or {})
    tokens[key] = encrypt_token(token)
    set_internal(webhook_tokens=tokens)
    return token


def _entry_overrides(suggestion_value: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Size, stop, target and break-even trail for this one trade, in percent of entry.

    The break-even trail arms once the trade is ahead by its round-trip fees
    plus the operator's buffer, and then trails by that same distance, so the
    stop has moved to roughly break-even after fees by the time it can trail.
    ``services/risk/`` decides the stop either way.
    """
    sizing = suggestion_value["sizing"]
    notional = float(sizing["notional"]) or 1.0
    round_trip_pct = (
        (float(sizing["entry_fee"]) + float(sizing["exit_fee_after_window"])) / notional * 100
    )
    trail_pct = round_trip_pct + float(settings.get("breakeven_buffer_pct", 0.05))
    stop_pct = float(suggestion_value["stop_pct"])
    trail = (
        {"x": round(trail_pct, 4), "y": 0}
        if trail_pct < float(suggestion_value["target_pct"])
        else {"x": 0, "y": 0}
    )
    return {
        "quantity": int(sizing["contracts"]),
        "sl_pts": round(stop_pct, 4),
        "target_pts": round(float(suggestion_value["target_pct"]), 4),
        "risk_unit": "percent",
        "trail": trail,
    }


def _bracket(suggestion_value: dict[str, Any]) -> dict[str, Any]:
    """A stop held on Delta itself, so the position is protected if OpenAlgo stops.

    It sits a little beyond the managed stop, so in normal running the managed
    stop fires first and Delta's is only the fallback.
    """
    side = 1 if suggestion_value["action"] == "LONG" else -1
    entry = float(suggestion_value["entry_price"])
    stop_pct = float(suggestion_value["stop_pct"]) * 1.5
    return {
        "bracket_stop_loss_price": round(entry * (1 - side * stop_pct / 100), 2),
        "bracket_stop_trigger_method": "mark_price",
    }


def place_trade(
    *,
    user_id: str,
    symbol: str,
    interval: str,
    mode: str,
    expected_action: str,
    expected_contracts: int | None = None,
) -> dict[str, Any]:
    """Open the suggested trade now, at market. Returns what happened, in words.

    The suggestion is computed again here, not trusted from the browser: the
    side, the size and the levels are whatever the latest signal says. If the
    side changed since the operator looked, nothing is sent.
    """
    from services.strategy_module import signals

    if mode not in MODES:
        return {"ok": False, "message": "Choose Sandbox or Live."}
    symbol = data.normalize_symbol(symbol)
    settings = _settings()
    if symbol not in [data.normalize_symbol(s) for s in settings.get("symbols") or []]:
        return {"ok": False, "message": f"{symbol} is not on the ML shortlist."}
    current = suggestion(symbol, interval, mode=mode, user_id=user_id)
    if current["action"] != expected_action:
        return {
            "ok": False,
            "message": (
                f"The signal changed to {current['action']} since you looked, so nothing was "
                "sent. Check the new suggestion and try again."
            ),
            "suggestion": current,
        }
    if not current["tradable"]:
        return {
            "ok": False,
            "message": current.get("message") or "This suggestion cannot be traded.",
            "suggestion": current,
        }
    contracts = int(current["sizing"]["contracts"])
    if expected_contracts is not None and contracts > int(expected_contracts):
        return {
            "ok": False,
            "message": (
                f"The size grew from {expected_contracts} to {contracts} contracts since you "
                "looked, so nothing was sent. Check the new figures and try again."
            ),
            "suggestion": current,
        }
    if mode == "live":
        refusal = live_gate(symbol, interval, user_id)
        if refusal:
            return {"ok": False, "message": refusal, "suggestion": current}

    strategy, error = ensure_strategy(user_id, mode)
    if error:
        return {"ok": False, "message": error, "suggestion": current}
    leg = leg_for(strategy, symbol)
    if leg is None:
        return {
            "ok": False,
            "message": f"The ML strategy has no {symbol} leg.",
            "suggestion": current,
        }
    if (mode == "live") != bool(strategy.live_enabled):
        return {
            "ok": False,
            "message": "The ML strategy is in the other mode. Close its open trades first.",
            "suggestion": current,
        }

    action = "long_entry" if current["action"] == "LONG" else "short_entry"
    held = _held(strategy, leg.get("id"))
    if held:
        return {
            "ok": False,
            "message": (
                f"A {held} {symbol} trade is already open in {mode.title()}. Close it before "
                "opening another; a new entry would otherwise add to it or flip it."
            ),
            "suggestion": current,
        }
    # Plain values, read now: a Sandbox fill replays synchronously and removes
    # the scoped session, which leaves the strategy row detached afterwards.
    strategy_id = int(strategy.id)
    leg_id = leg.get("id")
    result = signals.handle_signal(
        strategy,
        action,
        leg_id=leg_id,
        overrides=_entry_overrides(current, settings),
        bracket=_bracket(current) if mode == "live" else None,
    )
    if not result.ok:
        return {
            "ok": False,
            "message": result.error or _note_message(result.note),
            "suggestion": current,
        }
    if result.note is not None:
        return {"ok": False, "message": _note_message(result.note), "suggestion": current}
    _record_trade_meta(strategy_id, result.run_id, leg_id, current)
    return {
        "ok": True,
        "message": (
            f"{current['action']} {contracts} {symbol} contracts sent to "
            f"{'Delta Exchange' if mode == 'live' else 'the Sandbox'}."
        ),
        "strategy_id": strategy_id,
        "run_id": result.run_id,
        "leg_id": leg_id,
        "suggestion": current,
    }


_NOTES = {
    "already_long": "A LONG trade on this symbol is already open. Close it first.",
    "already_short": "A SHORT trade on this symbol is already open. Close it first.",
    "flip_pending": "The previous trade on this symbol is still closing. Try again in a moment.",
    "run_stopping": "The previous ML session is closing its positions. Try again in a moment.",
}


def _note_message(note: str | None) -> str:
    return _NOTES.get(note or "", "The trade was not sent.")


def _held(strategy: Any, leg_id: Any) -> str | None:
    """LONG or SHORT if this leg holds or is opening a position, else None."""
    from services.strategy_module import state

    run_id = getattr(strategy, "current_run_id", None)
    if not run_id:
        return None
    snapshot = state.get_run_state(int(run_id))
    if snapshot is None:
        return None
    leg = (snapshot.get("legs") or {}).get(str(leg_id))
    if leg and (leg.get("status") == "open" or leg.get("superseded")):
        return "LONG" if leg.get("position") == "B" else "SHORT"
    if str(leg_id) in (snapshot.get("signal_entry_claims") or {}):
        return "pending"
    return None


def _record_trade_meta(
    strategy_id: int, run_id: int | None, leg_id: Any, value: dict[str, Any]
) -> None:
    """What the worker's smart exit needs about an open trade, kept beside it."""
    from ml_signals.worker_store import update_trades

    record = {
        "strategy_id": strategy_id,
        "run_id": run_id,
        "leg_id": leg_id,
        "symbol": value["symbol"],
        "interval": value["interval"],
        "mode": value["mode"],
        "side": value["action"],
        "opened_at": time.time(),
        "entry_suggestion": {
            key: value.get(key)
            for key in ("entry_price", "stop_price", "target_price", "ev_pct", "model_version")
        },
        "sizing": value.get("sizing"),
    }

    def add(trades: dict[str, Any]) -> dict[str, Any]:
        trades[f"{run_id}:{leg_id}"] = record
        return trades

    try:
        update_trades(add)
    except Exception:
        # The trade is open and managed by its stop and target either way;
        # only the early exit would miss it.
        logger.exception("Could not record ML trade %s:%s for the smart exit", run_id, leg_id)


# ---------------------------------------------------------------------------
# Open trades, as the page and the smart exit see them
# ---------------------------------------------------------------------------


def _leg_view(
    strategy: Any, run_id: int, leg: dict[str, Any], meta: dict[str, Any] | None, now: float
) -> dict[str, Any]:
    """One open leg with its net P&L after fees and the voucher it would earn."""
    from services.crypto_fee_service import contract_fees, fee_profile, voucher_earned_this_month
    from services.crypto_fees import open_position_fees

    symbol = str(leg.get("symbol") or "")
    contract, contract_value = contract_fees(symbol, "CRYPTO")
    profile = fee_profile()
    qty = float(leg.get("qty") or 0)
    entry = float(leg.get("entry_avg") or 0)
    price = float(leg.get("ltp") or entry or 0)
    side = 1 if leg.get("position") == "B" else -1
    gross = (price - entry) * qty * contract_value * side if entry and price else 0.0
    opened_at = float((meta or {}).get("opened_at") or now)
    held = max(0.0, (now - opened_at) / 60)
    fees = open_position_fees(
        contract,
        profile,
        entry_notional=qty * contract_value * entry,
        exit_notional=qty * contract_value * price,
        held_minutes=held,
        voucher_earned_this_month=voucher_earned_this_month(),
    )
    net = gross - fees.entry_fee - fees.exit_fee_now
    notional = qty * contract_value * entry
    return {
        "key": f"{run_id}:{leg.get('leg_id')}",
        "strategy_id": int(strategy.id),
        "run_id": run_id,
        "leg_id": leg.get("leg_id"),
        "mode": "live" if strategy.live_enabled else "sandbox",
        "symbol": symbol.removesuffix("FUT"),
        "side": "LONG" if side > 0 else "SHORT",
        "status": leg.get("status"),
        "entry_status": leg.get("entry_status"),
        "contracts": qty,
        "contract_value": contract_value,
        "entry_price": entry or None,
        "last_price": price or None,
        "stop_price": leg.get("effective_sl"),
        "target_price": leg.get("effective_target"),
        "trail_active": bool(leg.get("trail_active")),
        "gross_pnl": gross,
        "fees_paid": fees.entry_fee,
        "exit_fee_now": fees.exit_fee_now,
        "exit_fee_after_window": fees.exit_fee_after_window,
        "window_remaining_minutes": fees.window_remaining_minutes,
        "voucher_now": fees.voucher_now,
        "net_pnl": net,
        "pnl_pct": (gross / notional * 100) if notional else 0.0,
        "held_minutes": held,
        "interval": (meta or {}).get("interval"),
        "opened_at": opened_at,
        "exit_kind": leg.get("exit_kind"),
        "smart_exit": (meta or {}).get("smart_exit"),
    }


def open_trades(user_id: str, now: float | None = None) -> list[dict[str, Any]]:
    """Every open or opening ML leg in both modes, newest first."""
    from database import strategy_module_db as store
    from database.ml_settings_db import get_settings
    from ml_signals.worker_store import read_trades
    from services.strategy_module import state

    now = time.time() if now is None else now
    settings = get_settings()
    metas = read_trades()
    out = []
    for key in ("sandbox_strategy_id", "live_strategy_id"):
        strategy_id = settings.get(key)
        if not strategy_id:
            continue
        strategy = store.get_strategy(int(strategy_id), user_id)
        if strategy is None or not strategy.current_run_id:
            continue
        run_id = int(strategy.current_run_id)
        snapshot = state.get_run_state(run_id) or {}
        for leg in (snapshot.get("legs") or {}).values():
            if leg.get("status") != "open":
                continue
            meta = metas.get(f"{run_id}:{leg.get('leg_id')}")
            out.append(_leg_view(strategy, run_id, leg, meta, now))
    return sorted(out, key=lambda t: t["opened_at"], reverse=True)


def recent_closed(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """The last ML trades that closed, with why each was closed."""
    from database import strategy_module_db as store
    from database.ml_settings_db import get_settings

    settings = get_settings()
    rows = []
    for key, mode in (("sandbox_strategy_id", "sandbox"), ("live_strategy_id", "live")):
        strategy_id = settings.get(key)
        if not strategy_id:
            continue
        orders = store.list_orders_for_strategy(int(strategy_id))
        entries: dict[tuple, dict] = {}
        for order in orders:
            ref = (order.get("run_id"), order.get("leg_id"), order.get("position_ref"))
            if order.get("kind") == "entry":
                entries[ref] = order
                continue
            if order.get("status") != "complete":
                continue
            entry = entries.get(ref)
            if not entry or not entry.get("avg_fill_price") or not order.get("avg_fill_price"):
                continue
            side = 1 if entry.get("action") == "BUY" else -1
            rows.append(
                {
                    "mode": mode,
                    "symbol": str(order.get("symbol") or "").removesuffix("FUT"),
                    "side": "LONG" if side > 0 else "SHORT",
                    "contracts": order.get("filled_qty") or order.get("qty"),
                    "entry_price": entry.get("avg_fill_price"),
                    "exit_price": order.get("avg_fill_price"),
                    "reason": _CLOSE_REASONS.get(str(order.get("kind")), order.get("kind")),
                    "opened_at": entry.get("placed_at"),
                    "closed_at": order.get("filled_at") or order.get("placed_at"),
                    "move_pct": (
                        (float(order["avg_fill_price"]) / float(entry["avg_fill_price"]) - 1)
                        * 100
                        * side
                    ),
                }
            )
    rows.sort(key=lambda r: str(r.get("closed_at") or ""), reverse=True)
    return rows[:limit]


_CLOSE_REASONS = {
    "exit_sl": "Stop loss (or trailing stop)",
    "exit_target": "Target",
    "exit_signal": "Smart exit",
    "exit_leg_manual": "Closed by you",
    "exit_close_all": "Closed by you",
    "exit_eod": "Session end",
    "exit_daily_loss_limit": "Daily loss limit",
    "exit_recovery": "Recovered after a restart",
    "exit_overall_sl": "Combined stop",
    "exit_overall_target": "Combined target",
    "exit_lock_profit": "Profit lock",
}


def close_trade(user_id: str, run_id: int, leg_id: Any) -> dict[str, Any]:
    """Close one open ML leg at market, by hand."""
    from database import strategy_module_db as store
    from database.ml_settings_db import get_settings
    from services.strategy_module import engine

    run = store.get_run(int(run_id))
    settings = get_settings()
    ml_ids = {settings.get("sandbox_strategy_id"), settings.get("live_strategy_id")}
    if run is None or run.strategy_id not in ml_ids:
        return {"ok": False, "message": "That is not an open ML trade."}
    result = engine.close_leg(int(run_id), leg_id, user_id)
    if result.get("ok"):
        return {"ok": True, "message": "Closing the trade at market."}
    return {"ok": False, "message": result.get("error") or "The trade could not be closed."}


# ---------------------------------------------------------------------------
# Reconciliation: a Live leg that Delta has already closed
# ---------------------------------------------------------------------------


def delta_open_sizes(user_id: str) -> dict[str, float] | None:
    """Signed open contracts per Delta symbol (BTCUSD, ...), or None when Delta did not answer."""
    from broker.deltaexchange.api.order_api import get_positions
    from database.auth_db import get_auth_token

    token = get_auth_token(user_id)
    if not token:
        return None
    try:
        positions = get_positions(token, strict=True)
    except Exception as exc:
        logger.warning("Could not read Delta positions for reconciliation: %s", exc)
        return None
    sizes: dict[str, float] = {}
    for position in positions or []:
        symbol = str(position.get("product_symbol") or "")
        try:
            sizes[symbol] = sizes.get(symbol, 0.0) + float(position.get("size") or 0)
        except (TypeError, ValueError):
            continue
    return sizes


def reconcile_live(user_id: str) -> list[dict[str, Any]]:
    """Close the record of any Live ML leg that Delta no longer holds.

    This is what happens when Delta's own protective stop fires while
    OpenAlgo is asleep or busy. Nothing is sent to the broker: the exit is
    claimed under the run lock, so no other rule can also act on it, and the
    leg is settled at the last known price. Only a leg whose entry filled and
    that has no exit in flight is considered, so a fill still on its way is
    never mistaken for a closed position.
    """
    from database.ml_settings_db import get_settings
    from services.strategy_module import engine, state

    settings = get_settings()
    strategy_id = settings.get("live_strategy_id")
    if not strategy_id:
        return []
    from database import strategy_module_db as store

    strategy = store.get_strategy(int(strategy_id), user_id)
    if strategy is None or not strategy.current_run_id or not strategy.live_enabled:
        return []
    run_id = int(strategy.current_run_id)
    strategy_row_id = int(strategy.id)
    snapshot = state.get_run_state(run_id) or {}
    candidates = [
        leg
        for leg in (snapshot.get("legs") or {}).values()
        if leg.get("status") == "open"
        and leg.get("entry_status") == "complete"
        and not leg.get("exit_kind")
        and not leg.get("superseded")
    ]
    if not candidates:
        return []
    sizes = delta_open_sizes(user_id)
    if sizes is None:
        return []
    settled = []
    for leg in candidates:
        br_symbol = str(leg.get("symbol") or "").removesuffix("FUT")
        held = sizes.get(br_symbol, 0.0)
        side = 1 if leg.get("position") == "B" else -1
        if held * side > 0:
            continue
        claimed = state.claim_leg_exit(run_id, leg.get("leg_id"), "exit_broker_flat")
        if claimed is None:
            continue
        price = claimed.get("ltp") or claimed.get("entry_avg")
        engine.apply_fill(
            run_id,
            claimed.get("leg_id"),
            float(price) if price else None,
            is_entry=False,
            filled_qty=int(claimed.get("qty") or 0),
            position_ref=claimed.get("position_ref"),
        )
        store.record_event(
            strategy_row_id,
            user_id,
            "ml_broker_flat",
            (
                f"Delta no longer holds {br_symbol}, so leg {claimed.get('leg_id')} was marked "
                "closed. Its own stop on Delta most likely filled; the exact price is in "
                "Delta's trade history."
            ),
            run_id=run_id,
            leg_id=claimed.get("leg_id"),
            severity="warn",
        )
        settled.append({"run_id": run_id, "leg_id": claimed.get("leg_id"), "symbol": br_symbol})
    return settled
