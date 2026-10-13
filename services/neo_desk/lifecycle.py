"""Native exposure management remains active independently of the signal subprocess."""

from datetime import datetime
from decimal import Decimal as D

from database import neo_desk_db as desk
from database import strategy_module_db as native
from services.strategy_module import engine, state
from utils.keyed_locks import KeyedLocks

from .fees import estimate
from .risk_adapter import evaluate
from .types import IST

owner_locks = KeyedLocks(name="neo-owner-controls", reentrant=True)


def _owned(owner, trade_id):
    config = desk.view(owner)
    try:
        rid = int(trade_id)
    except (TypeError, ValueError):
        raise ValueError("This is not the terminal-owned trade.") from None
    protection = desk.get_run_protection(owner, rid)
    if protection is None:
        raise ValueError("This is not the terminal-owned trade.")
    row = native.get_run(rid)
    if not row or not native.get_strategy(row.strategy_id, owner) or row.stopped_at is not None:
        raise ValueError("Owned exposure has not been reconciled as active.")
    snap = state.get_run_state(rid)
    if not snap:
        raise ValueError("Native run recovery is incomplete. Reconcile before changing protection.")
    return {**config, "protection": protection}, snap


def evaluate_schedule(now, owned_state, config=None):
    if now.tzinfo is None:
        raise ValueError("Square-off requires a timezone-aware clock.")
    if not owned_state or not owned_state.get("legs"):
        return False
    clock = now.astimezone(IST)
    entered = config.get("execute_at") if isinstance(config, dict) else None
    day = datetime.fromisoformat(entered).astimezone(IST) if entered else clock
    deadline = day.replace(hour=15, minute=29, second=0, microsecond=0)
    return clock >= deadline


