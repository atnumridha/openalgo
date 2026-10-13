from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from services.neo_desk.types import Candle, Contract, Quote

IST = ZoneInfo("Asia/Kolkata")


def when(clock="09:45"):
    return datetime.fromisoformat("2026-10-13T" + clock + ":00").replace(tzinfo=IST)


def bars(profile="orb_trail", direction="CE", last="09:30"):
    sign = 1 if direction == "CE" else -1
    start = when("09:15")
    warm = [
        Candle(start - timedelta(minutes=15 * (300 - i)), D(100), D(101), D(99), D(100))
        for i in range(300)
    ]
    if profile == "donchian_controls":
        warm = [
            Candle(
                start - timedelta(minutes=15 * (300 - i)),
                D(100) + D(sign) * D(i) / 2,
                D(101) + D(sign) * D(i) / 2,
                D(99) + D(sign) * D(i) / 2,
                D(100) + D(sign) * D(i) / 2,
            )
            for i in range(300)
        ]
        base = warm[-1].close
        warm += [Candle(when("09:15"), base, base + 1, base - 1, base)]
        close = base + sign * D(3)
        return (
            warm + [Candle(when(last), close - sign, close + D(".1"), close - D(".1") - 2, close)]
            if sign == 1
            else warm + [Candle(when(last), close + 1, close + D("2.1"), close - D(".1"), close)]
        )
    today = [Candle(when("09:15"), D(100), D(101), D(99), D(100))]
    if profile == "price_retest":
        today += [replace(today[0], time=when(t)) for t in ("09:30", "09:45")]
        if sign == 1:
            today += [
                Candle(when("10:00"), D(100), D(103), D("99.9"), D(102)),
                Candle(when("10:15"), D(102), D(104), D("100.9"), D("103.9")),
            ]
        else:
            today += [
                Candle(when("10:00"), D(100), D("100.1"), D(97), D(98)),
                Candle(when("10:15"), D(98), D("99.1"), D(96), D("96.1")),
            ]
    else:
        t = when("09:30")
        while t < when(last):
            today.append(replace(today[0], time=t))
            t += timedelta(minutes=15)
        today.append(
            Candle(
                when(last),
                D(100),
                D(105) if sign == 1 else D(101),
                D(99) if sign == 1 else D(95),
                D(104) if sign == 1 else D(96),
            )
        )
    return warm + today


def contract(side="CE", **kw):
    return replace(
        Contract("NIFTY13OCT2622500" + side, "NFO", when().date(), D(22500), side, 65, D(".05")),
        **kw,
    )


def quote(c=None, **kw):
    c = c or contract()
    return replace(Quote(c.symbol, D("49.8"), D("50.2"), 65, 65, when(), when()), **kw)
