"""Session-authenticated Kotak home desk. All mutations retain Flask CSRF protection."""

import csv
import io
from datetime import datetime
from functools import wraps

from flask import Blueprint, Response, jsonify, request, session

from services.kotak_assistant import runtime, setup_live
from services.kotak_assistant.analysis import (
    IST,
    analyse,
    atr,
    completed,
    fill_time,
    journal,
    plan,
    snap,
)
from services.kotak_assistant.execution import same
from services.kotak_assistant.risk_policy import plan_cash
from services.kotak_assistant.ticket_plans import trend_plan

kotak_assistant_bp = Blueprint("kotak_assistant", __name__, url_prefix="/kotak-assistant/api")


def guarded(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not session.get("user"):
            return jsonify(status="error", message="Not authenticated"), 401
        if session.get("broker") != "kotak":
            return jsonify(status="error", message="Connect Kotak Neo to use this desk"), 403
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError, TypeError) as e:
            return jsonify(status="error", message=str(e)), 409
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Kotak home request failed")
            return jsonify(
                status="error", message="Kotak data unavailable; refresh or reconnect your broker"
            ), 503
        finally:
            runtime.cleanup_sessions()

    return inner


def current_mode():
    from database.settings_db import get_analyze_mode

    return "analyze" if get_analyze_mode() else "live"


def desk(mode=None):
    c = runtime.controller(session["user"], mode or current_mode())
    c.g.credentials()
    return c


def action_data(entry=False):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    mode = data.get("mode")
    if mode not in ("live", "analyze"):
        raise ValueError("Execution mode required")
    if entry and mode != current_mode():
        raise ValueError("Mode changed; refresh the displayed ticket")
    return desk(mode), data


def public_state(c):
    d = c.state()
    result = {
        k: d.get(k)
        for k in ("settings", "mode", "book_time", "heartbeat", "positions", "orders", "day")
    }
    result["trades"] = [{**t, "mode": c.g.mode} for t in d["trades"].values()]
    result["scope"] = c.scope
    return result


@kotak_assistant_bp.get("/broker-monitor")
@guarded
def broker_monitor():
    # Always the actual Kotak account, even while the order ticket is in Paper.
    response = jsonify(status="success", data=runtime.monitor(session["user"]).snapshot())
    response.headers["Cache-Control"] = "no-store"
    return response


