"""Shadow profit protection outcomes for one admitted sandbox entry.

This module has no trading path. A caller supplies the same observed entry and
market facts to all three profiles and persists the returned JSON state. The
shared aggregate risk core alone decides stops, targets and profit floors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from services.risk.aggregate import evaluate_aggregate
from services.risk.models import AggregateRisk
from services.strategy_module import risk_adapter

_LEG_FIELDS = frozenset(
    {
        "leg_id",
        "position",
        "entry_avg",
        "qty",
        "sl_pts",
        "target_pts",
        "risk_unit",
        "trail_x",
        "trail_y",
        "effective_sl",
        "effective_target",
        "highest_price",
        "lowest_price",
    }
)


def _positive(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive finite number") from exc
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return number


def _moment(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _profile() -> dict[str, Any]:
    return {
        "status": "observing",
        "remaining_qty": 0,
        "filled_qty": 0,
        "simulated_realized_pnl": None,
        "trigger_mark_pnl": None,
        "trigger_at": None,
        "closed_at": None,
        "reason": None,
        "peak_profit": 0.0,
        "trough_pnl": 0.0,
        "max_drawdown": 0.0,
        "last_mark_pnl": 0.0,
        "lock_armed": False,
        "lock_floor": None,
        "missed_fill": False,
        "exit_fill_quality": None,
        "trigger_quote": None,
        "fill_events": [],
    }


def start_comparison(
    *,
    run_id: int,
    position_ref: str,
    broker_connection_id: str,
    symbol: str,
    exchange: str,
    run_open_positions: int,
    mode: str,
    side: str,
    entry_price: float,
    quantity: int,
    planned_stop_risk: float,
    overall_stop_remaining: float,
    daily_allowance_remaining: float,
    baseline_risk: dict[str, Any],
    baseline_leg_state: dict[str, Any],
    entry_at: datetime,
    cutoff_at: datetime,
    entry_timestamp_source: str = "local_confirmation",
) -> dict[str, Any]:
    """Freeze an admitted entry's risk budget; no profile can enlarge it."""
    if mode != "sandbox":
        raise ValueError("profit comparison requires a sandbox entry")
    if not run_id or not position_ref:
        raise ValueError("run and position identity are required")
    if not all(
        isinstance(item, str) and item.strip()
        for item in (
            broker_connection_id,
            symbol,
            exchange,
        )
    ):
        raise ValueError("broker connection and instrument identity are required")
    if run_open_positions != 1:
        raise ValueError("comparison currently requires a single open position in the run")
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    entry = _positive(entry_price, "entry price")
    budget = min(
        _positive(planned_stop_risk, "planned risk"),
        _positive(overall_stop_remaining, "overall stop risk"),
        _positive(daily_allowance_remaining, "daily risk allowance"),
    )
    start = _moment(entry_at, "entry time")
    cutoff = _moment(cutoff_at, "cutoff")
    if cutoff <= start:
        raise ValueError("cutoff must follow entry")
    if entry_timestamp_source not in {"broker_fill", "local_confirmation"}:
        raise ValueError("entry timestamp source is unsupported")
    # Validate the caller's current baseline rule before it is frozen.
    if not isinstance(baseline_risk, dict):
        raise ValueError("baseline risk must be a mapping")
    baseline = AggregateRisk.from_state(baseline_risk)
    if not isinstance(baseline_leg_state, dict):
        raise ValueError("baseline leg state is required")
    leg_state = {key: baseline_leg_state[key] for key in _LEG_FIELDS if key in baseline_leg_state}
    leg_risk = risk_adapter.leg_to_position_risk(leg_state)
    if (
        leg_risk.entry_price != entry
        or int(leg_risk.quantity) != quantity
        or (leg_risk.is_long != (side == "BUY"))
    ):
        raise ValueError("baseline leg must match the admitted entry")
    if (
        baseline.combined_stoploss is None
        and baseline.combined_target is None
        and leg_risk.effective_stop is None
        and leg_risk.target_price is None
    ):
        raise ValueError("baseline must contain a stop or target")
    profiles = {name: _profile() for name in ("baseline", "early", "room")}
    for profile in profiles.values():
        profile["remaining_qty"] = quantity
    return {
        "schema_version": 1,
        "run_id": run_id,
        "position_ref": position_ref,
        "mode": mode,
        "broker_connection_id": broker_connection_id.strip(),
        "symbol": symbol.strip().upper(),
        "exchange": exchange.strip().upper(),
        "side": side,
        "entry_price": entry,
        "quantity": quantity,
        "risk_budget": budget,
        "baseline_risk": baseline_risk.copy(),
        "baseline_leg_state": leg_state,
        "baseline_scope": "single_position_per_leg_and_aggregate",
        "entry_at": start.isoformat(),
        "entry_timestamp_source": entry_timestamp_source,
        "cutoff_at": cutoff.isoformat(),
        "last_observed_at": None,
        "profiles": profiles,
        "fees": None,
    }


