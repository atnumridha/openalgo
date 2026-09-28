"""Closed-bar rule screening on real option candles, with conservative fills."""

import random
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from services.research.analytics import session_analytics
from services.research.costs import (
    decimal_value,
    order_cost,
    validate_cost_dates,
    validate_cost_schedule,
)
from services.research.dataset import digest
from services.risk import BreachReason, PositionRisk, evaluate_position
from services.risk.admission import ML_RISK_RECIPE, planned_entry_risk
from services.risk.budget import (
    SHARED_POLICY_VERSIONS,
    BudgetPolicy,
    BudgetTrade,
    budget_snapshot,
    evaluate_budget,
)
from services.risk.cash_exit import (
    CASH_RECIPES,
    CASH_RISK_RECIPE,
    current_configuration,
    pacing_config,
    recipe_exit,
    recipe_policy,
)
from services.risk.profit_exit import (
    PROFIT_RECIPE,
    PROFIT_RECIPES,
    profit_config,
    profit_open,
    profit_reason,
)

LEGACY_DEFAULTS = {
    "lookback": 20,
    "stop_pct": 0.10,
    "target_pct": 0.20,
    "volume_ratio": 1.2,
    "pullback_tolerance": 0.002,
}
DEFAULTS = LEGACY_DEFAULTS | {"target_pct": 0.30}
CANDIDATES = [
    {
        "id": "trend_breakout_filtered",
        "name": "Filtered breakout · minute execution",
        "description": "Prior-bar trend confirmation, non-expiry options, liquidity and affordability filters, one-lot technical stops admitted within the all-in equity risk limit, a rising profit stop with no hard target and a 5-minute cooldown. Research hypothesis, not proven profitable.",
        "defaults": DEFAULTS,
    },
    {
        "id": "trend_breakout",
        "name": "Trend and breakout",
        "description": "Close breaks the previous N-bar range in the direction of a rising or falling N-bar mean.",
        "defaults": DEFAULTS,
    },
    {
        "id": "vwap_pullback",
        "name": "Trend, VWAP pullback and volume",
        "description": "Trend-aligned reclaim of session VWAP with volume at least the configured multiple of the previous N-bar mean.",
        "defaults": DEFAULTS,
    },
]
ENGINE_VERSION = "closed-bar-profit-lock-v6"
FILTER_RULES = {
    "fast_bars": 8,
    "slow_bars": 21,
    "slope_bars": 5,
    "cooldown_minutes": 15,
    "daily_trade_cap": 3,
    "min_expiry_days": 1,
    "max_expiry_days": 7,
    "min_premium": 20,
    "max_premium": 120,
    "max_strike_distance": 500,
    "min_volume_lots": 10,
    "atr_bars": 10,
    "atr_multiple": 1.5,
    "max_stop_pct": 0.25,
}


class Cancelled(Exception):
    pass


def research_capital(config):
    """Legacy stored configurations predate the explicit capital input."""
    value = config.get("capital", 10000)
    amount = decimal_value(value, "capital", minimum=1, maximum=1000000000)
    if amount != amount.to_integral_value():
        raise ValueError("capital must be a whole rupee amount")
    return amount


