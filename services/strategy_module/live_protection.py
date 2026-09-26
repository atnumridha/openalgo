"""Broker-held Kotak stop lifecycle for fixed-stop strategy positions.

Live entry stays unavailable unless the strategy is bound to the active Kotak
connection and every leg has a fixed stop that this adapter can mirror at the
broker. The app keeps the stop order as the leg's active exit owner; ordinary
strategy exits cancel and reconcile it before sending a replacement exit.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text

from database import auth_db
from database import strategy_module_db as store
from services.strategy_module import order_dispatch, risk_adapter, state
from utils.logging import get_logger

logger = get_logger(__name__)


def _connection_for_api_key(api_key: str) -> tuple[str | None, str | None]:
    """Return the active broker and connection pinned to this exact API key."""
    owner = auth_db.verify_api_key(api_key) if api_key else None
    if not owner:
        return None, None
    try:
        with auth_db.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT bc.id, bc.broker FROM api_keys ak JOIN broker_connections bc "
                    "ON bc.id=ak.broker_connection_id AND bc.user_id=ak.user_id "
                    "WHERE ak.user_id=:owner AND bc.status IN ('connected','authenticated') "
                    "AND bc.is_revoked=0"
                ),
                {"owner": owner},
            ).mappings().first()
        if not row:
            return None, None
        return str(row["id"]), str(row["broker"] or "").lower()
    except Exception:
        logger.exception("Could not verify strategy broker connection")
        return None, None


def _active_kotak_pin(api_key: str, expected_connection_id: str) -> bool:
    """Match the live token broker and durable API-key connection at dispatch time."""
    connection_id, pinned_broker = _connection_for_api_key(api_key)
    _token, active_broker, error = order_dispatch.resolve_live_auth(api_key)
    return bool(
        not error
        and connection_id == str(expected_connection_id or "")
        and pinned_broker == "kotak"
        and str(active_broker or "").lower() == "kotak"
    )


def entry_block_reason(broker: str, strategy: dict[str, Any], api_key: str) -> str | None:
    """Check the fixed-stop Kotak path before any live entry is admitted."""
    if str(broker or "").lower() != "kotak":
        return "Broker-held strategy stops are not enabled for this broker"
    pinned_id, pinned_broker = _connection_for_api_key(api_key)
    configured_id = str(strategy.get("broker_connection_id") or "")
    if not pinned_id or not configured_id or pinned_id != configured_id or pinned_broker != "kotak":
        return "Select the connected Kotak account pinned to this strategy before live entry"
    legs = strategy.get("legs") or []
    if not legs:
        return "Live entry requires at least one leg with a fixed protective stop"
    for leg in legs:
        try:
            stop = float(leg.get("sl_pts") or 0)
        except (TypeError, ValueError):
            stop = 0
        if not math.isfinite(stop) or stop <= 0:
            return f"Leg {leg.get('id', '?')} needs a positive per-leg stop-loss"
        if leg.get("trail"):
            return "Live entry currently supports fixed stops; disable per-leg trailing first"
    if strategy.get("trail_sl_to_entry"):
        return "Live entry currently supports fixed stops; disable trail-to-entry first"
    return None


def _position_stop(run_id: int, leg_id: Any, position_ref: str) -> tuple[dict, dict, Any] | None:
    run = store.get_run(run_id)
    if run is None or run.mode != "live" or str(run.broker or "").lower() != "kotak":
        return None
    strategy_row = store.get_strategy_unscoped(run.strategy_id)
    snapshot = state.get_run_state(run_id)
    primary = (snapshot.get("legs") or {}).get(str(leg_id)) if snapshot else None
    if strategy_row is None or primary is None:
        return None
    leg = _owner_for_position(primary, position_ref)
    if leg is None:
        return None
    if leg.get("status") != "open" or int(leg.get("qty") or 0) <= 0:
        return None
    strategy = store.strategy_to_dict(strategy_row)
    strategy["user_id"] = str(strategy_row.user_id)
    return strategy, leg, store.run_to_dict(run)


def _owner_for_position(primary: dict[str, Any], position_ref: str) -> dict[str, Any] | None:
    """Return a managed primary or outgoing signal-flip owner by incarnation."""
    owner = _owner_state_for_position(primary, position_ref)
    if owner is None:
        return None
    if owner is primary:
        return primary
    # Superseded state intentionally stores only ownership facts. It is the
    # same configured leg/instrument, but has its own side, entry and size.
    return {**primary, **owner, "leg_id": primary.get("leg_id"), "status": "open"}


def _owner_state_for_position(primary: dict[str, Any], position_ref: str) -> dict[str, Any] | None:
    if primary.get("position_ref") == position_ref:
        return primary
    outgoing = primary.get("superseded")
    if isinstance(outgoing, dict) and outgoing.get("position_ref") == position_ref:
        return outgoing
    return None


def _verify_working_stop(
    api_key: str, broker_order_id: str, expected: dict[str, Any]
) -> dict[str, Any] | None:
    """Require exact broker-order-book evidence for a resting stop."""
    auth_token, broker, error = order_dispatch.resolve_live_auth(api_key)
    if error or broker != "kotak":
        return None
    from services.orderbook_service import get_orderbook_with_auth

    try:
        ok, response, _ = get_orderbook_with_auth(auth_token, broker, None)
    except Exception:
        logger.exception("Could not verify Kotak protective order %s", broker_order_id)
        return None
    payload = response if isinstance(response, dict) else {}
    data = payload.get("data")
    orders = data.get("orders") if isinstance(data, dict) else data
    if not ok or not isinstance(orders, list):
        return None
    for order in orders:
        if not isinstance(order, dict) or str(order.get("orderid") or "") != broker_order_id:
            continue
        try:
            quantity_ok = int(order.get("quantity") or 0) == int(expected["quantity"])
            trigger_ok = math.isclose(
                float(order.get("trigger_price") or 0),
                float(expected["trigger_price"]),
                rel_tol=0,
                abs_tol=0.00001,
            )
        except (TypeError, ValueError):
            return None
        if (
            str(order.get("order_status") or "").strip().lower() in {"open", "trigger pending"}
            and str(order.get("symbol") or "") == expected["symbol"]
            and str(order.get("exchange") or "").upper() == expected["exchange"].upper()
            and str(order.get("action") or "").upper() == expected["action"]
            and str(order.get("pricetype") or "").upper() == "SL"
            and str(order.get("product") or "").upper() == expected["product"].upper()
            and quantity_ok
            and trigger_ok
        ):
            return order
    return None


def protect_entry_fill(
    run_id: int,
    leg_id: Any,
    position_ref: str,
    *,
    entry_order_id: int,
    entry_is_terminal: bool,
) -> bool:
    """Protect a confirmed Kotak fill; partial entries are cancelled first."""
    current = _position_stop(run_id, leg_id, position_ref)
    if current is None:
        return False
    strategy, leg, run = current
    api_key = _api_key_for(strategy["id"])
    if not api_key or not _active_kotak_pin(api_key, str(run.get("broker_connection_id") or "")):
        _failure(run, strategy, leg, "The strategy's pinned Kotak connection is unavailable")
        return False

    if not entry_is_terminal:
        entry = store.get_order(entry_order_id)
        if entry is None or not entry.broker_order_id:
            _failure(run, strategy, leg, "Partial entry has no exact broker order reference")
            return False
        entry_broker_order_id = str(entry.broker_order_id)
        cancelled = order_dispatch.cancel_order(
            mode="live", api_key=api_key, broker_order_id=entry_broker_order_id
        )
        if not cancelled.ok:
            _failure(run, strategy, leg, "Could not cancel the unfilled entry remainder")
            return False
        fact = order_dispatch.fetch_order_status(
            mode="live", api_key=api_key, broker_order_id=entry_broker_order_id
        )
        if not fact.ok or fact.order is None:
            _failure(run, strategy, leg, "Cancelled entry quantity could not be reconciled")
            return False
        from services.strategy_module import order_events

        order_events.apply_order_snapshot(entry_broker_order_id, fact.order)
        reconciled_entry = store.get_order(entry_order_id)
        if reconciled_entry is None or reconciled_entry.status not in {
            "complete", "cancelled", "rejected"
        }:
            _failure(
                run,
                strategy,
                leg,
                "Kotak has not confirmed the entry remainder terminal; protective quantity is not final",
            )
            return False
        current = _position_stop(run_id, leg_id, position_ref)
        if current is None:
            return True
        strategy, leg, run = current

    position = risk_adapter.leg_to_position_risk(leg)
    trigger = position.stop_price
    if trigger is None or not math.isfinite(float(trigger)) or float(trigger) <= 0:
        _failure(run, strategy, leg, "The configured stop could not be derived from the confirmed fill")
        _close_run(run, strategy)
        return False

    # A prior stop, if present, must belong to this exact position and match
    # the configured stop calculated from the confirmed average fill. Existing
    # working protection is left alone; it is never duplicated on a replay.
    matching_stops = [
        row for row in store.list_orders(run_id)
        if row.get("kind") == "protective_stop" and row.get("position_ref") == position_ref
    ]
    for row in matching_stops:
        if row.get("status") in {"pending", "unknown"}:
            _failure(run, strategy, leg, "A prior protective stop outcome is unresolved; duplicate stop blocked")
            return False
        if row.get("status") == "open":
            if row.get("broker_order_id") and _verify_working_stop(
                api_key,
                str(row["broker_order_id"]),
                {
                    "symbol": leg["symbol"],
                    "exchange": leg["exchange"],
                    "action": order_dispatch.exit_action(leg["position"]),
                    "quantity": int(leg["qty"]),
                    "trigger_price": float(trigger),
                    "product": row.get("product") or "",
                },
            ):
                return True
            _failure(run, strategy, leg, "Existing protective order does not match the held position")
            return False

    action = order_dispatch.exit_action(leg["position"])
    product = order_dispatch.product_for_exchange(strategy.get("product", "NRML"), leg["exchange"])
    stop_order = order_dispatch.build_order(
        symbol=leg["symbol"], exchange=leg["exchange"], action=action,
        quantity=int(leg["qty"]), product=product,
        strategy_name=f"{strategy.get('name', '')}:protective-stop",
        pricetype="SL-M", trigger_price=float(trigger),
    )
    stop_order["position_ref"] = position_ref
    stop_order["_strategy_broker"] = "kotak"
    stop_order["_strategy_connection_id"] = str(run.get("broker_connection_id") or "")
    row = store.record_order(
        run_id, int(leg_id), "protective_stop",
        {**stop_order, "qty": int(leg["qty"]), "position_ref": position_ref, "status": "pending"},
    )
    if row is None:
        _failure(run, strategy, leg, "Protective stop intent could not be saved before submission")
        _close_run(run, strategy)
        return False
    row_id = int(row.id)
    with state.run_state(run_id) as active:
        primary = (active.get("legs") or {}).get(str(leg_id)) if active else None
        active_leg = _owner_state_for_position(primary, position_ref) if primary else None
        if active_leg is None:
            store.update_order(row_id, status="unknown", reject_reason="position changed during stop placement")
            _failure(run, strategy, leg, "Position ownership changed while placing the protective stop")
            return False
        # _owner_for_position returns the nested superseded object itself for
        # an outgoing flip owner, so this binds the exact incarnation.
        active_leg["exit_order_id"] = row_id
        active_leg["exit_kind"] = "protective_stop"
        active_leg["protective_stop_trigger"] = float(trigger)

    result = order_dispatch.dispatch_order(
        mode="live", api_key=api_key, order=stop_order, intent="protection"
    )
    from services.strategy_module import engine

    acknowledgement_recorded = engine._record_acknowledgement(
        row_id, result, int(strategy["id"]), str(strategy["user_id"]),
        run_id, leg_id,
    )
    if result.unknown:
        _failure(run, strategy, leg, "Protective stop submission outcome is unknown; reconcile before retry")
        return False
    if not result.ok or not result.broker_order_id:
        state.release_order_exit(run_id, leg_id, row_id, position_ref)
        _failure(run, strategy, leg, result.error or "Kotak rejected the protective stop")
        _close_run(run, strategy)
        return False
    if not acknowledgement_recorded:
        _failure(run, strategy, leg, "Kotak accepted the stop but its exact broker reference could not be saved")
        return False

    engine._replay_order_update(str(result.broker_order_id))
    expected = {
        "symbol": leg["symbol"], "exchange": leg["exchange"], "action": action,
        "quantity": int(leg["qty"]), "trigger_price": float(trigger), "product": product,
    }
    if _verify_working_stop(api_key, str(result.broker_order_id), expected) is None:
        store.update_order(row_id, status="unknown", reject_reason="Broker stop could not be verified")
        _failure(run, strategy, leg, "Kotak did not confirm the stop with matching instrument, side, quantity and trigger")
        return False
    from services.strategy_module.lifecycle_events import record_and_notify

    record_and_notify(
        int(strategy["id"]), str(strategy["user_id"]), "protective_stop_verified",
        f"Kotak protective stop verified for {leg['symbol']} quantity {leg['qty']} at {trigger}",
        run_id=run_id, leg_id=leg_id, mode="live",
    )
    return True


def cancel_before_exit(
    run_id: int, leg_id: Any, user_id: str, *, position_ref: str | None = None
) -> tuple[bool, str | None]:
    """Cancel and reconcile the native stop before a software or manual exit."""
    snapshot = state.get_run_state(run_id) or {}
    primary = (snapshot.get("legs") or {}).get(str(leg_id))
    if not primary:
        return True, None
    if position_ref is None:
        refs = [
            owner.get("position_ref")
            for owner in (primary, primary.get("superseded"))
            if owner
            and owner.get("position_ref")
            and owner.get("exit_order_id")
            and owner.get("exit_kind") == "protective_stop"
        ]
        for owner_ref in refs:
            released, reason = cancel_before_exit(
                run_id, leg_id, user_id, position_ref=str(owner_ref)
            )
            if not released:
                return False, reason
        run = store.get_run(run_id)
        if run is None:
            return False, "Strategy run is unavailable while reconciling its protective stop"
        return True, None

    owner = _owner_state_for_position(primary, position_ref)
    if owner is None:
        return False, "Position ownership changed; no competing exit was sent"
    if not owner.get("exit_order_id") or owner.get("exit_kind") != "protective_stop":
        return True, None
    stop = store.get_order(int(owner["exit_order_id"]))
    run = store.get_run(run_id)
    if stop is None or run is None or not stop.broker_order_id:
        return False, "Protective stop ownership is unresolved; reconcile broker orders first"
    stop_row_id = int(stop.id)
    stop_broker_order_id = str(stop.broker_order_id)
    strategy_id = int(run.strategy_id)
    run_broker = str(run.broker or "").lower()
    run_connection_id = str(run.broker_connection_id or "")
    # _api_key_for accepts a strategy id, not a user id. Resolve through the
    # run's owner so protective stops can actually be cancelled before a
    # software exit; otherwise every live close remains permanently blocked.
    api_key = _api_key_for(strategy_id)
    strategy_row = store.get_strategy_unscoped(strategy_id)
    if (
        not api_key
        or strategy_row is None
        or str(strategy_row.user_id) != str(user_id)
        or run_broker != "kotak"
        or not _active_kotak_pin(api_key, run_connection_id)
    ):
        return False, "Kotak session is unavailable; protective stop remains the active exit"
    with state.run_state(run_id) as active:
        active_primary = (active.get("legs") or {}).get(str(leg_id)) if active else None
        active_leg = (
            _owner_state_for_position(active_primary, position_ref)
            if active_primary
            else None
        )
        if active_leg is None or active_leg.get("exit_order_id") != stop_row_id:
            return False, "Protective stop ownership changed; no competing exit was sent"
        active_leg["protective_stop_cancel_expected_order_id"] = stop_row_id

    cancel = order_dispatch.cancel_order(
        mode="live", api_key=api_key, broker_order_id=stop_broker_order_id
    )
    if not cancel.ok:
        _clear_expected_protective_cancel(run_id, leg_id, stop_row_id, position_ref)
        return False, cancel.error or "Kotak did not confirm protective stop cancellation"
    fact = order_dispatch.fetch_order_status(
        mode="live", api_key=api_key, broker_order_id=stop_broker_order_id
    )
    if not fact.ok or fact.order is None:
        _clear_expected_protective_cancel(run_id, leg_id, stop_row_id, position_ref)
        return False, fact.error or "Protective stop cancellation outcome is unknown"
    from services.strategy_module import order_events

    order_events.apply_order_snapshot(stop_broker_order_id, fact.order)
    _clear_expected_protective_cancel(run_id, leg_id, stop_row_id, position_ref)
    after = state.get_run_state(run_id) or {}
    current = (after.get("legs") or {}).get(str(leg_id))
    current_owner = _owner_for_position(current, position_ref) if current else None
    if current_owner is None:
        terminal_stop = store.get_order(stop_row_id)
        if terminal_stop is not None and terminal_stop.status == "complete":
            return True, None
        return False, "Position ownership changed while cancelling its protective stop"
    if current_owner.get("status") != "open" or int(current_owner.get("qty") or 0) <= 0:
        # The stop may have filled while cancellation was in flight. The
        # caller must not send a second exit against a position now known flat.
        return True, None
    if current_owner.get("exit_order_id") == stop_row_id:
        return False, "Protective stop still owns the position; no competing exit was sent"
    return True, None


def resize_after_partial_stop_fill(
    run_id: int, leg_id: Any, position_ref: str, stop_order_id: int
) -> bool:
    """Cancel an oversized remainder after a partial stop fill and cover what remains."""
    current = _position_stop(run_id, leg_id, position_ref)
    if current is None:
        return True
    strategy, leg, _run = current
    stop = store.get_order(stop_order_id)
    if stop is None or stop.kind != "protective_stop" or stop.position_ref != position_ref:
        _failure(_run, strategy, leg, "Partial stop fill has no exact durable stop owner")
        return False

    released, reason = cancel_before_exit(
        run_id, leg_id, str(strategy["user_id"]), position_ref=position_ref
    )
    if not released:
        _failure(
            _run,
            strategy,
            leg,
            reason or "Partial stop remainder could not be reconciled; it may exceed remaining exposure",
        )
        return False

    refreshed = _position_stop(run_id, leg_id, position_ref)
    if refreshed is None:
        return True
    refreshed_strategy, refreshed_leg, refreshed_run = refreshed
    entry_order_id = refreshed_leg.get("entry_order_id")
    if entry_order_id is None:
        _failure(refreshed_run, refreshed_strategy, refreshed_leg, "Remaining position has no entry order owner")
        return False
    return protect_entry_fill(
        run_id,
        leg_id,
        position_ref,
        entry_order_id=int(entry_order_id),
        entry_is_terminal=True,
    )


def verify_recovered_run(run_id: int, api_key: str) -> list[str]:
    """Verify held positions against their durable broker stop orders on boot."""
    snapshot = state.get_run_state(run_id) or {}
    run = store.get_run(run_id)
    if run is None or not _active_kotak_pin(api_key, str(run.broker_connection_id or "")):
        return ["run broker connection does not match the active Kotak API key"]
    issues: list[str] = []
    orders = store.list_orders(run_id)
    for primary in (snapshot.get("legs") or {}).values():
        owners = [primary]
        outgoing = primary.get("superseded")
        if isinstance(outgoing, dict):
            owners.append({**primary, **outgoing, "status": "open"})
        for leg in owners:
            if leg.get("status") != "open" or int(leg.get("qty") or 0) <= 0:
                continue
            stops = [
                row for row in orders
                if row.get("kind") == "protective_stop"
                and row.get("position_ref") == leg.get("position_ref")
                and row.get("status") == "open"
                and row.get("broker_order_id")
            ]
            if len(stops) != 1:
                issues.append(str(leg.get("symbol") or leg.get("leg_id")))
                continue
            stop = stops[0]
            risk = risk_adapter.leg_to_position_risk(leg)
            if risk.stop_price is None or not math.isfinite(float(risk.stop_price)):
                issues.append(str(leg.get("symbol") or leg.get("leg_id")))
                continue
            expected = {
                "symbol": leg["symbol"], "exchange": leg["exchange"],
                "action": order_dispatch.exit_action(leg["position"]),
                "quantity": int(leg["qty"]), "trigger_price": float(risk.stop_price),
                "product": stop.get("product") or "",
            }
            if _verify_working_stop(api_key, str(stop["broker_order_id"]), expected) is None:
                issues.append(str(leg.get("symbol") or leg.get("leg_id")))
    return issues


def _api_key_for(strategy_id: int) -> str | None:
    strategy = store.get_strategy_unscoped(strategy_id)
    if strategy is None:
        return None
    from services.strategy_module.engine import _api_key_for as get_key

    return get_key(str(strategy.user_id))


def _clear_expected_protective_cancel(
    run_id: int, leg_id: Any, order_id: int, position_ref: str
) -> None:
    """Clear the transient marker used to distinguish our cancel from a lost stop."""
    with state.run_state(run_id) as active:
        primary = (active.get("legs") or {}).get(str(leg_id)) if active else None
        owner = _owner_state_for_position(primary, position_ref) if primary else None
        if owner and owner.get("protective_stop_cancel_expected_order_id") == order_id:
            owner.pop("protective_stop_cancel_expected_order_id", None)


def _failure(run: Any, strategy: dict, leg: dict, message: str) -> None:
    from services.strategy_module.lifecycle_events import record_and_notify

    record_and_notify(
        int(strategy["id"]), str(strategy["user_id"]), "protective_stop_failed",
        message, run_id=int(run["id"]), leg_id=leg.get("leg_id"), severity="critical", mode="live",
    )


def _close_run(run: Any, strategy: dict) -> None:
    from services.strategy_module.engine import stop_run

    try:
        stop_run(int(run["id"]), str(strategy["user_id"]), reason="protection_failed")
    except Exception:
        logger.exception("Could not close strategy run %s after protection failure", run.get("id"))
