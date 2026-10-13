"""Shared at-most-two-lot affordability and planned premium-risk sizing."""

from decimal import Decimal as D

from .fees import estimate

MAX_LOTS = 2


def size_entry(available, entry, lot_size, stop=None, *, depth=None, brokerage=D(10)):
    for lots in range(MAX_LOTS, 0, -1):
        quantity = lots * lot_size
        if depth is not None and quantity > depth:
            continue
        cost = entry * quantity + estimate("BUY", entry, quantity, brokerage)
        if cost > available:
            continue
        if stop is not None:
            exit = max(D(".05"), stop - D(".50"))
            risk = (
                (entry - exit) * quantity
                + estimate("BUY", entry, quantity, brokerage)
                + estimate("SELL", exit, quantity, brokerage)
            )
            if risk > min(D(500), available * D(".05")):
                continue
        return quantity, cost
    return 0, D(0)
