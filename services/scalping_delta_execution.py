"""Delta terminal policy: post-only entries/targets, reduce-only market protection.

The journal is committed before order submission. A transport failure leaves an
unresolved intent, which must be reconciled by client ID before another order.
Only this terminal's pending orders are canceled; position reads must succeed.
"""
import hashlib
import json
import math
import uuid
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from sqlalchemy import Column, Integer, String
from database.scalping_db import Base, db_session
from utils.smart_order_guard import SymbolLocks

locks = SymbolLocks(name="scalping-delta")


class Intent(Base):
    __tablename__ = "scalping_delta_intent"
    id = Column(Integer, primary_key=True)
    account = Column(String(64), nullable=False, index=True)
    symbol = Column(String(60), nullable=False)
    product = Column(String(10), nullable=False)
    client_id = Column(String(32), nullable=False, unique=True)
    order_id = Column(String(80), nullable=True)
    purpose = Column(String(10), nullable=False)
    status = Column(String(16), nullable=False, default="unknown")


def init_db():
    from database.scalping_db import engine
    Intent.__table__.create(engine, checkfirst=True)


def account(auth):
    return hashlib.sha256(auth.encode()).hexdigest()


def pending(symbol, product, auth):
    return db_session.query(Intent).filter_by(account=account(auth), symbol=symbol, product=product).filter(Intent.status.in_(["unknown", "open", "filled"])).all()


def record(symbol, product, auth, purpose):
    row = Intent(account=account(auth), symbol=symbol, product=product,
                 client_id="scalp-" + uuid.uuid4().hex[:24], purpose=purpose, status="unknown")
    db_session.add(row)
    db_session.commit()  # Fail BEFORE submission if durability cannot be established.
    return row


def update(row, status, order_id=None):
    row.status = status
    if order_id is not None:
        row.order_id = str(order_id)
    db_session.commit()


def leverage_value(value):
    if value is None:
        return 25
    if isinstance(value, bool):
        raise ValueError("Leverage must be a whole number from 1 to 200")
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n != n.to_integral_value() or not 1 <= n <= 200:
            raise ValueError()
        return int(n)
    except Exception as exc:
        raise ValueError("Leverage must be a whole number from 1 to 200") from exc


def quote(symbol, exchange, auth):
    from broker.deltaexchange.api.data import BrokerData
    return BrokerData(auth).get_quotes(symbol, exchange)


def maker_price(symbol, exchange, action, auth, target=0):
    book = quote(symbol, exchange, auth)
    bid, ask = float(book.get("bid", 0)), float(book.get("ask", 0))
    if not all(math.isfinite(v) and v > 0 for v in (bid, ask)) or bid >= ask:
        raise ValueError("A valid bid/ask is required for a post-only order; no market fallback")
    price = bid if action == "BUY" else ask
    if target:
        step = contract_tick(symbol, exchange)
        rounded = (Decimal(str(target)) / step).to_integral_value(rounding=ROUND_FLOOR if action == "BUY" else ROUND_CEILING) * step
        price = min(price, float(rounded)) if action == "BUY" else max(price, float(rounded))
    return price


def contract_tick(symbol, exchange):
    from database.token_db import get_symbol_info
    info = get_symbol_info(symbol, exchange)
    tick = Decimal(str(getattr(info, "tick_size", 0) or 0))
    if not tick.is_finite() or tick <= 0:
        raise ValueError("Delta tick size unavailable; target order blocked")
    return tick


def entry_order(data, leverage, auth):
    lev = leverage_value(leverage)
    return {**data, "pricetype": "LIMIT", "post_only": True, "leverage": lev,
            "price": maker_price(data["symbol"], data["exchange"], data["action"], auth)}


