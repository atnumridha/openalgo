"""Estimated per-execution charges, never actual paid contract-note charges."""

from decimal import ROUND_HALF_UP
from decimal import Decimal as D


def money(value):
    return D(value).quantize(D(".01"), rounding=ROUND_HALF_UP)


def estimate(side, price, quantity, brokerage=D(0)):
    t = D(price) * quantity
    exchange = t * D(".000355299")
    sebi = t * D(".000001")
    ipft = t * D(".000000001")
    return sum(
        money(x)
        for x in (
            brokerage,
            exchange,
            sebi,
            ipft,
            (brokerage + exchange + sebi + ipft) * D(".18"),
            t * D(".00003") if side == "BUY" else D(0),
            t * D(".0015") if side == "SELL" else D(0),
        )
    )