def validate_configuration(
    data,
    candidate,
    parameters,
    costs,
    seed=42,
    *,
    capital=25000,
    cooldown_minutes=5,
    policy_version=None,
    risk_recipe=None,
):
    if candidate not in {c["id"] for c in CANDIDATES}:
        raise ValueError("Select a supported deterministic candidate")
    if not isinstance(parameters, dict) or set(parameters) - set(DEFAULTS):
        raise ValueError("Unknown rule parameters")
    legacy = policy_version == BudgetPolicy().version
    if policy_version not in (None, BudgetPolicy().version, *SHARED_POLICY_VERSIONS):
        raise ValueError("Unsupported risk policy version")
    selected_recipe = (
        risk_recipe
        if risk_recipe is not None
        else (PROFIT_RECIPE if policy_version == "shared-300-3r-v1" else
              "one-lot-technical-profit-lock-v4" if policy_version == "equity-1pct-v2" else CASH_RISK_RECIPE)
    )
    selected_policy = policy_version or recipe_policy(selected_recipe).version
    if legacy and risk_recipe is not None:
        raise ValueError("Legacy policy cannot bind a whole-lot risk recipe")
    if not legacy and recipe_policy(selected_recipe).version != selected_policy:
        raise ValueError("Risk recipe and risk policy must be bound together")
    params = (LEGACY_DEFAULTS if legacy else DEFAULTS) | parameters
    pace = pacing_config(cooldown_minutes)
    for key, (minimum, maximum) in {
        "lookback": (2, 200),
        "stop_pct": (0.001, 0.9),
        "target_pct": (0.001, 5),
        "volume_ratio": (0.01, 10),
        "pullback_tolerance": (0, 0.05),
    }.items():
        params[key] = float(decimal_value(params[key], key, minimum=minimum, maximum=maximum))
    if not legacy and Decimal(str(params["target_pct"])) != Decimal(str(params["stop_pct"])) * 3:
        raise ValueError("Current cash recipe requires exactly 3R before charges")
    if params["lookback"] != int(params["lookback"]):
        raise ValueError("lookback must be a whole number")
    params["lookback"] = int(params["lookback"])
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("seed must be a whole number between 0 and 4294967295")
    schedule = validate_cost_schedule(costs)
    validated_capital = research_capital({"capital": capital})
    if not legacy and any(not c.get("tick_size") for c in data["metadata"]["contracts"]):
        raise ValueError("Cash stop requires explicit contract tick_size")
    if candidate == "trend_breakout_filtered":
        if data["metadata"].get("execution_bar_minutes", data["metadata"]["bar_minutes"]) != 1:
            raise ValueError("Filtered breakout requires one-minute option execution bars")
        if any(not c.get("tick_size") for c in data["metadata"]["contracts"]):
            raise ValueError("Filtered breakout requires explicit contract tick_size")
    validate_cost_dates(schedule, data["sessions"])
    if schedule.get("exchange") and any(
        contract["exchange"] != schedule["exchange"] for contract in data["metadata"]["contracts"]
    ):
        raise ValueError("Cost schedule exchange must match every dataset contract")
    if candidate == "vwap_pullback" and any(
        row["volume"] is None
        for row in data["rows"]
        if row["symbol"] == data["metadata"]["underlying_symbol"]
    ):
        raise ValueError(
            "VWAP candidate requires observed underlying volume on every bar; index volume cannot be invented"
        )
    if candidate == "vwap_pullback":
        opening = data["metadata"].get("session_open")
        if opening is None:
            raise ValueError(
                "VWAP candidate requires explicit metadata session_open; no opening time is assumed"
            )
        first_bars = {}
        for row in data["rows"]:
            if row["symbol"] == data["metadata"]["underlying_symbol"]:
                first_bars.setdefault(row["timestamp"][:10], row["timestamp"])
        for day in data["sessions"]:
            expected = datetime.fromisoformat(f"{day}T{opening}:00+05:30") + timedelta(
                minutes=data["metadata"]["bar_minutes"]
            )
            if first_bars.get(day) != expected.isoformat():
                raise ValueError(
                    f"Incomplete underlying session {day}: session VWAP requires its first closed bar at {expected.isoformat()}"
                )
    return {
        "candidate": candidate,
        "parameters": params,
        "costs": schedule,
        "seed": seed,
        "engine_version": (
            "closed-bar-rules-v2"
            if legacy
            else (
                "closed-bar-profit-trail-v4"
                if selected_policy == "shared-300-3r-v1"
                else ENGINE_VERSION
            )
        ),
        **(
            {}
            if legacy
            else {
                "risk_policy_version": selected_policy,
                "risk_recipe": selected_recipe,
                "pacing": pace,
                "max_hold_minutes": 15,
            }
        ),
        "dataset_hash": data["content_hash"],
        "capital": int(validated_capital),
        **(
            {
                "filters": {
                    k: v
                    for k, v in FILTER_RULES.items()
                    if legacy or k not in ("cooldown_minutes", "daily_trade_cap")
                }
            }
            if candidate == "trend_breakout_filtered"
            else {}
        ),
    }


def _signal(history, candidate, params):
    n = params["lookback"]
    if len(history) <= n:
        return None
    current, previous = history[-1], history[-n - 1 : -1]
    mean = sum(row["close"] for row in previous) / n
    shifted_mean = sum(row["close"] for row in history[-n:]) / n
    rising = shifted_mean > mean
    falling = shifted_mean < mean
    if candidate == "trend_breakout_filtered":
        rules = FILTER_RULES
        prior = history[:-1]
        if len(prior) < rules["slow_bars"] + rules["slope_bars"]:
            return None
        fast = sum(r["close"] for r in prior[-rules["fast_bars"] :]) / rules["fast_bars"]
        slow = sum(r["close"] for r in prior[-rules["slow_bars"] :]) / rules["slow_bars"]
        older = prior[-rules["slow_bars"] - rules["slope_bars"] : -rules["slope_bars"]]
        old_slow = sum(r["close"] for r in older) / rules["slow_bars"]
        rising, falling = fast > slow > old_slow, fast < slow < old_slow
    if candidate in ("trend_breakout", "trend_breakout_filtered"):
        if rising and current["close"] > max(row["high"] for row in previous):
            return "CE"
        if falling and current["close"] < min(row["low"] for row in previous):
            return "PE"
        return None
    volume = sum(row["volume"] for row in history)
    baseline_volume = sum(row["volume"] for row in previous) / n
    if (
        not volume
        or not baseline_volume
        or current["volume"] < baseline_volume * params["volume_ratio"]
    ):
        return None
    vwap = (
        sum((row["high"] + row["low"] + row["close"]) / 3 * row["volume"] for row in history)
        / volume
    )
    tolerance = params["pullback_tolerance"]
    if (
        rising
        and current["low"] <= vwap * (1 + tolerance)
        and current["close"] > vwap
        and current["close"] > current["open"]
    ):
        return "CE"
    if (
        falling
        and current["high"] >= vwap * (1 - tolerance)
        and current["close"] < vwap
        and current["close"] < current["open"]
    ):
        return "PE"
    return None


