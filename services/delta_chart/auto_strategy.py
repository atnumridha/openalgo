"""Offline Delta 1m/5m EMA entry policy, using standard fees and Decimal money.

Inputs are snapshots; this module never reads credentials, performs I/O or places orders.
Raw history timestamps must be UTC candle opens, newest first.

Fixed, prospective setup rules (not fitted to the observed trade sample): both
EMA9/15 slopes over three completed bars must support the aligned 1m/5m trend,
with at least .1 ATR14 separation on each timeframe. A countertrend-colored
pullback must touch the previously known EMA9/15 zone +/- .25 ATR within the
prior five bars, then a trend-colored candle must close one tick beyond its
preceding high/low and beyond EMA9. Only the first such continuation qualifies.
The completed pullback and any retained swing define invalidation: .25 ATR
buffer, >=1 ATR / three ticks noise floor, with NO upper risk/stop clipping.
Whole lots shrink to the INR20 risk cap; if one cannot fit, wait. No daily halt.
"""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from math import isfinite

from services.delta_chart.ema import ema_backfill


class InvalidEvidence(ValueError):
    pass


def _number(value, *, positive=False):
    if value is None or isinstance(value, bool):
        raise InvalidEvidence('Missing or invalid numeric evidence.')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise InvalidEvidence('Invalid numeric evidence.') from None
    if not number.is_finite() or not isfinite(float(number)) or (positive and (number <= 0 or float(number) <= 0)):
        raise InvalidEvidence('Nonfinite or nonpositive numeric evidence.')
    return number


def _integer(value):
    number = _number(value, positive=True)
    if number != number.to_integral_value() or number > 9007199254740991:
        raise InvalidEvidence('A positive safe integer is required.')
    return int(number)


