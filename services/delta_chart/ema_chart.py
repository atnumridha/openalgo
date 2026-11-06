"""Completed-chart OHLC confirmation, isolated from legacy Auto EMA readings."""
import math
import time
from decimal import Decimal

from services.delta_chart.ema import ema_backfill
from services.delta_chart.three_ema import alignment_events


def ema_chart_backfill(candles, seconds=None, *, observed_at=None, allow_session_gaps=False):
    """Extend the legacy payload with first qualifying three-EMA chart events.

    Wall-clock closure is rechecked here. Without interval or OHLC evidence this
    preserves close-only compatibility, but cannot assert a triple confirmation.
    """
    if not isinstance(allow_session_gaps, bool):
        raise ValueError('Expected a boolean session-gap policy')
    result = ema_backfill(candles)
    result.update(alignment_crosses=[], alignment_algorithm='ema-9-15-21-alignment-v1')
    if seconds is None:
        return result
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0 or seconds != int(seconds):
        raise ValueError('Expected a positive integer chart interval')
    if not all(all(field in b for field in ('open', 'high', 'low')) for b in candles):
        return result
    bars, previous, unconfirmed_gap = [], None, False
    for candle in candles:
        try:
            stamp = float(candle['time'])
            prices = {field: Decimal(str(candle[field])) for field in ('open', 'high', 'low', 'close')}
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise ValueError('Expected complete finite chart OHLC') from None
        if any(not v.is_finite() or v <= 0 for v in prices.values()):
            raise ValueError('Expected positive finite chart OHLC')
        if prices['high'] < max(prices['open'], prices['close'], prices['low']) or prices['low'] > min(prices['open'], prices['close']):
            raise ValueError('Invalid chart OHLC range')
        if previous is not None and stamp-previous != seconds:
            gap = stamp-previous
            # Session charts may omit overnight/weekend bars. This display-only
            # policy cannot confirm an X over an intraday hole or changed phase.
            session_break = (allow_session_gaps and gap > seconds and gap % seconds == 0
                             and int(stamp//86400) != int(previous//86400))
            if not session_break:
                if not allow_session_gaps:
                    raise ValueError('Expected aligned contiguous chart candles')
                unconfirmed_gap = True
        bars.append(dict(time=stamp, **prices))
        previous = stamp
    observed = time.time() if observed_at is None else float(observed_at)
    if not math.isfinite(observed):
        raise ValueError('Expected finite observation time')
    if unconfirmed_gap:
        # Illiquid session instruments can omit candles. Retain their established
        # EMA lines, but fail closed for X confirmation instead of blanking them.
        return result
    bars = [bar for bar in bars if bar['time']+seconds <= observed]
    result['alignment_crosses'] = [dict(time=event['source_time'],
        value=float((event['ema9']+event['ema21'])/2),
        side='up' if event['side'] == 'buy' else 'down') for event in alignment_events(bars)]
    return result