def _tick(price, contract, *, up=False):
    tick = contract.get("tick_size")
    if not tick:
        return float(price)
    step = Decimal(str(tick))
    return float(
        (Decimal(str(price)) / step).to_integral_value(
            rounding=ROUND_CEILING if up else ROUND_FLOOR
        )
        * step
    )


def _slipped(price, slip, contract, *, buy=False):
    factor = Decimal(1) + Decimal(str(slip)) * (1 if buy else -1)
    return _tick(Decimal(str(price)) * factor, contract, up=buy)


def _filtered_contract(
    contracts,
    bars,
    option_history,
    underlying,
    direction,
    day,
    equity,
    policy,
    costs,
    slip,
    rejections,
):
    """Choose from quotes available at the signal; never consult the next candle."""
    rules = FILTER_RULES
    choices = sorted(
        (c for c in contracts if c["option_type"] == direction),
        key=lambda c: (c["expiry"], abs(c["strike"] - underlying["close"]), c["symbol"]),
    )
    for contract in choices:
        quote = bars.get(contract["symbol"])
        if quote is None:
            continue
        dte = (datetime.fromisoformat(contract["expiry"]) - datetime.fromisoformat(day)).days
        reason = None
        units = contract["lot_size"] * contract["multiplier"]
        if not rules["min_expiry_days"] <= dte <= rules["max_expiry_days"]:
            reason = "expiry_filter"
        elif abs(contract["strike"] - underlying["close"]) > rules["max_strike_distance"]:
            reason = "strike_distance_filter"
        elif not rules["min_premium"] <= quote["close"] <= rules["max_premium"]:
            reason = "premium_filter"
        elif quote["volume"] is None or quote["volume"] < rules["min_volume_lots"] * units:
            reason = "liquidity_filter"
        observed = list(option_history[contract["symbol"]])
        if reason is None and len(observed) < rules["atr_bars"] + 1:
            reason = "missing_volatility_history"
        if reason:
            rejections[reason] += 1
            continue
        atr = (
            sum(
                max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"]))
                for a, b in zip(observed, observed[1:], strict=False)
            )
            / rules["atr_bars"]
        )
        if atr * rules["atr_multiple"] > quote["close"] * rules["max_stop_pct"]:
            rejections["volatility_filter"] += 1
            continue
        estimated = _slipped(quote["close"], slip, contract, buy=True)
        premium = Decimal(str(estimated * units))
        if premium + order_cost(premium, "BUY", costs) > min(equity, policy.capital) * (
            1 - policy.cash_buffer_pct
        ):
            rejections["unaffordable_signal_quote"] += 1
            continue
        return contract, atr
    return None, None


def _metrics(trades, initial=10000):
    net = [trade["net_pnl"] for trade in trades]
    wins, losses = sum(x for x in net if x > 0), -sum(x for x in net if x < 0)
    equity = peak = initial
    dd = streak = max_streak = 0
    for pnl in net:
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, (peak - equity) / peak * 100)
        streak = streak + 1 if pnl < 0 else 0
        max_streak = max(max_streak, streak)
    return {
        "trade_count": len(net),
        "net_pnl": round(sum(net), 2),
        "expectancy": round(sum(net) / len(net), 2) if net else None,
        "profit_factor": round(wins / losses, 4) if losses else None,
        "profit_factor_unbounded": bool(wins and not losses),
        "max_drawdown_pct": round(dd, 4),
        "max_losing_streak": max_streak,
        "win_rate": round(sum(x > 0 for x in net) / len(net) * 100, 2) if net else None,
        "ending_equity": round(equity, 2),
    }


def _liquidation_equity(active, price, equity, costs, slippage):
    exit_price = _slipped(price, slippage, active["contract"])
    gross = Decimal(str((exit_price - active["entry_price"]) * active["units"]))
    return (
        equity
        + gross
        - active["entry_fees"]
        - order_cost(Decimal(str(exit_price * active["units"])), "SELL", costs)
    )


def _drawdown_breached(policy, day, marked_equity, peak):
    # Entry reservations do not reduce marked equity twice. All actual fee and
    # liquidation assumptions already reach this pure shared-policy decision.
    return budget_snapshot(policy, (), day, marked_equity, peak)["paused"]


