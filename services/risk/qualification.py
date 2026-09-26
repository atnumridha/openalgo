"""Pure prospective execution evidence and fixed forward qualification policy.

Inputs are supplied by the durable collector. This module reads no clock, data
store, broker or application state. Costs are estimates, never charged fees.
"""

from datetime import datetime
from decimal import Decimal

from services.research.costs import (
    decimal_value,
    order_cost,
    validate_cost_dates,
    validate_cost_schedule,
)

POLICY = {
    "version": "forward-v1",
    "min_final_trades": 20,
    "min_sessions": 30,
    "min_closed_trades": 100,
    "min_profit_factor": 1.2,
    "max_drawdown_pct": 15,
    "approval_days": 7,
    "max_quote_age_seconds": 5,
    "max_fill_delay_seconds": 30,
    "stress_cost_multiplier": 2,
    "stress_slippage_multiplier": 2,
}
ZERO = Decimal("0")
TERMINAL = {"complete", "filled", "rejected", "cancelled"}


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Execution timestamps must include their time zone")
    return parsed


def evaluate_trade(row, quotes, binding, registered_at):
    """Value filled quantities at adverse executable prices and diagnose gaps."""
    issues = []
    net = stress = ZERO
    buys = sells = ZERO
    orders = (row.get("evidence") or {}).get("orders") or []
    result = {
        "status": row.get("status", "pending"),
        "session_day": row.get("session_day"),
        "net_pnl": None,
        "stressed_net_pnl": None,
        "orders_count": len(orders),
        "valid": False,
        "issues": issues,
        "marked_net": None,
    }
    try:
        costs = validate_cost_schedule(binding["costs"])
        validate_cost_dates(costs, [row["session_day"]])
        if (row.get("details") or {}).get("costs") != costs:
            issues.append("The trade cost assumptions differ from this campaign.")
        enrollment = timestamp(registered_at)
        if len(orders) > 64:
            raise ValueError("The trade has more orders than the evidence limit")
        seen = set()
        for order in orders:
            order_id = str(order.get("id") or "")
            if not order_id or order_id in seen:
                raise ValueError("An order is missing its identity or appears more than once")
            seen.add(order_id)
            if order.get("symbol") != (row.get("details") or {}).get("symbol") or order.get(
                "exchange"
            ) != (row.get("details") or {}).get("exchange"):
                raise ValueError("Orders do not belong to the same registered instrument")
            side = str(order.get("action") or "").upper()
            if side not in {"BUY", "SELL"}:
                raise ValueError("An order side is missing")
            status = str(order.get("status") or "").lower()
            if status not in TERMINAL:
                issues.append("An order is still working or its outcome is unknown.")
            qty = decimal_value(order.get("filled_qty"), "Filled quantity")
            requested = decimal_value(
                order.get("qty", order.get("quantity")), "Requested quantity", minimum="0.000001"
            )
            if qty > requested or (status in {"complete", "filled"} and qty != requested):
                issues.append("Filled and requested quantities do not agree.")
            # Rejections/cancellations are visible and disqualifying even when no
            # fill occurred: discarding these would select only successful fills.
            if status in {"rejected", "cancelled"}:
                issues.append("A rejected or cancelled order needs a new campaign.")
            if qty == 0:
                continue
            receipt = quotes.get(order_id)
            if not isinstance(receipt, dict):
                raise ValueError("A filled order has no authenticated quote receipt")
            if receipt.get("error"):
                raise ValueError("The authenticated quote could not be captured")
            if (
                receipt.get("source") != "authenticated_broker"
                or receipt.get("broker") != binding["broker"]
                or receipt.get("broker_connection_id") != binding["broker_connection_id"]
                or (
                    binding.get("broker_account_hash")
                    and receipt.get("broker_account_hash") != binding["broker_account_hash"]
                )
                or receipt.get("symbol") != order.get("symbol")
                or receipt.get("exchange") != order.get("exchange")
                or receipt.get("action") != side
                or decimal_value(receipt.get("quantity"), "Quoted order quantity") != requested
            ):
                raise ValueError("The quote does not match this order and broker account")
            market = timestamp(receipt.get("market_at"))
            captured = timestamp(receipt.get("captured_at"))
            placed = timestamp(order.get("placed_at"))
            filled_at = order.get("filled_at")
            if not filled_at and status not in TERMINAL and row.get("status") != "closed":
                filled_at = row.get("_observed_at")
            filled = timestamp(filled_at)
            # placed_at records the durable intent. Its authenticated quote is
            # captured next, immediately before dispatch.
            if not (enrollment <= placed <= captured <= filled):
                raise ValueError("Quote and fill timestamps do not prove prospective execution")
            if not 0 <= (captured - market).total_seconds() <= POLICY["max_quote_age_seconds"]:
                raise ValueError("The broker quote was stale or its timestamp was in the future")
            if (filled - captured).total_seconds() > POLICY["max_fill_delay_seconds"]:
                raise ValueError("The fill occurred too long after its quote")
            bid = decimal_value(receipt.get("bid"), "Bid", minimum="0.000001")
            ask = decimal_value(receipt.get("ask"), "Ask", minimum="0.000001")
            if ask < bid:
                raise ValueError("The broker quote was crossed")
            depth = decimal_value(
                receipt.get("ask_qty" if side == "BUY" else "bid_qty"), "Quote depth"
            )
            if depth < requested:
                raise ValueError("Quoted liquidity was insufficient for the order")
            actual = decimal_value(order.get("avg_fill_price"), "Filled price", minimum="0.000001")
            price = max(actual, ask) if side == "BUY" else min(actual, bid)
            slip = Decimal(str(costs["slippage_bps"])) / 10000
            direction = 1 if side == "BUY" else -1
            notional = price * (1 + direction * slip) * qty
            stressed = price * (1 + direction * slip * 2) * qty
            net += -direction * notional - order_cost(notional, side, costs)
            stress += -direction * stressed - order_cost(stressed, side, costs) * 2
            if side == "BUY":
                buys += qty
            else:
                sells += qty
        if buys >= sells:
            remaining = buys - sells
            if remaining:
                mark = decimal_value(
                    row["evidence"].get("mark"), "Observed liquidation mark", minimum="0.000001"
                )
                liquidation = mark * remaining * (1 - Decimal(str(costs["slippage_bps"])) / 10000)
                result["marked_net"] = float(
                    net + liquidation - order_cost(liquidation, "SELL", costs)
                )
            elif orders:
                result["marked_net"] = float(net)
            elif not row.get("filled") and row.get("status") in {"pending", "void"}:
                result["marked_net"] = 0.0
        if not orders:
            issues.append("No order outcomes have been recorded yet.")
        if buys != sells or (row.get("status") == "closed" and not buys):
            issues.append("Filled entry and exit quantities are not balanced.")
        if row.get("status") not in {"closed", "void"}:
            issues.append("The position is not resolved.")
        if row.get("status") == "void":
            issues.append("The reserved trade did not complete.")
        if row.get("status") == "closed" and not row.get("filled"):
            issues.append("The ledger does not confirm filled exposure.")
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        result["marked_net"] = None
        issues.append(
            str(exc) if isinstance(exc, ValueError) else "Execution evidence is incomplete."
        )
    result["valid"] = not issues
    if result["valid"]:
        result["net_pnl"] = float(net.quantize(Decimal("0.01")))
        result["stressed_net_pnl"] = float(stress.quantize(Decimal("0.01")))
    return result