@kotak_assistant_bp.get("/snapshot")
@guarded
def snapshot():
    c = desk()
    result = public_state(c)
    result["error"] = None
    # Cache books for UI polling; the monitor and entry/exit paths use fresh reads.
    try:
        c.g.cached("ui_reconcile", 5, c.reconcile)
        result = public_state(c)
    except Exception as e:
        result["error"] = str(e)
    if c.g.mode == "analyze":
        live = desk("live")
        result["live_trades"] = [
            t for t in public_state(live)["trades"] if t["status"] not in ("closed", "rejected")
        ]
    underlying = request.args.get("underlying", "NIFTY")
    if underlying not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        raise ValueError("Choose NIFTY, BANKNIFTY or SENSEX")
    exchange = "BFO" if underlying == "SENSEX" else "NFO"
    ix = "BSE_INDEX" if underlying == "SENSEX" else "NSE_INDEX"
    strategy = request.args.get("strategy", "trend")
    signal_mode = request.args.get("signal_mode", "confirmed")
    if strategy not in ("trend", "opening_reversal") or signal_mode not in ("confirmed", "early"):
        raise ValueError("Choose a supported strategy and mode")
    result.update(
        underlying=underlying,
        exchange=exchange,
        index_quote=None,
        analysis={"action": "WAIT", "reason": "Data unavailable", "zones": []},
        chain=None,
        setup={
            "strategy": strategy,
            "version": "1.0",
            "mode": signal_mode,
            "stage": "waiting_history",
            "reason": "Waiting for index data",
            "evidence": [],
            "eligible": False,
        },
        execution_readiness=[],
    )
    try:
        result["index_quote"] = c.g.quote(underlying, ix)
        now = c.clock()
        one = c.g.history(underlying, ix, "1m")
        five = c.g.history(underlying, ix, "5m")
        result["analysis"] = analyse(one, five, now)
        result["setup"] = setup_live.refresh(
            c, underlying, one, five, result["index_quote"], strategy, signal_mode
        )
        chart = result["setup"]
        result["index_quote"] = chart.pop("current_quote", result["index_quote"])
        now = c.clock()
        # Legacy levels remain available, while the selected strategy owns its
        # advisory action. Account errors are displayed independently below.
        result["analysis"].update(
            action=("CALL" if chart.get("direction") == "CE" else "PUT")
            if chart.get("eligible")
            else "WAIT",
            reason=chart["reason"],
            setup_id=chart.get("setup_id"),
            index_entry=chart.get("index_entry"),
            invalidation=chart.get("invalidation"),
            index_target=chart.get("index_target"),
            expires=chart.get("expires"),
        )
        if not c.g.session_open(exchange, result["settings"]["cutoff"]):
            result["analysis"].update(
                action="WAIT", reason="Market closed or square-off cutoff reached"
            )
        if result.get("error") or not result.get("book_time") or now - result["book_time"] > 15:
            result["analysis"].update(action="WAIT", reason="Account data unavailable or stale")
        day = result.get("day") or {}
        blocked = (
            day.get("entry_limits", {}).get("blocked_reason")
            or day.get("halt")
            or ("Loss cooldown active" if now < day.get("cooldown_until", 0) else None)
        )
        if not day.get("risk_available", False):
            blocked = day.get("risk_error") or "Account risk reconciliation unavailable"
        if blocked:
            result["analysis"].update(action="WAIT", reason=blocked)
        result["execution_readiness"] = [
            {
                "name": "Account",
                "ready": not bool(result.get("error")),
                "reason": result.get("error") or "Account connected",
            },
            {
                "name": "Order books",
                "ready": bool(result.get("book_time") and now - result["book_time"] <= 15),
                "reason": "Broker books current"
                if result.get("book_time") and now - result["book_time"] <= 15
                else "Broker order/position data unavailable or stale",
            },
            {
                "name": "Risk policy",
                "ready": not bool(blocked),
                "reason": blocked or "Configured account limits allow entry",
            },
        ]
        expiry = request.args.get("expiry", "")
        if expiry:
            count = int(request.args.get("count", "8"))
            if not 1 <= count <= 20:
                raise ValueError("Strike window must be 1–20")
            result["chain"] = c.g.ladder(underlying, expiry, count)
            result["chain_time"] = c.g._cache[("chain", underlying, expiry, count)][0]
            selected = request.args.get("symbol", "")
            selected_pair = next(
                (
                    (row, side, row[side.lower()])
                    for row in result["chain"]["chain"]
                    for side in ("CE", "PE")
                    if (row.get(side.lower()) or {}).get("symbol") == selected
                ),
                None,
            )
            if selected_pair:
                row, side, leg = selected_pair
                contract = result["selected_contract"] = {
                    "symbol": selected,
                    "side": side,
                    "strike": row["strike"],
                    "expiry": expiry,
                    "strategy": strategy,
                    "reason": "Waiting for the selected option quote",
                }
                try:
                    meta = c.g.metadata(selected, exchange)
                    # Cash budgets need no option ATR history. Structural stops do.
                    candles = (
                        setup_live.session_bars(
                            c.g.history(selected, exchange, "1m"),
                            60,
                            c.clock(),
                            exchange,
                            setup_live._calendar(c, exchange),
                        )
                        if strategy == "trend"
                        else []
                    )
                    q = c.g.quote(selected, exchange)
                    contract["quote"] = q
                    fresh_now = c.clock()
                    if not (q.get("ask", 0) > 0 and 0 <= fresh_now - q.get("time", 0) <= 5):
                        contract["reason"] = "Fresh ask unavailable for the selected strike"
                    elif strategy == "trend" and (
                        not candles or fresh_now - candles[-1]["time"] > 125
                    ):
                        contract["reason"] = (
                            "Waiting for fresh completed candles for the selected strike"
                        )
                    else:
                        entry = snap(q["ask"], meta["tick"], True)
                        day = datetime.fromtimestamp(fresh_now, IST).date().isoformat()
                        p = (
                            plan_cash(
                                entry,
                                meta["lot"],
                                meta["tick"],
                                exchange,
                                result["settings"],
                                500,
                                3,
                                day,
                                lot=meta["lot"],
                            )
                            if strategy == "opening_reversal"
                            else trend_plan(
                                entry,
                                candles,
                                meta["lot"],
                                meta["tick"],
                                meta["lot"],
                                exchange,
                                result["settings"],
                                float(request.args.get("rr", "2")),
                                day,
                            )
                        )
                        contract.update(plan=p, reason=p["reason"])
                        if strategy == "trend" and p["fits"]:
                            result["selected_plan"] = p
                except (ValueError, TypeError, KeyError):
                    contract["reason"] = (
                        "Selected option plan unavailable; check the quote and completed candles"
                    )
            setup = {
                **result["setup"],
                "action": "CALL"
                if result["setup"].get("direction") == "CE"
                else "PUT"
                if result["setup"].get("direction") == "PE"
                else "WAIT",
            }
            candidates = []
            for row in result["chain"]["chain"]:
                leg = row.get("ce" if setup["action"] == "CALL" else "pe")
                if setup["action"] == "WAIT" or not leg:
                    continue
                bid, ask = leg.get("bid", 0), leg.get("ask", 0)
                if not 0 < bid <= ask or (ask - bid) / ask * 100 > result["settings"]["spread"]:
                    continue
                candidates.append(
                    (
                        abs(row["strike"] - result["chain"]["atm_strike"]),
                        (ask - bid) / ask,
                        -(leg.get("volume") or 0),
                        row["strike"],
                        leg,
                    )
                )
            if candidates:
                nearest = sorted(
                    {row["strike"] for row in result["chain"]["chain"]},
                    key=lambda k: abs(k - result["chain"]["atm_strike"]),
                )[:5]
                candidates = [x for x in candidates if x[3] in nearest]
                candidates.sort(key=lambda x: (x[1], x[2], x[0]))
                if candidates:
                    _, _, _, strike, leg = candidates[0]
                    meta = c.g.metadata(leg["symbol"], exchange)
                    q = c.g.quote(leg["symbol"], exchange)
                    if (
                        not q.get("ask")
                        or now - q.get("time", 0) > 5
                        or not 0 < q.get("bid", 0) <= q["ask"]
                    ):
                        result["execution_readiness"].append(
                            {
                                "name": "Option quote",
                                "ready": False,
                                "reason": "Fresh two-sided option quote unavailable",
                            }
                        )
                    elif (q["ask"] - q["bid"]) / q["ask"] * 100 > result["settings"]["spread"]:
                        result["execution_readiness"].append(
                            {
                                "name": "Option spread",
                                "ready": False,
                                "reason": "Selected option spread exceeds configured limit",
                            }
                        )
                    else:
                        entry = snap(q["ask"], meta["tick"], True)
                        ratio = float(request.args.get("rr", "2"))
                        day = datetime.fromtimestamp(now, IST).date().isoformat()
                        option_bars = setup_live.session_bars(
                            c.g.history(leg["symbol"], exchange, "1m"),
                            60,
                            now,
                            exchange,
                            setup_live._calendar(c, exchange),
                        )
                        p = (
                            plan_cash(
                                entry,
                                meta["lot"],
                                meta["tick"],
                                exchange,
                                result["settings"],
                                500,
                                3,
                                day,
                                lot=meta["lot"],
                            )
                            if strategy == "opening_reversal"
                            else trend_plan(
                                entry,
                                option_bars,
                                meta["lot"],
                                meta["tick"],
                                meta["lot"],
                                exchange,
                                result["settings"],
                                ratio,
                                day,
                            )
                        )
                        if p["fits"]:
                            result["recommendation"] = {
                                "symbol": leg["symbol"],
                                "strike": strike,
                                "side": setup["action"],
                                "lot": meta["lot"],
                                "tick": meta["tick"],
                                "plan": p,
                                "reason": "Near ATM with narrow spread; option premium plan uses the fresh ask",
                                "alternatives": [
                                    {
                                        "strike": x[3],
                                        "symbol": x[4]["symbol"],
                                        "spread": round(x[1], 3),
                                    }
                                    for x in candidates[1:4]
                                ],
                            }
                            result["execution_readiness"].append(
                                {
                                    "name": "Premium plan",
                                    "ready": p["net_rr"] >= 1.5,
                                    "reason": "Estimated net reward/risk " + str(p["net_rr"]),
                                }
                            )
                        else:
                            result["execution_readiness"].append(
                                {"name": "Premium plan", "ready": False, "reason": p["reason"]}
                            )
            elif setup["action"] != "WAIT":
                result["execution_readiness"].append(
                    {
                        "name": "Contract",
                        "ready": False,
                        "reason": "No sufficiently liquid near-ATM contract in the loaded strikes",
                    }
                )

    except Exception as e:
        result["analysis"].update(action="WAIT", reason=str(e))
    response = jsonify(status="success", data=result)
    response.headers["Cache-Control"] = "no-store"
    return response


