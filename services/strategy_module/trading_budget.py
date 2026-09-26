"""Translate Strategy Module orders into the shared, durable capital budget.

Fees are modeled using the operator's explicit dated schedule. They are never
presented as broker-reconciled charges. All exits stay in the existing engine.
"""

from datetime import datetime
from decimal import Decimal

from database import trading_risk_db as ledger
from services.research.costs import (
    decimal_value,
    order_cost,
    validate_cost_dates,
    validate_cost_schedule,
)
from services.risk.budget import BudgetDecision
from services.strategy_module import session
from utils.logging import get_logger

logger = get_logger(__name__)
ZERO = Decimal("0")


class StaleTradeSnapshot(Exception):
    """Another observer committed while this snapshot was being calculated."""


def _update_snapshot(row, **values):
    user, mode = row["scope"].rsplit("|", 1)
    if ledger.update_trade(user, mode, row["ref"], expected=row, **values) is False:
        raise StaleTradeSnapshot()
    _sync_qualification(user, mode, row["ref"])


def _sync_qualification(user, mode, ref):
    if mode != "sandbox":
        return
    from services.research import qualification

    rows = ledger.list_trades(user, mode, ref=ref)
    if rows:
        row = rows[0]
        row["budget_snapshot"] = ledger.status(user, mode, row["session_day"])
        qualification.record_trade(user, ref, row)


def trading_day(now=None):
    now = now or datetime.now(session.IST)
    return session.session_day(now.astimezone(session.IST)).isoformat()


def _refusal(code):
    return BudgetDecision(False, code, "first", ZERO), None


def reserve_entry(user, strategy, legs, mode, broker, facts, now):
    """Called under admission lock, before any order can be submitted."""
    value = (
        strategy.get
        if isinstance(strategy, dict)
        else lambda key, default=None: getattr(strategy, key, default)
    )
    if len(legs) != 1 or value("strategy_type", "intraday") != "intraday":
        return _refusal("single_leg_intraday_required")
    leg = legs[0]
    exchange = str(leg.get("exchange") or "").upper()
    if leg.get("position") != "B" or exchange not in {"NFO", "BFO", "MCX"}:
        return _refusal("long_options_only")
    if not str(leg.get("symbol") or "").endswith(("CE", "PE")):
        return _refusal("long_options_only")
    try:
        quantity = decimal_value(leg.get("quantity") or leg.get("qty"), "quantity", minimum=1)
        lot = decimal_value(leg.get("lot_size"), "lot_size", minimum=1)
        if (
            quantity != quantity.to_integral_value()
            or lot != lot.to_integral_value()
            or quantity % lot
        ):
            return _refusal("whole_lots_required")
        # NFO/BFO quantities are exchange units. MCX monetary units must be
        # explicitly verified by the resolver; this build must not guess them.
        multiplier = decimal_value(
            leg.get("price_multiplier", 1 if exchange in {"NFO", "BFO"} else None),
            "price_multiplier",
            minimum=1,
        )
        if multiplier != 1:
            return _refusal("unsupported_contract_multiplier")
    except ValueError:
        return _refusal("contract_metadata_required")
    costs = ledger.get_costs(user)
    if costs is None:
        return _refusal("cost_schedule_required")
    try:
        costs = validate_cost_schedule(costs)
        day = trading_day(now)
        validate_cost_dates(costs, [day])
    except ValueError:
        return _refusal("cost_schedule_expired_or_invalid")
    if mode == "live":
        from services.research.jobs import live_release_reason

        reason = live_release_reason(
            str(user),
            int(value("id")),
            strategy,
            ledger.POLICY.version,
            costs,
        )
        if reason:
            return _refusal("validated_live_release_required")
    reconcile_account(user, mode)
    current = ledger.list_trades(user, mode, active_only=True)
    expected = {}
    for row in current:
        if row["broker"] != (broker or mode) or not row["filled"]:
            continue
        key = (row["details"]["exchange"].upper(), row["details"]["symbol"].upper())
        remaining = row["evidence"].get("remaining_quantity")
        if remaining is None:
            return _refusal("untracked_portfolio_exposure")
        expected[key] = expected.get(key, ZERO) + decimal_value(remaining, "remaining_quantity")
    observed = {}
    for broker_exchange, symbol, quantity in getattr(facts, "broker_quantities", ()):
        if broker_exchange.upper() in {"NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX"} and quantity:
            observed[(broker_exchange.upper(), symbol.upper())] = Decimal(str(quantity))
    expected = {key: qty for key, qty in expected.items() if qty}
    if observed != expected or facts.open_derivative_positions != len(observed):
        return _refusal("untracked_portfolio_exposure")
    if any(
        value is None or not value.is_finite()
        for value in (facts.entry_risk, facts.estimated_debit, facts.available_cash)
    ):
        return _refusal("risk_evidence_missing")
    premium = facts.estimated_debit
    entry_fee = order_cost(premium, "BUY", costs)
    # Using entry turnover for the stop-side fee is conservative for long
    # options. Execution at worse prices is handled by the monitoring ledger.
    exit_fee = order_cost(premium, "SELL", costs)
    slippage = premium * Decimal(str(costs["slippage_bps"])) / Decimal("10000") * 2
    risk = facts.entry_risk + entry_fee + exit_fee + slippage
    ref = str(leg.get("position_ref") or "")
    result = ledger.reserve(
        user,
        mode,
        ref,
        day,
        risk,
        premium + entry_fee,
        "mcx" if exchange == "MCX" else "index",
        broker or mode,
        int(value("id")),
        {
            "costs": costs,
            "symbol": leg["symbol"],
            "exchange": exchange,
            "quantity": str(quantity),
            "multiplier": str(multiplier),
            "policy_version": ledger.POLICY.version,
        },
        broker_cash=facts.available_cash,
    )
    if result.allowed and mode == "sandbox":
        try:
            from services.research import qualification

            qualification.register_entry(str(user), int(value("id")), ref)
        except Exception:
            logger.exception("Prospective campaign registration failed")
            ledger.update_trade(
                user,
                mode,
                ref,
                status="void",
                net_pnl=ZERO,
                filled=False,
                evidence={"reason": "qualification_registration_failed"},
            )
            _sync_qualification(user, mode, ref)
            return _refusal("paper_registration_required")
    return result, ref if result.allowed else None