def _risk_for(name: str, state: dict[str, Any], profile: dict[str, Any]) -> AggregateRisk:
    budget = float(state["risk_budget"])
    if name == "baseline":
        config = state["baseline_risk"]
        return AggregateRisk.from_state(
            {
                **config,
                "lock_armed": profile["lock_armed"],
                "lock_floor": profile["lock_floor"],
                "peak_pnl": profile["peak_profit"],
                "trough_pnl": profile["trough_pnl"],
            }
        )
    return AggregateRisk(
        combined_stoploss=budget,
        lock_profit_at=budget * (0.5 if name == "early" else 1.0),
        lock_profit_floor=budget * 0.1,
        lock_trail_step=budget * 0.5,
        lock_armed=profile["lock_armed"],
        lock_floor=profile["lock_floor"],
        peak_pnl=profile["peak_profit"],
        trough_pnl=profile["trough_pnl"],
    )


def _executable_book(
    *,
    side: str,
    at: datetime,
    bid: Any,
    ask: Any,
    bid_qty: Any,
    ask_qty: Any,
    quote_at: datetime | None,
    max_quote_age_seconds: float,
) -> tuple[float, int] | None:
    if quote_at is None:
        return None
    stamp = _moment(quote_at, "quote time")
    age = (at - stamp).total_seconds()
    if age < 0 or age > max_quote_age_seconds:
        return None
    try:
        bid_price, ask_price = float(bid), float(ask)
        available = float(bid_qty if side == "BUY" else ask_qty)
    except (ValueError, TypeError):
        return None
    if not all(isfinite(item) for item in (bid_price, ask_price, available)):
        return None
    if bid_price <= 0 or ask_price <= bid_price or available < 1:
        return None
    return (bid_price if side == "BUY" else ask_price), int(available)