@kotak_assistant_bp.post("/config")
@guarded
def config():
    c, data = action_data()
    return jsonify(status="success", data=c.configure(data.get("settings")))


@kotak_assistant_bp.post("/preview")
@guarded
def preview():
    c, data = action_data(True)
    return jsonify(status="success", data=c.preview(data.get("order", {})))


@kotak_assistant_bp.post("/cash-plan")
@guarded
def cash_plan():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    c = desk()
    result = plan_cash(
        data["entry"],
        data["quantity"],
        data["tick"],
        data["exchange"],
        c.state()["settings"],
        data.get("loss_budget", 500),
        data.get("target_multiple", 3),
        datetime.fromtimestamp(c.clock(), IST).date().isoformat(),
        lot=data.get("lot", 1),
    )
    response = jsonify(status="success", data=result)
    response.headers["Cache-Control"] = "no-store"
    return response


@kotak_assistant_bp.get("/setup-replay")
@guarded
def setup_replay():
    """Historical evaluation has no Coordinator reconciliation or ticket writes."""
    from datetime import timedelta

    from services.kotak_assistant.setup_review import evaluate_replay

    c = desk()
    underlying = request.args.get("underlying", "NIFTY")
    if underlying not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        raise ValueError("Choose NIFTY, BANKNIFTY or SENSEX")
    strategy = request.args.get("strategy", "trend")
    signal_mode = request.args.get("signal_mode", "confirmed")
    until = float(request.args["until"])
    if not 0 < until <= c.clock():
        raise ValueError("Replay cursor must be a historical exchange timestamp")
    day = datetime.fromtimestamp(until, IST).date()
    exchange = "BSE" if underlying == "SENSEX" else "NSE"
    ix = "BSE_INDEX" if underlying == "SENSEX" else "NSE_INDEX"
    window = setup_live._calendar(c, exchange)(day, exchange)
    if not window:
        raise ValueError("No exchange session on the selected replay date")
    start = window["start_ms"] / 1000
    one = setup_live.session_bars(
        c.g.history_range(
            underlying, ix, "1m", (day - timedelta(days=10)).isoformat(), day.isoformat()
        ),
        60,
        until,
        exchange,
        setup_live._calendar(c, exchange),
    )
    five = setup_live.session_bars(
        c.g.history_range(
            underlying, ix, "5m", (day - timedelta(days=10)).isoformat(), day.isoformat()
        ),
        300,
        until,
        exchange,
        setup_live._calendar(c, exchange),
    )
    tape = setup_live.repository(c).events(setup_live.scope_for(c, underlying), start, until)
    if len(tape) > 250000:
        raise ValueError("Recorded session exceeds replay event limit; choose an earlier cursor")
    data = evaluate_replay(
        one, five, tape, until, start, f"{exchange}:{day.isoformat()}", strategy, signal_mode
    )
    data.update(strategy=strategy, underlying=underlying)
    data["evidence"] = [*data.get("evidence", []), *data.get("replay", {}).get("limitations", [])]
    response = jsonify(status="success", data=data)
    response.headers["Cache-Control"] = "no-store"
    return response


