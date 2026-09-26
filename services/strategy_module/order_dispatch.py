"""The single place a strategy run turns a decision into an order.

Every order the module places - entries, rule-driven exits, manual closes,
square-offs - goes through :func:`dispatch_order`. One decision point means the
live and sandbox paths cannot drift apart, and the engine never has to know
which one it is on.

Three deliberate departures from how the rest of the product places orders:

**Mode is per run, not global.** OpenAlgo's analyzer setting is a single
platform-wide switch. A strategy chooses live or sandbox when the run starts,
and two runs may disagree, so this module branches explicitly on the run's own
mode and calls each pipe directly.

A live order passes ``force_live=True``, which is load bearing rather than
decorative: ``place_order_with_auth`` consults the global toggle before it
looks at the broker arguments, so without the flag an operator turning the
analyzer on to try something elsewhere would divert a live run's exits into the
sandbox. Those report success, so the engine would close the leg and finalise
the run while the real broker position stayed open with nothing managing it.
Nothing here changes the toggle.

**Action Center is bypassed.** ``place_order`` routes API-key orders into the
semi-automatic approval queue when that is enabled. That is right for a signal
arriving from outside and wrong here: a stop-loss exit that sits in a queue
waiting for a human is not a stop loss. The module calls
``place_order_with_auth``, which is the same code path minus the queue.

**Broker authorisation is resolved fresh, per order, and never cached in run
state.** Indian broker tokens expire daily around 3 AM IST, and a run may be
open across that boundary. If authorisation cannot be resolved, an automated
exit is refused and reported rather than attempted: leaving the position open
and telling the operator is recoverable, and pretending to have exited is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

# Exits are always MARKET. A limit exit that does not fill is not an exit, and
# every exit this module places is a risk decision that has already fired.
EXIT_PRICETYPE = "MARKET"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """What one placement attempt produced.

    ``ok`` is whether the order reached the broker or the sandbox, not whether
    it filled. Fills arrive later, over the order-update event.
    """

    ok: bool
    broker_order_id: str | None = None
    response: dict[str, Any] | None = None
    error: str | None = None
    unknown: bool = False

    @property
    def outcome(self) -> str:
        if self.unknown:
            return "unknown"
        return "accepted" if self.ok else "rejected"

    @property
    def rejected(self) -> bool:
        return not self.ok and not self.unknown


@dataclass(frozen=True, slots=True)
class OrderStatusResult:
    """One broker orderbook fact, or why it could not be read."""

    ok: bool
    order: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AccountSnapshotResult:
    """Read-only broker order and position books for uncertain-delivery review."""

    orders_ok: bool
    positions_ok: bool
    orders: tuple[dict[str, Any], ...] = ()
    positions: tuple[dict[str, Any], ...] = ()


# Which venues list derivatives, for the purpose of naming the product.
# /scalping already carries this rule (blueprints/scalping.py), and every
# broker enforces it: CNC is a delivery product for cash, NRML a carry-forward
# product for derivatives, and neither is accepted on the other's venue.
#
# There is deliberately no set of "products a derivative accepts" beside this
# one. Two such sets used to sit here and were referenced by nothing, which
# read as a validation rule that ran somewhere and did not: the product is
# translated per venue below rather than refused, so a legal value for the
# venue is produced instead of being demanded from the caller.
DERIVATIVE_EXCHANGES_FOR_PRODUCT = frozenset({"NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "NCO"})


def product_for_exchange(product: str, exchange: str) -> str:
    """The venue's spelling of the product the strategy asked for.

    A strategy carries one product for every leg, so a basket holding a cash
    leg and an option leg could not be given a product both would accept, and
    the default NRML reached NSE and BSE while CNC reached NFO, BFO, MCX and
    CDS. Nothing downstream catches it: the schemas and the sandbox only check
    the value is one of the three, so it went to the broker as configured.

    The product is read as the intent rather than as a literal. MIS is
    intraday everywhere and passes through. Anything else means carry the
    position, which is NRML on a derivatives venue and CNC on cash, so a mixed
    basket works and no leg is ever sent a product its venue refuses.
    """
    wanted = (product or "").upper()
    if wanted == "MIS":
        return "MIS"
    if (exchange or "").upper() in DERIVATIVE_EXCHANGES_FOR_PRODUCT:
        return "NRML"
    return "CNC"


def build_order(
    *,
    symbol: str,
    exchange: str,
    action: str,
    quantity: int,
    product: str,
    strategy_name: str,
    pricetype: str = "MARKET",
    price: float = 0,
    trigger_price: float = 0,
    protective_stop_required: bool = False,
    protective_stop_loss_points: float | None = None,
) -> dict[str, Any]:
    """The order payload, in the shape the placement services expect.

    Quantity is a string because that is what the rest of the order path uses;
    passing an int works today but diverges from every other caller.
    """
    return {
        "symbol": symbol,
        "exchange": exchange,
        "action": action.upper(),
        "quantity": str(int(quantity)),
        # Translated to what this venue accepts. Every order the module places
        # passes through here, so this is the one place it has to be right.
        "product": product_for_exchange(product, exchange),
        "pricetype": pricetype,
        "price": str(price or 0),
        "trigger_price": str(trigger_price or 0),
        # Tags the order so it is attributable in the orderbook and in logs.
        "strategy": strategy_name,
        # Internal execution admission facts. Broker mappers ignore these;
        # they let the final live dispatch boundary reject unprotected entries.
        "protective_stop_required": bool(protective_stop_required),
        "protective_stop_loss_points": protective_stop_loss_points,
    }


def exit_action(position: str) -> str:
    """The action that closes a leg.

    Derived from the leg's own recorded side, never from its configuration. The
    original reads the configured side, which defaults to "B" for every leg
    including short ones, so a rule-driven exit on a short leg placed another
    SELL and doubled the position instead of covering it.
    """
    normalised = (position or "").upper()
    if normalised == "B":
        return "SELL"
    if normalised == "S":
        return "BUY"
    raise ValueError(f"Cannot derive an exit action from position {position!r}")


def resolve_live_auth(api_key: str) -> tuple[str | None, str | None, str | None]:
    """Broker authorisation for a live order, as ``(auth_token, broker, error)``.

    Resolved on every call rather than held for the life of the run. A token
    refreshed during the trading day is picked up transparently, and a session
    that has expired or been revoked is reported instead of being used.
    """
    try:
        from database.auth_db import get_auth_token_broker

        auth_token, broker = get_auth_token_broker(api_key)
        if not auth_token or not broker:
            return None, None, "Broker session is not available or has expired"
        return auth_token, broker, None
    except Exception:
        logger.exception("Could not resolve broker authorisation for a live order")
        return None, None, "Could not resolve broker authorisation"


def dispatch_signal_order(
    *,
    strategy_id: int,
    user_id: str,
    mode: str,
    api_key: str,
    order: dict[str, Any],
    intent: str,
) -> DispatchResult:
    """Recheck signal automation at dispatch without gating manual orders or exits."""
    if intent == "entry":
        from services.strategy_module import automation_control

        allowed, error = automation_control.require_automation_entry(strategy_id, user_id)
        if not allowed:
            return DispatchResult(ok=False, error=error)
    return dispatch_order(mode=mode, api_key=api_key, order=order, intent=intent)


def dispatch_order(
    *,
    mode: str,
    api_key: str,
    order: dict[str, Any],
    intent: str,
) -> DispatchResult:
    """Place one order, live or sandbox, and normalise the answer.

    Both pipes return ``(success, response, status_code)``, so the caller gets
    one shape whichever ran.
    """
    if intent not in {"entry", "exit", "protection"}:
        return DispatchResult(ok=False, error=f"Unknown order intent: {intent!r}")
    if intent == "protection" and mode != "live":
        return DispatchResult(ok=False, error="Broker-held protection is available only for live runs")
    if mode == "sandbox":
        return _dispatch_sandbox(api_key, order)
    if mode == "live":
        expected_broker = str(order.get("_strategy_broker") or "").lower()
        expected_connection_id = str(order.get("_strategy_connection_id") or "")
        if not expected_broker or not expected_connection_id:
            return DispatchResult(
                ok=False,
                error="Live strategy orders require an explicit pinned broker connection",
            )
        if intent == "entry":
            protection_error = live_entry_protection_reason(order)
            if protection_error:
                return DispatchResult(ok=False, error=protection_error)
        return _dispatch_live(
            api_key,
            order,
            intent=intent,
            expected_broker=expected_broker,
            expected_connection_id=expected_connection_id,
        )
    return DispatchResult(ok=False, error=f"Unknown run mode: {mode!r}")


def live_entry_protection_reason(order: dict[str, Any] | None = None) -> str | None:
    """Last order-boundary check: only strategy entries carrying fixed-stop intent pass."""
    if order is None:
        return "Live entry requires a verified Kotak strategy and fixed per-leg stop"
    if str(order.get("exchange") or "").upper() not in {"NSE", "BSE", "NFO", "BFO", "MCX"}:
        return "Kotak broker-held stops are not enabled for this exchange"
    if order.get("protective_stop_required") is not True:
        return "Live entry requires a configured broker-held protective stop"
    try:
        points = Decimal(str(order.get("protective_stop_loss_points")))
    except (InvalidOperation, TypeError, ValueError):
        points = Decimal("0")
    if not points.is_finite() or points <= 0:
        return "Live entry requires a positive per-leg stop-loss"
    return None


def _limit_price_from_quote(
    symbol: str, exchange: str, action: str, executable_price: Decimal
) -> Decimal | None:
    """Tick-align a half-percent adverse entry cap from a broker quote."""
    from database.token_db import get_symbol_info

    info = get_symbol_info(symbol, exchange)
    try:
        tick = Decimal(str(getattr(info, "tick_size", None)))
        if not tick.is_finite() or tick <= 0:
            return None
        factor = Decimal("1.005") if action == "BUY" else Decimal("0.995")
        rounding = ROUND_FLOOR if action == "BUY" else ROUND_CEILING
        cap = (executable_price * factor / tick).to_integral_value(rounding=rounding) * tick
        marketable = cap >= executable_price if action == "BUY" else cap <= executable_price
        return cap if cap > 0 and marketable else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def bounded_live_entry_order(
    order: dict[str, Any], auth_token: str, broker: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Build a marketable limit from a fresh, executable broker quote.

    The cap is a worst permitted entry price, not a promise of execution.
    Callers must reserve risk using this same cap and reject an adverse quote
    change that exceeds the reserved price before submitting the order.
    """
    from services.strategy_module import portfolio_governor

    action = str(order.get("action") or "").upper()
    if action not in {"BUY", "SELL"}:
        return None, "Live entry side is unavailable"
    leg = {
        "symbol": order.get("symbol"),
        "exchange": order.get("exchange"),
        "quantity": order.get("quantity"),
        "position": "B" if action == "BUY" else "S",
    }
    executable = portfolio_governor._quote_price(leg, auth_token, broker)
    if executable is None:
        return None, "A fresh broker quote with a usable spread and depth is required for entry"
    cap = _limit_price_from_quote(
        str(order.get("symbol") or ""),
        str(order.get("exchange") or ""),
        action,
        executable,
    )
    if cap is None:
        return None, "No marketable contract tick fits the bounded entry price"
    bounded = dict(order)
    bounded.update(pricetype="LIMIT", price=format(cap, "f"), trigger_price="0")
    return bounded, None


