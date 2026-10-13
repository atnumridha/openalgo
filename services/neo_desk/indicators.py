"""Causal previous-bar Donchian, EMA200 and Wilder ATR14."""

from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Point:
    upper: D | None
    lower: D | None
    ema: D
    atr: D | None


def compute_indicators(bars, length=20):
    points = []
    ranges = []
    ema = None
    atr = None
    for i, b in enumerate(bars):
        prior = bars[max(0, i - length) : i]
        ema = b.close if ema is None else ema + D(2) / 201 * (b.close - ema)
        tr = b.high - b.low
        if i:
            tr = max(tr, abs(b.high - bars[i - 1].close), abs(b.low - bars[i - 1].close))
        ranges.append(tr)
        if i == 13:
            atr = sum(ranges[:14]) / 14
        elif i > 13:
            atr = (atr * 13 + tr) / 14
        points.append(
            Point(
                max(b.high for b in prior) if len(prior) == length else None,
                min(b.low for b in prior) if len(prior) == length else None,
                ema,
                atr,
            )
        )
    return points