def _drawdown_exit_price(active, bar, equity, peak, policy, day, costs, slippage):
    """Find the crossed net-equity boundary without duplicating budget rules."""
    lower, upper = bar["low"], bar["open"]
    for _ in range(48):
        middle = (lower + upper) / 2
        mark = _liquidation_equity(active, middle, equity, costs, slippage)
        if _drawdown_breached(policy, day, mark, peak):
            lower = middle
        else:
            upper = middle
    return lower


def _report_budget_snapshot(policy, ledger, day, equity, peak, day_start_equity):
    snapshot = budget_snapshot(policy, ledger, day, equity, peak, day_start_equity=day_start_equity)
    if policy.version not in {"equity-1pct-v2", "fixed-300-v3"}:
        # Additive live-account diagnostics must not rewrite sealed old reports.
        for key in (
            "daily_limit",
            "day_start_equity",
            "risk_reduced",
            "drawdown_pct",
            "position_count",
        ):
            snapshot.pop(key, None)
        if policy.version == "two-bucket-v1":
            for key in ("policy_version", "per_trade_limit"):
                snapshot.pop(key, None)
    return snapshot


def run_replay(
    data, config, sessions=None, check_cancel=None, stress=False, *, research_signals=None
):
    """One serial portfolio; long options only. Never synthesizes option bars."""
    max_hold_minutes = config.get("max_hold_minutes")
    if max_hold_minutes is not None and (
        type(max_hold_minutes) is not int or max_hold_minutes not in (5, 10, 15)
    ):
        raise ValueError("Research holding time must be 5, 10 or 15 minutes")
    current = current_configuration(config)
    pace = config["pacing"] if current else FILTER_RULES
    risk_recipe = config.get("risk_recipe")
    if risk_recipe is not None and (
        risk_recipe not in (ML_RISK_RECIPE, *CASH_RECIPES)
        or (risk_recipe == ML_RISK_RECIPE and config["candidate"] != "trend_breakout_filtered")
    ):
        raise ValueError("Unsupported ML admission risk recipe")
    if research_signals is None and "research_signal_hash" in config:
        raise ValueError("The recorded research signal schedule is required")
    if research_signals is not None:
        if not isinstance(research_signals, dict) or len(research_signals) > 100000:
            raise ValueError("Research signal schedule must be a bounded mapping")
        if config.get("research_signal_hash") != digest(research_signals):
            raise ValueError("Research signal hash differs from the recorded schedule")
        observed = {
            row["timestamp"]
            for row in data["rows"]
            if row["symbol"] == data["metadata"]["underlying_symbol"]
        }
        contracts_by_symbol = {c["symbol"]: c for c in data["metadata"]["contracts"]}
        for at, choice in research_signals.items():
            direction = choice.get("direction") if isinstance(choice, dict) else choice
            if at not in observed or direction not in ("CE", "PE"):
                raise ValueError(
                    "Research direction must reference an observed closed underlying bar"
                )
            if isinstance(choice, dict):
                symbol = choice.get("symbol")
                if (
                    set(choice) != {"direction", "symbol"}
                    or not isinstance(symbol, str)
                    or symbol not in contracts_by_symbol
                    or contracts_by_symbol[symbol]["option_type"] != direction
                ):
                    raise ValueError(
                        "Research schedule must bind the scored contract and direction"
                    )
            elif "research_model_hash" in config:
                raise ValueError("Model schedule must bind the scored contract")
    allowed = set(sessions if sessions is not None else data["sessions"])
    meta, params, costs = data["metadata"], config["parameters"], dict(config["costs"])
    if stress:
        costs["slippage_bps"] = min(1000, costs["slippage_bps"] * 2 + 10)
        costs["brokerage_per_order"] *= 1.5
    by_time = defaultdict(dict)
    for row in data["rows"]:
        if row["timestamp"][:10] in allowed:
            by_time[row["timestamp"]][row["symbol"]] = row
    bar_delta = timedelta(minutes=meta["bar_minutes"])
    execution_minutes = meta.get("execution_bar_minutes", meta["bar_minutes"])
    execution_delta = timedelta(minutes=execution_minutes)
    filtered = config["candidate"] == "trend_breakout_filtered"
    option_history = defaultdict(lambda: deque(maxlen=FILTER_RULES["atr_bars"] + 1))
    last_exit = None
    daily_entries = 0
    initial_capital = research_capital(config)
    policy, ledger = (
        (
            recipe_policy(risk_recipe, initial_capital)
            if current
            else BudgetPolicy(capital=initial_capital)
        ),
        [],
    )
    equity = peak = day_start_equity = initial_capital
    history, trades, rejections = [], [], Counter()
    underlying_session_complete = True
    active = pending = None
    prior_day = None
    incomplete = []
    max_open_drawdown = 0.0
    drawdown_paused = False
    exposure_bars = 0
    slip = costs["slippage_bps"] / 10000
    for count, (at, bars) in enumerate(sorted(by_time.items())):
        if check_cancel and count % 100 == 0:
            check_cancel()
        day = at[:10]
        if day != prior_day:
            history = []
            option_history.clear()
            last_exit, daily_entries = None, 0
            underlying_session_complete = True
            if active:
                incomplete.append(
                    {
                        "symbol": active["contract"]["symbol"],
                        "signal_at": active["signal_at"],
                        "reason": "missing_session_close",
                    }
                )
                break
            pending = None
            prior_day = day
            day_start_equity = equity
        if pending and at >= pending["entry_bar_at"]:
            contract = pending["contract"]
            bar = bars.get(contract["symbol"]) if at == pending["entry_bar_at"] else None
            if bar is None:
                rejections["missing_next_option_bar"] += 1
            else:
                entry = _slipped(bar["open"], slip, contract, buy=True)
                exact_entry = Decimal(str(entry))
                distance = exact_entry * Decimal(str(params["stop_pct"]))
                if filtered:
                    distance = max(
                        distance,
                        Decimal(str(pending["signal_atr"]))
                        * Decimal(str(FILTER_RULES["atr_multiple"])),
                    )
                stop = _tick(exact_entry - distance, contract)
                exact_distance = exact_entry - Decimal(str(stop))
                target = _tick(
                    (
                        exact_entry
                        + exact_distance
                        * Decimal(str(params["target_pct"]))
                        / Decimal(str(params["stop_pct"]))
                    )
                    if filtered
                    else exact_entry * (1 + Decimal(str(params["target_pct"]))),
                    contract,
                    up=True,
                )
                if current:
                    try:
                        stop, target, _ = recipe_exit(exact_entry, distance, contract, risk_recipe)
                        exact_distance = exact_entry - stop
                        stop, target = float(stop), float(target)
                    except ValueError:
                        rejections["invalid_cash_stop_tick"] += 1
                        pending = None
                        continue
                entry_gap = filtered and (
                    not FILTER_RULES["min_premium"] <= entry <= FILTER_RULES["max_premium"]
                    or (distance if current else exact_distance)
                    > exact_entry * Decimal(str(FILTER_RULES["max_stop_pct"]))
                )
                lot_units = contract["lot_size"] * contract["multiplier"]
                one_premium = Decimal(str(entry * lot_units))
                max_lots = int(
                    (min(equity, policy.capital) * (1 - policy.cash_buffer_pct)) / one_premium
                )
                if entry_gap:
                    max_lots = 0
                if current:
                    max_lots = min(max_lots, 1)
                admitted = None
                rejected_code = "budget_or_drawdown_limit"
                low_lots, high_lots = 1, min(max_lots, 10000)
                while low_lots <= high_lots:
                    lots = (low_lots + high_lots) // 2
                    units = lot_units * lots
                    entry_fees = order_cost(Decimal(str(entry * units)), "BUY", costs)
                    if risk_recipe in (ML_RISK_RECIPE, *CASH_RECIPES):
                        planned = planned_entry_risk(
                            exact_distance * Decimal(str(units)), Decimal(str(entry * units)), costs
                        )
                    else:
                        planned_exit = _slipped(stop, slip, contract)
                        planned = (
                            Decimal(str((entry - planned_exit) * units))
                            + entry_fees
                            + order_cost(Decimal(str(planned_exit * units)), "SELL", costs)
                        )
                    if Decimal(str(entry * units)) + entry_fees > min(equity, policy.capital) * (
                        1 - policy.cash_buffer_pct
                    ):
                        high_lots = lots - 1
                        continue
                    decision = evaluate_budget(
                        policy,
                        ledger,
                        day,
                        equity,
                        peak,
                        planned,
                        paused=drawdown_paused,
                        day_start_equity=day_start_equity,
                        proposed_gross_risk=exact_distance * Decimal(str(units))
                        if current
                        else None,
                    )
                    if decision.allowed:
                        admitted = (lots, units, entry_fees, planned, decision.bucket)
                        low_lots = lots + 1
                    else:
                        rejected_code = decision.code if current else "budget_or_drawdown_limit"
                        high_lots = lots - 1
                if admitted:
                    daily_entries += 1
                    lots, units, entry_fees, planned, bucket = admitted
                    active = {
                        **pending,
                        "entry_price": entry,
                        "quantity": lots * contract["lot_size"],
                        "units": units,
                        "entry_fees": entry_fees,
                        "planned": planned,
                        "bucket": bucket,
                        "last_bar_at": at,
                        "initial_stop": stop,
                        "target_milestone": target,
                        "profit_protection": profit_config(contract, costs, recipe=risk_recipe)
                        if risk_recipe in PROFIT_RECIPES
                        else None,
                        "risk": PositionRisk(
                            entry_price=entry,
                            quantity=units,
                            stop_price=stop,
                            target_price=target,
                        ),
                    }
                else:
                    rejections[
                        "entry_gap_filter"
                        if entry_gap
                        else ("unaffordable_whole_lot" if max_lots < 1 else rejected_code)
                    ] += 1
            pending = None
        if active:
            bar = bars.get(active["contract"]["symbol"])
            expected = (datetime.fromisoformat(active["last_bar_at"]) + execution_delta).isoformat()
            if at != active["entry_bar_at"] and (at > expected or (at == expected and bar is None)):
                incomplete.append(
                    {
                        "symbol": active["contract"]["symbol"],
                        "reason": "missing_option_bar_during_exposure",
                    }
                )
                break
            if bar and at[11:16] > meta["session_close"]:
                incomplete.append(
                    {"symbol": active["contract"]["symbol"], "reason": "missing_session_close"}
                )
                break
            if bar:
                active["last_bar_at"] = at
                exposure_bars += 1
                risk = active["risk"]
                opening_mark = _liquidation_equity(active, bar["open"], equity, costs, slip)
                peak = max(peak, opening_mark)
                max_open_drawdown = max(
                    max_open_drawdown, float((peak - opening_mark) / peak * 100)
                )
                exit_price = reason = None
                ambiguous_exit = False
                protection = active["profit_protection"]
                if protection:
                    risk, opening = profit_open(risk, bar["open"], protection)
                    active["risk"] = risk
                else:
                    opening = evaluate_position(risk, bar["open"])
                if opening.reason == BreachReason.STOP:
                    exit_price, reason = (
                        bar["open"],
                        profit_reason(risk) if protection else "stop_loss",
                    )
                elif _drawdown_breached(policy, day, opening_mark, peak):
                    exit_price, reason = bar["open"], "portfolio_drawdown"
                elif opening.reason == BreachReason.TARGET:
                    exit_price, reason = bar["open"], "target"
                else:
                    low_mark = _liquidation_equity(active, bar["low"], equity, costs, slip)
                    if evaluate_position(risk, bar["low"]).reason == BreachReason.STOP:
                        exit_price, reason = (
                            risk.stop_price,
                            profit_reason(risk) if protection else "stop_loss",
                        )
                    if _drawdown_breached(policy, day, low_mark, peak):
                        drawdown_price = _drawdown_exit_price(
                            active, bar, equity, peak, policy, day, costs, slip
                        )
                        # On a declining path the higher protective threshold
                        # is crossed first. Do not use a low reached after exit.
                        if exit_price is None or drawdown_price >= exit_price:
                            exit_price, reason = drawdown_price, "portfolio_drawdown"
                    ambiguous_exit = bool(
                        reason
                        and risk.target_price is not None
                        and bar["high"] >= risk.target_price
                    )
                    if reason is None:
                        max_open_drawdown = max(
                            max_open_drawdown, float((peak - low_mark) / peak * 100)
                        )
                        if evaluate_position(risk, bar["high"]).reason == BreachReason.TARGET:
                            exit_price, reason = risk.target_price, "target"
                        elif max_hold_minutes is not None and datetime.fromisoformat(
                            at
                        ) >= datetime.fromisoformat(active["signal_at"]) + timedelta(
                            minutes=max_hold_minutes
                        ):
                            exit_price, reason = bar["close"], "time_limit"
                        elif at[11:16] >= meta["session_close"]:
                            exit_price, reason = bar["close"], "session_close"
                if protection and reason is None:
                    risk, closing = profit_open(risk, bar["close"], protection)
                    active["risk"] = risk
                    if closing.breached:
                        exit_price, reason = bar["close"], profit_reason(risk)
                if reason:
                    exit_mark = _liquidation_equity(active, exit_price, equity, costs, slip)
                    max_open_drawdown = max(
                        max_open_drawdown, float((peak - exit_mark) / peak * 100)
                    )
                    drawdown_paused = (
                        drawdown_paused
                        or reason == "portfolio_drawdown"
                        or _drawdown_breached(policy, day, exit_mark, peak)
                    )
                else:
                    # Opens and closes have known order. An OHLC high cannot
                    # prove a new peak happened before the same candle's low.
                    close_mark = _liquidation_equity(active, bar["close"], equity, costs, slip)
                    peak = max(peak, close_mark)
                if reason:
                    exit_price = _slipped(exit_price, slip, active["contract"])
                    gross = Decimal(str((exit_price - active["entry_price"]) * active["units"]))
                    charges = active["entry_fees"] + order_cost(
                        Decimal(str(exit_price * active["units"])), "SELL", costs
                    )
                    net = (gross - charges).quantize(Decimal("0.01"))
                    trade = {
                        key: active[key]
                        for key in ("signal_at", "entry_bar_at", "quantity", "entry_price")
                    }
                    trade.update(
                        symbol=active["contract"]["symbol"],
                        expiry=active["contract"]["expiry"],
                        lot_size=active["contract"]["lot_size"],
                        multiplier=active["contract"]["multiplier"],
                        exit_at=at,
                        exit_price=exit_price,
                        gross_pnl=float(gross.quantize(Decimal("0.01"))),
                        costs=float(charges),
                        net_pnl=float(net),
                        exit_reason=reason,
                        planned_risk=float(active["planned"]),
                        gross_planned_risk=float(
                            (
                                Decimal(str(active["entry_price"]))
                                - Decimal(str(active["initial_stop"]))
                            )
                            * Decimal(str(active["units"]))
                        ),
                        completion_sequence=len(trades) + 1,
                        completion_day=day,
                        budget_bucket=active["bucket"],
                        ambiguous_exit=ambiguous_exit,
                        stop_price=active["initial_stop"],
                        final_stop_price=risk.stop_price,
                        target_price=active["target_milestone"],
                    )
                    trade["risk_reserve_headroom"] = (
                        trade["planned_risk"] - trade["gross_planned_risk"]
                    )
                    trades.append(trade)
                    ledger.append(
                        BudgetTrade(
                            str(len(trades)),
                            day,
                            active["bucket"],
                            "closed",
                            active["planned"],
                            net_pnl=net,
                            filled=True,
                            close_sequence=len(trades),
                            completion_day=day,
                        )
                    )
                    equity += net
                    peak = max(peak, equity)
                    trade["budget_after_close"] = {
                        k: float(v) if isinstance(v, Decimal) else v
                        for k, v in _report_budget_snapshot(
                            policy, ledger, day, equity, peak, day_start_equity
                        ).items()
                    }
                    active = None
                    last_exit = datetime.fromisoformat(at)
                    if len(trades) >= 5000:
                        incomplete.append({"reason": "trade_limit_reached"})
                        break
        if filtered:
            for symbol, row in bars.items():
                if symbol == meta["underlying_symbol"]:
                    continue
                observed = option_history[symbol]
                if (
                    observed
                    and datetime.fromisoformat(at)
                    - datetime.fromisoformat(observed[-1]["timestamp"])
                    != execution_delta
                ):
                    observed.clear()
                observed.append(row)
        underlying = bars.get(meta["underlying_symbol"])
        if underlying:
            if (
                history
                and datetime.fromisoformat(at) - datetime.fromisoformat(history[-1]["timestamp"])
                != bar_delta
            ):
                history = []
                underlying_session_complete = False
                rejections["underlying_bar_gap"] += 1
            history.append(underlying)
            choice = research_signals.get(at) if research_signals is not None else None
            scored_symbol = choice["symbol"] if isinstance(choice, dict) else None
            direction = (
                (
                    (choice["direction"] if isinstance(choice, dict) else choice)
                    if research_signals is not None
                    else _signal(history, config["candidate"], params)
                )
                if underlying_session_complete or config["candidate"] != "vwap_pullback"
                else None
            )
            if direction and not active and not pending:
                contracts = (
                    [c for c in meta["contracts"] if c["symbol"] == scored_symbol]
                    if scored_symbol is not None
                    else meta["contracts"]
                )
                entry_at = (datetime.fromisoformat(at) + execution_delta).isoformat()
                if entry_at[:10] != day or entry_at[11:16] >= meta["session_close"]:
                    rejections["after_entry_cutoff"] += 1
                    continue
                if filtered or current:
                    if (
                        pace["daily_trade_cap"] is not None
                        and daily_entries >= pace["daily_trade_cap"]
                    ):
                        rejections["daily_trade_cap"] += 1
                        continue
                    if last_exit and datetime.fromisoformat(at) - last_exit < timedelta(
                        minutes=pace["cooldown_minutes"]
                    ):
                        rejections["cooldown"] += 1
                        continue
                if filtered:
                    contract, atr = _filtered_contract(
                        contracts,
                        bars,
                        option_history,
                        underlying,
                        direction,
                        day,
                        equity,
                        policy,
                        costs,
                        slip,
                        rejections,
                    )
                    if contract is None:
                        rejections["no_eligible_observed_contract"] += 1
                        continue
                    pending = {
                        "contract": contract,
                        "signal_at": at,
                        "entry_bar_at": entry_at,
                        "signal_atr": atr,
                    }
                    continue
                eligible = [
                    c for c in contracts if c["option_type"] == direction and c["expiry"] >= day
                ]
                eligible.sort(
                    key=lambda c: (c["expiry"], abs(c["strike"] - underlying["close"]), c["symbol"])
                )
                if not eligible:
                    rejections["missing_point_in_time_contract"] += 1
                    continue
                contract = eligible[0]
                if contract["symbol"] not in by_time.get(entry_at, {}):
                    rejections["missing_next_option_bar"] += 1
                    continue
                if contract["symbol"] not in bars:
                    rejections["missing_signal_option_quote"] += 1
                    continue
                pending = {"contract": contract, "signal_at": at, "entry_bar_at": entry_at}
    if active and not incomplete:
        incomplete.append(
            {"symbol": active["contract"]["symbol"], "reason": "missing_session_close"}
        )
    if check_cancel:
        check_cancel()
    metrics = _metrics(trades, initial=float(initial_capital))
    metrics["initial_capital"] = int(initial_capital)
    metrics["closed_trade_max_drawdown_pct"] = metrics["max_drawdown_pct"]
    metrics["max_drawdown_pct"] = round(max_open_drawdown, 4)
    metrics["max_observed_open_drawdown_pct"] = round(max_open_drawdown, 4)
    metrics["peak_equity"] = float(peak.quantize(Decimal("0.01")))
    metrics["drawdown_paused"] = drawdown_paused
    if current:
        metrics["daily_stop_count"] = len(
            {t["completion_day"] for t in trades if t["budget_after_close"]["daily_stopped"]}
        )
        metrics["max_daily_losing_streak"] = max(
            (t["budget_after_close"]["consecutive_losses"] for t in trades), default=0
        )
    metrics["equity_mark_convention"] = (
        "Net liquidation equity at observed opens/closes; adverse lows use the previously observed peak."
    )
    metrics["exposure_bars"] = exposure_bars
    metrics["signal_bar_minutes"] = meta["bar_minutes"]
    metrics["execution_bar_minutes"] = execution_minutes
    metrics["ambiguous_exit_count"] = sum(t["ambiguous_exit"] for t in trades)
    if incomplete:
        metrics["realized_net_pnl"] = metrics["net_pnl"]
        metrics["net_pnl"] = None
        metrics["ending_equity"] = None
        metrics["expectancy"] = None
        metrics["profit_factor"] = None
        metrics["profit_factor_unbounded"] = False
        metrics["win_rate"] = None
    reasons = [
        "Candle screening cannot establish executable bid/ask spreads, market depth, latency or partial fills.",
        "Verified forward Sandbox evidence and explicit release review are required.",
    ]
    if incomplete:
        reasons.append("Incomplete position outcomes make this replay unqualified.")
    if metrics["ambiguous_exit_count"]:
        reasons.append(
            "Some candles touched both protective exit and target; stop-first results are conservative assumptions, not observed order."
        )
    return {
        "risk_policy_version": policy.version,
        "pacing": dict(pace),
        "metrics": metrics,
        "session_analytics": session_analytics(
            {"trades": trades, "incomplete_outcomes": incomplete},
            allowed,
            initial=float(initial_capital),
        ),
        "trades": trades,
        "rejections": dict(rejections),
        "incomplete_outcomes": incomplete,
        "configuration_hash": digest(config),
        "qualification": {"eligible_for_live": False, "reasons": reasons},
    }


