"""Portfolio-level admission control for Strategy Module entries.

The decision function is deliberately pure. Broker and Strategy Module facts
are collected separately so every rejection can be reproduced from its audit
payload, while exits and sandbox orders bypass live-entry policy entirely.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from threading import Lock, RLock
from typing import Any

import pytz

IST = pytz.timezone("Asia/Kolkata")

_admission_registry_lock = RLock()
_admission_locks: dict[str, Lock] = {}
_entry_reservations: dict[str, list[_EntryReservation]] = {}
_reservation_cash_baselines: dict[str, Decimal] = {}


@dataclass(frozen=True, slots=True)
class GovernorPolicy:
    max_cash_positions: int = 2
    max_nifty_option_positions: int = 1
    cash_risk_pct: Decimal = Decimal("0.015")
    option_risk_pct: Decimal = Decimal("0.03")
    combined_risk_pct: Decimal = Decimal("0.04")
    cash_buffer_pct: Decimal = Decimal("0.20")
    daily_loss_pct: Decimal = Decimal("0.04")
    minimum_reward_risk: Decimal = Decimal("1.5")
    cooldown_minutes: int = 30


@dataclass(frozen=True, slots=True)
class EntryFacts:
    """Aggregated facts needed to decide one proposed entry."""

    intent: str = "entry"
    mode: str = "live"
    available_cash: Decimal | None = None
    open_cash_positions: int | None = None
    open_nifty_option_positions: int | None = None
    entry_cash_positions: int = 0
    entry_nifty_option_positions: int = 0
    entry_cash_risk: Decimal | None = None
    entry_option_lot_risk: Decimal | None = None
    entry_risk: Decimal | None = None
    open_risk: Decimal | None = None
    estimated_debit: Decimal | None = None
    minimum_reward_risk: Decimal | None = None
    session_pnl: Decimal | None = None
    consecutive_stopped_runs: int | None = None
    last_stopped_at: datetime | None = None
    has_option_entry: bool = False
    intraday: bool = True
    reservation_components: tuple[ReservationComponent, ...] = field(
        default=(), repr=False, compare=False
    )
    broker_quantities: tuple[tuple[str, str, Decimal], ...] = field(
        default=(), repr=False, compare=False
    )


@dataclass(frozen=True, slots=True)
class GovernorDecision:
    allowed: bool
    code: str
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        """Return an audit-safe representation without JSON-hostile Decimals."""

        def serialise(value: Any) -> Any:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat()
            return value

        return {
            "allowed": self.allowed,
            "code": self.code,
            "message": self.message,
            "metrics": {key: serialise(value) for key, value in self.metrics.items()},
        }


@dataclass(frozen=True, slots=True)
class ReservationComponent:
    """One admitted leg's facts kept until broker/state reconciliation."""

    leg_id: Any
    cash_positions: int
    nifty_option_positions: int
    configured_risk: Decimal
    estimated_debit: Decimal
    exchange: str
    symbol: str
    quantity_delta: Decimal
    baseline_quantity: Decimal
    run_id: int | None = None
    position_ref: str | None = None
    entry_order_id: int | None = None


@dataclass(slots=True)
class _EntryReservation:
    user_id: str
    components: list[ReservationComponent]
    available_cash_at_admission: Decimal | None
    committed: bool = False


class EntryAdmission:
    """A user gate plus provisional portfolio reservation for one entry."""

    __slots__ = ("_lock", "_released", "_reservation")

    def __init__(self, lock: Lock, reservation: _EntryReservation) -> None:
        self._lock = lock
        self._released = False
        self._reservation = reservation

    def commit(self, run_id: int, exposures: list[dict[str, Any]]) -> None:
        """Keep only broker-accepted legs after releasing the admission gate."""
        accepted = {str(item.get("leg_id")): item for item in exposures}
        with _admission_registry_lock:
            self._reservation.components = [
                replace(
                    component,
                    run_id=run_id,
                    position_ref=str(accepted[str(component.leg_id)].get("position_ref") or ""),
                    entry_order_id=accepted[str(component.leg_id)].get("entry_order_id"),
                )
                for component in self._reservation.components
                if str(component.leg_id) in accepted
            ]
            self._reservation.committed = bool(self._reservation.components)
            if self._reservation.committed:
                if (
                    any(component.estimated_debit > 0 for component in self._reservation.components)
                    and self._reservation.available_cash_at_admission is not None
                ):
                    _reservation_cash_baselines.setdefault(
                        self._reservation.user_id,
                        self._reservation.available_cash_at_admission,
                    )
            else:
                _remove_reservation(self._reservation)

    def release(self) -> None:
        if self._released:
            return
        if not self._reservation.committed:
            _remove_reservation(self._reservation)
        self._released = True
        self._lock.release()


def _admission_lock(user_id: str) -> Lock:
    with _admission_registry_lock:
        return _admission_locks.setdefault(str(user_id), Lock())


