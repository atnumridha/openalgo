"""Conservative OHLC replay of the native setup and protection core. No order imports."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR
from decimal import Decimal as D

from .fees import estimate
from .presets import get_preset
from .risk_adapter import evaluate
from .serialization import public_setup
from .signals import anchor_setup, evaluate_setup
from .sizing import size_entry
from .types import IST


@dataclass(frozen=True)
class ReplayRequest:
    dataset: str
    profile: str
    symbol: str
    expiry: date
    start: date
    end: date
    initial_cash: D = D(10000)
    compound: bool = False


def whole_lots(cash, premium, lot_size, entry_fee):
    if cash <= entry_fee or premium <= 0 or lot_size <= 0:
        return 0
    return max(0, int((cash - entry_fee) // (premium * lot_size)))


def run_replay(dataset, request):
    if (
        request.symbol != "NIFTY"
        or request.end < request.start
        or (request.end - request.start).days > 366
        or not request.initial_cash.is_finite()
        or request.initial_cash <= 0
    ):
        raise ValueError(
            "Choose NIFTY and a valid date range up to one year with positive research cash."
        )
    preset = get_preset(request.profile)
    cash = request.initial_cash
    trades = []
    skipped = []
    discovered_gaps = set()
    if not dataset.calendar:
        discovered_gaps.add("No recorded trading dates in this dataset.")
    else:
        if request.start < min(dataset.calendar):
            discovered_gaps.add("Requested dates begin before the recorded archive: " + min(dataset.calendar).isoformat())
        if request.end > max(dataset.calendar):
            discovered_gaps.add("Requested dates end after the recorded archive: " + max(dataset.calendar).isoformat())
    equity = []
    drawdown = D(0)
    peak = cash
    lookup = {b.time: b for b in dataset.index}
    active_until = None
    blocked = False
    day_net = {}
    day_count = {}
    for i, bar in enumerate(dataset.index):
        day = bar.time.astimezone(IST).date()
        if not request.start <= day <= request.end or day not in dataset.calendar or blocked:
            continue
        setup = evaluate_setup(dataset.index[: i + 1], preset)
        if not setup:
            continue
        now = setup.execute_at
        if active_until and now <= active_until:
            continue
        if day_count.get(day, 0) >= 3 or day_net.get(day, D(0)) <= -1000:
            skipped.append({"time": now.isoformat(), "reason": "Daily entry/loss guard"})
            continue
        next_index = lookup.get(now)
        if not next_index or next_index.repaired:
            discovered_gaps.add("Missing/repaired current index observation at " + now.isoformat())
            skipped.append({"time": now.isoformat(), "reason": "Missing current index observation"})
            continue
        setup = anchor_setup(setup, next_index.open)
        if not setup:
            continue
        choices = []
        for symbol, c in dataset.contracts.items():
            b = dataset.options.get(symbol, {}).get(now)
            if (
                c.expiry != request.expiry
                or c.expiry < day
                or c.option_type != setup.direction
                or c.lot_size != 65
            ):
                continue
            if not b or b.repaired:
                discovered_gaps.add(
                    "Missing/repaired option entry observations at " + now.isoformat()
                )
                continue
            if abs(b.open - 50) > 5:
                continue
            if preset.controlled and any(
                (now - timedelta(minutes=n)) not in dataset.options[symbol]
                or dataset.options[symbol][now - timedelta(minutes=n)].repaired
                for n in range(1, 6)
            ):
                discovered_gaps.add(
                    "Missing/repaired recent option observations at " + now.isoformat()
                )
                continue
            entry = ((b.open + D(".50")) / c.tick_size).to_integral_value(
                rounding=ROUND_CEILING
            ) * c.tick_size
            stop = (
                (entry * D(".90") / c.tick_size).to_integral_value(rounding=ROUND_FLOOR)
                * c.tick_size
                if preset.controlled
                else None
            )
            sizing_cash = cash if request.compound else min(cash, request.initial_cash)
            qty, cost = size_entry(sizing_cash, entry, c.lot_size, stop)
            if qty and cost <= cash:
                choices.append(
                    (
                        abs(b.open - 50),
                        abs(c.strike - setup.index_reference),
                        symbol,
                        c,
                        b,
                        entry,
                        qty,
                        stop,
                        cost,
                    )
                )
        if not choices:
            skipped.append(
                {
                    "time": now.isoformat(),
                    "reason": "No observed near-₹50 option fits metadata, recent-data, risk and cash checks",
                }
            )
            continue
        _, _, symbol, c, first, entry, qty, stop, cost = min(choices, key=lambda x: x[:3])
        cash -= cost
        day_count[day] = day_count.get(day, 0) + 1
        p = {
            **public_setup(setup),
            "quantity": qty,
            "tick_size": str(c.tick_size),
            "controlled": preset.controlled,
            "option_stop": str(stop) if stop else None,
            "option_target": None,
            "index_stop": str(setup.initial_stop),
            "index_peak": str(setup.index_reference),
            "net_peak": None,
            "net_floor": None,
            "cash_trail_enabled": preset.controlled,
            "cash_activation": "1000",
            "cash_distance": "250",
        }
        trade = {
            "symbol": symbol,
            "direction": setup.direction,
            "profile": request.profile,
            "entry_time": now.isoformat(),
            "entry_price": str(entry),
            "quantity": qty,
            "index_reference": str(setup.index_reference),
            "initial_index_stop": str(setup.initial_stop),
            "index_target": str(setup.target),
            "status": "open",
            "entry_fees": str(estimate("BUY", entry, qty)),
            "trail": [],
            "option_bars": [],
            "index_bars": [],
        }
        stamp = now
        deadline = now.replace(hour=15, minute=29)
        latest_index = setup.index_reference
        resolved = False
        while stamp <= deadline:
            b = dataset.options[symbol].get(stamp)
            if not b or b.repaired:
                trade["status"] = "unresolved_option_gap"
                trade["missing_at"] = stamp.isoformat()
                blocked = True
                break
            finished_index = lookup.get(stamp - timedelta(minutes=15))
            if stamp > now and finished_index and not finished_index.repaired:
                latest_index = finished_index.close
            trade["option_bars"].append(
                {
                    "time": int(stamp.timestamp()),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
            )
            # Evaluate pre-existing protection at the observed low first. No high-created trail is backdated.
            updated, reason = evaluate(
                p, {"entry_avg": entry, "qty": qty}, latest_index, b.low, day_net.get(day, D(0))
            )
            if stamp == deadline:
                reason = reason or "15:29 IST square-off"
            if reason:
                exit_price = max(c.tick_size, (b.open if stamp == deadline else b.low) - D(".50"))
                exit_price = (exit_price / c.tick_size).to_integral_value(
                    rounding=ROUND_FLOOR
                ) * c.tick_size
                fees = estimate("BUY", entry, qty) + estimate("SELL", exit_price, qty)
                gross = (exit_price - entry) * qty
                net = gross - fees
                cash += exit_price * qty - estimate("SELL", exit_price, qty)
                day_net[day] = day_net.get(day, D(0)) + net
                active_until = stamp
                trade.update(
                    status="closed",
                    exit_time=stamp.isoformat(),
                    exit_price=str(exit_price),
                    gross=str(gross),
                    fees=str(fees),
                    net=str(net),
                    reason=reason,
                    ambiguous_intrabar=True,
                )
                peak = max(peak, cash)
                drawdown = min(drawdown, cash - peak)
                equity.append({"time": stamp.isoformat(), "cash": str(cash)})
                resolved = True
                break
            p, _ = evaluate(
                p, {"entry_avg": entry, "qty": qty}, latest_index, b.close, day_net.get(day, D(0))
            )
            trade["trail"].append(
                {
                    "time": int(stamp.timestamp()),
                    "option_stop": p.get("option_stop"),
                    "index_stop": p["index_stop"],
                    "index_target": p["target"],
                }
            )
            stamp += timedelta(minutes=1)
        if not resolved and trade["status"] == "open":
            trade["status"] = "unresolved_option_gap"
            blocked = True
        trade["index_bars"] = [
            {
                "time": int(b.time.timestamp()),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
            }
            for b in dataset.index
            if now - timedelta(minutes=60) <= b.time <= stamp
        ]
        trades.append(trade)
    closed = [t for t in trades if t["status"] == "closed"]
    known = sum((D(t["net"]) for t in closed), D(0))
    fees = sum(
        (D(t["fees"]) if t["status"] == "closed" else D(t["entry_fees"]) for t in trades), D(0)
    )
    unresolved = [t for t in trades if t["status"] != "closed"]
    covered = [d for d in dataset.calendar if request.start <= d <= request.end]
    complete = (
        bool(covered)
        and not unresolved
        and request.start >= min(dataset.calendar)
        and request.end <= max(dataset.calendar)
        and not dataset.gaps
        and not discovered_gaps
    )
    return {
        "dataset": dataset.identity,
        "profile": request.profile,
        "initial_cash": str(request.initial_cash),
        "trades": trades,
        "skipped": skipped,
        "equity": equity,
        "known_realized_net": str(known),
        "net_complete": str(known) if complete else None,
        "fees_estimate": str(fees),
        "ending_cash": str(cash) if complete else None,
        "available_cash_model": str(cash),
        "wins": sum(D(t["net"]) > 0 for t in closed),
        "closed_count": len(closed),
        "unresolved_count": len(unresolved),
        "drawdown": str(drawdown),
        "coverage": {
            "complete": complete,
            "dates": [d.isoformat() for d in covered],
            "source": dataset.source,
            "gaps": dataset.gaps + sorted(discovered_gaps),
        },
        "assumptions": [
            "OHLC observations proxy execution; buy open + ₹0.50, sell conservative observed low/open - ₹0.50. Historical bid/ask, depth and exact execution order are unavailable.",
            "Stop-first intrabar evaluation; new trails apply after their confirming observation. No forward filling across missing option minutes.",
            "Index protection observes confirmed 15-minute closes; tick-level intrabar behaviour cannot be reproduced.",
            "Estimated ₹10 executed-order brokerage; a dated free-promotion window has not been verified. Live and research allow up to two whole lots, with affordability, current depth (Live) and controlled-profile risk guards. Stops can slip beyond their threshold.",
        ],
    }
