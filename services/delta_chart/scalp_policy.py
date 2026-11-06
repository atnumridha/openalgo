"""Fee-aware legacy floors and adaptive candle trailing; pure offline arithmetic."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def profit_protection(
    entry, mark, size, contract_value, tick, entry_fees, exit_rate, peak
):
    coin = abs(size) * contract_value
    long = size > 0
    net = (
        (mark - entry) * size * contract_value - entry_fees - coin * mark * exit_rate
    ) * 85
    peak = max(peak, net)
    # Activate only after the verified after-fee peak reaches ₹15.
    # The tick-distance check below still preserves the existing broker stop
    # until the ₹10 floor can be placed safely.
    if peak < Decimal(15):
        return peak, None, None, False
    floor = max(Decimal(10), peak - Decimal(10))
    if net <= floor:
        return peak, floor, None, True
    fee_per_coin = entry_fees / coin
    lock_per_coin = floor / (85 * coin)
    raw = (
        (entry + fee_per_coin + lock_per_coin) / (1 - exit_rate)
        if long
        else (entry - fee_per_coin - lock_per_coin) / (1 + exit_rate)
    )
    stop = (raw / tick).to_integral_value(
        rounding=ROUND_CEILING if long else ROUND_FLOOR
    ) * tick
    # Being too close to place the tick-rounded stop is not a take-profit signal.
    # Keep existing broker protection and wait for room; only an actual net-floor
    # breach (checked above) authorizes a profit-floor market close.
    too_close = stop >= mark - tick if long else stop <= mark + tick
    return peak, floor, None if too_close else stop, False


def _adaptive_number(value, positive=False):
    from decimal import InvalidOperation
    from math import isfinite

    if value is None or isinstance(value, bool):
        raise ValueError("Invalid candle or risk evidence")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid candle or risk evidence") from None
    if not result.is_finite() or not isfinite(float(result)) or (positive and result <= 0):
        raise ValueError("Invalid candle or risk evidence")
    return result


def adaptive_candle_segment(candles, interval_seconds, observed_at, now):
    """Verify descending raw UTC history; only completed contiguous bars count."""
    span = _adaptive_number(interval_seconds, True)
    observed, current = _adaptive_number(observed_at, True), _adaptive_number(now, True)
    if span != span.to_integral_value() or span > 86400:
        raise ValueError("Unsupported candle interval")
    if observed > current or current-observed > 30:
        raise ValueError("Stale or future candle observation")
    if not isinstance(candles, list) or len(candles) > 10000:
        raise ValueError("Missing bounded candle history")
    segment, previous = [], None
    for candle in candles:
        if not isinstance(candle, dict):
            break
        try:
            stamp = _adaptive_number(candle['time'], True)
            if stamp != stamp.to_integral_value() or stamp % span or (previous is not None and stamp >= previous):
                break
            previous = stamp
            if stamp+span > observed or stamp+span > current:
                continue
            bar = {'time':int(stamp), **{key:_adaptive_number(candle[key], True)
                   for key in ('open','high','low','close')}}
            if (bar['high'] < max(bar['open'],bar['low'],bar['close'])
                    or bar['low'] > min(bar['open'],bar['close'])
                    or (segment and segment[-1]['time']-stamp != span)):
                break
            segment.append(bar)
            if len(segment) == 300:
                break
        except (KeyError, ValueError, TypeError):
            break
    expected = (int(current//span)-1)*int(span)
    if len(segment) < 15 or segment[0]['time'] != expected:
        raise ValueError("Waiting for fresh contiguous completed candles")
    return segment[::-1]


def adaptive_profit_protection(entry, mark, size, contract_value, tick, entry_fees, exit_rate, peak,
                               candles, interval_seconds, observed_at, now, current_stop, *, first_fill_at=None):
    """Stage risk reduction and profit locks along completed post-fill structure.

    Three full post-fill bars supply wick extremes, with a quarter ATR14 buffer
    and at least one ATR behind mark. The structural candidate may reduce loss,
    then lock partial profit, then cover INR10; no rupee goal moves it inside
    structure. Positive locks require verified USD0.15 net peak. Peak is
    remembered but never authorizes a fixed-gap exit.
    """
    from decimal import InvalidOperation

    reason = 'Waiting for fresh completed candle structure; existing SL retained.'
    try:
        entry, mark, contract_value, tick, current_stop = (
            _adaptive_number(value, True) for value in (entry,mark,contract_value,tick,current_stop))
        size, entry_fees, exit_rate, peak = (
            _adaptive_number(value) for value in (size,entry_fees,exit_rate,peak))
        if size == 0 or entry_fees < 0 or not 0 <= exit_rate < 1 or peak < 0:
            raise ValueError('Invalid fee or position evidence')
        coin, long = abs(size)*contract_value, size > 0
        net = ((mark-entry)*size*contract_value-entry_fees-coin*mark*exit_rate)*85
        peak = max(peak, net)
        bars = adaptive_candle_segment(candles,interval_seconds,observed_at,now)
        if first_fill_at is None:
            return peak,None,None,False,'Waiting for verified first-fill timing and three completed post-fill candles; existing SL retained.'
        first_fill = _adaptive_number(first_fill_at, True)
        post_fill = [bar for bar in bars if bar['time'] >= first_fill]
        if first_fill > _adaptive_number(observed_at, True) or len(post_fill) < 3:
            return peak,None,None,False,'Waiting for three fully post-fill completed candles; existing SL retained.' 
        recent = bars[-15:]
        atr = sum(max(bar['high']-bar['low'],abs(bar['high']-prior['close']),
                      abs(bar['low']-prior['close'])) for prior,bar in zip(recent,recent[1:])) / 14
        if atr <= 0:
            raise ValueError('ATR must be positive')
        distance = max(atr,tick*2)
        raw = (min(min(bar['low'] for bar in post_fill[-3:])-atr*Decimal('.25'),mark-distance)
               if long else max(max(bar['high'] for bar in post_fill[-3:])+atr*Decimal('.25'),mark+distance))
        stop = (raw/tick).to_integral_value(rounding=ROUND_FLOOR if long else ROUND_CEILING)*tick
        if stop <= 0:
            raise ValueError('Structural stop is not positive')
        stop_net = ((stop-entry)*size*contract_value-entry_fees-coin*stop*exit_rate)*85
        if (stop <= current_stop if long else stop >= current_stop):
            return peak,None,None,False,'Existing acknowledged SL is tighter than completed post-fill candle structure; SL retained.'
        tick_profit = coin*tick*85
        if stop_net >= tick_profit and peak < Decimal('.15')*85:
            return peak,None,None,False,'Waiting for verified USD0.15 net peak before locking positive profit; existing SL retained.'
        if stop_net >= Decimal(10):
            return peak,Decimal(10),stop,False,'Structural SL now covers INR10 net after fees; trailing completed post-fill candles.'
        if stop_net >= tick_profit:
            return peak,stop_net,stop,False,'Locking partial net profit along completed post-fill candle structure; INR10 lock waits for room.'
        return peak,None,stop,False,'Reducing risk along completed post-fill candle structure; fees and one profit tick are not yet covered.'
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError, ZeroDivisionError):
        return peak,None,None,False,reason