def cancel_order(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
) -> DispatchResult:
    """Cancel a strategy order through the run's own execution pipe.

    Used both for an entry whose run is stopping and for an exit retry made too
    large by a late cumulative correction. Like placement, this bypasses the
    platform analyzer toggle because ``mode`` was fixed durably at run start.
    """
    if not broker_order_id:
        return DispatchResult(ok=False, error="Broker order id is unavailable")
    if mode == "sandbox":
        from services.sandbox_service import sandbox_cancel_order

        request = {"orderid": broker_order_id}
        original = {**request, "apikey": api_key}
        try:
            ok, response, _status = sandbox_cancel_order(request, api_key, original)
        except Exception:
            logger.exception("Sandbox strategy cancellation raised for %s", broker_order_id)
            return DispatchResult(
                ok=False,
                broker_order_id=broker_order_id,
                error="Sandbox strategy cancellation failed",
            )
        result = _normalise(ok, response)
        return DispatchResult(
            ok=result.ok,
            broker_order_id=result.broker_order_id or broker_order_id,
            response=result.response,
            error=result.error,
        )
    if mode != "live":
        return DispatchResult(ok=False, error=f"Unknown run mode: {mode!r}")

    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return DispatchResult(ok=False, broker_order_id=broker_order_id, error=error)

    from services.cancel_order_service import import_broker_module

    broker_module = import_broker_module(broker)
    if broker_module is None:
        return DispatchResult(
            ok=False,
            broker_order_id=broker_order_id,
            error="Broker-specific cancellation module is unavailable",
        )
    try:
        response, status_code = broker_module.cancel_order(broker_order_id, auth_token)
    except Exception:
        logger.exception("Live strategy cancellation raised for %s", broker_order_id)
        return DispatchResult(
            ok=False,
            broker_order_id=broker_order_id,
            error="Live strategy cancellation failed",
        )
    payload = response if isinstance(response, dict) else {}
    if status_code == 200:
        return DispatchResult(ok=True, broker_order_id=broker_order_id, response=payload)
    return DispatchResult(
        ok=False,
        broker_order_id=broker_order_id,
        response=payload,
        error=payload.get("message") or "Broker refused strategy cancellation",
    )


