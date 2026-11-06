"""Independent completed-bar EMA9/15/21 alignment detector; no I/O or execution.

A regime starts at a witnessed transition into strict ordering. Gaps/slopes and
price may qualify later, but only its first qualifying close can signal. A regime
already in progress when EMA21 seeds is deliberately ineligible: its transition
cannot be established from the supplied history.
"""
from bisect import bisect_right
from decimal import Decimal

from services.delta_chart.ema import ema_backfill
from services.delta_chart.auto_strategy import InvalidEvidence

D = Decimal


def atr14(bars):
    spans = [max(b['high']-b['low'], abs(b['high']-p['close']), abs(b['low']-p['close']))
             for p, b in zip(bars, bars[1:])]
    if len(spans) < 14:
        raise InvalidEvidence('Waiting for ATR14 history.')
    value = sum(spans[:14]) / 14
    for span in spans[14:]:
        value = (value*13+span)/14
    if value <= 0:
        raise InvalidEvidence('ATR14 must be positive.')
    return value


def _series(bars):
    readings = ema_backfill([dict(time=b['time'], close=float(b['close'])) for b in bars])
    return {p: {point['time']: D(str(point['value'])) for point in readings[p]['points']}
            for p in ('9', '15', '21')}


def alignment_events(bars, higher=None):
    """All first qualifying regimes in ascending validated, completed bars.

    Chart callers omit higher. Auto supplies higher to retain its as-of 5m
    direction gate; a rejected higher direction never consumes the regime.
    """
    if len(bars) < 25 or (higher is not None and len(higher) < 15):
        return []
    values = _series(bars)
    higher_values = _series(higher) if higher is not None else None
    higher_stamps = [b['time'] for b in higher if b['time'] in higher_values['15']] if higher is not None else []
    # Wilder's ATR is advanced once per bar, with exactly the legacy seed and
    # arithmetic order, so a 10000-bar chart remains linear in its history.
    atr_values, seed, value = {}, [], None
    for index, (previous, bar) in enumerate(zip(bars, bars[1:]), 1):
        span = max(bar['high']-bar['low'], abs(bar['high']-previous['close']),
                   abs(bar['low']-previous['close']))
        if index <= 14:
            seed.append(span)
            if index == 14:
                value = sum(seed)/14
        else:
            value = (value*13+span)/14
        atr_values[index] = value
    events = []
    prior_order, transition, consumed = None, None, False
    for index in range(20, len(bars)):
        bar, stamp = bars[index], bars[index]['time']
        fast, middle, slow = (values[p][stamp] for p in ('9', '15', '21'))
        order = 1 if fast > middle > slow else -1 if fast < middle < slow else 0
        if order != prior_order:
            transition = stamp if prior_order is not None and order else None
            consumed = False
        prior_order = order
        if not order or transition is None or consumed or index < 23:
            continue
        atr = atr_values[index]
        if atr <= 0:
            raise InvalidEvidence('ATR14 must be positive.')
        if min(abs(fast-middle), abs(middle-slow)) < atr*D('.1'):
            continue
        older = bars[index-3]['time']
        if any((values[p][stamp]-values[p][older])*order <= 0 for p in ('9', '15', '21')):
            continue
        if ((bar['close']-fast)*order <= 0 or (bar['close']-slow)*order <= 0):
            continue
        # At a 1m close, only already-closed 5m readings are eligible.
        if higher_values is not None:
            position = bisect_right(higher_stamps, stamp+60-300)-1
            if position < 0:
                continue
            higher_stamp = higher_stamps[position]
            if (higher_values['9'][higher_stamp]-higher_values['15'][higher_stamp])*order <= 0:
                continue
        consumed = True
        long = order == 1
        events.append(dict(strategy_id='ema_three', side='buy' if long else 'sell',
                           setup_time=transition, source_time=stamp, interval_seconds=60,
                           latest=bar, atr=atr, wick=min(slow, bar['low']) if long else max(slow, bar['high']),
                           ema9=fast, ema15=middle, ema21=slow,
                           **({'entry_floor': fast} if long else {'entry_ceiling': fast})))
    return events


def detect(bars, higher):
    """Return an Auto candidate only on the latest bar, preserving consumption."""
    events = alignment_events(bars, higher)
    return events[-1:] if events and events[-1]['source_time'] == bars[-1]['time'] else []