def _sync_trade(row, order_snapshot=None):
    from database import strategy_module_db as store
    from services.strategy_module import state

    if row["run_id"] is None:
        return
    user, mode = row["scope"].rsplit("|", 1)
    orders = [
        o
        for o in (store.list_orders(row["run_id"]) if order_snapshot is None else order_snapshot)
        if o.get("position_ref") == row["ref"]
    ]
    if not orders:
        # A dispatch could have reached the broker without a local ack row.
        # Keep its full reservation until explicitly reconciled.
        return
    buy_qty = sell_qty = buy_value = sell_value = fees = ZERO
    costs = row["details"]["costs"]
    working = False
    for order in orders:
        status = str(order.get("status") or "").lower()
        filled = order.get("filled_qty")
        if filled is None and status in {"complete", "filled"}:
            raise ValueError("Filled order quantity is unavailable")
        qty = decimal_value(0 if filled is None else filled, "filled quantity")
        working = working or status not in {"complete", "filled", "rejected", "cancelled"}
        if qty == 0:
            continue
        price = decimal_value(order.get("avg_fill_price"), "filled price", minimum="0.000001")
        value = price * qty
        action = str(order.get("action") or "").upper()
        fees += order_cost(value, action, costs)
        if action == "BUY":
            buy_qty += qty
            buy_value += value
        else:
            sell_qty += qty
            sell_value += value
    if sell_qty > buy_qty:
        raise ValueError("Exit fills exceed the recorded entry quantity")
    remaining = buy_qty - sell_qty
    if buy_qty == 0:
        if not working:
            _update_snapshot(
                row, status="void", net_pnl=ZERO, filled=False, evidence={"orders": orders}
            )
        return
    mark = ZERO
    closing_cost = ZERO
    if remaining:
        snapshot = state.get_run_state(row["run_id"]) or {}
        leg = next(
            (
                x
                for x in (snapshot.get("legs") or {}).values()
                if x.get("position_ref") == row["ref"]
            ),
            None,
        )
        if leg is None:
            raise ValueError("Filled exposure is missing from managed state")
        mark = decimal_value(
            leg.get("ltp") or leg.get("entry_avg") or buy_value / buy_qty,
            "mark",
            minimum="0.000001",
        )
        # A still-working partial exit is the same order; reserve only the
        # incremental fee needed to finish it, not another brokerage charge.
        working_sells = [
            o
            for o in orders
            if o.get("action") == "SELL"
            and str(o.get("status")) not in {"complete", "filled", "rejected", "cancelled"}
        ]
        if len(working_sells) == 1:
            o = working_sells[0]
            prior = Decimal(str(o.get("filled_qty") or 0)) * Decimal(
                str(o.get("avg_fill_price") or 0)
            )
            closing_cost = order_cost(prior + mark * remaining, "SELL", costs) - (
                order_cost(prior, "SELL", costs) if prior else ZERO
            )
        else:
            closing_cost = order_cost(mark * remaining, "SELL", costs)
        closing_cost += mark * remaining * Decimal(str(costs["slippage_bps"])) / Decimal("10000")
    net = sell_value + mark * remaining - buy_value - fees - closing_cost
    status = "open" if remaining or working else "closed"
    cash_flow = sell_value - buy_value - fees
    working_buy = any(
        o.get("action") == "BUY"
        and str(o.get("status")).lower() not in {"complete", "filled", "rejected", "cancelled"}
        for o in orders
    )
    committed_cash = min(cash_flow, -row["premium"]) if working_buy else cash_flow
    evidence = {
        "orders": orders,
        "modeled_fees": str(fees),
        "estimated_liquidation_cost": str(closing_cost),
        "net_cash_flow": str(cash_flow),
        "committed_cash_flow": str(committed_cash),
        "cost_basis": "operator_schedule_estimate",
        "remaining_quantity": str(remaining),
        "mark": str(mark),
    }
    if (
        row["status"] == status
        and row["net_pnl"] == net
        and {key: value for key, value in row["evidence"].items() if key != "_ledger_revision"}
        == evidence
    ):
        _sync_qualification(user, mode, row["ref"])
        return
    _update_snapshot(row, status=status, net_pnl=net, filled=True, evidence=evidence)