def cancel_exit_order(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
) -> DispatchResult:
    """Backward-compatible name for correction-retry cancellation."""
    return cancel_order(
        mode=mode,
        api_key=api_key,
        broker_order_id=broker_order_id,
    )


def fetch_order_status(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
) -> OrderStatusResult:
    """Read one order through the run's sandbox or live order-status path."""
    if not broker_order_id:
        return OrderStatusResult(ok=False, error="Broker order id is unavailable")

    request = {"orderid": broker_order_id}
    if mode == "sandbox":
        from services.sandbox_service import sandbox_get_order_status

        original = {**request, "apikey": api_key}
        try:
            ok, response, _status = sandbox_get_order_status(request, api_key, original)
        except Exception:
            logger.exception("Sandbox strategy status lookup raised for %s", broker_order_id)
            return OrderStatusResult(ok=False, error="Sandbox order status lookup failed")
    elif mode == "live":
        auth_token, broker, error = resolve_live_auth(api_key)
        if error:
            return OrderStatusResult(ok=False, error=error)

        # The shared order-status endpoint follows the platform analyzer
        # toggle and can return a sandbox order for this ID. This run's mode
        # is live, so inspect the broker-pinned live book directly.
        from services.orderbook_service import get_orderbook_with_auth

        try:
            ok, response, _status = get_orderbook_with_auth(auth_token, broker, None)
        except Exception:
            logger.exception("Live strategy status lookup raised for %s", broker_order_id)
            return OrderStatusResult(ok=False, error="Live order status lookup failed")
        payload = response if isinstance(response, dict) else {}
        data = payload.get("data")
        orders = data.get("orders") if isinstance(data, dict) else data
        if ok and isinstance(orders, list):
            for order in orders:
                if (
                    isinstance(order, dict)
                    and str(order.get("orderid") or "").strip() == broker_order_id
                ):
                    # Some broker orderbooks, including Kotak's mapped book,
                    # omit cumulative fill size and price. A terminal status
                    # without those facts must not be folded as a flat or
                    # safely filled order. Read the live tradebook by the same
                    # authenticated broker identity, never by analyzer mode.
                    book_fill_is_usable = False
                    if "filled_quantity" in order and "average_price" in order:
                        try:
                            book_filled = int(order["filled_quantity"])
                            book_price = float(order["average_price"])
                            book_requested = int(order.get("quantity") or 0)
                            complete = (
                                str(order.get("order_status") or "").strip().lower()
                                == "complete"
                            )
                            book_fill_is_usable = (
                                book_filled >= 0
                                and (book_filled == 0 or book_price > 0)
                                and (
                                    not complete
                                    or (
                                        book_filled > 0
                                        and (book_requested <= 0 or book_filled >= book_requested)
                                    )
                                )
                            )
                        except (TypeError, ValueError, OverflowError):
                            pass
                    if book_fill_is_usable:
                        return OrderStatusResult(ok=True, order=order)
                    from services.tradebook_service import get_tradebook_with_auth

                    try:
                        trades_ok, trades_payload, _ = get_tradebook_with_auth(
                            auth_token, broker, None
                        )
                    except Exception:
                        logger.exception("Live tradebook lookup raised for %s", broker_order_id)
                        return OrderStatusResult(ok=False, error="Live tradebook is unavailable")
                    trades = (
                        trades_payload.get("data")
                        if isinstance(trades_payload, dict)
                        else None
                    )
                    if not trades_ok or not isinstance(trades, list):
                        return OrderStatusResult(ok=False, error="Live tradebook is unavailable")
                    filled = 0
                    trade_value = 0.0
                    try:
                        for trade in trades:
                            if not isinstance(trade, dict) or str(
                                trade.get("orderid") or ""
                            ).strip() != broker_order_id:
                                continue
                            quantity = int(trade.get("quantity") or 0)
                            price = float(trade.get("average_price") or 0)
                            if quantity <= 0 or price <= 0:
                                return OrderStatusResult(
                                    ok=False, error="Live tradebook fill is incomplete"
                                )
                            filled += quantity
                            trade_value += quantity * price
                        requested = int(order.get("quantity") or 0)
                    except (TypeError, ValueError, OverflowError):
                        return OrderStatusResult(ok=False, error="Live tradebook fill is invalid")
                    # No exact trade rows are not proof of zero fills: the
                    # tradebook may lag the orderbook. In particular, folding
                    # a cancelled part-fill as zero would release an unknown
                    # intent while a real position remains at the broker.
                    if filled == 0:
                        return OrderStatusResult(ok=False, error="Live fill quantity is unverified")
                    if (
                        str(order.get("order_status") or "").strip().lower() == "complete"
                        and requested > 0
                        and filled < requested
                    ):
                        return OrderStatusResult(ok=False, error="Live tradebook fill is incomplete")
                    return OrderStatusResult(
                        ok=True,
                        order={
                            **order,
                            "filled_quantity": filled,
                            "average_price": trade_value / filled,
                        },
                    )
            return OrderStatusResult(ok=False, error="Broker order ID is absent from the live book")
        return OrderStatusResult(
            ok=False,
            error=payload.get("message") or "Live broker orderbook is unavailable",
        )
    else:
        return OrderStatusResult(ok=False, error=f"Unknown run mode: {mode!r}")

    payload = response if isinstance(response, dict) else {}
    order = payload.get("data")
    if ok and isinstance(order, dict):
        return OrderStatusResult(ok=True, order=order)
    return OrderStatusResult(
        ok=False,
        error=payload.get("message") or "Broker order status is unavailable",
    )