def evaluate_experiment(data, config, kind="development", check_cancel=None):
    sessions = data["sessions"]
    if len(sessions) < 80:
        raise ValueError(
            "At least 80 sessions are required: 20 development and 60 sealed final sessions"
        )
    selected = sessions[-60:] if kind == "final" else sessions[:-60]
    if kind == "final":
        report = run_replay(data, config, selected, check_cancel)
        report["split"] = {
            "kind": kind,
            "evaluated_sessions": len(selected),
            "holdout_sessions": 60,
        }
        return report
    split = max(1, int(len(selected) * 0.7))
    report = run_replay(data, config, selected[:split], check_cancel)
    report["oos"] = run_replay(data, config, selected[split:], check_cancel)
    report["stress"] = run_replay(data, config, selected[split:], check_cancel, stress=True)
    report["split"] = {
        "kind": kind,
        "development_sessions": len(selected),
        "training_sessions": split,
        "oos_sessions": len(selected) - split,
        "holdout_sessions": 60,
        "last_development_date": selected[-1],
        "holdout_consumed": False,
    }
    values = [trade["net_pnl"] for trade in report["oos"]["trades"]]
    # Session blocks preserve intraday dependence; empty sessions contribute zero.
    daily = dict.fromkeys(selected[split:], 0.0)
    for trade in report["oos"]["trades"]:
        daily[trade["signal_at"][:10]] += trade["net_pnl"]
    totals, rng = [], random.Random(config["seed"])
    if values and not report["oos"]["incomplete_outcomes"]:
        blocks = list(daily.values())
        for iteration in range(200):
            if check_cancel and iteration % 20 == 0:
                check_cancel()
            totals.append(sum(rng.choice(blocks) for _ in blocks))
        totals.sort()
    report["bootstrap"] = {
        "method": "200 session-block resamples of OOS net P&L",
        "seed": config["seed"],
        "net_pnl_p05": round(totals[10], 2) if totals else None,
        "net_pnl_p95": round(totals[189], 2) if totals else None,
        "warning": (
            "Unavailable: incomplete OOS position outcomes prevent a net P&L bootstrap."
            if report["oos"]["incomplete_outcomes"]
            else "Exploratory uncertainty only; repeated development selection invalidates confirmatory OOS claims."
        ),
    }
    return report
