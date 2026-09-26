"""Attach order-free profit-rule comparisons to confirmed sandbox entries."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

from sqlalchemy import text

from database import profit_comparison_db as comparison_store
from database import strategy_module_db as store
from services.strategy_module import risk_adapter, session, state
from services.strategy_module.profit_comparison import start_comparison
from utils.logging import get_logger

IST = ZoneInfo("Asia/Kolkata")
logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _remaining_session_allowance(strategy, run_row, current_run: dict) -> float | None:
    """Conservatively debit every session loss; unknown evidence disables comparison."""
    limit = strategy.daily_loss_limit_inr
    if limit is None or float(limit) <= 0:
        return None
    since = session.session_started_at(_now().astimezone(IST)).astimezone(UTC).replace(
        tzinfo=None
    )
    runs = store.list_user_runs(
        strategy.user_id, limit=501, since=since, mode="sandbox",
        broker="sandbox", strategy_id=run_row.strategy_id,
    )
    if runs is None or len(runs) >= 501:
        return None
    spent = 0.0
    realized_by_run: dict[int, float] = {}
    for row in runs:
        if row.get("mode") != "sandbox" or row.get("strategy_id") != run_row.strategy_id:
            return None
        if row["id"] == run_row.id:
            pnl = float(current_run.get("pnl_total") or 0)
            realized_by_run[row["id"]] = float(current_run.get("pnl_realized") or 0)
        elif row.get("stopped_at") is not None:
            pnl = float(row.get("pnl_realized") or 0)
            realized_by_run[row["id"]] = pnl
        else:
            other = state.get_run_state(row["id"])
            if other is None:
                return None
            pnl = float(other.get("pnl_total") or 0)
            realized_by_run[row["id"]] = float(other.get("pnl_realized") or 0)
        if not isfinite(pnl) or not isfinite(realized_by_run[row["id"]]):
            return None
        spent += max(0.0, -pnl)
    if not store.filled_orders_have_usable_evidence(
        [row["id"] for row in runs],
        completed_run_ids=[row["id"] for row in runs if row.get("stopped_at")],
        run_realized=realized_by_run,
    ):
        return None
    return max(0.0, float(limit) - spent)


def attach_confirmed_entry(run_id: int, leg_id: int | str) -> dict | None:
    """Create one durable shadow entry without placing or changing orders.

    The real run lock is never held here. Missing identity, a multi-position run,
    or unverifiable risk budget simply leaves the comparison unavailable.
    """
    run_row = store.get_run(run_id)
    if run_row is None or run_row.mode != "sandbox" or not run_row.broker_connection_id:
        return None
    strategy = store.get_strategy_unscoped(run_row.strategy_id)
    if strategy is None or strategy.strategy_type != "intraday":
        return None
    snapshot = state.get_run_state(run_id)
    if not snapshot:
        return None
    open_legs = [
        leg for leg in snapshot.get("legs", {}).values()
        if leg.get("status") == "open" and int(leg.get("qty") or 0) > 0
    ]
    if len(open_legs) != 1 or any(
        leg.get("superseded") for leg in snapshot.get("legs", {}).values()
    ):
        return None
    leg = open_legs[0]
    if str(leg.get("leg_id")) != str(leg_id) or leg.get("entry_status") != "complete":
        return None
    if not all(leg.get(key) for key in ("position_ref", "symbol", "exchange", "entry_avg")):
        return None
    position = risk_adapter.leg_to_position_risk(leg)
    if position.initial_stop_price is None:
        return None
    planned = abs(position.entry_price - position.initial_stop_price) * position.quantity
    overall = strategy.overall_sl_mtm
    if overall is None:
        return None
    overall_remaining = float(overall) - max(0.0, -float(snapshot.get("pnl_total") or 0))
    daily_remaining = _remaining_session_allowance(strategy, run_row, snapshot)
    if min(planned, overall_remaining, daily_remaining or 0) <= 0:
        return None
    now = _now()
    cutoff_time = strategy.exit_time or time(15, 15)
    cutoff = datetime.combine(now.astimezone(IST).date(), cutoff_time, IST).astimezone(UTC)
    if cutoff <= now:
        return None
    prepared = start_comparison(
        run_id=run_id, position_ref=leg["position_ref"],
        broker_connection_id=run_row.broker_connection_id,
        symbol=leg["symbol"], exchange=leg["exchange"],
        run_open_positions=1, mode="sandbox",
        side="BUY" if leg.get("position") == "B" else "SELL",
        entry_price=position.entry_price, quantity=int(position.quantity),
        planned_stop_risk=planned, overall_stop_remaining=overall_remaining,
        daily_allowance_remaining=daily_remaining,
        baseline_risk=asdict(risk_adapter.run_to_aggregate_risk(snapshot, store.strategy_to_dict(strategy))),
        baseline_leg_state=leg, entry_at=now, cutoff_at=cutoff,
    )
    return comparison_store.create_if_absent(prepared)


def _verified_kotak_connection(api_key: str | None) -> str | None:
    if not api_key:
        return None
    from database import auth_db

    owner = auth_db.verify_api_key(api_key)
    if not owner:
        return None
    with auth_db.engine.connect() as connection:
        return connection.execute(text(
            "SELECT bc.id FROM api_keys ak JOIN broker_connections bc "
            "ON bc.id = ak.broker_connection_id AND bc.user_id = ak.user_id "
            "WHERE ak.user_id = :owner AND bc.broker = 'kotak' "
            "AND bc.status IN ('connected', 'authenticated') AND bc.is_revoked = 0"
        ), {"owner": owner}).scalar_one_or_none()


def _book(data: dict, source: str) -> tuple[object, object, object, object]:
    """Only fresh depth from this packet, never cached or LTP-derived prices."""
    if source == "websocket" and data.get("book_fresh") is not True:
        return None, None, None, None
    depth = data.get("depth") if isinstance(data.get("depth"), dict) else {}
    buys = depth.get("buy") or []
    sells = depth.get("sell") or []
    if buys and sells:
        buy, sell = buys[0], sells[0]
        return buy.get("price"), sell.get("price"), buy.get("quantity"), sell.get("quantity")
    return data.get("bid"), data.get("ask"), data.get("bid_qty"), data.get("ask_qty")


def observe_market_packet(
    packet: dict, received_at: datetime, source: str, api_key: str | None
) -> int:
    """Advance matching shadows from a verified pinned, native-timed Kotak quote."""
    if source not in {"websocket", "rest"}:
        return 0
    pending = comparison_store.list_pending(received_at)
    if not pending:
        return 0
    data = packet.get("data") if isinstance(packet.get("data"), dict) else packet
    if not isinstance(data, dict) or data.get("market_time_missing"):
        return 0
    native = data.get("ltt") or data.get("lstup_time") or data.get("market_timestamp")
    if source == "rest":
        native = native or data.get("timestamp")
    if native is None:
        return 0
    from services.strategy_module.portfolio_governor import _quote_timestamp

    market_at = _quote_timestamp(native)
    connection_id = _verified_kotak_connection(api_key)
    if market_at is None or connection_id is None:
        return 0
    symbol = str(packet.get("symbol") or "").upper()
    exchange = str(packet.get("exchange") or "").upper()
    if not symbol or not exchange:
        return 0
    bid, ask, bid_qty, ask_qty = _book(data, source)
    book_at = market_at if all(value is not None for value in (bid, ask, bid_qty, ask_qty)) else None
    advanced = 0
    for snapshot in pending:
        if (
            snapshot["broker_connection_id"] != connection_id
            or snapshot["symbol"] != symbol
            or snapshot["exchange"] != exchange
        ):
            continue
        previous = snapshot.get("last_observed_at")
        if previous and market_at <= datetime.fromisoformat(previous):
            continue
        try:
            comparison_store.observe(
                snapshot["run_id"], snapshot["position_ref"],
                observed_at=market_at, received_at=received_at,
                ltp=data.get("ltp"), source="prospective",
                broker_connection_id=connection_id, symbol=symbol, exchange=exchange,
                bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty, quote_at=book_at,
            )
            advanced += 1
        except ValueError:
            # Stale, future, or out-of-order market evidence is expected during
            # reconnect; none of it can be used to improve a shadow result.
            continue
        except Exception:
            logger.exception("Could not persist sandbox comparison observation")
    return advanced


def poll_pending_comparisons() -> dict[str, int]:
    """Keep shadows observing after the real run exits, using read-only quotes.

    One batch per pinned Kotak account per cycle. A missing/stale quote does
    not trigger a fill, and no order-capable API is reachable from this path.
    """
    from database import auth_db
    from services import quotes_service

    now = _now()
    counts = {"quotes": 0, "observations": 0, "cutoff": 0}
    pending = comparison_store.list_pending(now)
    groups: dict[tuple[str, str], dict[tuple[str, str], None]] = {}
    for snapshot in pending:
        run_row = store.get_run(snapshot["run_id"])
        if run_row is None or run_row.broker_connection_id != snapshot["broker_connection_id"]:
            continue
        strategy = store.get_strategy_unscoped(run_row.strategy_id)
        if strategy is None:
            continue
        key = (strategy.user_id, snapshot["broker_connection_id"])
        groups.setdefault(key, {})[(snapshot["symbol"], snapshot["exchange"])] = None

    for (user_id, connection_id), symbols in groups.items():
        try:
            api_key = auth_db.get_api_key_for_tradingview(user_id)
            if _verified_kotak_connection(api_key) != connection_id:
                continue
            pairs = [{"symbol": symbol, "exchange": exchange} for symbol, exchange in symbols]
            for offset in range(0, len(pairs), 40):
                ok, response, _status = quotes_service.get_multiquotes(
                    pairs[offset:offset + 40], api_key=api_key
                )
                if not ok or not isinstance(response, dict):
                    continue
                for packet in response.get("results") or []:
                    if not isinstance(packet, dict) or not isinstance(packet.get("data"), dict):
                        continue
                    counts["quotes"] += 1
                    counts["observations"] += observe_market_packet(
                        packet, received_at=_now(), source="rest", api_key=api_key
                    )
        except Exception:
            logger.exception("Could not poll pinned Kotak sandbox comparison quotes")
    counts["cutoff"] = comparison_store.finalize_due(_now())
    return counts