def _segment(raw, seconds, observed, now):
    if not isinstance(raw, list) or len(raw) > 10000:
        raise InvalidEvidence('Expected bounded UTC candle history.')
    result, previous_raw = [], None
    for candle in raw:
        if not isinstance(candle, dict):
            break
        try:
            stamp = _integer(candle['time'])
            if previous_raw is not None and stamp >= previous_raw:
                break
            previous_raw = stamp
            # Neither a later wall clock nor an unclosed OHLC can confirm a bar.
            if stamp + seconds > observed or stamp + seconds > now:
                continue
            bar = {'time': stamp, **{key: _number(candle[key], positive=True)
                                    for key in ('open', 'high', 'low', 'close')}}
            if (stamp % seconds or bar['high'] < max(bar['open'], bar['close'], bar['low'])
                    or bar['low'] > min(bar['open'], bar['close'])
                    or (result and result[-1]['time'] - stamp != seconds)):
                break
            result.append(bar)
            if len(result) == 300:
                break
        except (InvalidEvidence, KeyError, TypeError):
            break
    if len(result) < 55 or result[0]['time'] != (int(now) // seconds - 1) * seconds:
        raise InvalidEvidence(f'Waiting for 55 fresh contiguous completed {seconds}s candles.')
    return result[::-1]


def _levels(bars):
    latest, support, resistance = bars[-1]['close'], None, None
    for i in range(2, len(bars) - 2):
        bar, left, right, after = bars[i], bars[i-2:i], bars[i+1:i+3], bars[i+1:]
        low, high = bar['low'], bar['high']
        if (low < latest and all(b['low'] > low for b in left)
                and all(b['low'] >= low for b in right) and all(b['close'] >= low for b in after)):
            support = low if support is None else max(support, low)
        if (high > latest and all(b['high'] < high for b in left)
                and all(b['high'] <= high for b in right) and all(b['close'] <= high for b in after)):
            resistance = high if resistance is None else min(resistance, high)
    return support, resistance


def _json_bar(bar):
    return {key: (value if key == 'time' else float(value)) for key, value in bar.items()}


def _reading(bars):
    ema = ema_backfill([{'time': b['time'], 'close': float(b['close'])} for b in bars])
    fast, slow = ema['9']['value'], ema['15']['value']
    _number(fast, positive=True)
    _number(slow, positive=True)
    # Compare current averages: equal EMA values cannot authorize a direction.
    direction = 'up' if fast > slow else 'down' if fast < slow else 'sideways'
    return direction, fast, slow


def _atr(bars):
    recent = bars[-15:]
    value = sum(max(b['high']-b['low'], abs(b['high']-p['close']), abs(b['low']-p['close']))
                for p, b in zip(recent, recent[1:])) / 14
    if value <= 0:
        raise InvalidEvidence('ATR must be positive.')
    return value


def _pullback_setup(bars, long, tick):
    def counter(bar):
        return bar['close'] < bar['open'] if long else bar['close'] > bar['open']

    def continuation(index):
        bar, previous = bars[index], bars[index-1]
        _, fast, _ = _reading(bars[:index+1])
        fast = _number(fast, positive=True)
        return (bar['close'] > bar['open'] and bar['close'] >= previous['high']+tick and bar['close'] > fast) if long else (
            bar['close'] < bar['open'] and bar['close'] <= previous['low']-tick and bar['close'] < fast)

    anchor = None
    for index in range(len(bars)-2, len(bars)-7, -1):
        bar = bars[index]
        if not counter(bar):
            continue
        _, fast, slow = _reading(bars[:index])
        tolerance = _atr(bars[:index])*Decimal('.25')
        lower, upper = min(_number(fast), _number(slow)), max(_number(fast), _number(slow))
        if bar['low'] <= upper+tolerance and bar['high'] >= lower-tolerance:
            anchor = index
            while anchor > 0 and counter(bars[anchor-1]):
                anchor -= 1
            if anchor < len(bars)-6:
                raise InvalidEvidence('The EMA pullback is stale; waiting for a fresh pullback.')
            break
    if anchor is None:
        raise InvalidEvidence('Waiting for a recent completed pullback to the EMA9/15 zone.')
    if any(continuation(index) for index in range(anchor+1, len(bars)-1)):
        raise InvalidEvidence('This pullback already had its continuation; waiting for a new setup.')
    if not continuation(len(bars)-1):
        raise InvalidEvidence('Waiting for a trend-colored continuation close beyond the preceding candle.')
    wick = min(b['low'] for b in bars[anchor:]) if long else max(b['high'] for b in bars[anchor:])
    return bars[anchor]['time'], wick


def _patterns(bars):
    """Brief observations only; patterns never gate the EMA entry decision."""
    last, previous = bars[-1], bars[-2]
    body = abs(last['close'] - last['open'])
    span = last['high'] - last['low']
    patterns = []
    if span > 0 and body <= span * Decimal('.1'):
        patterns.append({'name': 'doji', 'time': last['time'], 'direction': 'neutral'})
    if (last['close'] > last['open'] and previous['close'] < previous['open']
            and last['open'] <= previous['close'] and last['close'] >= previous['open']):
        patterns.append({'name': 'bullish_engulfing', 'time': last['time'], 'direction': 'up'})
    if (last['close'] < last['open'] and previous['close'] > previous['open']
            and last['open'] >= previous['close'] and last['close'] <= previous['open']):
        patterns.append({'name': 'bearish_engulfing', 'time': last['time'], 'direction': 'down'})
    return patterns


def decide(state, fast_candles, slow_candles, settings, observed_at, now):
    """Return JSON-safe context, a proposed maker action or None, and its reason."""
    context = {'source_time': None, 'direction': 'unavailable', 'higher_direction': 'unavailable',
               'trend_summary': 'Waiting for fresh completed candles.', 'support': None, 'resistance': None,
               'ema9': None, 'ema15': None, 'higher_ema9': None, 'higher_ema15': None,
               'patterns': [], 'candle_count': 0, 'higher_candle_count': 0,
               'setup_status': 'waiting', 'setup_time': None, 'setup_id': None, 'stop_source': None}
    def reject(reason):
        context['setup_reason'] = reason
        return {'context': context, 'action': None, 'reason': reason}
    try:
        observed, current = _number(observed_at, positive=True), _number(now, positive=True)
        if observed > current or current - observed > 30:
            raise InvalidEvidence('Candle observation is stale or ahead of the current clock.')
        fast = _segment(fast_candles, 60, observed, current)
        slow = _segment(slow_candles, 300, observed, current)
        direction, ema9, ema15 = _reading(fast)
        higher, higher9, higher15 = _reading(slow)
        support, resistance = _levels(fast)
        context.update(source_time=fast[-1]['time'], direction=direction, higher_direction=higher,
                       ema9=ema9, ema15=ema15, higher_ema9=higher9, higher_ema15=higher15,
                       trend_summary=f'1m: {direction} EMA9/15 · 5m: {higher} EMA9/15',
                       support=float(support) if support is not None else None,
                       resistance=float(resistance) if resistance is not None else None,
                       patterns=_patterns(fast), candle_count=len(fast), higher_candle_count=len(slow),
                       bars=[_json_bar(bar) for bar in fast[-55:]])
        if direction not in ('up', 'down') or direction != higher:
            return reject('Waiting for agreeing 1m and 5m EMA9/15 direction.')
        if not isinstance(state, dict) or state.get('connected') is not True:
            return reject('Waiting for a connected verified account snapshot.')
        try:
            snapshot_at = _number(state.get('asof'), positive=True)
        except InvalidEvidence:
            return reject('Waiting for a numeric, fresh account snapshot timestamp.')
        if snapshot_at > current or current-snapshot_at > 10:
            return reject('Account snapshot is stale or ahead of the current clock.')
        if state.get('position') or state.get('orders'):
            return reject('An account position or order is already active.')
        if not isinstance(settings, dict):
            raise InvalidEvidence('Invalid automation settings.')
        product, ticker, sizing = state['product'], state['ticker'], state['sizing']
        tick = _number(product['tick_size'], positive=True)
        cv = _number(product['contract_value'], positive=True)
        leverage = _integer(settings['leverage'])
        if leverage > min(200, _number(product['max_leverage'], positive=True)):
            raise InvalidEvidence('Leverage exceeds the verified product limit.')
        bid, ask, mark = (_number(ticker[key], positive=True) for key in ('bid','ask','mark'))
        if bid > ask or bid % tick or ask % tick:
            raise InvalidEvidence('Invalid or off-tick maker quotes.')
        long = direction == 'up'
        side, entry = ('buy', bid) if long else ('sell', ask)
        sign = Decimal(1) if long else Decimal(-1)
        atr, higher_atr = _atr(fast), _atr(slow)
        _, older9, older15 = _reading(fast[:-3])
        _, higher_older9, higher_older15 = _reading(slow[:-3])
        slopes = [(_number(value)-_number(previous))*sign for value, previous in
                  ((ema9, older9), (ema15, older15), (higher9, higher_older9), (higher15, higher_older15))]
        context.update(ema9_slope=float(slopes[0]*sign), ema15_slope=float(slopes[1]*sign),
                       higher_ema9_slope=float(slopes[2]*sign), higher_ema15_slope=float(slopes[3]*sign))
        if any(slope <= 0 for slope in slopes):
            return reject('Waiting for supporting EMA9/15 slopes on both 1m and 5m.')
        if abs(_number(ema9)-_number(ema15)) < atr*Decimal('.1') or abs(_number(higher9)-_number(higher15)) < higher_atr*Decimal('.1'):
            return reject('EMA separation is too small relative to ATR; waiting outside chop.')
        latest = fast[-1]
        gap = (entry-latest['close']) * sign
        if gap > atr * Decimal('.5') or gap < -atr:
            return reject('Price moved too far from the last confirmed candle.')
        if latest['high']-latest['low'] > atr*2 or abs(latest['close']-latest['open']) > atr*Decimal('1.5'):
            return reject('A sharp move just finished; waiting for another completed candle.')
        if ((long and resistance is not None and resistance > latest['close'] and entry >= resistance)
                or (not long and support is not None and support < latest['close'] and entry <= support)):
            return reject('The breakout has not closed beyond support or resistance.')
        setup_time, pullback_wick = _pullback_setup(fast, long, tick)
        if ((long and (entry < fast[-2]['high']+tick or entry <= _number(ema9))) or
                (not long and (entry > fast[-2]['low']-tick or entry >= _number(ema9)))):
            return reject('Maker quote no longer holds the confirmed continuation break.')
        setup_id = f'ema:{side}:{setup_time}'
        level = support if long else resistance
        invalidation = pullback_wick
        stop_source = 'completed_pullback_wick'
        if level is not None and (level < invalidation if long else level > invalidation):
            invalidation, stop_source = level, 'confirmed_swing_and_pullback'
        if (long and entry <= invalidation) or (not long and entry >= invalidation):
            return reject('Maker quote is beyond the completed pullback invalidation.')
        structural = abs(entry-invalidation)+atr*Decimal('.25')
        risk = max(atr, structural, tick*3)
        stop = ((entry-sign*risk)/tick).to_integral_value(rounding=ROUND_FLOOR if long else ROUND_CEILING)*tick
        context.update(setup_status='confirmed_continuation', setup_time=setup_time, setup_id=setup_id,
                       stop_source=stop_source, invalidation=float(invalidation), atr=float(atr),
                       structural_stop=float(stop), setup_reason='Fresh EMA-zone pullback and closed continuation confirmed.')
        actual_risk = abs(entry-stop)
        target = entry + sign*2*actual_risk
        if stop <= 0 or target <= 0:
            raise InvalidEvidence('Stop or target is not positive.')
        if (not isinstance(sizing, dict) or sizing.get('currency') != 'USD'
                or not isinstance(sizing.get('version'), str) or not sizing['version']):
            raise InvalidEvidence('Waiting for verified standard USD fees and balance.')
        maker, taker, tax = (_number(sizing[key]) for key in ('maker_fee_rate','taker_fee_rate','fee_tax_rate'))
        available = _number(sizing['available_balance'])
        if any(value < 0 or value > 1 for value in (maker,taker,tax)) or available < 0:
            raise InvalidEvidence('Invalid standard fee or available balance evidence.')
        target_fees = (entry*maker+target*taker)*(1+tax)
        if abs(target-entry) < target_fees+tick:
            return reject('Scalp target does not cover standard entry/exit fees plus one tick.')
        cost = max(entry,mark,bid,ask)*cv*(1/Decimal(leverage)+maker*(1+tax))
        affordable = int(available*Decimal('.99')/cost)
        loss_per_lot = (actual_risk+(entry*maker+stop*taker)*(1+tax))*cv*85
        risk_cap = int(Decimal(20)/loss_per_lot)
        fraction = settings.get('balance_fraction')
        if fraction is None:
            size = _integer(settings['manual_quantity'])
            if size > risk_cap or size > affordable:
                return reject('Manual quantity exceeds the INR20 risk cap or available margin.')
        else:
            fraction = _number(fraction, positive=True)
            if fraction not in (Decimal('.1'),Decimal('.25'),Decimal('.5'),Decimal('.75'),Decimal(1)):
                raise InvalidEvidence('Unsupported balance fraction.')
            size = min(int(fraction*available*Decimal('.99')/cost),risk_cap)
        if size < 1 or size > 9007199254740991:
            return reject('Available balance or INR20 risk cap does not fund one contract.')
        action = {'strategy_id':'ema', 'setup_time':setup_time, 'setup_id':setup_id, 'side':side,'size':size,'order_type':'limit_order','price':float(entry),'leverage':leverage,
                  'auto_protection': {'stop':float(stop),'target':float(target),'source_time':fast[-1]['time'],
                                      'interval_seconds':60,'reason':'Fresh EMA pullback/continuation; buffered structural invalidation, 2R reference.'}}
        if fraction is not None:
            action.update(balance_fraction=float(fraction),sizing_version=sizing['version'])
        return {'context':context,'action':action,'reason':'Fresh EMA pullback/continuation with aligned 1m/5m slopes; structural stop and standard risk checks passed.'}
    except (InvalidEvidence, KeyError, TypeError, ValueError, InvalidOperation, OverflowError, ZeroDivisionError) as exc:
        return reject(str(exc) if isinstance(exc, InvalidEvidence) else 'Missing or malformed strategy evidence.')