def fetch_account_snapshot(*, mode: str, api_key: str) -> AccountSnapshotResult:
    """Inspect both account books without inferring ownership from appearance.

    Symbol, side and quantity can match another surface's order. Callers may
    use a confirmed broker ID to reconcile an exact row, but must never use an
    apparently absent or similar book entry to release a keyless intent.
    """
    if mode == "sandbox":
        from services.sandbox_service import sandbox_get_orderbook, sandbox_get_positions

        try:
            orders_ok, orders_payload, _ = sandbox_get_orderbook(api_key, {"apikey": api_key})
        except Exception:
            logger.exception("Could not read sandbox orderbook for uncertain order")
            orders_ok, orders_payload = False, {}
        try:
            positions_ok, positions_payload, _ = sandbox_get_positions(
                api_key, {"apikey": api_key}
            )
        except Exception:
            logger.exception("Could not read sandbox positions for uncertain order")
            positions_ok, positions_payload = False, {}
    elif mode == "live":
        auth_token, broker, error = resolve_live_auth(api_key)
        if error:
            return AccountSnapshotResult(orders_ok=False, positions_ok=False)
        from services.orderbook_service import get_orderbook_with_auth
        from services.positionbook_service import get_positionbook_with_auth

        try:
            orders_ok, orders_payload, _ = get_orderbook_with_auth(auth_token, broker, None)
        except Exception:
            logger.exception("Could not read live orderbook for uncertain order")
            orders_ok, orders_payload = False, {}
        try:
            positions_ok, positions_payload, _ = get_positionbook_with_auth(
                auth_token, broker, None
            )
        except Exception:
            logger.exception("Could not read live positions for uncertain order")
            positions_ok, positions_payload = False, {}
    else:
        return AccountSnapshotResult(orders_ok=False, positions_ok=False)

    order_data = orders_payload.get("data") if isinstance(orders_payload, dict) else None
    orders = order_data.get("orders") if isinstance(order_data, dict) else order_data
    positions = positions_payload.get("data") if isinstance(positions_payload, dict) else None
    return AccountSnapshotResult(
        orders_ok=bool(orders_ok and isinstance(orders, list)),
        positions_ok=bool(positions_ok and isinstance(positions, list)),
        orders=tuple(row for row in orders if isinstance(row, dict)) if isinstance(orders, list) else (),
        positions=(
            tuple(row for row in positions if isinstance(row, dict))
            if isinstance(positions, list)
            else ()
        ),
    )


