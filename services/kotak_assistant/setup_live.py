"""Durable observed-event adapter. Signals never call order submission APIs."""

import copy
import math
from datetime import datetime

from utils.keyed_locks import KeyedLocks

from . import setups
from .analysis import IST
from .setup_data import SetupStore, continuity_gaps, session_bars

_locks = KeyedLocks(name="kotak-chart-setups")


def session_window(day, exchange):
    from database.market_calendar_db import get_effective_session_window

    return get_effective_session_window(day, exchange)


def repository(c):
    with _locks.hold(("repository", id(c.store))):
        if not hasattr(c.store, "chart_setup_store"):
            c.store.chart_setup_store = SetupStore(c.store.engine)
        return c.store.chart_setup_store


def scope_for(c, underlying):
    return f"{c.g.user}:{getattr(c.g, 'account', c.scope)}:{underlying}"


def _calendar(c, exchange):
    def read(day, _exchange):
        return c.g.cached(
            ("setup_calendar", exchange, day.isoformat()), 60, lambda: session_window(day, exchange)
        )

    return read


def refresh(c, underlying, one, five, quote, strategy="trend", mode="confirmed", keep_alive=True):
    if underlying not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        raise ValueError("Choose NIFTY, BANKNIFTY or SENSEX")
    if strategy not in ("trend", "opening_reversal") or mode not in ("confirmed", "early"):
        raise ValueError("Choose a supported strategy and mode")
    now = c.clock()
    day = datetime.fromtimestamp(now, IST).date()
    exchange = "BSE" if underlying == "SENSEX" else "NSE"
    ix = "BSE_INDEX" if underlying == "SENSEX" else "NSE_INDEX"
    calendar = _calendar(c, exchange)
    window = calendar(day, exchange)
    start = window["start_ms"] / 1000 if window else now
    end = window["end_ms"] / 1000 if window else now
    session_id = f"{exchange}:{day.isoformat()}"
    opened = bool(window and start <= now < end)
    one = session_bars(one, 60, now, exchange, calendar)
    five = session_bars(five, 300, now, exchange, calendar)
    scope = scope_for(c, underlying)
    repo = repository(c)
    quote = quote or {}
    # A cold historical read may take several seconds. Recheck the quote
    # after that work instead of presenting its pre-load receipt as current.
    quoted_at = float(quote.get("observed_time") or quote.get("time") or 0)
    if opened and now - quoted_at > 5 and callable(getattr(c.g, "quote", None)):
        quote = c.g.quote(underlying, ix)
        now = c.clock()
        opened = bool(window and start <= now < end)
    source = quote.get("source") or "Broker snapshot"
    observed = float(quote.get("observed_time") or quote.get("time") or 0)
    fresh = bool(quote.get("ltp") and math.isfinite(observed) and -3 <= now - observed <= 5)
    batch = {"events": [], "dropped": 0, "connection": None}
    with _locks.hold(scope):
        body, version = repo.read(scope)
        drain = getattr(c.g, "drain_setup_events", None)
        if callable(drain):
            batch = drain(underlying, ix)
        try:
            old_session = body.get("session_id")
            state = body.get("opening") if old_session == session_id else None
            if not state:
                state = setups.initial_opening_state(session_id)
            connection = batch.get("connection")
            disconnected = bool(
                body.get("connection") and connection and connection != body["connection"]
            )
            if disconnected or batch.get("dropped"):
                reset_time = min((e["time"] for e in batch["events"]), default=now)
                state = setups.reset_observation(
                    state,
                    reset_time,
                    "Feed reconnect or missing observed prices; fresh reference crossing required",
                )
            events = []
            for e in batch["events"]:
                if start <= float(e.get("time", 0)) < end:
                    events.append(e)
            # REST is a sampled observation. Do not pretend identical cached
            # responses are separate ticks, or duplicate a websocket tick.
            if opened and fresh and source != "Live feed":
                event_id = f"rest:{underlying}:{observed:.6f}"
                if body.get("snapshot_id") != event_id:
                    events.append(
                        {
                            "id": event_id,
                            "time": observed,
                            "price": float(quote["ltp"]),
                            "source": "Broker snapshot",
                            "time_basis": "receipt",
                        }
                    )
                    body["snapshot_id"] = event_id
            events.sort(key=lambda e: (e["time"], e.get("id", "")))
            resets = []
            if disconnected or batch.get("dropped"):
                resets.append(
                    {
                        "id": f"reset:{connection}:{reset_time:.6f}",
                        "time": reset_time,
                        "type": "reset",
                        "source": "feed_gap",
                        "reason": "Feed reconnect or missing observed prices",
                    }
                )
            evidence = []
            if source != "Live feed":
                evidence.append(
                    "REST sampled snapshots: intervening price crossings may be missed."
                )
            if disconnected or batch.get("dropped"):
                evidence.append(
                    "Feed coverage gap: untriggered watches reset; consumed directions preserved."
                )
            for event in events:
                last = state.get("last_event")
                # Save delayed events for historical analysis, but never turn a
                # crossing missed during a disconnect into a fresh live entry.
                if now - event["time"] > 10 or event["time"] > now + 3:
                    event["live_eligible"] = False
                    evidence.append(
                        "Delayed observation saved for replay; not a fresh live trigger."
                    )
                    continue
                if last and event["time"] - last["time"] > 10:
                    state = setups.reset_observation(
                        state,
                        event["time"],
                        "Observed-price gap; fresh reference crossing required",
                    )
                    resets.append(
                        {
                            "id": "reset:" + event["id"],
                            "time": event["time"],
                            "type": "reset",
                            "source": "feed_gap",
                            "reason": "Observed-price gap; fresh reference crossing required",
                        }
                    )
                state = setups.advance_opening(state, one, event, event["time"], session_id, start)
            state = setups.advance_opening(state, one, None, now, session_id, start)
            trends = body.get("trends", {}) if old_session == session_id else {}
            signature = [
                one[-1]["time"] if one else None,
                five[-1]["time"] if five else None,
                int(now // 60),
            ]
            if body.get("trend_signature") != signature or not trends:
                trends = {
                    m: setups.trend_setup(one, five, now, m, start) for m in ("confirmed", "early")
                }
            terminals = body.get("trend_terminals", {}) if old_session == session_id else {}
            terminals = {
                key: value for key, value in terminals.items() if value.get("expires", 0) > now
            }
            observations = list(events)
            if opened and fresh:
                observations.append({"time": observed, "price": float(quote["ltp"])})
            for m in trends:
                key = trends[m].get("setup_id")
                if key in terminals:
                    trends[m].update(terminals[key])
                else:
                    trends[m] = setups.observe_trend(trends[m], observations, now)
                    if key and trends[m].get("terminal_at"):
                        terminals[key] = {
                            k: trends[m][k]
                            for k in ("stage", "eligible", "reason", "terminal_at", "expires")
                        }
            result = copy.deepcopy(
                trends[mode] if strategy == "trend" else setups.opening_result(state, now)
            )
            result.update(
                strategy=strategy,
                version="1.0",
                underlying=underlying,
                source=source,
                session={"id": session_id, "start": start, "end": end, "open": opened},
                read_only=False,
            )
            result["evidence"] = [*result.get("evidence", []), *evidence]
            result["observed_at"] = observed or None
            result["current_quote"] = quote
            result["chart_fresh"] = fresh
            if not opened:
                result.update(
                    stage="market_closed",
                    eligible=False,
                    reason="Exchange session closed; use replay to inspect completed setups",
                )
            elif not fresh:
                result.update(
                    eligible=False, reason="Fresh index quote unavailable; setup evidence retained"
                )
            if result.get("expires") and now >= result["expires"]:
                result["eligible"] = False
            new_body = {
                **body,
                "user": c.g.user,
                "account_scope": c.scope,
                "mode": c.g.mode,
                "underlying": underlying,
                "session_id": session_id,
                "opening": state,
                "trends": trends,
                "trend_signature": signature,
                "connection": connection or body.get("connection"),
                "trend_terminals": terminals,
                "updated": now,
                "last_view": now if keep_alive else body.get("last_view", 0),
            }
            if old_session != session_id:
                new_body["prune_before"] = now - 35 * 86400
            else:
                new_body.pop("prune_before", None)
            if not repo.commit(scope, version, new_body, [*resets, *events]):
                raise ValueError("Setup checkpoint changed; waiting for next refresh")
            return result
        except Exception:
            restore = getattr(c.g, "restore_setup_events", None)
            if callable(restore):
                restore(batch["events"])
            raise


def poll_saved(c, underlying):
    """Called by the existing one-second monitor, including after restart."""
    ix = "BSE_INDEX" if underlying == "SENSEX" else "NSE_INDEX"
    quote = c.g.quote(underlying, ix)
    return refresh(
        c,
        underlying,
        c.g.history(underlying, ix, "1m"),
        c.g.history(underlying, ix, "5m"),
        quote,
        keep_alive=False,
    )
