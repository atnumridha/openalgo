"""Portfolio-level admission control for Strategy Module entries.

The decision function is deliberately pure. Broker and Strategy Module facts
are collected separately so every rejection can be reproduced from its audit
payload, while exits and sandbox orders bypass live-entry policy entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytz

IST = pytz.timezone("Asia/Kolkata")


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


def _ist(now: datetime) -> datetime:
    if now.tzinfo is None:
        return IST.localize(now)
    return now.astimezone(IST)


def _decision(
    allowed: bool, code: str, message: str, metrics: dict[str, Any]
) -> GovernorDecision:
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
        return _decision(False, "cash_buffer", "The entry would breach the 20% cash buffer", metrics)
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
        return _decision(False, "position_limit", "The portfolio position limit is reached", metrics)

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


def _quote_price(
    leg: dict[str, Any], auth_token: str, broker: str
) -> Decimal | None:
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


def _open_configured_risk(user_id: str) -> Decimal | None:
    """Configured risk for Strategy Module positions held by this process."""

    from database import strategy_module_db as store
    from services.strategy_module import state

    total = Decimal("0")
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
        positions_ok, positions_response, _positions_status = (
            positionbook_service.get_positionbook(auth_token=auth_token, broker=broker)
        )
    except Exception:
        return _unavailable_live_facts()
    if not funds_ok or not positions_ok:
        return _unavailable_live_facts()

    available_cash = _decimal(
        _value(funds_response, "availablecash", "available_cash", "cash")
    )
    position_rows = _position_rows(positions_response)
    if available_cash is None or position_rows is None:
        return _unavailable_live_facts()

    open_cash_positions = 0
    open_nifty_option_positions = 0
    for position in position_rows:
        quantity = _decimal(_value(position, "netqty", "net_qty", "quantity"))
        if quantity is None:
            return _unavailable_live_facts()
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
        if needs_quote and price is None:
            estimated_debit = None
        elif position == "B" and estimated_debit is not None:
            estimated_debit += price * quantity

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
        intraday=str(_strategy_value(strategy, "strategy_type", "intraday")).lower()
        == "intraday",
    )