def _number_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def observe_comparison(
    state: dict[str, Any],
    *,
    observed_at: datetime,
    ltp: float,
    source: str,
    broker_connection_id: str,
    symbol: str,
    exchange: str,
    received_at: datetime | None = None,
    bid: Any = None,
    ask: Any = None,
    bid_qty: Any = None,
    ask_qty: Any = None,
    quote_at: datetime | None = None,
    max_quote_age_seconds: float = 3.0,
    max_market_age_seconds: float = 3.0,
) -> dict[str, Any]:
    """Advance every shadow outcome on one common, valid observation.

    Historical checkpoints lacking a book can establish a trigger only.
    Prospective exits remain pending until a fresh executable book arrives.
    """
    if source not in {"replay", "prospective"}:
        raise ValueError("source must be replay or prospective")
    if (
        broker_connection_id != state["broker_connection_id"]
        or symbol.strip().upper() != state["symbol"]
        or exchange.strip().upper() != state["exchange"]
    ):
        raise ValueError("observation identity does not match the admitted entry")
    at = _moment(observed_at, "observation time")
    if source == "prospective":
        if received_at is None:
            raise ValueError("prospective observation requires receipt time")
        age = (_moment(received_at, "receipt time") - at).total_seconds()
        if age < 0 or age > max_market_age_seconds:
            raise ValueError("stale or future market observation")
    if at < datetime.fromisoformat(state["entry_at"]):
        raise ValueError("observation predates entry")
    previous = state.get("last_observed_at")
    if previous and at <= datetime.fromisoformat(previous):
        raise ValueError("observations must be strictly ordered")
    price = _positive(ltp, "last price")
    cutoff = datetime.fromisoformat(state["cutoff_at"])
    if at > cutoff:
        raise ValueError("observation is after the intraday cutoff")
    book = _executable_book(
        side=state["side"],
        at=at,
        bid=bid,
        ask=ask,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        quote_at=quote_at,
        max_quote_age_seconds=max_quote_age_seconds,
    )
    quote_evidence = {
        "market_at": at.isoformat(),
        "received_at": _moment(received_at, "receipt time").isoformat()
        if received_at is not None
        else None,
        "ltp": price,
        "quote_at": _moment(quote_at, "quote time").isoformat() if quote_at is not None else None,
        "bid": _number_or_none(bid),
        "ask": _number_or_none(ask),
        "bid_qty": _number_or_none(bid_qty),
        "ask_qty": _number_or_none(ask_qty),
        "executable": book is not None,
    }
    direction = 1 if state["side"] == "BUY" else -1
    entry = float(state["entry_price"])
    for name, profile in state["profiles"].items():
        if profile["status"] in {"closed", "trigger_only", "cutoff"}:
            continue
        realized = float(profile["simulated_realized_pnl"] or 0.0)
        remaining = int(profile["remaining_qty"])
        mark = realized + direction * (price - entry) * remaining
        previous_peak = float(profile["peak_profit"])
        profile["peak_profit"] = max(previous_peak, mark)
        profile["trough_pnl"] = min(float(profile["trough_pnl"]), mark)
        profile["max_drawdown"] = max(
            float(profile["max_drawdown"]),
            profile["peak_profit"] - mark,
        )
        profile["last_mark_pnl"] = mark
        if profile["status"] == "observing":
            leg_reason = None
            if name == "baseline":
                leg_decision = risk_adapter.evaluate_leg(state["baseline_leg_state"], price)
                if leg_decision.breached:
                    leg_reason = leg_decision.reason.value
            decision = evaluate_aggregate(
                _risk_for(name, state, profile),
                realized,
                mark - realized,
            )
            profile["lock_armed"] = decision.lock_armed
            profile["lock_floor"] = decision.lock_floor
            if leg_reason or decision.breached:
                profile["reason"] = leg_reason or str(decision.reason.value)
                profile["trigger_at"] = at.isoformat()
                profile["trigger_mark_pnl"] = mark
                profile["trigger_quote"] = quote_evidence.copy()
                profile["status"] = "exit_pending"
            elif at >= cutoff:
                profile["reason"] = "intraday_cutoff"
                profile["trigger_at"] = at.isoformat()
                profile["trigger_mark_pnl"] = mark
                profile["trigger_quote"] = quote_evidence.copy()
                profile["status"] = "exit_pending"
        if profile["status"] not in {"exit_pending", "partial"}:
            continue
        if book is None:
            profile["missed_fill"] = True
            if source == "replay":
                profile["status"] = "trigger_only"
                profile["exit_fill_quality"] = "trigger_only_estimate"
            elif at >= cutoff:
                profile["status"] = "cutoff"
            continue
        execution_price, available_qty = book
        fill_qty = min(remaining, available_qty)
        profile["filled_qty"] += fill_qty
        profile["remaining_qty"] -= fill_qty
        profile["simulated_realized_pnl"] = (
            realized + direction * (execution_price - entry) * fill_qty
        )
        profile["fill_events"].append(
            {
                "at": at.isoformat(),
                "quote": quote_evidence.copy(),
                "quantity": fill_qty,
                "price": execution_price,
                "remaining_qty": profile["remaining_qty"],
            }
        )
        profile["exit_fill_quality"] = (
            "replay_book_estimate" if source == "replay" else "prospective_book_estimate"
        )
        if profile["remaining_qty"] == 0:
            profile["status"] = "closed"
            profile["closed_at"] = at.isoformat()
            profile["max_drawdown"] = max(
                profile["max_drawdown"],
                profile["peak_profit"] - profile["simulated_realized_pnl"],
            )
        else:
            profile["status"] = "partial"
            profile["missed_fill"] = True
    state["last_observed_at"] = at.isoformat()
    return state


def summarize_comparison(state: dict[str, Any]) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for name, profile in state["profiles"].items():
        triggered = profile["trigger_mark_pnl"]
        realized = profile["simulated_realized_pnl"]
        if profile["status"] == "closed":
            exit_pnl = realized
        elif profile["status"] == "trigger_only":
            exit_pnl = triggered
        else:
            exit_pnl = None
        profiles[name] = {
            "status": profile["status"],
            "reason": profile["reason"],
            "simulated_realized_pnl": realized,
            "peak_profit": profile["peak_profit"],
            "peak_to_exit_giveback": (
                max(0.0, profile["peak_profit"] - exit_pnl) if exit_pnl is not None else None
            ),
            "max_drawdown": profile["max_drawdown"],
            "filled_qty": profile["filled_qty"],
            "remaining_qty": profile["remaining_qty"],
            "missed_fill": profile["missed_fill"],
            "trigger_mark_pnl": triggered,
            "trigger_quote": profile["trigger_quote"],
            "fill_events": profile["fill_events"],
            "trigger_at": profile["trigger_at"],
            "closed_at": profile["closed_at"],
            "early_exit_vs_baseline": (
                profile["closed_at"] < state["profiles"]["baseline"]["closed_at"]
                if name != "baseline"
                and profile["closed_at"]
                and state["profiles"]["baseline"]["closed_at"]
                else None
            ),
            "fees": None,
            "outcome_quality": profile["exit_fill_quality"],
        }
    return {
        "run_id": state["run_id"],
        "position_ref": state["position_ref"],
        "broker_connection_id": state["broker_connection_id"],
        "symbol": state["symbol"],
        "exchange": state["exchange"],
        "risk_budget": state["risk_budget"],
        "baseline_scope": state["baseline_scope"],
        "entry_timestamp_source": state["entry_timestamp_source"],
        "profiles": profiles,
        "fees": None,
    }