def _remove_reservation(reservation: _EntryReservation) -> None:
    with _admission_registry_lock:
        reservations = _entry_reservations.get(reservation.user_id)
        if not reservations:
            return
        try:
            reservations.remove(reservation)
        except ValueError:
            return
        if not reservations:
            _entry_reservations.pop(reservation.user_id, None)
        _clear_unused_cash_baseline(reservation.user_id)


def _clear_unused_cash_baseline(user_id: str) -> None:
    if not any(
        component.estimated_debit > 0
        for reservation in _entry_reservations.get(str(user_id), ())
        if reservation.committed
        for component in reservation.components
    ):
        _reservation_cash_baselines.pop(str(user_id), None)


def release_terminal_entry_reservation(entry_order_id: int) -> None:
    """Forget reservation components whose entry ended with no exposure."""
    with _admission_registry_lock:
        for user_id, reservations in list(_entry_reservations.items()):
            for reservation in list(reservations):
                reservation.components = [
                    component
                    for component in reservation.components
                    if component.entry_order_id != entry_order_id
                ]
                if not reservation.components:
                    _remove_reservation(reservation)
            _clear_unused_cash_baseline(user_id)


def _broker_quantity_map(facts: EntryFacts) -> dict[tuple[str, str], Decimal]:
    return {
        (str(exchange).upper(), str(symbol).upper()): quantity
        for exchange, symbol, quantity in facts.broker_quantities
    }


def _broker_reflects(
    component: ReservationComponent,
    quantities: dict[tuple[str, str], Decimal],
) -> bool:
    if not component.exchange or not component.symbol or component.quantity_delta == 0:
        return False
    current = quantities.get((component.exchange, component.symbol), Decimal("0"))
    target = component.baseline_quantity + component.quantity_delta
    if component.quantity_delta > 0:
        return current >= target
    return current <= target


def _terminal_without_exposure(component: ReservationComponent) -> bool:
    if component.run_id is None or component.position_ref is None:
        return False
    from database import strategy_module_db as store
    from services.strategy_module import state

    order = store.get_order(component.entry_order_id) if component.entry_order_id else None
    order_filled = _decimal(getattr(order, "filled_qty", 0)) if order else None
    if (
        order
        and str(order.status).lower() in {"rejected", "cancelled"}
        and order_filled is not None
        and order_filled <= 0
    ):
        return True
    snapshot = state.get_run_state(component.run_id)
    leg = (snapshot.get("legs") or {}).get(str(component.leg_id)) if snapshot else None
    if not leg or str(leg.get("position_ref") or "") != component.position_ref:
        return False
    if str(leg.get("status") or "").lower() in {"closed", "rejected", "cancelled"}:
        return True
    if str(leg.get("entry_status") or "").lower() in {"rejected", "cancelled"}:
        return True
    order_id = leg.get("entry_order_id")
    state_order = store.get_order(order_id) if order_id is not None else None
    state_filled = _decimal(getattr(state_order, "filled_qty", 0)) if state_order else None
    return bool(
        state_order
        and str(state_order.status).lower() in {"rejected", "cancelled"}
        and state_filled is not None
        and state_filled <= 0
    )


def _terminal_partial_component(
    component: ReservationComponent,
) -> ReservationComponent | None:
    """Shrink a dead partial order to exposure the broker can still reveal."""
    if component.entry_order_id is None:
        return component
    from database import strategy_module_db as store

    order = store.get_order(component.entry_order_id)
    if order is None or str(order.status).lower() not in {"rejected", "cancelled"}:
        return component
    filled = _decimal(getattr(order, "filled_qty", None))
    if filled is None:
        return component
    if filled <= 0:
        return None
    admitted_quantity = abs(component.quantity_delta)
    if admitted_quantity <= 0 or filled >= admitted_quantity:
        return component
    fraction = filled / admitted_quantity
    return replace(
        component,
        configured_risk=component.configured_risk * fraction,
        estimated_debit=component.estimated_debit * fraction,
        quantity_delta=filled if component.quantity_delta > 0 else -filled,
    )


def _component_has_reserved_exposure(component: ReservationComponent) -> bool:
    return bool(
        component.cash_positions
        or component.nifty_option_positions
        or component.configured_risk > 0
        or component.estimated_debit > 0
    )


def _reconcile_reserved_debit(user_id: str, available_cash: Decimal | None) -> None:
    """Consume cash decreases for quantity-correlated reservations only."""
    if available_cash is None:
        return
    baseline = _reservation_cash_baselines.get(user_id)
    if baseline is None:
        return
    visible_debit = baseline - available_cash
    if visible_debit <= 0:
        return

    remaining = visible_debit
    for reservation in _entry_reservations.get(user_id, ()):
        if not reservation.committed:
            continue
        reconciled: list[ReservationComponent] = []
        for component in reservation.components:
            if remaining > 0 and component.estimated_debit > 0 and component.quantity_delta == 0:
                consumed = min(remaining, component.estimated_debit)
                component = replace(
                    component,
                    estimated_debit=component.estimated_debit - consumed,
                )
                remaining -= consumed
            if _component_has_reserved_exposure(component):
                reconciled.append(component)
        reservation.components = reconciled

    _reservation_cash_baselines[user_id] = available_cash
    _clear_unused_cash_baseline(user_id)