def final_screen_passes(run):
    try:
        report = run["report"]
        metrics = report["metrics"]
        return bool(
            run["kind"] == "final"
            and run["status"] == "completed"
            and run.get("frozen_at")
            and report.get("split", {}).get("kind") == "final"
            and not report.get("incomplete_outcomes")
            and int(metrics["trade_count"]) >= POLICY["min_final_trades"]
            and decimal_value(metrics["net_pnl"], "Final net", minimum="0.000001") > 0
        )
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return False


def evaluate_campaign(
    final_run,
    trades,
    *,
    max_drawdown_pct,
    marks_complete,
    risk_breach=False,
    binding_current=True,
    source_current=True,
):
    """Eligibility is fixed policy, not operator-supplied thresholds."""
    closed = [t for t in trades if t.get("valid") and t.get("status") == "closed"]
    values = [Decimal(str(t["net_pnl"])) for t in closed]
    net = sum(values, ZERO)
    stress = sum((Decimal(str(t["stressed_net_pnl"])) for t in closed), ZERO)
    wins = sum((x for x in values if x > 0), ZERO)
    losses = -sum((x for x in values if x < 0), ZERO)
    factor = wins / losses if losses else None
    sessions = len({t["session_day"] for t in closed})
    unresolved = sum(t.get("status") not in {"closed", "void"} for t in trades)
    invalid = sum(not t.get("valid") for t in trades)
    metrics = {
        "session_count": sessions,
        "closed_trade_count": len(closed),
        "net_pnl": float(net),
        "expectancy": float(net / len(closed)) if closed else None,
        "profit_factor": float(factor) if factor is not None else None,
        "profit_factor_unbounded": bool(wins > 0 and losses == 0),
        "stressed_net_pnl": float(stress),
        "max_drawdown_pct": max_drawdown_pct,
        "unresolved_count": unresolved,
        "invalid_count": invalid,
        "risk_breach": risk_breach,
    }
    checks = []

    def check(code, passed, message, actual, required):
        checks.append(
            {
                "code": code,
                "passed": bool(passed),
                "message": message,
                "actual": actual,
                "required": required,
            }
        )

    check(
        "final_screen",
        final_screen_passes(final_run),
        "The sealed final screen must be complete and profitable with at least 20 trades.",
        (final_run.get("report") or {}).get("metrics"),
        "20 trades and positive net result",
    )
    check(
        "sessions",
        sessions >= POLICY["min_sessions"],
        "Collect at least 30 distinct forward trading sessions.",
        sessions,
        POLICY["min_sessions"],
    )
    check(
        "closed_trades",
        len(closed) >= POLICY["min_closed_trades"],
        "Collect at least 100 verified closed Sandbox trades.",
        len(closed),
        POLICY["min_closed_trades"],
    )
    check(
        "expectancy",
        net > 0,
        "Net expectancy must be positive after estimated costs.",
        metrics["expectancy"],
        "> 0",
    )
    check(
        "profit_factor",
        (factor is not None and factor >= Decimal("1.2")) or (wins > 0 and losses == 0),
        "Profit factor must be at least 1.2.",
        metrics["profit_factor"],
        POLICY["min_profit_factor"],
    )
    check(
        "stress",
        stress > 0,
        "Net result must remain positive with doubled fees and adverse slippage.",
        float(stress),
        "> 0",
    )
    check(
        "drawdown",
        marks_complete
        and max_drawdown_pct is not None
        and max_drawdown_pct <= POLICY["max_drawdown_pct"],
        "Marked equity evidence must be complete and observed drawdown at most 15%.",
        max_drawdown_pct,
        POLICY["max_drawdown_pct"],
    )
    check("resolved", unresolved == 0, "Resolve every registered position.", unresolved, 0)
    check(
        "execution",
        invalid == 0 and bool(trades),
        "Every registered order must have valid execution evidence.",
        invalid,
        0,
    )
    check(
        "risk",
        not risk_breach,
        "The campaign must have no risk breach or pause.",
        risk_breach,
        False,
    )
    check(
        "binding",
        binding_current,
        "Strategy, Flow, broker account, source and costs must match this campaign.",
        binding_current,
        True,
    )
    check(
        "source_evidence",
        source_current,
        "Campaign evidence must include every current durable ledger update. Reconcile to recover missing updates.",
        source_current,
        True,
    )
    return {"eligible": all(c["passed"] for c in checks), "checks": checks, "metrics": metrics}