def sync_run(run_id, *, active_only=False, position_ref=None):
    if run_id is None:
        return
    from database import strategy_module_db as store

    rows = ledger.list_trades(run_id=run_id, active_only=active_only, ref=position_ref)
    if not rows:
        return
    orders = store.list_orders(run_id)
    for original in rows:
        row = original
        user, mode = row["scope"].rsplit("|", 1)
        for attempt in range(3):
            try:
                _sync_trade(row, orders)
                break
            except StaleTradeSnapshot:
                if attempt == 2:
                    ledger.pause(user, mode, "Concurrent trade updates need reconciliation")
                    break
                row = ledger.list_trades(user, mode, run_id=run_id, ref=row["ref"])[0]
                orders = store.list_orders(run_id)
            except Exception as error:
                ledger.pause(user, mode, f"Trade evidence needs reconciliation: {error}")
                logger.exception("Could not reconcile trading budget for run %s", run_id)
                break


def reconcile_account(user, mode):
    for run_id in {
        r["run_id"]
        for r in ledger.list_trades(user, mode, active_only=True)
        if r["run_id"] is not None
    }:
        sync_run(run_id, active_only=True)


def dispatch_started(user, mode, ref, run_id):
    ledger.bind_run(user, mode, ref, run_id)


def release_admission(user, mode, ref, dispatched):
    if not dispatched:
        ledger.update_trade(
            user,
            mode,
            ref,
            status="void",
            net_pnl=ZERO,
            filled=False,
            evidence={"reason": "not_dispatched"},
        )
    else:
        reconcile_account(user, mode)
    _sync_qualification(user, mode, ref)


def breached_runs(run_id):
    """Return existing managed runs requiring exit; never dispatch an order."""
    if run_id is None:
        return []
    scope = ledger.scope_for_run(run_id)
    if scope is None:
        return []
    user, mode = scope
    reconcile_account(user, mode)
    snapshot = ledger.status(user, mode, trading_day())
    active = ledger.list_trades(user, mode, active_only=True)
    return [
        (r["run_id"], user)
        for r in active
        if r["run_id"] is not None and r["bucket"] in snapshot["exit_buckets"]
    ]