def _reconcile_reservations(user_id: str, facts: EntryFacts) -> list[ReservationComponent]:
    user_key = str(user_id)
    quantities = _broker_quantity_map(facts)
    active: list[ReservationComponent] = []
    with _admission_registry_lock:
        for reservation in list(_entry_reservations.get(user_key, ())):
            if not reservation.committed:
                continue
            reconciled: list[ReservationComponent] = []
            for component in reservation.components:
                adjusted = _terminal_partial_component(component)
                if adjusted is None:
                    continue
                if _terminal_without_exposure(adjusted):
                    continue
                if _broker_reflects(adjusted, quantities):
                    adjusted = replace(
                        adjusted,
                        cash_positions=0,
                        nifty_option_positions=0,
                        configured_risk=Decimal("0"),
                        quantity_delta=Decimal("0"),
                    )
                if _component_has_reserved_exposure(adjusted):
                    reconciled.append(adjusted)
            reservation.components = reconciled
            if not reservation.components:
                _remove_reservation(reservation)
        _reconcile_reserved_debit(user_key, facts.available_cash)
        for reservation in list(_entry_reservations.get(user_key, ())):
            reservation.components = [
                component
                for component in reservation.components
                if _component_has_reserved_exposure(component)
            ]
            if reservation.components:
                active.extend(reservation.components)
            else:
                _remove_reservation(reservation)
    return active


def _merge_reservations(user_id: str, facts: EntryFacts) -> EntryFacts:
    if facts.mode != "live":
        return facts
    active = _reconcile_reservations(user_id, facts)
    if not active:
        return facts
    if (
        facts.open_cash_positions is None
        or facts.open_nifty_option_positions is None
        or facts.open_risk is None
        or facts.estimated_debit is None
    ):
        return facts
    return replace(
        facts,
        open_cash_positions=facts.open_cash_positions
        + sum(component.cash_positions for component in active),
        open_nifty_option_positions=facts.open_nifty_option_positions
        + sum(component.nifty_option_positions for component in active),
        open_risk=facts.open_risk
        + sum((component.configured_risk for component in active), Decimal("0")),
        estimated_debit=facts.estimated_debit
        + sum((component.estimated_debit for component in active), Decimal("0")),
    )


def _fallback_reservation_components(
    facts: EntryFacts,
    resolved_legs: list[dict[str, Any]],
) -> tuple[ReservationComponent, ...]:
    """Supply aggregate test/legacy facts when the adapter has no leg detail."""
    if facts.reservation_components:
        return facts.reservation_components
    if not resolved_legs or facts.entry_risk is None or facts.estimated_debit is None:
        return ()
    leg = resolved_legs[0]
    quantity = _decimal(leg.get("quantity") or leg.get("qty")) or Decimal("0")
    position = str(leg.get("position") or "").upper()
    exchange = str(leg.get("exchange") or "").upper()
    symbol = str(leg.get("symbol") or "").upper()
    baseline = _broker_quantity_map(facts).get((exchange, symbol), Decimal("0"))
    return (
        ReservationComponent(
            leg_id=leg.get("leg_id") or leg.get("id"),
            cash_positions=facts.entry_cash_positions,
            nifty_option_positions=facts.entry_nifty_option_positions,
            configured_risk=facts.entry_risk,
            estimated_debit=facts.estimated_debit,
            exchange=exchange,
            symbol=symbol,
            quantity_delta=quantity if position == "B" else -quantity,
            baseline_quantity=baseline,
        ),
    )


def _ist(now: datetime) -> datetime:
    if now.tzinfo is None:
        return IST.localize(now)
    return now.astimezone(IST)


def _decision(allowed: bool, code: str, message: str, metrics: dict[str, Any]) -> GovernorDecision:
    return GovernorDecision(allowed=allowed, code=code, message=message, metrics=metrics)


