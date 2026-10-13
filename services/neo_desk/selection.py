from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR
from decimal import Decimal as D

from .fees import estimate
from .types import IST, Selection


def select_contract(
    contracts,
    quotes,
    preset,
    available_limit,
    now,
    *,
    direction=None,
    index_reference=None,
    recent_bars=None,
    brokerage=D(10),
):
    candidates = []
    if now.tzinfo is None or not D(available_limit).is_finite() or D(available_limit) <= 0:
        return Selection(False, error="Fresh available trading limit is required.")
    for c in contracts:
        q = quotes.get(c.symbol)
        if (
            c.option_type != direction
            or c.exchange != "NFO"
            or c.expiry < now.astimezone(IST).date()
            or c.lot_size != 65
            or c.tick_size <= 0
            or not q
            or q.symbol != c.symbol
            or not q.fresh(now)
        ):
            continue
        if (
            not all(D(x).is_finite() and x > 0 for x in (q.bid, q.ask))
            or q.ask < q.bid
            or abs(q.ask - 50) > 5
            or q.ask - q.bid > min(D(1), q.ask * D(".01"))
            or q.bid_qty is None
            or q.ask_qty is None
            or min(q.bid_qty, q.ask_qty) < c.lot_size
        ):
            continue
        if preset.controlled:
            times = {
                b.time
                for b in (recent_bars or {}).get(c.symbol, [])
                if b.confirmed and not b.repaired and b.time + timedelta(minutes=1) <= now
            }
            if any(
                now.replace(second=0, microsecond=0) - timedelta(minutes=n) not in times
                for n in range(1, 6)
            ):
                continue
        limit = ((q.ask + D(".50")) / c.tick_size).to_integral_value(
            rounding=ROUND_CEILING
        ) * c.tick_size
        stop = (
            (limit * D(".90") / c.tick_size).to_integral_value(rounding=ROUND_FLOOR) * c.tick_size
            if preset.controlled
            else None
        )
        cost = limit * c.lot_size + estimate("BUY", limit, c.lot_size, brokerage)
        if cost > available_limit:
            continue
        if stop is not None:
            exit = max(c.tick_size, stop - D(".50"))
            loss = (
                (limit - exit) * c.lot_size
                + estimate("BUY", limit, c.lot_size, brokerage)
                + estimate("SELL", exit, c.lot_size, brokerage)
            )
            if loss > min(D(500), D(available_limit) * D(".05")):
                continue
        candidates.append(
            (
                abs(q.ask - 50),
                q.ask - q.bid,
                abs(c.strike - D(str(index_reference))) if index_reference is not None else D(0),
                c.symbol,
                Selection(True, c, q, c.lot_size, limit, cost, stop),
            )
        )
    return (
        min(candidates, key=lambda x: x[:4])[-1]
        if candidates
        else Selection(
            False, error="No option fits fresh premium, depth, lot, risk and trading-limit checks."
        )
    )