def protection(data, config, tick):
    """Derive initial protection from the submitted maker price, using Decimal ticks."""
    entry = Decimal(str(data["price"]))
    tick = Decimal(str(tick or 0))
    long = data["action"] == "BUY"
    def rounded(p, up):
        if tick > 0:
            p = (p / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick
        if not p.is_finite() or p <= 0:
            raise ValueError("SL/target must have a positive price")
        return p
    def distance(field, unit):
        n = Decimal(str(config.get(field, "")))
        if not n.is_finite() or n <= 0:
            raise ValueError("Enter a positive stop-loss/target distance")
        return entry * n / 100 if config.get(unit) == "PCT" else n
    stop = target = Decimal(0)
    if config.get("slOn"):
        d = distance("slValue", "slUnit")
        stop = rounded(entry - d if long else entry + d, long)
        if (long and stop >= entry) or (not long and stop <= entry):
            raise ValueError("SL must be beyond one tick on the loss side of entry")
    if config.get("tgtOn"):
        if config.get("tgtUnit") == "RR":
            if not stop:
                raise ValueError("Initial 1:2 target requires a stop-loss")
            d = 2 * abs(entry - stop)
        else:
            d = distance("tgtValue", "tgtUnit")
        target = rounded(entry + d if long else entry - d, long)
    return {"symbol": data["symbol"], "exchange": data["exchange"], "product": data["product"],
            "mode": "live", "side": data["action"], "entry_price": float(entry),
            "quantity": data["quantity"], "initial_sl": float(stop), "current_sl": float(stop),
            "target": float(target), "highest_price": float(entry), "lowest_price": float(entry),
            "trailing_enabled": False, "trailing_step": 0, "is_active": True, "exit_reason": ""}


def request(path, auth, **kwargs):
    from broker.deltaexchange.api.order_api import get_api_response
    return get_api_response(path, auth, **kwargs)


def reconcile(row, auth):
    result = request(f"/v2/orders/client_order_id/{row.client_id}", auth, method="GET")
    if not result.get("success") or not isinstance(result.get("result"), dict):
        # An unknown POST outcome is NOT proof of rejection, even if GET is not yet found.
        raise RuntimeError("Delta order outcome unresolved; keeping protection and blocking duplicate orders")
    order = result["result"]
    state = order.get("state")
    if state not in ("open", "pending", "closed", "cancelled"):
        raise RuntimeError("Delta returned an unknown order state")
    status = "open" if state in ("open", "pending") else "done"
    # After this confirmed terminal state, /v2/positions supplies the authoritative
    # residual size (including any late entry fills) before another reduction.
    update(row, status, order.get("id"))
    return order


def cancel(row, auth):
    order = reconcile(row, auth)
    if row.status in ("done", "filled"):
        return
    result = request("/v2/orders", auth, method="DELETE", payload=json.dumps({"id": order["id"], "product_id": order["product_id"]}))
    if not result.get("success"):
        raise RuntimeError("Delta cancellation unconfirmed; protection retained")
    reconcile(row, auth)
    if row.status != "done":
        raise RuntimeError("Delta order still open after cancellation")


def net_quantity(symbol, exchange, product, auth):
    # Delta documents up to 10s lag on /positions/margined. The product-scoped
    # /positions endpoint reports real-time size and is required for closures.
    from database.token_db import get_token
    token = get_token(symbol, exchange)
    if not token:
        raise ValueError("Unknown Delta contract")
    resp = request("/v2/positions", auth, method="GET", params={"product_id": int(token)})
    if not resp.get("success") or not isinstance(resp.get("result"), dict):
        raise RuntimeError("Delta position unavailable; protection retained")
    raw = resp["result"].get("size")
    if isinstance(raw, bool):
        raise RuntimeError("Invalid Delta position quantity")
    try:
        qty = Decimal(str(raw))
        if not qty.is_finite() or qty != qty.to_integral_value():
            raise ValueError()
    except Exception as exc:
        raise RuntimeError("Invalid Delta position quantity") from exc
    return int(qty)


def submit(data, auth, api_key, purpose):
    row = record(data["symbol"], data["product"], auth, purpose)
    data = {**data, "client_order_id": row.client_id}
    # Validate without risking an implicit mode switch in the middle of an exit.
    from services.place_order_service import validate_order_data, place_order_with_auth
    original = {**data, "apikey": api_key}
    valid, validated, error = validate_order_data(original)
    if not valid:
        update(row, "rejected")
        raise ValueError(error)
    ok, response, code = place_order_with_auth(validated, auth, "deltaexchange", original, force_live=True)
    if ok and response.get("orderid"):
        update(row, "open", response["orderid"])
    elif response.get("submission_uncertain") is False:
        update(row, "rejected")
    else:
        # Service error strings may conceal a transport timeout. Resolve by client ID;
        # never auto-retry an uncertain submission, even across server restarts.
        try:
            reconcile(row, auth)
        except RuntimeError:
            raise RuntimeError("Order was not confirmed; reconcile the Delta order before retrying")
    return ok, response, code


def place_entry(data, config, leverage, auth, api_key, *, verified_defaults=None):
    symbol, exchange, product = data["symbol"], data["exchange"], data["product"]
    with locks.hold(symbol, exchange, product) as held:
        if not held:
            raise RuntimeError("Another order for this contract is being processed")
        for row in pending(symbol, product, auth):
            reconcile(row, auth)
        if pending(symbol, product, auth) or net_quantity(symbol, exchange, product, auth):
            raise ValueError("Manage the existing Delta position/order before starting another entry on this contract")
        data = entry_order(data, leverage, auth)
        if verified_defaults and not math.isclose(
            data['price'], verified_defaults['entry'], rel_tol=0, abs_tol=1e-9
        ):
            raise ValueError('Maker price changed; refresh the defaults before submitting')
        from database.token_db import get_symbol_info
        info = get_symbol_info(symbol, exchange)
        state = protection(data, config, getattr(info, "tick_size", 0))
        if verified_defaults and any(
            not math.isclose(state[key], verified_defaults[price], rel_tol=0, abs_tol=1e-9)
            for key, price in (('initial_sl', 'stop'), ('target', 'target'))
        ):
            raise ValueError('Protection prices changed; refresh the defaults before submitting')
        from database.scalping_db import upsert_sl_state, track_symbol
        if not upsert_sl_state(state) or not track_symbol(symbol, exchange, product, mode="live"):
            raise RuntimeError("Protection could not be saved; entry blocked")
        ok, resp, code = submit(data, auth, api_key, "entry")
        return ok, {**resp, "entry_price": data["price"], "protection_saved": True, "leverage": data["leverage"], "execution": "post_only"}, code


def manage_exit(state, reason, auth, api_key, on_flat=None):
    """Return True ONLY after no owned pending entry/exit remains and position is flat.

    Called under tick cooldown, including while a maker target is pending. Stops
    cancel owned entry/target remainders before re-reading the quantity to reduce.
    """
    symbol, exchange, product = state["symbol"], state["exchange"], state["product"]
    with locks.hold(symbol, exchange, product) as held:
        if not held:
            return False
        checked = authoritative_state(state, reason)
        if checked is None:
            return False
        state, reason = checked
        reason = requested_exit(state, reason)
        rows = pending(symbol, product, auth)
        emergency = reason in ("sl", "close")
        for row in rows:
            try:
                reconcile(row, auth)
            except RuntimeError:
                # A maker read/cancel failure must not block a reduce-only stop.
                # Unknown market closures still block duplicate market orders.
                if not emergency or row.purpose not in ("entry", "target"):
                    raise
        rows = pending(symbol, product, auth)
        if reason in ("sl", "close", "target"):
            for row in rows:
                if row.purpose == "entry" or (reason in ("sl", "close") and row.purpose == "target"):
                    try:
                        cancel(row, auth)
                    except RuntimeError:
                        if not emergency:
                            raise
        qty = net_quantity(symbol, exchange, product, auth)
        rows = pending(symbol, product, auth)
        if not qty:
            # An unfilled entry must retain its protection; a reduce-only exit
            # left after flattening is canceled to avoid affecting a later trade.
            if any(row.purpose == "entry" for row in rows):
                return False
            for row in rows:
                if row.status == "filled":
                    update(row, "done")
                else:
                    cancel(row, auth)
            if on_flat:
                on_flat()
            else:
                from database.scalping_db import delete_sl_state
                delete_sl_state(symbol, exchange, product, mode="live")
            return True
        if not reason:
            return False
        if any(row.purpose != "entry" and not (emergency and row.purpose == "target") for row in rows):
            return False  # Resting/unknown exit exists: never send a duplicate.
        action = "SELL" if qty > 0 else "BUY"
        data = {"strategy": "SCALPING", "symbol": symbol, "exchange": exchange, "product": product,
                "action": action, "quantity": abs(qty), "reduce_only": True, "pricetype": "MARKET"}
        if reason == "target":
            data.update(pricetype="LIMIT", post_only=True,
                        price=maker_price(symbol, exchange, action, auth, float(state["target"])))
        submit(data, auth, api_key, reason)
        return False  # An order acknowledgement is not a fill confirmation.


def authoritative_state(snapshot, reason):
    """Validate a queued trigger against protection after acquiring its execution lock."""
    from database.scalping_db import ScalpingSLState, _to_dict
    row = db_session.query(ScalpingSLState).filter_by(symbol=snapshot["symbol"], exchange=snapshot["exchange"], product=snapshot["product"], mode="live", is_active=True).first()
    if reason == "close":
        return (_to_dict(row) if row else snapshot), reason
    if row is None:
        return None  # User cleared the protection; never recreate it from a queued tick.
    if snapshot.get("generation") and snapshot["generation"] != row.generation:
        return None  # This is a later trade on the same contract.
    if reason == "target" and (not row.target or row.target != snapshot.get("target")):
        reason = None
    if reason == "sl" and row.exit_reason not in ("sl", "close") and row.current_sl != snapshot.get("current_sl"):
        reason = None
    return _to_dict(row), reason


def requested_exit(state, reason):
    from database.scalping_db import ScalpingSLState, upsert_sl_state
    row = db_session.query(ScalpingSLState).filter_by(symbol=state["symbol"], exchange=state["exchange"], product=state["product"], mode="live").first()
    if row and row.exit_reason in ("sl", "close"):
        return row.exit_reason
    if row and row.exit_reason == "target" and reason not in ("sl", "close"):
        return "target"
    if reason in ("sl", "close", "target"):
        if not upsert_sl_state({"symbol":state["symbol"],"exchange":state["exchange"],"product":state["product"],"mode":"live","exit_reason":reason,"is_active":True}):
            raise RuntimeError("Unable to persist the closure request")
    return reason


def edit_protection(symbol, exchange, product, auth, callback, new_target=None, clearing=False):
    """Cancel an old maker target before changing/removing its saved protection."""
    from database.scalping_db import ScalpingSLState
    with locks.hold(symbol, exchange, product) as held:
        if not held:
            raise RuntimeError("Another order for this contract is being processed")
        current = db_session.query(ScalpingSLState).filter_by(symbol=symbol, exchange=exchange, product=product, mode="live").first()
        if current and current.exit_reason in ("sl", "close"):
            raise ValueError("A protective closure is pending; wait for it to finish")
        changed = clearing or (current and new_target is not None and new_target != current.target)
        if changed:
            for row in pending(symbol, product, auth):
                reconcile(row, auth)
                if row.purpose == "entry" and row.status == "open":
                    raise ValueError("Cancel the pending entry before clearing/changing its target")
                if row.purpose == "target" and row.status == "open":
                    cancel(row, auth)
                if row.status in ("unknown", "filled"):
                    raise ValueError("An exit is settling; wait for confirmed position state")
            if current and current.exit_reason == "target":
                current.exit_reason = ""
                db_session.commit()
        return callback()
