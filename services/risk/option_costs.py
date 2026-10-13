"""Pure estimated NSE option fees; actual charges remain an accounting fact."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP
from decimal import Decimal as D


@dataclass(frozen=True)
class FeeSchedule:
    brokerage: D = D(0)
    exchange: D = D(".000355299")
    sebi: D = D(".000001")
    ipft: D = D(".000000001")
    gst: D = D(".18")
    stamp: D = D(".00003")
    stt: D = D(".0015")


def money(value):
    return D(value).quantize(D(".01"), rounding=ROUND_HALF_UP)


def estimate_option_fees(side, price, quantity, rates=FeeSchedule()):
    if side not in ("BUY", "SELL") or quantity <= 0 or price <= 0:
        raise ValueError("A fee estimate requires an executed side, price and quantity.")
    t = D(price) * quantity
    exchange = t * rates.exchange
    sebi = t * rates.sebi
    ipft = t * rates.ipft
    return sum(
        money(x)
        for x in (
            rates.brokerage,
            exchange,
            sebi,
            ipft,
            (rates.brokerage + exchange + sebi + ipft) * rates.gst,
            t * rates.stamp if side == "BUY" else D(0),
            t * rates.stt if side == "SELL" else D(0),
        )
    )