def evaluate_entry(
    facts: EntryFacts,
    policy: GovernorPolicy,
    now: datetime,
) -> GovernorDecision:
    """Apply the live-entry policy in stable, fail-closed order."""

    if facts.intent == "exit":
        return _decision(True, "exit_allowed", "Exits are never blocked by the governor", {})
    if facts.intent != "entry":
        return _decision(False, "risk_missing", "The order intent is unavailable", {})
    if facts.mode == "sandbox":
        return _decision(True, "sandbox_allowed", "Sandbox entries bypass live portfolio facts", {})

    now_ist = _ist(now)
    local_time = now_ist.timetz().replace(tzinfo=None)
    if facts.intraday and (local_time < time(9, 20) or local_time > time(15, 0)):
        return _decision(
            False,
            "outside_entry_window",
            "New entries are allowed only from 09:20 through 15:00 IST",
            {"evaluated_at": now_ist},
        )
    if facts.has_option_entry and local_time > time(14, 45):
        return _decision(
            False,
            "option_window_closed",
            "New option entries are not allowed after 14:45 IST",
            {"evaluated_at": now_ist},
        )

    required = (
        facts.available_cash,
        facts.open_cash_positions,
        facts.open_nifty_option_positions,
        facts.entry_cash_risk,
        facts.entry_option_lot_risk,
        facts.entry_risk,
        facts.open_risk,
        facts.estimated_debit,
        facts.minimum_reward_risk,
        facts.session_pnl,
        facts.consecutive_stopped_runs,
    )
    if any(value is None for value in required):
        return _decision(
            False,
            "risk_missing",
            "Live funds, positions, quotes, and configured protective risk are required",
            {},
        )
    if facts.available_cash <= 0 or facts.minimum_reward_risk < policy.minimum_reward_risk:
        return _decision(
            False,
            "risk_missing",
            "A positive cash balance, protective stop, and target of at least 1.5R are required",
            {"minimum_reward_risk": facts.minimum_reward_risk},
        )

    cash_risk_limit = facts.available_cash * policy.cash_risk_pct
    option_risk_limit = facts.available_cash * policy.option_risk_pct
    combined_risk_limit = facts.available_cash * policy.combined_risk_pct
    cash_buffer_required = facts.available_cash * policy.cash_buffer_pct
    daily_loss_limit = facts.available_cash * policy.daily_loss_pct
    combined_risk = facts.open_risk + facts.entry_risk
    cash_remaining = facts.available_cash - facts.estimated_debit
    metrics = {
        "available_cash": facts.available_cash,
        "entry_cash_risk": facts.entry_cash_risk,
        "entry_option_lot_risk": facts.entry_option_lot_risk,
        "entry_risk": facts.entry_risk,
        "open_risk": facts.open_risk,
        "combined_risk": combined_risk,
        "cash_risk_limit": cash_risk_limit,
        "option_risk_limit": option_risk_limit,
        "combined_risk_limit": combined_risk_limit,
        "estimated_debit": facts.estimated_debit,
        "cash_remaining": cash_remaining,
        "cash_buffer_required": cash_buffer_required,
        "session_pnl": facts.session_pnl,
        "daily_loss_limit": daily_loss_limit,
        "open_cash_positions": facts.open_cash_positions,
        "open_nifty_option_positions": facts.open_nifty_option_positions,
        "entry_cash_positions": facts.entry_cash_positions,
        "entry_nifty_option_positions": facts.entry_nifty_option_positions,
        "consecutive_stopped_runs": facts.consecutive_stopped_runs,
    }

    if facts.entry_cash_risk > cash_risk_limit:
        return _decision(False, "cash_trade_risk", "Cash entry risk exceeds 1.5%", metrics)
    if facts.entry_option_lot_risk > option_risk_limit:
        return _decision(
            False,
            "option_lot_risk",
            "Long-option risk per minimum lot exceeds 3%",
            metrics,
        )
    if combined_risk > combined_risk_limit:
        return _decision(
            False,
            "combined_open_risk",
            "Combined configured open risk exceeds 4%",
            metrics,
        )
    if cash_remaining < cash_buffer_required:
        return _decision(
            False, "cash_buffer", "The entry would breach the 20% cash buffer", metrics
        )
    if facts.session_pnl <= -daily_loss_limit:
        return _decision(False, "daily_loss_lock", "The 4% daily loss lock is active", metrics)
    if facts.consecutive_stopped_runs >= 3:
        return _decision(
            False,
            "consecutive_loss_lock",
            "Three consecutive stopped runs lock entries for the session",
            metrics,
        )
    if facts.consecutive_stopped_runs >= 2 and facts.last_stopped_at is not None:
        last_stopped_at = _ist(facts.last_stopped_at)
        cooldown_until = last_stopped_at + timedelta(minutes=policy.cooldown_minutes)
        metrics["cooldown_until"] = cooldown_until
        if now_ist < cooldown_until:
            return _decision(False, "cooldown", "The stopped-run cooldown is active", metrics)

    if (
        facts.open_cash_positions + facts.entry_cash_positions > policy.max_cash_positions
        or facts.open_nifty_option_positions + facts.entry_nifty_option_positions
        > policy.max_nifty_option_positions
    ):
        return _decision(
            False, "position_limit", "The portfolio position limit is reached", metrics
        )

    return _decision(True, "entry_allowed", "The entry is within every governor limit", metrics)


def _value(source: Any, *aliases: str) -> Any:
    """Read a case-insensitive broker alias from nested response dictionaries."""

    if not isinstance(source, dict):
        return None
    normalised = {str(key).lower(): value for key, value in source.items()}
    for alias in aliases:
        if alias.lower() in normalised:
            return normalised[alias.lower()]
    nested = normalised.get("data")
    if isinstance(nested, dict):
        return _value(nested, *aliases)
    return None


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None
    return number if number.is_finite() else None


def _strategy_value(strategy: Any, name: str, default: Any = None) -> Any:
    if isinstance(strategy, dict):
        return strategy.get(name, default)
    return getattr(strategy, name, default)