def request_owned_exit(owner_id, trade_id, reason, request_id):
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
        return {"ok": False, "error": "An exit request identity is required."}
    with owner_locks.hold(owner_id):
        try:
            config, snap = _owned(owner_id, trade_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        # stop_run cancels working entry remainders and claims only exact confirmed exposure.
        # Its native claim and originating-mode dispatcher handle duplicate/refused/late fills.
        result = engine.stop_run(int(trade_id), owner_id, reason=reason)
        desk.configure(
            owner_id,
            status=reason
            if result.get("ok")
            else result.get("error") or "Exit remains managed; retry reconciliation.",
        )
        return result


def observed_price(owner, symbol, exchange):
    from database.auth_db import get_auth_token
    from services.quotes_service import get_quotes
    from services.depth_service import get_depth
    from time import monotonic

    auth = get_auth_token(owner)
    if not auth:
        return None
    started = monotonic()
    if exchange == "NFO":
        ok, response, _ = get_depth(symbol, exchange, auth_token=auth, broker="kotak")
        bids = response.get("data", {}).get("bids", []) if ok else []
        value = bids[0].get("price") if bids and bids[0].get("quantity", 0) > 0 else None
    else:
        ok, response, _ = get_quotes(symbol, exchange, auth_token=auth, broker="kotak")
        value = response.get("data", {}).get("ltp") if ok else None
    if monotonic() - started > 5:
        return None
    # Broker reads are used only inside the cash session; a last-known quote after close is not live.
    now = datetime.now(IST)
    if now.weekday() >= 5 or not 555 <= now.hour * 60 + now.minute < 930:
        return None
    return D(str(value)) if value and D(str(value)).is_finite() and D(str(value)) > 0 else None


def update_protection(owner_id, trade_id, changes, *, quote_provider=None, now=None):
    allowed = {
        "option_stop",
        "option_target",
        "cash_trail_enabled",
        "cash_activation",
        "cash_distance",
    }
    if not isinstance(changes, dict) or not changes or set(changes) - allowed:
        raise ValueError("Choose option SL, target and cash trailing controls only.")
    config, snap = _owned(owner_id, trade_id)
    leg = snap["legs"].get("1", {})
    provider = quote_provider or (
        lambda symbol, exchange: observed_price(owner_id, symbol, exchange)
    )
    bid = provider(leg["symbol"], leg["exchange"])
    if bid is None:
        raise ValueError("A fresh option bid is required to edit protection.")
    position_ref = leg.get("position_ref")
    with owner_locks.hold(owner_id):
        config, snap = _owned(owner_id, trade_id)
        leg = snap["legs"].get("1", {})
        if (
            leg.get("entry_avg") is None
            or not leg.get("qty")
            or leg.get("exit_claim_token")
            or leg.get("exit_order_id")
            or snap.get("stopping")
            or leg.get("position_ref") != position_ref
        ):
            raise ValueError("A confirmed owned fill without a pending exit is required.")
        p = dict(config["protection"])
        tick = D(p["tick_size"])
        entry = D(str(leg["entry_avg"]))
        qty = int(leg["qty"])
        for key, value in changes.items():
            if key == "cash_trail_enabled":
                if not isinstance(value, bool):
                    raise ValueError("Choose whether the cash trail is enabled.")
                if p.get("net_floor") is not None and not value:
                    raise ValueError("An earned cash trail cannot be disabled.")
                p[key] = value
                continue
            try:
                v = D(str(value))
            except Exception as e:
                raise ValueError(
                    "Protection prices and cash values must be positive numbers."
                ) from e
            if not v.is_finite() or v <= 0:
                raise ValueError("Protection prices and cash values must be positive numbers.")
            if key in ("option_stop", "option_target") and v % tick:
                raise ValueError("Choose a price on the option tick grid.")
            if key == "option_stop":
                if v >= bid:
                    raise ValueError("The option SL must be below the current executable bid.")
                if p.get("option_stop") is not None and v < D(p["option_stop"]):
                    raise ValueError("The option SL cannot loosen existing protection.")
                exit = max(tick, v - D(".50"))
                loss = (
                    (entry - exit) * qty + estimate("BUY", entry, qty) + estimate("SELL", exit, qty)
                )
                if loss > 500:
                    raise ValueError("The option SL exceeds the planned ₹500 loss guard.")
            if key == "option_target" and v <= max(entry, bid):
                raise ValueError("The option target must be above entry and the current bid.")
            p[key] = str(v)
        if D(p.get("cash_activation", "1000")) <= D(p.get("cash_distance", "250")):
            raise ValueError("Cash trailing activation must exceed its distance.")
        desk.save_run_protection(owner_id, int(trade_id), p)
        desk.configure(owner_id, status="Manual protection saved; exits remain managed.")
        return p


def day_performance(owner, day, mode=None):
    config = desk.view(owner)
    sid = config.get("strategy_id")
    if not sid:
        return D(0), 0
    net = D(0)
    count = 0
    for run in native.list_runs(sid, limit=200):
        stamp = run.get("started_at")
        if (
            not stamp
            or datetime.fromisoformat(stamp).astimezone(IST).date() != day
            or run.get("mode") != (mode or config["mode"])
        ):
            continue
        orders = native.list_orders(run["id"])
        accepted = False
        for o in orders:
            filled = int(o.get("filled_qty") or 0)
            if o.get("kind") == "entry" and (
                filled or o.get("status") in ("pending", "open", "complete")
            ):
                accepted = True
            if filled and o.get("avg_fill_price"):
                net -= estimate(o.get("action"), D(str(o["avg_fill_price"])), filled)
        if accepted:
            count += 1
        net += D(str(run.get("pnl_realized") or 0))
    return net, count


def run_schedule_once(owner_id, *, now=None, run_id=None):
    now = now or datetime.now(IST)
    config = desk.view(owner_id)
    rid = run_id or config.get("run_id")
    if rid and evaluate_schedule(
        now, state.get_run_state(rid), desk.get_run_protection(owner_id, rid)
    ):
        return request_owned_exit(
            owner_id, str(rid), "15:29 IST intraday square-off", f"schedule-{rid}"
        )


def manage_once(owner_id, *, now=None, quote_provider=None, run_id=None):
    now = now or datetime.now(IST)
    config = desk.view(owner_id)
    rid = run_id or config.get("run_id")
    if not rid:
        return
    row = native.get_run(rid)
    if row and row.stopped_at is not None:
        with owner_locks.hold(owner_id):
            if desk.view(owner_id).get("run_id") == rid:
                desk.configure(
                    owner_id,
                    run_id=None,
                    pending=False,
                    status="Owned run is flat; awaiting the next confirmed setup.",
                )
        return
    if evaluate_schedule(now, state.get_run_state(rid), desk.get_run_protection(owner_id, rid)):
        return run_schedule_once(owner_id, now=now, run_id=rid)
    snap = state.get_run_state(rid)
    if not snap:
        desk.configure(
            owner_id,
            activation="Stopped",
            status="Native ownership recovery is incomplete; entries remain stopped.",
        )
        return
    leg = snap["legs"].get("1", {})
    if not leg.get("entry_avg") or not leg.get("qty") or snap.get("stopping"):
        return
    position_ref = leg.get("position_ref")
    provider = quote_provider or (
        lambda symbol, exchange: observed_price(owner_id, symbol, exchange)
    )
    # Quote reads hold neither the owner control lock nor the native run lock.
    index = provider("NIFTY", "NSE_INDEX")
    bid = provider(leg["symbol"], leg["exchange"])
    with owner_locks.hold(owner_id):
        current = desk.view(owner_id)
        fresh = state.get_run_state(rid)
        leg = (fresh or {}).get("legs", {}).get("1", {})
        if (
            not fresh
            or fresh.get("stopping")
            or leg.get("position_ref") != position_ref
            or not leg.get("qty")
            or leg.get("exit_claim_token")
            or leg.get("exit_order_id")
        ):
            return
        row = native.get_run(rid)
        if not row or row.stopped_at is not None:
            return
        net, _ = day_performance(owner_id, now.astimezone(IST).date(), mode=str(row.mode))
        # Current open entry costs are included once in running net by the core.
        net += estimate("BUY", D(str(leg["entry_avg"])), int(leg["qty"]))
        protection = desk.get_run_protection(owner_id, rid)
        if protection is None:
            return
        p, reason = evaluate(protection, leg, index, bid, net)
        p["observed_at"] = now.isoformat()
        p["option_bid"] = str(bid) if bid is not None else None
        desk.save_run_protection(owner_id, rid, p)
        if reason:
            return request_owned_exit(owner_id, str(rid), reason, f"risk-{rid}")


def manage_all_owned(owner_id, *, now=None, quote_provider=None, schedule_only=False):
    c = desk.view(owner_id)
    managed = desk.managed_run_ids(owner_id)
    if any(rid != c.get("run_id") for rid in managed):
        desk.configure(
            owner_id,
            activation="Stopped",
            status="An older owned run requires reconciliation; new entries stopped, exact exits remain managed.",
        )
    for rid in managed:
        if schedule_only:
            run_schedule_once(owner_id, now=now, run_id=rid)
        else:
            manage_once(owner_id, now=now, quote_provider=quote_provider, run_id=rid)
    # Clear a closed current pointer even when no active protection row remains.
    if c.get("run_id") and c["run_id"] not in managed:
        manage_once(owner_id, now=now, quote_provider=quote_provider)


def recover_provider():
    for (owner,) in desk.db_session.query(desk.NeoDesk.owner).all():
        c = desk.view(owner)
        if c.get("pending") and not c.get("run_id") and c.get("strategy_id"):
            strategy = native.get_strategy(c["strategy_id"], owner)
            rid = strategy.current_run_id if strategy else None
            row = native.get_run(rid) if rid else None
            p = c.get("protection") or {}
            claims = desk.db_session.query(desk.NeoClaim).filter_by(owner=owner, run_id=None).all()
            matches = [
                claim
                for claim in claims
                if claim.setup.get("execute_at") == p.get("execute_at")
                and claim.setup.get("profile") == p.get("profile")
            ]
            orders = native.list_orders(rid) if rid else []
            entries = [o for o in orders if o.get("kind") == "entry"]
            exact = (
                len(entries) == 1
                and entries[0].get("symbol") == p.get("symbol")
                and entries[0].get("exchange") == p.get("exchange")
                and entries[0].get("action") == "BUY"
                and int(entries[0].get("qty") or 0) == p.get("quantity")
            )
            if (
                row
                and row.stopped_at is None
                and row.trigger_source == "neo_confirmed_setup"
                and row.mode == p.get("mode")
                and len(matches) == 1
                and exact
            ):
                desk.bind(owner, matches[0].signal_key, rid, p)
        desk.configure(
            owner,
            activation="Stopped",
            status="Application restarted; owned exits restored, new entries require Start.",
        )


def management_pass(schedule_only=False):
    from utils.db_sessions import remove_all_scoped_sessions
    from utils.logging import get_logger

    try:
        owners = [owner for (owner,) in desk.db_session.query(desk.NeoDesk.owner).all()]
        for owner in owners:
            try:
                manage_all_owned(owner, schedule_only=schedule_only)
            except Exception:
                get_logger(__name__).exception("Neo Desk protection pass failed")
                desk.db_session.rollback()
                desk.configure(
                    owner,
                    activation="Stopped",
                    status="Protection check failed. Inspect the native run and broker position immediately.",
                )
    finally:
        from .views import publish_owner

        for owner in locals().get("owners", []):
            publish_owner(owner)
        remove_all_scoped_sessions()


def start_management():
    from services.strategy_module.scheduler import get_scheduler

    desk.init_db()
    recover_provider()
    from .research_jobs import recover_jobs
    recover_jobs()
    scheduler = get_scheduler()
    if scheduler is None:
        raise RuntimeError("Native strategy scheduler is unavailable; entries cannot be started.")
    scheduler.add_job(
        management_pass,
        "interval",
        seconds=1,
        id="neo-owned-protection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        management_pass,
        "interval",
        seconds=1,
        id="neo-independent-squareoff",
        kwargs={"schedule_only": True},
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
