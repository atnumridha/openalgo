"""Closed-bar rule screening on real option candles, with conservative fills."""

import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from services.research.costs import (
    decimal_value,
    order_cost,
    validate_cost_dates,
    validate_cost_schedule,
)
from services.research.dataset import digest
from services.risk import BreachReason, PositionRisk, evaluate_position
from services.risk.budget import BudgetPolicy, BudgetTrade, budget_snapshot, evaluate_budget

DEFAULTS = {
    "lookback": 20,
    "stop_pct": 0.10,
    "target_pct": 0.20,
    "volume_ratio": 1.2,
    "pullback_tolerance": 0.002,
}
CANDIDATES = [
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
ENGINE_VERSION = "closed-bar-rules-v1"


class Cancelled(Exception):
    pass


def validate_configuration(data, candidate, parameters, costs, seed=42):
    if candidate not in {c["id"] for c in CANDIDATES}:
        raise ValueError("Select a supported deterministic candidate")
    if not isinstance(parameters, dict) or set(parameters) - set(DEFAULTS):
        raise ValueError("Unknown rule parameters")
    params = DEFAULTS | parameters
    for key, (minimum, maximum) in {
        "lookback": (2, 200),
        "stop_pct": (0.001, 0.9),
        "target_pct": (0.001, 5),
        "volume_ratio": (0.01, 10),
        "pullback_tolerance": (0, 0.05),
    }.items():
        params[key] = float(decimal_value(params[key], key, minimum=minimum, maximum=maximum))
    if params["lookback"] != int(params["lookback"]):
        raise ValueError("lookback must be a whole number")
    params["lookback"] = int(params["lookback"])
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("seed must be a whole number between 0 and 4294967295")
    schedule = validate_cost_schedule(costs)
    validate_cost_dates(schedule, data["sessions"])
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
        "engine_version": ENGINE_VERSION,
        "dataset_hash": data["content_hash"],
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
    if candidate == "trend_breakout":
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
    exit_price = price * (1 - slippage)
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


def run_replay(data, config, sessions=None, check_cancel=None, stress=False):
    """One serial portfolio; long options only. Never synthesizes option bars."""
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
    policy, ledger = BudgetPolicy(), []
    equity = peak = Decimal("10000")
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
        if pending and at >= pending["entry_bar_at"]:
            contract = pending["contract"]
            bar = bars.get(contract["symbol"]) if at == pending["entry_bar_at"] else None
            if bar is None:
                rejections["missing_next_option_bar"] += 1
            else:
                entry = bar["open"] * (1 + slip)
                lot_units = contract["lot_size"] * contract["multiplier"]
                one_premium = Decimal(str(entry * lot_units))
                max_lots = int(
                    (min(equity, policy.capital) * (1 - policy.cash_buffer_pct)) / one_premium
                )
                admitted = None
                low_lots, high_lots = 1, min(max_lots, 10000)
                while low_lots <= high_lots:
                    lots = (low_lots + high_lots) // 2
                    units = lot_units * lots
                    entry_fees = order_cost(Decimal(str(entry * units)), "BUY", costs)
                    stop = entry * (1 - params["stop_pct"])
                    planned_exit = stop * (1 - slip)
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
                        policy, ledger, day, equity, peak, planned, paused=drawdown_paused
                    )
                    if decision.allowed:
                        admitted = (lots, units, entry_fees, planned, decision.bucket)
                        low_lots = lots + 1
                    else:
                        high_lots = lots - 1
                if admitted:
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
                        "risk": PositionRisk(
                            entry_price=entry,
                            quantity=units,
                            stop_price=entry * (1 - params["stop_pct"]),
                            target_price=entry * (1 + params["target_pct"]),
                        ),
                    }
                else:
                    rejections[
                        "unaffordable_whole_lot" if max_lots < 1 else "budget_or_drawdown_limit"
                    ] += 1
            pending = None
        if active:
            bar = bars.get(active["contract"]["symbol"])
            expected = (datetime.fromisoformat(active["last_bar_at"]) + bar_delta).isoformat()
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
                opening = evaluate_position(risk, bar["open"])
                if opening.reason == BreachReason.STOP:
                    exit_price, reason = bar["open"], "stop_loss"
                elif _drawdown_breached(policy, day, opening_mark, peak):
                    exit_price, reason = bar["open"], "portfolio_drawdown"
                elif opening.reason == BreachReason.TARGET:
                    exit_price, reason = bar["open"], "target"
                else:
                    low_mark = _liquidation_equity(active, bar["low"], equity, costs, slip)
                    if evaluate_position(risk, bar["low"]).reason == BreachReason.STOP:
                        exit_price, reason = risk.stop_price, "stop_loss"
                    if _drawdown_breached(policy, day, low_mark, peak):
                        drawdown_price = _drawdown_exit_price(
                            active, bar, equity, peak, policy, day, costs, slip
                        )
                        # On a declining path the higher protective threshold
                        # is crossed first. Do not use a low reached after exit.
                        if exit_price is None or drawdown_price >= exit_price:
                            exit_price, reason = drawdown_price, "portfolio_drawdown"
                    if reason is None:
                        max_open_drawdown = max(
                            max_open_drawdown, float((peak - low_mark) / peak * 100)
                        )
                        if evaluate_position(risk, bar["high"]).reason == BreachReason.TARGET:
                            exit_price, reason = risk.target_price, "target"
                        elif at[11:16] >= meta["session_close"]:
                            exit_price, reason = bar["close"], "session_close"
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
                    exit_price *= 1 - slip
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
                        budget_bucket=active["bucket"],
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
                        )
                    )
                    equity += net
                    peak = max(peak, equity)
                    active = None
                    if len(trades) >= 5000:
                        incomplete.append({"reason": "trade_limit_reached"})
                        break
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
            direction = (
                _signal(history, config["candidate"], params)
                if underlying_session_complete or config["candidate"] != "vwap_pullback"
                else None
            )
            if direction and not active and not pending:
                entry_at = (datetime.fromisoformat(at) + bar_delta).isoformat()
                if entry_at[:10] != day or entry_at[11:16] >= meta["session_close"]:
                    rejections["after_entry_cutoff"] += 1
                    continue
                eligible = [
                    c
                    for c in meta["contracts"]
                    if c["option_type"] == direction and c["expiry"] >= day
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
    metrics = _metrics(trades)
    metrics["closed_trade_max_drawdown_pct"] = metrics["max_drawdown_pct"]
    metrics["max_drawdown_pct"] = round(max_open_drawdown, 4)
    metrics["max_observed_open_drawdown_pct"] = round(max_open_drawdown, 4)
    metrics["peak_equity"] = float(peak.quantize(Decimal("0.01")))
    metrics["drawdown_paused"] = drawdown_paused
    metrics["equity_mark_convention"] = (
        "Net liquidation equity at observed opens/closes; adverse lows use the previously observed peak."
    )
    metrics["exposure_bars"] = exposure_bars
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
    return {
        "metrics": metrics,
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
