"""Read-only causal replay and evidence-bounded historical setup review.

Index candles count setups, never option profits. Financial samples must come
from supplied broker round trips or an explicitly supplied option quote/history
scenario. This module has no broker, account, database or clock access.
"""

import copy
import math
from datetime import datetime

from .analysis import IST, completed, fees, number
from .setups import (
    advance_opening,
    initial_opening_state,
    observe_trend,
    opening_result,
    reset_observation,
    trend_setup,
)

GROUPS = ("trend:confirmed", "trend:early", "opening_reversal:literal")
OPENING = {"opening_reversal", "opening_swing_reversal"}


def _events(events, now, start=None):
    """Use only observations already recorded by the replay cursor."""
    result = []
    seen = set()
    for event in events:
        try:
            time = number(event["time"])
            received = number(
                event.get("observed_at", event.get("received_at", event.get("received", time)))
            )
            reset = event.get("type") == "reset" or event.get("kind") == "observation_gap"
            price = None if reset else number(event["price"])
            identity = str(event.get("id") or f"{time}:{price}:{event.get('source')}")
            if (
                not (start is None or time >= start)
                or max(time, received) > now
                or (price is not None and price <= 0)
                or identity in seen
                or event.get("kind") == "option_quote"
            ):
                continue
            seen.add(identity)
            source = {"Broker snapshot": "rest_snapshot", "Live feed": "websocket"}.get(
                event.get("source"), event.get("source", "observed")
            )
            result.append(
                {
                    **event,
                    "time": time,
                    "price": price,
                    "id": identity,
                    "source": source,
                    "type": "reset" if reset else event.get("type", "price"),
                }
            )
        except (ValueError, TypeError, KeyError):
            continue
    return sorted(
        result,
        key=lambda e: (
            e.get("observed_at", e.get("received_at", e.get("received", e["time"]))),
            e["time"],
            0 if e["type"] == "reset" else 1,
            e["id"],
        ),
    )


def _opening_replay(one, events, now, session_start, session_id):
    state = initial_opening_state(session_id)
    for event in events:
        if event["type"] == "reset":
            state = reset_observation(
                state, event["time"], event.get("reason", "Recorded observation gap")
            )
            continue
        if event.get("live_eligible") is False:
            continue
        last = state.get("last_event")
        if last and event["time"] - last["time"] > 10:
            state = reset_observation(
                state, event["time"], "Observed-price gap; fresh reference crossing required"
            )
        # Each event sees candles only as of its observed timestamp. Delayed
        # observations cannot use a pivot that became known later.
        state = advance_opening(state, one, event, event["time"], session_id, session_start)
    return advance_opening(state, one, None, now, session_id, session_start)


def evaluate_replay(one, five, events, now, session_start, session_id, strategy, mode="confirmed"):
    """Evaluate the shared strategy at a historical cursor; never permit entry."""
    now, session_start = number(now), number(session_start)
    tape = _events(events, now, session_start)
    if strategy in OPENING:
        result = opening_result(_opening_replay(one, tape, now, session_start, session_id), now)
    elif strategy == "trend":
        result = observe_trend(
            trend_setup(one, five, now, mode=mode, session_start=session_start), tape, now
        )
    else:
        raise ValueError("Choose a supported chart setup strategy")
    result = copy.deepcopy(result)
    result.update(historical_eligible=bool(result.get("eligible")), eligible=False, read_only=True)
    for direction in result.get("directions", {}).values():
        direction.update(historical_eligible=bool(direction.get("eligible")), eligible=False)
    price_tape = [e for e in tape if e["type"] != "reset"]
    sources = sorted({str(e.get("source", "observed")) for e in price_tape})
    basis = (
        "unavailable"
        if not price_tape
        else "sampled_snapshots"
        if all(s == "rest_snapshot" for s in sources)
        else "recorded_observations"
    )
    limitations = ["Replay is read only; a historical setup cannot submit a live entry."]
    if not price_tape:
        limitations.append(
            "OHLC alone cannot establish the opening strategy's observed reference break or intrabar trigger."
        )
    else:
        limitations.append(
            "Only recorded observations are replayed; missing ticks and unrecorded crossings remain unknown."
        )
    if "rest_snapshot" in sources:
        limitations.append("REST snapshots are sampled prices; intervening ticks are unavailable.")
    skipped = sum(e.get("live_eligible") is False for e in price_tape)
    if skipped:
        limitations.append(
            f"{skipped} delayed observations were recorded but could not trigger a fresh live setup."
        )
    result["replay"] = {
        "cursor": now,
        "event_count": len(price_tape),
        "reset_count": sum(e["type"] == "reset" for e in tape),
        "sources": sources,
        "intrabar_basis": basis,
        "complete_tick_coverage": False,
        "limitations": limitations,
    }
    return result