def _dispatch_sandbox(api_key: str, order: dict[str, Any]) -> DispatchResult:
    from services.sandbox_service import sandbox_place_order

    original = dict(order)
    original["apikey"] = api_key
    try:
        ok, response, _status = sandbox_place_order(dict(order), api_key, original)
    except Exception:
        logger.exception("Sandbox order placement raised for %s", order.get("symbol"))
        return DispatchResult(ok=False, error="Sandbox order placement failed")

    return _normalise(ok, response)


def _dispatch_live(
    api_key: str,
    order: dict[str, Any],
    *,
    intent: str,
    expected_broker: str,
    expected_connection_id: str,
) -> DispatchResult:
    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        # Deliberately not attempted. See the module docstring: refusing and
        # saying so leaves a recoverable situation, and a silent failure does
        # not.
        return DispatchResult(ok=False, error=error)

    # Recheck the API key's exact pin at the final dispatch boundary. The
    # browser's selected broker or a strategy's earlier preflight is not enough:
    # another login/switch may have changed the active session since admission.
    from services.strategy_module import live_protection

    pinned_id, pinned_broker = live_protection._connection_for_api_key(api_key)
    if (
        str(broker or "").lower() != expected_broker
        or expected_broker != "kotak"
        or pinned_broker != expected_broker
        or pinned_id != expected_connection_id
        or (intent == "protection" and expected_broker != "kotak")
    ):
        return DispatchResult(
            ok=False,
            error="The active broker session no longer matches this strategy's pinned account",
        )

    if intent == "entry":
        if str(order.get("pricetype") or "").upper() != "LIMIT":
            return DispatchResult(ok=False, error="Live entry requires a reserved limit price")
        try:
            reserved_cap = Decimal(str(order.get("price")))
        except (InvalidOperation, TypeError, ValueError):
            reserved_cap = Decimal("0")
        if not reserved_cap.is_finite() or reserved_cap <= 0:
            return DispatchResult(ok=False, error="Live entry requires a reserved limit price")
        bounded, bound_error = bounded_live_entry_order(order, auth_token, broker)
        if bound_error or bounded is None:
            return DispatchResult(ok=False, error=bound_error or "Live entry quote is unavailable")
        fresh_cap = Decimal(str(bounded["price"]))
        action = str(order.get("action") or "").upper()
        if (action == "BUY" and fresh_cap > reserved_cap) or (
            action == "SELL" and fresh_cap < reserved_cap
        ):
            return DispatchResult(
                ok=False,
                error="The quote moved beyond this entry's reserved limit; reassess the trade",
            )
        order = bounded

    from services.place_order_service import place_order_with_auth

    # These private routing claims belong to the strategy engine, not the
    # broker API. Never forward them to a plugin adapter or broker.
    order = {key: value for key, value in order.items() if not key.startswith("_strategy_")}
    original = dict(order)
    original["apikey"] = api_key
    try:
        ok, response, status = place_order_with_auth(
            dict(order),
            auth_token,
            broker,
            original,
            # The run already decided this is live. Without force_live the
            # platform-wide analyzer toggle would divert it to the sandbox,
            # which reports success and leaves a real position orphaned.
            force_live=True,
        )
    except Exception:
        logger.exception("Live order placement raised for %s", order.get("symbol"))
        return DispatchResult(
            ok=False,
            unknown=True,
            error="Live order placement outcome is unknown after an interrupted broker call",
        )

    # The shared placement service can turn a broker transport failure into a
    # generic HTTP 500 (Kotak does this after POST). No broker rejection fact
    # survived that path, and a reference in such a payload is unconfirmed.
    if not ok and (status is None or status >= 500):
        payload = response if isinstance(response, dict) else {}
        return DispatchResult(
            ok=False,
            unknown=True,
            response=payload,
            error=payload.get("message") or "Live order placement outcome is unknown",
        )
    if ok and not (isinstance(response, dict) and response.get("orderid")):
        return DispatchResult(
            ok=False,
            unknown=True,
            response=response if isinstance(response, dict) else {},
            error="Live order was reported accepted without a broker order ID",
        )
    return _normalise(ok, response)


def _normalise(ok: bool, response: Any) -> DispatchResult:
    """One shape out of either pipe."""
    payload = response if isinstance(response, dict) else {}
    if ok:
        return DispatchResult(
            ok=True,
            broker_order_id=payload.get("orderid"),
            response=payload,
        )
    return DispatchResult(
        ok=False,
        # A rejected order can still carry a broker reference, and the audit row
        # is more useful with it than without.
        broker_order_id=payload.get("orderid"),
        response=payload,
        error=payload.get("message") or "Order rejected",
    )
