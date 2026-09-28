"""Pure server-side frozen-model scoring and replay-equivalent entry planning."""

from datetime import datetime, timedelta
from decimal import Decimal
from math import isfinite

from services.research.costs import order_cost
from services.research.dataset import digest
from services.research.ml import (
    ML_FEATURES,
    _require_frame_columns,
    build_opportunities,
    build_underlying_features,
    signal_schedule,
)
from services.research.ml_artifact import predict_probabilities, validate_artifact
from services.research.replay import _tick, research_capital
from services.risk.admission import ML_RISK_RECIPE, planned_entry_risk
from services.risk.budget import BudgetPolicy, evaluate_budget
from services.risk.cash_exit import CASH_RECIPES, recipe_exit, recipe_policy


def validate_completed_rows(rows, now, symbol, *, minutes=1, settle_seconds=5):
    """Require aligned, timezone-aware bar ends with a fresh final close."""
    stamps = []
    for row in rows:
        if row.get("symbol") != symbol:
            continue
        try:
            at = datetime.fromisoformat(row["timestamp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{symbol} has an invalid bar timestamp") from exc
        if at.tzinfo is None or at.utcoffset() != timedelta(hours=5, minutes=30):
            raise ValueError(f"{symbol} bars require IST timestamps")
        elapsed = (now - at).total_seconds()
        if elapsed < settle_seconds:
            raise ValueError(f"{symbol} has a future or incomplete bar")
        stamps.append(at)
    if not stamps:
        raise ValueError(f"{symbol} has no completed bars")
    if stamps != sorted(set(stamps)):
        raise ValueError(f"{symbol} bars are unordered or duplicated")
    today = [at for at in stamps if at.date() == now.date()]
    if not today:
        raise ValueError(f"{symbol} has no current-session bars")
    if (now - today[-1]).total_seconds() > 55:
        raise ValueError(f"{symbol} completed bar is stale")
    if any(
        later - earlier != timedelta(minutes=minutes)
        for earlier, later in zip(today, today[1:], strict=False)
    ):
        raise ValueError(f"{symbol} current-session bars contain a gap")
    return today[-1].isoformat()


def score_observed(data, artifact, costs, *, capital, threshold, now, risk_recipe=ML_RISK_RECIPE):
    """Return the exact scored contract from completed broker bars, or wait."""
    validate_artifact(artifact)
    underlying_symbol = data["metadata"]["underlying_symbol"]
    at = validate_completed_rows(
        data["rows"], now, underlying_symbol, minutes=data["metadata"]["bar_minutes"]
    )
    today = now.date().isoformat()
    for contract in data["metadata"]["contracts"]:
        rows = [
            row
            for row in data["rows"]
            if row["symbol"] == contract["symbol"] and row["timestamp"][:10] == today
        ]
        if rows:
            # A less recent contract can be excluded by the eligibility filter;
            # a candidate for this close must have an exact matching bar.
            if rows[-1]["timestamp"] == at:
                validate_completed_rows(rows, now, contract["symbol"])
    features = build_underlying_features(data)
    opportunities, rejected = build_opportunities(
        data, features, costs, capital=capital, risk_recipe=risk_recipe
    )
    if opportunities.empty:
        raise ValueError(f"No eligible observed option contract at {at}; filters: {rejected}")
    latest = opportunities[opportunities.timestamp == at].copy()
    if latest.empty:
        raise ValueError(f"No eligible observed option contract at {at}; filters: {rejected}")
    scores = predict_probabilities(
        artifact, _require_frame_columns(latest, ML_FEATURES).to_numpy(dtype=float)
    )
    schedule = signal_schedule(latest, scores, threshold)
    choice = schedule.get(at)
    if choice is None:
        raise ValueError(
            f"Frozen model did not exceed its {threshold} probability threshold at {at}"
        )
    selected = next(c for c in data["metadata"]["contracts"] if c["symbol"] == choice["symbol"])
    option_rows = [
        row
        for row in data["rows"]
        if row["symbol"] == choice["symbol"] and row["timestamp"][:10] == today
    ]
    if option_rows[-1]["timestamp"] != at:
        raise ValueError("Scored option contract has no matching completed bar")
    opening = data["metadata"].get("session_open", "09:15")
    first_end = (
        datetime.fromisoformat(f"{today}T{opening}:00+05:30") + timedelta(minutes=1)
    ).isoformat()
    if option_rows[0]["timestamp"] != first_end:
        raise ValueError("Scored option contract is missing the session-opening feature seed")
    validate_completed_rows(option_rows, now, choice["symbol"])
    last = option_rows[-11:]
    if len(last) != 11:
        raise ValueError("Scored option contract lacks volatility warmup")
    atr = (
        sum(
            max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"]))
            for a, b in zip(last[:-1], last[1:], strict=True)
        )
        / 10
    )
    probability = next(
        float(score)
        for row, score in zip(latest.itertuples(index=False), scores, strict=True)
        if row.symbol == choice["symbol"] and row.direction == choice["direction"]
    )
    return {
        **choice,
        "signal_at": at,
        "score": probability,
        "model_hash": digest(artifact),
        "contract": selected,
        "atr": atr,
    }


def entry_plan(
    contract,
    *,
    entry,
    atr,
    costs,
    capital,
    equity=None,
    peak=None,
    day=None,
    ledger=(),
    paused=False,
    risk_recipe=ML_RISK_RECIPE,
    daily_stopped=False,
    day_start_equity=None,
):
    """Use replay's tick, fee, affordability and shared budget math at observed entry."""
    amount = research_capital({"capital": capital})
    equity = Decimal(str(equity if equity is not None else amount))
    peak = Decimal(str(peak if peak is not None else equity))
    if day_start_equity is not None:
        day_start_equity = Decimal(str(day_start_equity))
    day = day or datetime.now().date().isoformat()
    current = risk_recipe in CASH_RECIPES
    policy = recipe_policy(risk_recipe, amount) if current else BudgetPolicy(capital=amount)
    if risk_recipe not in (ML_RISK_RECIPE, *CASH_RECIPES):
        raise ValueError("Frozen ML admission risk recipe changed")
    if not isfinite(float(entry)) or not isfinite(float(atr)) or entry <= 0 or atr < 0:
        raise ValueError("Current option entry or volatility is invalid")
    exact = Decimal(str(entry))
    technical = max(exact * Decimal(".10"), Decimal(str(atr)) * Decimal("1.5"))
    if current:
        stop, target, _ = recipe_exit(exact, technical, contract, risk_recipe)
    else:
        stop = Decimal(str(_tick(exact - technical, contract)))
        target = Decimal(str(_tick(exact + (exact - stop) * 2, contract, up=True)))
    distance = exact - stop
    filter_distance = technical if current else distance
    if not 20 <= entry <= 120 or distance <= 0 or filter_distance > exact * Decimal(".25"):
        raise ValueError("Entry gap violates the premium or volatility filter")
    units_value = contract["lot_size"] * contract["multiplier"]
    if not isfinite(float(units_value)) or units_value <= 0 or int(units_value) != units_value:
        raise ValueError("Scored contract has no valid whole lot")
    units = int(units_value)
    admitted = None
    max_lots = min(
        10000, int((min(equity, amount) * (1 - policy.cash_buffer_pct)) / (exact * units))
    )
    if current:
        max_lots = min(max_lots, 1)
    for lots in range(1, max_lots + 1):
        quantity_units = units * lots
        debit = exact * quantity_units
        entry_fee = order_cost(debit, "BUY", costs)
        if debit + entry_fee > min(equity, amount) * (1 - policy.cash_buffer_pct):
            break
        planned = planned_entry_risk(distance * quantity_units, debit, costs)
        decision = evaluate_budget(
            policy,
            ledger,
            day,
            equity,
            peak,
            planned,
            paused=paused,
            proposed_gross_risk=distance * quantity_units if current else None,
            daily_stopped=daily_stopped,
            day_start_equity=day_start_equity,
        )
        if not decision.allowed:
            break
        admitted = (lots, planned, decision.bucket)
    if admitted is None:
        raise ValueError("No whole lot fits the shared cash, risk or drawdown budget")
    lots, planned, bucket = admitted
    return {
        "symbol": contract["symbol"],
        "lots": lots,
        "quantity": lots * contract["lot_size"],
        "stop_price": float(stop),
        "target_price": float(target),
        "sl_pts": float(distance),
        "target_pts": float(target - exact),
        "planned_risk": float(planned),
        "gross_planned_risk": float(distance * units * lots),
        "budget_bucket": bucket,
    }