@kotak_assistant_bp.post("/entry")
@guarded
def entry():
    c, data = action_data(True)
    result = c.enter(data.get("ticket"))
    runtime.start()
    return jsonify(status="success", data=result)


@kotak_assistant_bp.post("/exit")
@guarded
def exit_trade():
    c, data = action_data()
    result = c.exit(data.get("trade_id"), data.get("quantity"), data.get("request_id"))
    runtime.start()
    return jsonify(status="success", data=result)


@kotak_assistant_bp.post("/stop")
@guarded
def stop():
    c, data = action_data()
    return jsonify(status="success", data=c.tighten(data.get("trade_id"), data.get("sl")))


@kotak_assistant_bp.get("/journal")
@guarded
def export_journal():
    c = desk()
    selected = request.args.get("date", datetime.now(IST).date().isoformat())
    try:
        datetime.strptime(selected, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Journal date must be YYYY-MM-DD") from None
    data = c.reconcile()
    j = data["journals"].get(selected)
    if j is None:
        b = c.books()
        j = journal(b["fills"], b["positions"], selected, data["settings"]["brokerage"])
        if selected != datetime.now(IST).date().isoformat() and not j["fills"]:
            j.update(
                complete=False, reason="No archived journal or broker fills available for this date"
            )

    def safe(value):
        return (
            "'" + value
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@"))
            else value
        )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "Symbol",
            "Exchange",
            "Gross P&L",
            "Estimated net P&L",
            "Entry IST",
            "Exit IST",
            "Duration seconds",
            "Setup",
        ]
    )
    for cycle in j["cycles"]:
        writer.writerow(
            [
                safe(cycle["symbol"]),
                cycle["exchange"],
                cycle["gross"],
                cycle["net"],
                datetime.fromtimestamp(cycle["start"], IST).isoformat(),
                datetime.fromtimestamp(cycle["end"], IST).isoformat(),
                cycle["duration"],
                cycle["setup"],
            ]
        )
    writer.writerow(["Reconciliation", j["complete"], safe(j["reason"])])
    writer.writerow([])
    writer.writerow(["Individual fills"])
    writer.writerow(
        ["Symbol", "Exchange", "Side", "Quantity", "Average price", "Order ID", "Fill ID", "Time"]
    )
    for fill in j["fills"]:
        writer.writerow(
            [
                safe(fill.get(k, ""))
                for k in (
                    "symbol",
                    "exchange",
                    "action",
                    "quantity",
                    "average_price",
                    "orderid",
                    "tradeid",
                    "timestamp",
                )
            ]
        )
    writer.writerow([])
    writer.writerow(["Orders including rejections and cancellations"])
    writer.writerow(
        [
            "Symbol",
            "Exchange",
            "Side",
            "Quantity",
            "Order ID",
            "Type",
            "Status",
            "Price",
            "Stop trigger",
            "Time",
            "Broker message",
        ]
    )
    for order in data.get("orders", []):
        try:
            if (
                datetime.fromtimestamp(fill_time(order.get("timestamp")), IST).date().isoformat()
                != selected
            ):
                continue
        except (ValueError, TypeError):
            continue
        writer.writerow(
            [
                safe(order.get(k, ""))
                for k in (
                    "symbol",
                    "exchange",
                    "action",
                    "quantity",
                    "orderid",
                    "pricetype",
                    "order_status",
                    "price",
                    "trigger_price",
                    "timestamp",
                    "message",
                )
            ]
        )
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=kotak-trading-journal.csv"},
    )


@kotak_assistant_bp.post("/adopt")
@guarded
def adopt():
    c, data = action_data()
    result = c.adopt(data.get("position", {}))
    runtime.start()
    return jsonify(status="success", data=result)