def _bar_coverage(rows, seconds, now):
    bars = completed(rows, now, seconds)
    gaps = []
    for a, b in zip(bars, bars[1:], strict=False):
        if (
            datetime.fromtimestamp(a["time"], IST).date()
            == datetime.fromtimestamp(b["time"], IST).date()
            and b["time"] - a["time"] > seconds
        ):
            gaps.append(
                {
                    "after": a["time"],
                    "before": b["time"],
                    "missing": int((b["time"] - a["time"]) // seconds) - 1,
                }
            )
    return {
        "count": len(bars),
        "first": bars[0]["time"] if bars else None,
        "last": bars[-1]["time"] if bars else None,
        "dates": sorted({datetime.fromtimestamp(b["time"], IST).date().isoformat() for b in bars}),
        "gaps": gaps,
    }


def _option_quotes(events, now, symbol=None, exchange=None):
    quotes = []
    for event in events:
        try:
            time, bid, ask = map(number, (event["time"], event["bid"], event["ask"]))
            received = number(
                event.get("observed_at", event.get("received_at", event.get("received", time)))
            )
            if (
                max(time, received) <= now
                and 0 < bid <= ask
                and event.get("symbol")
                and event.get("exchange") in ("NFO", "BFO")
                and event.get("source") in ("websocket", "rest_snapshot", "broker_quote")
                and (symbol is None or event["symbol"] == symbol)
                and (exchange is None or event["exchange"] == exchange)
            ):
                quotes.append({**event, "time": time, "bid": bid, "ask": ask})
        except (ValueError, TypeError, KeyError):
            continue
    return sorted(quotes, key=lambda e: e["time"])


def coverage_report(one, five, events, now, option_history=None):
    """Describe observed coverage without filling gaps or inventing option data."""
    now = number(now)
    one_info, five_info = _bar_coverage(one, 60, now), _bar_coverage(five, 300, now)
    recent_one = _bar_coverage(completed(one, now, 60)[-60:], 60, now)
    recent_five = _bar_coverage(completed(five, now, 300)[-250:], 300, now)
    fresh_one = recent_one["last"] is not None and now - (recent_one["last"] + 60) <= 65
    fresh_five = recent_five["last"] is not None and now - (recent_five["last"] + 300) <= 365
    options = option_history or []
    # Symbols are separate series; simultaneous contracts are never deduplicated
    # into a fabricated continuous option candle history.
    contracts = sorted(
        {
            (b.get("symbol"), b.get("exchange"))
            for b in options
            if b.get("symbol") and b.get("exchange") in ("NFO", "BFO")
        }
    )
    option_series = {
        f"{exchange}:{symbol}": _bar_coverage(
            [b for b in options if b.get("symbol") == symbol and b.get("exchange") == exchange],
            60,
            now,
        )
        for symbol, exchange in contracts
    }
    quotes = _option_quotes(events, now)
    quote_count = len(quotes)
    option_count = sum(s["count"] for s in option_series.values())
    tape = [e for e in _events(events, now) if e["type"] != "reset"]
    return {
        "checked_at": now,
        "one_minute": one_info,
        "five_minute": five_info,
        "warmup": {
            "one_required": 60,
            "five_required": 250,
            "trend_ready": one_info["count"] >= 60
            and five_info["count"] >= 250
            and not recent_one["gaps"]
            and not recent_five["gaps"]
            and fresh_one
            and fresh_five,
        },
        "event_tape": {
            "count": len(tape),
            "first": tape[0]["time"] if tape else None,
            "last": tape[-1]["time"] if tape else None,
            "complete_tick_coverage": False,
        },
        "option_history": {
            "count": option_count,
            "series": option_series,
            "quote_count": quote_count,
        },
        "financial_metrics_available": any(
            option_series[f"{q['exchange']}:{q['symbol']}"]["count"]
            for q in quotes
            if f"{q['exchange']}:{q['symbol']}" in option_series
        ),
        "limitations": [
            "No missing, overnight or holiday candles are manufactured. Calendar-valid input sessions must be supplied by the caller.",
            "Index signal counts are separate from option financial samples. Missing historical option contracts, quotes or fills prevent option return estimates.",
            "Minute OHLC does not establish intrabar order; a bar touching both stop and target uses the stop first.",
        ],
    }


def _unavailable_metrics():
    return {
        "status": "unavailable",
        "sample_count": 0,
        "gross": None,
        "fees": None,
        "net": None,
        "expectancy": None,
        "profit_factor": None,
        "max_drawdown": None,
        "win_rate": None,
    }


def trade_metrics(roundtrips):
    """Summarize supplied genuine round trips in closing-time order, net of fees."""
    if not roundtrips:
        return _unavailable_metrics()
    outcomes = []
    for trade in roundtrips:
        entry, exit_price = map(number, (trade["entry"], trade["exit"]))
        qty = trade["quantity"]
        entry_time, exit_time = map(number, (trade["entry_time"], trade["exit_time"]))
        brokerage = number(trade.get("brokerage", 0))
        slippage = number(trade.get("slippage", 0))
        if (
            not isinstance(qty, int)
            or isinstance(qty, bool)
            or qty <= 0
            or min(entry, exit_price) <= 0
            or min(brokerage, slippage) < 0
            or exit_time < entry_time
        ):
            raise ValueError(
                "Round trips require positive actual prices/quantity and chronological times"
            )
        day = datetime.fromtimestamp(entry_time, IST).date().isoformat()
        charge = fees(entry * qty, exit_price * qty, trade["exchange"], brokerage, day)["total"]
        gross = (exit_price - entry) * qty
        outcomes.append(
            {
                "closed_at": exit_time,
                "gross": gross,
                "fees": charge,
                "slippage": slippage * qty,
                "net": gross - charge - slippage * qty,
                "uncertain": bool(trade.get("intrabar_uncertain")),
            }
        )
    outcomes.sort(key=lambda t: t["closed_at"])
    equity = peak = drawdown = 0
    for row in outcomes:
        equity += row["net"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    wins = sum(row["net"] > 0 for row in outcomes)
    positive = sum(max(0, row["net"]) for row in outcomes)
    negative = -sum(min(0, row["net"]) for row in outcomes)
    return {
        "status": "available",
        "sample_count": len(outcomes),
        "gross": round(sum(row["gross"] for row in outcomes), 2),
        "fees": round(sum(row["fees"] for row in outcomes), 2),
        "slippage": round(sum(row["slippage"] for row in outcomes), 2),
        "net": round(equity, 2),
        "expectancy": round(equity / len(outcomes), 2),
        "profit_factor": round(positive / negative, 4) if negative else None,
        "profit_factor_status": "available" if negative else "no_losses",
        "max_drawdown": round(drawdown, 2),
        "win_rate": round(wins / len(outcomes), 4),
        "uncertain_sample_count": sum(row["uncertain"] for row in outcomes),
    }


def chronological_holdout(roundtrips, fraction=0.7):
    """Partition entire session dates once; never tune parameters on holdout."""
    fraction = number(fraction)
    if not 0 < fraction < 1:
        raise ValueError("The training fraction must be between zero and one")
    rows = sorted(copy.deepcopy(roundtrips), key=lambda t: number(t["entry_time"]))
    dates = sorted(
        {datetime.fromtimestamp(number(t["entry_time"]), IST).date().isoformat() for t in rows}
    )
    split = (
        max(1, min(len(dates) - 1, math.floor(len(dates) * fraction)))
        if len(dates) > 1
        else len(dates)
    )
    training_dates, holdout_dates = dates[:split], dates[split:]
    training, holdout = [], []
    for row in rows:
        day = datetime.fromtimestamp(number(row["entry_time"]), IST).date().isoformat()
        (training if day in training_dates else holdout).append(row)
    return {
        "training_dates": training_dates,
        "holdout_dates": holdout_dates,
        "training": training,
        "holdout": holdout,
        "status": "available" if holdout_dates else "insufficient_sessions",
    }


def option_bar_trade(plan, bars, quotes, now, symbol, exchange):
    """Bounded OHLC scenario using a genuine matching option entry quote.

    Prices come only from the supplied contract's quote/candles. A stop touched
    during a gap exits at the lower opening price. Same-bar ambiguity is marked
    and treated stop first; this is never represented as an actual broker fill.
    """
    entry_time = number(plan["entry_time"])
    matching = [
        q
        for q in _option_quotes(quotes, min(now, entry_time), symbol, exchange)
        if 0 <= entry_time - q["time"] <= 5
    ]
    if not matching:
        return None
    entry = matching[-1]["ask"]
    sl, target = map(number, (plan["sl"], plan["target"]))
    if not 0 < sl < entry < target:
        raise ValueError(
            "An option scenario requires a stop below the actual quote and target above it"
        )
    rows = completed(
        [
            b
            for b in bars
            if b.get("symbol") == symbol
            and b.get("exchange") == exchange
            and b.get("source") == "broker_history"
        ],
        now,
        60,
    )
    previous = None
    for row in rows:
        if row["time"] + 60 <= entry_time:
            continue
        if previous is None and row["time"] > entry_time:
            return None
        if previous is not None and row["time"] - previous > 60:
            return None
        previous = row["time"]
        stop, profit = row["low"] <= sl, row["high"] >= target
        # A partial entry minute can have reached its high before our quote.
        # Count a stop conservatively, but never turn that unknown order into
        # a winner. Full subsequent bars can establish the target normally.
        if row["time"] < entry_time and not stop:
            continue
        if not stop and not profit:
            continue
        return {
            "symbol": symbol,
            "exchange": exchange,
            "entry": entry,
            "exit": min(sl, row["open"]) if stop else target,
            "quantity": plan["quantity"],
            "entry_time": entry_time,
            "exit_time": row["time"] + 60,
            "sl": sl,
            "target": target,
            "outcome": "stop" if stop else "target",
            "intrabar_uncertain": bool((stop and profit) or row["time"] < entry_time),
            "provenance": "historical_option_ohlc",
            "brokerage": plan.get("brokerage", 0),
            "slippage": plan.get("slippage", 0),
        }
    return None


def _supported_roundtrip(trade, events, option_history, now):
    provenance = trade.get("provenance")
    if provenance == "broker_fills":
        return True
    try:
        symbol, exchange = trade["symbol"], trade["exchange"]
        if provenance == "historical_option_ohlc":
            scenario = option_bar_trade(trade, option_history or [], events, now, symbol, exchange)
            return bool(
                scenario
                and all(
                    abs(number(scenario[k]) - number(trade[k])) < 1e-7
                    for k in ("entry", "exit", "exit_time")
                )
            )
        if provenance == "recorded_option_quotes":
            for time_key, price_key, side in (
                ("entry_time", "entry", "ask"),
                ("exit_time", "exit", "bid"),
            ):
                time = number(trade[time_key])
                quotes = [
                    q
                    for q in _option_quotes(events, time, symbol, exchange)
                    if 0 <= time - q["time"] <= 5
                ]
                if not quotes or abs(quotes[-1][side] - number(trade[price_key])) > 1e-7:
                    return False
            return True
    except (ValueError, TypeError, KeyError):
        return False
    return False


def review_setups(
    one,
    five,
    events,
    now,
    session_start,
    session_id,
    option_history=None,
    roundtrips=None,
    baseline_roundtrips=None,
):
    """Review fixed strategy families without optimizing or manufacturing fills."""
    now, session_start = number(now), number(session_start)
    tape = _events(events, now, session_start)
    groups = {
        key: {"index_signal_count": 0, "signal_ids": [], "metrics": _unavailable_metrics()}
        for key in GROUPS
    }
    state = _opening_replay(one, tape, now, session_start, session_id)
    for direction in state["directions"].values():
        if direction.get("consumed") and direction.get("setup_id"):
            groups["opening_reversal:literal"]["signal_ids"].append(direction["setup_id"])
    for mode in ("confirmed", "early"):
        identities = set()
        for bar in completed(one, now, 60):
            cursor = bar["time"] + 60
            if cursor < session_start:
                continue
            result = trend_setup(one, five, cursor, mode=mode, session_start=session_start)
            if result.get("eligible") and result.get("setup_id"):
                identities.add(result["setup_id"])
        groups[f"trend:{mode}"]["signal_ids"] = sorted(identities)
    for key, group in groups.items():
        group["index_signal_count"] = len(group["signal_ids"])
        supplied = []
        baseline = []
        for source, target in ((roundtrips or [], supplied), (baseline_roundtrips or [], baseline)):
            for trade in source:
                strategy = (
                    "opening_reversal"
                    if trade.get("strategy") in OPENING
                    else trade.get("strategy")
                )
                mode = (
                    "literal" if strategy == "opening_reversal" else trade.get("mode", "confirmed")
                )
                if f"{strategy}:{mode}" == key and _supported_roundtrip(
                    trade, events, option_history, now
                ):
                    if number(trade["exit_time"]) <= now:
                        target.append(trade)
        group["metrics"] = trade_metrics(supplied)
        partition = chronological_holdout(supplied)
        group["holdout"] = {k: v for k, v in partition.items() if k not in ("training", "holdout")}
        group["holdout"].update(
            training_metrics=trade_metrics(partition["training"]),
            holdout_metrics=trade_metrics(partition["holdout"]),
        )
        group["baseline"] = trade_metrics(baseline)
    return {
        "read_only": True,
        "parameter_selection": "fixed_approved_parameters",
        "coverage": coverage_report(one, five, events, now, option_history),
        "groups": groups,
        "limitations": [
            "A setup is an index observation, not an option trade. Financial samples require supplied contract-specific evidence.",
            "Chronological holdout splits whole dates 70/30; no parameter search or holdout tuning is performed.",
            "Baseline comparison is unavailable unless genuine baseline round trips are supplied.",
        ],
    }