def _is_option(leg: dict[str, Any]) -> bool:
    segment = str(leg.get("segment") or "").lower()
    symbol = str(leg.get("symbol") or "").upper()
    exchange = str(leg.get("exchange") or "").upper()
    return segment in {"option", "options"} or (
        exchange in {"NFO", "BFO"} and symbol.endswith(("CE", "PE"))
    )


def _is_nifty_option(leg: dict[str, Any]) -> bool:
    symbol = str(leg.get("symbol") or "").upper()
    underlying = str(leg.get("underlying") or "").upper()
    return _is_option(leg) and (underlying == "NIFTY" or symbol.startswith("NIFTY"))


def _is_cash(leg: dict[str, Any]) -> bool:
    segment = str(leg.get("segment") or "").lower()
    exchange = str(leg.get("exchange") or "").upper()
    return segment == "cash" or (not _is_option(leg) and exchange in {"NSE", "BSE"})


def _position_rows(response: dict[str, Any]) -> list[dict[str, Any]] | None:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("positions", "positionbook"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return None


def _quote_price(leg: dict[str, Any], auth_token: str, broker: str) -> Decimal | None:
    from services import quotes_service

    try:
        ok, response, _status = quotes_service.get_quotes(
            str(leg.get("symbol") or ""),
            str(leg.get("exchange") or ""),
            auth_token=auth_token,
            broker=broker,
        )
    except Exception:
        return None
    if not ok or not isinstance(response, dict):
        return None
    data = response.get("data")
    if not isinstance(data, dict):
        return None
    if "ask" in {str(key).lower() for key in data}:
        ask = _decimal(_value(data, "ask"))
        return ask if ask is not None and ask > 0 else None
    ltp = _decimal(_value(data, "ltp"))
    return ltp if ltp is not None and ltp > 0 else None


def _risk_distance(leg: dict[str, Any], price: Decimal | None, field: str) -> Decimal | None:
    configured = _decimal(leg.get(field))
    if configured is None or configured <= 0:
        return None
    if str(leg.get("risk_unit") or "points").lower() == "percent":
        if price is None or price <= 0:
            return None
        return price * configured / Decimal("100")
    return configured


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _reconstruct_recovered_entry_reservations(
    user_id: str,
    facts: EntryFacts,
    api_key: str,
) -> bool:
    """Restore unfilled working-entry reservations lost with the process.

    Recovery deliberately restores a working entry as ``configured``: it may
    still fill, but it is not yet a confirmed position. The original
    admission reservation was process-local, so rebuild it from the recovered
    state and its durable order before evaluating another entry.

    Only a provably unfilled order with no broker-visible quantity is safe to
    reconstruct. A partial fill, an existing quantity in the same instrument,
    or missing stop/quote data leaves the pre-order baseline ambiguous; those
    cases fail closed instead of inventing risk or debit facts.
    """
    if facts.mode != "live":
        return True

    from database import strategy_module_db as store
    from services.strategy_module import recovery, state

    with _admission_registry_lock:
        reserved_order_ids = {
            component.entry_order_id
            for reservation in _entry_reservations.get(str(user_id), ())
            if reservation.committed
            for component in reservation.components
            if component.entry_order_id is not None
        }

    pending: list[tuple[dict[str, Any], Any]] = []
    try:
        for run_id in state.active_run_ids():
            run_row = store.get_run(run_id)
            if run_row is None or str(_row_value(run_row, "mode", "")) != "live":
                continue
            strategy = store.get_strategy_unscoped(int(_row_value(run_row, "strategy_id")))
            if strategy is None or str(_strategy_value(strategy, "user_id", "")) != str(user_id):
                continue
            snapshot = state.get_run_state(run_id)
            if snapshot is None:
                return False
            configured_legs = {
                str(leg.get("id") or leg.get("leg_id") or index): leg
                for index, leg in enumerate(_strategy_value(strategy, "legs", []) or [], start=1)
                if isinstance(leg, dict)
            }
            for leg_key, recovered_leg in (snapshot.get("legs") or {}).items():
                if str(recovered_leg.get("status") or "").lower() != "configured":
                    continue
                if not recovery.order_is_working(recovered_leg.get("entry_status")):
                    continue
                entry_order_id = recovered_leg.get("entry_order_id")
                if entry_order_id is None:
                    return False
                entry_order_id = int(entry_order_id)
                if entry_order_id in reserved_order_ids:
                    continue
                order = store.get_order(entry_order_id)
                if (
                    order is None
                    or int(_row_value(order, "run_id", -1)) != int(run_id)
                    or str(_row_value(order, "kind", "")) != "entry"
                    or not recovery.order_is_working(_row_value(order, "status"))
                ):
                    return False
                raw_filled = _row_value(order, "filled_qty")
                filled = Decimal("0") if raw_filled is None else _decimal(raw_filled)
                if filled is None or filled != 0:
                    return False
                shape = dict(configured_legs.get(str(leg_key)) or {})
                shape.update(recovered_leg)
                pending.append((shape, order))
    except Exception:
        return False

    if not pending:
        return True
    if (
        facts.available_cash is None
        or facts.open_cash_positions is None
        or facts.open_nifty_option_positions is None
    ):
        return False

    try:
        from database.auth_db import get_auth_token_broker

        auth_token, broker = get_auth_token_broker(api_key)
    except Exception:
        return False
    if not auth_token or not broker:
        return False

    quantities = _broker_quantity_map(facts)
    components: list[ReservationComponent] = []
    for leg, order in pending:
        exchange = str(_row_value(order, "exchange", "") or "").upper()
        symbol = str(_row_value(order, "symbol", "") or "").upper()
        quantity = _decimal(_row_value(order, "qty"))
        action = str(_row_value(order, "action", "") or "").upper()
        position = str(leg.get("position") or "").upper()
        position_ref = str(_row_value(order, "position_ref", "") or "")
        if (
            not exchange
            or not symbol
            or quantity is None
            or quantity <= 0
            or action not in {"BUY", "SELL"}
            or position not in {"B", "S"}
            or (action == "BUY") != (position == "B")
            or not position_ref
        ):
            return False

        # Without the original admission baseline, any visible quantity could
        # already include this order or could pre-date it. Refuse another
        # entry rather than double-counting or silently releasing exposure.
        baseline_quantity = quantities.get((exchange, symbol), Decimal("0"))
        if baseline_quantity != 0:
            return False

        needs_quote = action == "BUY" or str(leg.get("risk_unit") or "points").lower() == "percent"
        price = _quote_price(leg, auth_token, broker) if needs_quote else None
        if needs_quote and (price is None or price <= 0):
            return False
        stop_distance = _risk_distance(leg, price, "sl_pts")
        if stop_distance is None or stop_distance <= 0:
            return False

        components.append(
            ReservationComponent(
                leg_id=leg.get("leg_id") or leg.get("id"),
                cash_positions=int(_is_cash(leg)),
                nifty_option_positions=int(_is_nifty_option(leg)),
                configured_risk=stop_distance * quantity,
                estimated_debit=(price * quantity if action == "BUY" else Decimal("0")),
                exchange=exchange,
                symbol=symbol,
                quantity_delta=quantity if action == "BUY" else -quantity,
                baseline_quantity=baseline_quantity,
                run_id=int(_row_value(order, "run_id")),
                position_ref=position_ref,
                entry_order_id=int(_row_value(order, "id")),
            )
        )

    if not components:
        return True
    reservation = _EntryReservation(
        user_id=str(user_id),
        components=components,
        available_cash_at_admission=facts.available_cash,
        committed=True,
    )
    with _admission_registry_lock:
        # The per-user admission lock serializes normal callers. Keep this
        # idempotence check as a guard for explicit recovery/admin calls that
        # may populate state concurrently with startup.
        current_order_ids = {
            component.entry_order_id
            for current in _entry_reservations.get(str(user_id), ())
            if current.committed
            for component in current.components
        }
        reservation.components = [
            component
            for component in reservation.components
            if component.entry_order_id not in current_order_ids
        ]
        if reservation.components:
            _entry_reservations.setdefault(str(user_id), []).append(reservation)
            if any(component.estimated_debit > 0 for component in reservation.components):
                _reservation_cash_baselines.setdefault(str(user_id), facts.available_cash)
    return True


def _reserved_position_refs(user_id: str) -> set[str]:
    with _admission_registry_lock:
        return {
            component.position_ref
            for reservation in _entry_reservations.get(str(user_id), ())
            if reservation.committed
            for component in reservation.components
            if component.position_ref and component.configured_risk > 0
        }


def _open_configured_risk(user_id: str) -> Decimal | None:
    """Configured risk for Strategy Module positions held by this process."""

    from database import strategy_module_db as store
    from services.strategy_module import state

    total = Decimal("0")
    reserved_refs = _reserved_position_refs(user_id)
    for run_id in state.active_run_ids():
        run_row = store.get_run(run_id)
        if run_row is None:
            continue
        strategy = store.get_strategy_unscoped(run_row.strategy_id)
        if strategy is None or str(strategy.user_id) != str(user_id):
            continue
        snapshot = state.get_run_state(run_id)
        if snapshot is None:
            return None
        for leg in state.open_legs(snapshot):
            if str(leg.get("position_ref") or "") in reserved_refs:
                continue
            quantity = _decimal(leg.get("entry_filled_qty") or leg.get("qty"))
            price = _decimal(leg.get("entry_avg"))
            distance = _risk_distance(leg, price, "sl_pts")
            if quantity is None or quantity <= 0 or distance is None:
                return None
            total += distance * quantity
    return total


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        from datetime import UTC

        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(IST)


def _session_history(user_id: str) -> tuple[Decimal | None, int | None, datetime | None]:
    from database import strategy_module_db as store
    from services.strategy_module import session, state

    now = datetime.now(IST)
    session_day = session.session_day(now)
    completed: list[tuple[datetime, str, Decimal]] = []
    active_pnl = Decimal("0")
    try:
        strategies = store.list_strategies(user_id)
        for strategy in strategies:
            strategy_id = _strategy_value(strategy, "id")
            for run in store.list_runs(strategy_id):
                started = _parse_datetime(run.get("started_at"))
                if started is None or session.session_day(started) != session_day:
                    continue
                pnl = _decimal(run.get("pnl_realized"))
                if pnl is None:
                    return None, None, None
                stopped = _parse_datetime(run.get("stopped_at"))
                if stopped is not None:
                    completed.append((stopped, str(run.get("stop_reason") or ""), pnl))
        for run_id in state.active_run_ids():
            run_row = store.get_run(run_id)
            if run_row is None:
                continue
            strategy = store.get_strategy_unscoped(run_row.strategy_id)
            if strategy is None or str(strategy.user_id) != str(user_id):
                continue
            snapshot = state.get_run_state(run_id)
            if snapshot is None:
                return None, None, None
            realized = _decimal(snapshot.get("pnl_realized"))
            if realized is None:
                return None, None, None
            active_pnl += realized
    except Exception:
        return None, None, None

    completed.sort(key=lambda item: item[0], reverse=True)
    session_pnl = active_pnl + sum((item[2] for item in completed), Decimal("0"))
    loss_stop_reasons = {"overall_sl", "daily_loss_limit"}
    consecutive = 0
    for _stopped, reason, _pnl in completed:
        if reason not in loss_stop_reasons:
            break
        consecutive += 1
    return session_pnl, consecutive, completed[0][0] if completed else None


def _unavailable_live_facts() -> EntryFacts:
    return EntryFacts(intent="entry", mode="live")


def build_entry_facts(
    user_id: str,
    strategy: Any,
    resolved_legs: list[dict[str, Any]],
    api_key: str,
    mode: str,
) -> EntryFacts:
    """Collect live broker and Strategy Module facts for proposed resolved legs."""

    if mode == "sandbox":
        return EntryFacts(intent="entry", mode="sandbox")
    if mode != "live":
        return _unavailable_live_facts()

    from database.auth_db import get_auth_token_broker
    from services import funds_service, positionbook_service

    try:
        auth_token, broker = get_auth_token_broker(api_key)
    except Exception:
        return _unavailable_live_facts()
    if not auth_token or not broker:
        return _unavailable_live_facts()

    try:
        funds_ok, funds_response, _funds_status = funds_service.get_funds(
            auth_token=auth_token, broker=broker
        )
        positions_ok, positions_response, _positions_status = positionbook_service.get_positionbook(
            auth_token=auth_token, broker=broker
        )
    except Exception:
        return _unavailable_live_facts()
    if not funds_ok or not positions_ok:
        return _unavailable_live_facts()

    available_cash = _decimal(_value(funds_response, "availablecash", "available_cash", "cash"))
    position_rows = _position_rows(positions_response)
    if available_cash is None or position_rows is None:
        return _unavailable_live_facts()

    open_cash_positions = 0
    open_nifty_option_positions = 0
    broker_quantity_map: dict[tuple[str, str], Decimal] = {}
    for position in position_rows:
        quantity = _decimal(_value(position, "netqty", "net_qty", "quantity"))
        if quantity is None:
            return _unavailable_live_facts()
        exchange = str(_value(position, "exchange") or "").upper()
        symbol = str(_value(position, "symbol", "tradingsymbol") or "").upper()
        if exchange and symbol:
            broker_quantity_map[(exchange, symbol)] = quantity
        if quantity == 0:
            continue
        if _is_cash(position):
            open_cash_positions += 1
        if _is_nifty_option(position):
            open_nifty_option_positions += 1

    entry_cash_positions = 0
    entry_nifty_option_positions = 0
    cash_risk = Decimal("0")
    maximum_option_lot_risk = Decimal("0")
    entry_risk = Decimal("0")
    estimated_debit = Decimal("0")
    reward_risks: list[Decimal] = []
    has_option_entry = False
    reservation_components: list[ReservationComponent] = []

    for raw_leg in resolved_legs:
        leg = dict(raw_leg)
        quantity = _decimal(leg.get("quantity") or leg.get("qty"))
        if quantity is None or quantity <= 0:
            return _unavailable_live_facts()
        is_cash = _is_cash(leg)
        is_option = _is_option(leg)
        is_nifty_option = _is_nifty_option(leg)
        has_option_entry = has_option_entry or is_option
        entry_cash_positions += int(is_cash)
        entry_nifty_option_positions += int(is_nifty_option)

        position = str(leg.get("position") or "").upper()
        needs_quote = position == "B" or str(leg.get("risk_unit") or "points").lower() == "percent"
        price = _quote_price(leg, auth_token, broker) if needs_quote else None
        leg_debit = Decimal("0")
        if needs_quote and price is None:
            estimated_debit = None
        elif position == "B" and estimated_debit is not None:
            leg_debit = price * quantity
            estimated_debit += leg_debit

        stop_distance = _risk_distance(leg, price, "sl_pts")
        target_distance = _risk_distance(leg, price, "target_pts")
        if stop_distance is None or target_distance is None:
            entry_risk = None
            reward_risks = []
            break
        reward_risks.append(target_distance / stop_distance)
        leg_risk = stop_distance * quantity
        entry_risk += leg_risk
        if is_cash:
            cash_risk += leg_risk
        if is_option and position == "B":
            lot_size = _decimal(leg.get("lot_size") or leg.get("lotsize") or 1)
            if lot_size is None or lot_size <= 0:
                entry_risk = None
                break
            maximum_option_lot_risk = max(maximum_option_lot_risk, stop_distance * lot_size)
        exchange = str(leg.get("exchange") or "").upper()
        symbol = str(leg.get("symbol") or "").upper()
        reservation_components.append(
            ReservationComponent(
                leg_id=leg.get("leg_id") or leg.get("id"),
                cash_positions=int(is_cash),
                nifty_option_positions=int(is_nifty_option),
                configured_risk=leg_risk,
                estimated_debit=leg_debit,
                exchange=exchange,
                symbol=symbol,
                quantity_delta=quantity if position == "B" else -quantity,
                baseline_quantity=broker_quantity_map.get((exchange, symbol), Decimal("0")),
            )
        )

    broker_quantities = tuple(
        (exchange, symbol, quantity)
        for (exchange, symbol), quantity in sorted(broker_quantity_map.items())
    )
    _reconcile_reservations(
        user_id,
        EntryFacts(mode="live", broker_quantities=broker_quantities),
    )
    open_risk = _open_configured_risk(user_id)
    session_pnl, consecutive, last_stopped_at = _session_history(user_id)
    minimum_reward = min(reward_risks) if reward_risks else None

    return EntryFacts(
        intent="entry",
        mode="live",
        available_cash=available_cash,
        open_cash_positions=open_cash_positions,
        open_nifty_option_positions=open_nifty_option_positions,
        entry_cash_positions=entry_cash_positions,
        entry_nifty_option_positions=entry_nifty_option_positions,
        entry_cash_risk=cash_risk if entry_risk is not None else None,
        entry_option_lot_risk=maximum_option_lot_risk if entry_risk is not None else None,
        entry_risk=entry_risk,
        open_risk=open_risk,
        estimated_debit=estimated_debit,
        minimum_reward_risk=minimum_reward,
        session_pnl=session_pnl,
        consecutive_stopped_runs=consecutive,
        last_stopped_at=last_stopped_at,
        has_option_entry=has_option_entry,
        intraday=str(_strategy_value(strategy, "strategy_type", "intraday")).lower() == "intraday",
        reservation_components=tuple(reservation_components),
        broker_quantities=broker_quantities,
    )


def acquire_entry_admission(
    user_id: str,
    strategy: Any,
    resolved_legs: list[dict[str, Any]],
    api_key: str,
    mode: str,
    policy: GovernorPolicy,
    now: datetime,
    authorization_check: Callable[[], tuple[bool, str | None]] | None = None,
) -> tuple[GovernorDecision, EntryAdmission | None]:
    """Atomically evaluate and lease one user's Strategy Module entry path.

    A live lease deliberately remains locked after this function returns. The
    caller releases it only after an accepted dispatch is represented in run
    state, or after every refusal/failure path has finished. That makes a
    subsequent strategy collect fresh facts after the earlier entry is visible
    instead of evaluating concurrently against the same broker snapshot.
    """

    if mode == "sandbox":
        facts = build_entry_facts(user_id, strategy, resolved_legs, api_key, mode)
        return evaluate_entry(facts, policy, now), None

    lock = _admission_lock(user_id)
    lock.acquire()
    try:
        if authorization_check is not None:
            authorized, error = authorization_check()
            if not authorized:
                lock.release()
                return (
                    GovernorDecision(
                        allowed=False,
                        code="live_authorization_required",
                        message=error
                        or "Live automation is not authorized for this trading session",
                    ),
                    None,
                )
        raw_facts = build_entry_facts(user_id, strategy, resolved_legs, api_key, mode)
        if not _reconstruct_recovered_entry_reservations(user_id, raw_facts, api_key):
            lock.release()
            return (
                GovernorDecision(
                    allowed=False,
                    code="risk_missing",
                    message=(
                        "Recovered working-entry risk or debit could not be reconstructed safely"
                    ),
                ),
                None,
            )
        facts = _merge_reservations(user_id, raw_facts)
        decision = evaluate_entry(facts, policy, now)
        if decision.allowed:
            reservation = _EntryReservation(
                user_id=str(user_id),
                components=list(_fallback_reservation_components(raw_facts, resolved_legs)),
                available_cash_at_admission=raw_facts.available_cash,
            )
            with _admission_registry_lock:
                _entry_reservations.setdefault(str(user_id), []).append(reservation)
            return decision, EntryAdmission(lock, reservation)
        lock.release()
        return decision, None
    except Exception:
        lock.release()
        return (
            GovernorDecision(
                allowed=False,
                code="risk_missing",
                message="Portfolio admission facts could not be evaluated",
            ),
            None,
        )
