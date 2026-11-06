"""Deterministic offline setup ensemble. No I/O, execution, training or fill simulation.

Source-inspired adaptations are fixed and unbacktested: UTC daily boundaries; strict
2-left/2-right pivots; Wilder ATR14/RSI14 (30/70); .25 ATR touch/equality tolerance;
48 completed-bar range at least 2 ATR with prior RSI extreme and a directional
rejection body reclaiming the boundary; prior-20-bar breakout closed beyond one
exact tick then retouched within 3 bars; equal double extrema 3..30 bars apart
with the same closed-neckline/retest rule. Liquidity uses a previous UTC daily
high/low, an hourly sweep then its very next completed hourly confirmation, only
12:30..21:30 IST. The coordinator must reserve daily_key before entry attempts.
FVG requires confirmed daily HH/HL or LL/LH, a 15m pivot sweep on the discount /
premium side of the known current 4h open, a subsequent closed MSS, then a strict
three-candle gap (sweep searched within the previous 14 bars), unmitigated by any later completed bar, expiring after 4 bars.
Only the forming 4h OPEN is read, never its future high/low/close. Fibonacci
automatically anchors the latest opposite confirmed swing pair, or accepts explicit
settings['fib_anchors']={low,high,direction:'up'|'down'}. A .5..618 reaction must
close back beyond EMA9 with a same-direction body; optional anchor timestamps
must be completed. No historical quote is treated as a fill.

New structural stops are beyond the true invalidating wick, rounded outward;
they are never tightened to manufacture affordability. Standard fees, .99 balance
headroom and INR20 planned loss constrain whole contracts. A 2R price is a
reference; live target/trailing policy remains the coordinator's responsibility.
Current maker quotes must still hold reclaimed levels and remain within .5 ATR
favorable / 1 ATR adverse distance of the last completed setup candle.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR

from services.delta_chart import auto_strategy as ema
from services.delta_chart import three_ema
from services.delta_chart.auto_strategy import InvalidEvidence, _integer, _number, _segment

D = Decimal
VERSION = 3
PRIORITY = ('ema', 'ema_three', 'liquidity_sweep', 'fvg', 'breakout_retest', 'range_rsi', 'double_extrema', 'ema_fib')
SECONDS = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400}


def _atr(bars):
    return three_ema.atr14(bars)


def _rsi(bars):
    changes = [b['close'] - a['close'] for a, b in zip(bars, bars[1:])]
    gain = sum(max(c, D(0)) for c in changes[:14]) / 14
    loss = sum(max(-c, D(0)) for c in changes[:14]) / 14
    for change in changes[14:]:
        gain, loss = (gain * 13 + max(change, D(0))) / 14, (loss * 13 + max(-change, D(0))) / 14
    return D(100) if loss == 0 and gain else D(50) if loss == gain == 0 else 100 - 100 / (1 + gain / loss)


def _pivots(bars, key):
    low = key == 'low'
    return [(i, bar[key]) for i, bar in enumerate(bars) if 2 <= i < len(bars) - 2 and
            all((bar[key] < other[key] if low else bar[key] > other[key])
                for other in bars[i-2:i] + bars[i+1:i+3])]


def _setup(module, long, bars, wick, seconds, **extra):
    return dict(strategy_id=module, version=VERSION, side='buy' if long else 'sell',
                source_time=bars[-1]['time'], interval_seconds=seconds,
                wick=wick, latest=bars[-1], atr=_atr(bars),
                setup_time=extra.pop('setup_time',bars[-1]['time']), **extra)


def _range(bars, tick):
    latest, previous, prior = bars[-1], bars[-2], bars[-49:-1]
    atr, old_rsi = _atr(bars), _rsi(bars[:-1])
    low, high = min(b['low'] for b in prior), max(b['high'] for b in prior)
    if high - low < 2 * atr:
        return []
    tolerance = atr * D('.25')
    if old_rsi <= 30 and latest['low'] <= low + tolerance and latest['close'] >= low + tick and latest['close'] > latest['open']:
        return [_setup('range_rsi', True, bars, latest['low'], 300, entry_floor=low+tick)]
    if old_rsi >= 70 and latest['high'] >= high - tolerance and latest['close'] <= high - tick and latest['close'] < latest['open']:
        return [_setup('range_rsi', False, bars, latest['high'], 300, entry_ceiling=high-tick)]
    return []


def _retest(bars, index, level, long, tick, tolerance):
    latest = bars[-1]
    if not 1 <= len(bars) - 1 - index <= 3:
        return False
    following = bars[index+1:]
    if long:
        return (all(b['close'] >= level + tick for b in following)
                and level - tolerance <= latest['low'] <= level + tolerance
                and latest['close'] > latest['open'])
    return (all(b['close'] <= level - tick for b in following)
            and level - tolerance <= latest['high'] <= level + tolerance
            and latest['close'] < latest['open'])


def _breakout(bars, tick):
    tolerance, found = _atr(bars) * D('.25'), []
    for index in range(len(bars)-4, len(bars)-1):
        prior, bar = bars[index-20:index], bars[index]
        high, low = max(b['high'] for b in prior), min(b['low'] for b in prior)
        for long, level in ((True, high), (False, low)):
            broken = bar['close'] >= level + tick if long else bar['close'] <= level - tick
            if broken and _retest(bars, index, level, long, tick, tolerance):
                wick = min(b['low'] for b in bars[index+1:]) if long else max(b['high'] for b in bars[index+1:])
                found.append(_setup('breakout_retest', long, bars, wick, 300, setup_time=bar['time'], level=float(level),
                                    **({'entry_floor': level+tick} if long else {'entry_ceiling': level-tick})))
    return found[-1:]


def _double(bars, tick):
    tolerance, found = _atr(bars) * D('.25'), []
    for long, key in ((True, 'low'), (False, 'high')):
        pivots = _pivots(bars, key)
        for position, (second, value) in enumerate(pivots):
            for first, earlier in pivots[:position]:
                if not 3 <= second-first <= 30 or abs(value-earlier) > tolerance:
                    continue
                invalidation = min(value, earlier) if long else max(value, earlier)
                if any(b['low'] < invalidation if long else b['high'] > invalidation for b in bars[first+1:]):
                    continue
                between = bars[first+1:second]
                neckline = max(b['high'] for b in between) if long else min(b['low'] for b in between)
                for index in range(max(second+3, len(bars)-4), len(bars)-1):
                    bar = bars[index]
                    broken = bar['close'] >= neckline+tick if long else bar['close'] <= neckline-tick
                    # A neckline was crossed once, rather than already broken before confirmation.
                    before = bars[second+1:index]
                    unbroken = all(b['close'] < neckline+tick if long else b['close'] > neckline-tick for b in before)
                    if broken and unbroken and _retest(bars, index, neckline, long, tick, tolerance):
                        wick = min(value, earlier) if long else max(value, earlier)
                        found.append(_setup('double_extrema', long, bars, wick, 300, setup_time=bar['time'], level=float(neckline),
                                            **({'entry_floor': neckline+tick} if long else {'entry_ceiling': neckline-tick})))
    return found[-1:]


def _liquidity(hourly, daily, tick, now):
    # IST is UTC +05:30, no daylight-saving adjustment.
    minute = (int(now) % 86400) // 60 + 330
    if not 750 <= minute % 1440 <= 1290:
        return []
    sweep, confirm = hourly[-2:]
    previous_day = (sweep['time'] // 86400 - 1) * 86400
    prior = next((b for b in daily if b['time'] == previous_day), None)
    if prior is None:
        return []
    long = (sweep['low'] < prior['low'] and confirm['low'] >= sweep['low']
            and confirm['close'] >= sweep['high'] + tick
            and confirm['close'] > prior['low'] and confirm['close'] > confirm['open'])
    short = (sweep['high'] > prior['high'] and confirm['high'] <= sweep['high']
             and confirm['close'] <= sweep['low'] - tick
             and confirm['close'] < prior['high'] and confirm['close'] < confirm['open'])
    if long == short:
        return []
    day = datetime.fromtimestamp(confirm['time'], timezone.utc).date().isoformat()
    side = 'buy' if long else 'sell'
    return [_setup('liquidity_sweep', long, hourly, sweep['low'] if long else sweep['high'], 3600,
                   daily_key=f'{day}:{side}',
                   **({'entry_floor': max(sweep['high']+tick, prior['low']+tick)} if long else
                      {'entry_ceiling': min(sweep['low']-tick, prior['high']-tick)}))]


def _daily_direction(daily):
    lows, highs = _pivots(daily, 'low'), _pivots(daily, 'high')
    if len(lows) < 2 or len(highs) < 2:
        return None
    if lows[-1][1] > lows[-2][1] and highs[-1][1] > highs[-2][1]:
        return True
    if lows[-1][1] < lows[-2][1] and highs[-1][1] < highs[-2][1]:
        return False
    return None


def _current_open(raw, now):
    stamp = int(now) // 14400 * 14400
    if not isinstance(raw, list):
        raise InvalidEvidence('Waiting for the known current 4h open.')
    for bar in raw:
        if isinstance(bar, dict) and _integer(bar.get('time')) == stamp:
            return _number(bar.get('open'), positive=True)
    raise InvalidEvidence('Waiting for the known current 4h open.')


def _fvg(bars, daily, opening, tick, bid, ask):
    long = _daily_direction(daily)
    if long is None:
        return []
    quote, found = (bid if long else ask), []
    if (long and quote >= opening) or (not long and quote <= opening):
        return []
    for third in range(len(bars)-5, len(bars)):
        first, last = bars[third-2], bars[third]
        lower, upper = (first['high'], last['low']) if long else (last['high'], first['low'])
        if lower >= upper or not lower <= quote <= upper:
            continue
        if any(b['low'] <= upper if long else b['high'] >= lower for b in bars[third+1:]):
            continue
        for sweep_index in range(max(4, third-14), third-2):
            previous = bars[:sweep_index]
            lows, highs = _pivots(previous, 'low'), _pivots(previous, 'high')
            if not lows or not highs:
                continue
            sweep = bars[sweep_index]
            level = lows[-1][1] if long else highs[-1][1]
            opposite = highs[-1][1] if long else lows[-1][1]
            swept = (sweep['low'] < level and sweep['low'] < opening and sweep['close'] > level) if long else (
                sweep['high'] > level and sweep['high'] > opening and sweep['close'] < level)
            if not swept:
                continue
            invalidated = any(b['low'] < sweep['low'] if long else b['high'] > sweep['high']
                              for b in bars[sweep_index+1:])
            if invalidated:
                continue
            for mss in range(sweep_index+1, third-1):
                crossed = bars[mss]['close'] >= opposite+tick if long else bars[mss]['close'] <= opposite-tick
                if crossed:
                    found.append(_setup('fvg', long, bars, sweep['low'] if long else sweep['high'], 900, setup_time=last['time'],
                                        gap_low=float(lower), gap_high=float(upper), gap_time=last['time'],
                                        four_hour_open=float(opening), daily_direction='up' if long else 'down',
                                        entry_floor=lower, entry_ceiling=upper))
                    break
    return found[-1:]


def _fib(fast, context, settings, tick):
    direction = context.get('direction')
    if direction not in ('up', 'down') or context.get('higher_direction') != direction:
        return []
    long = direction == 'up'
    anchors = settings.get('fib_anchors')
    if isinstance(anchors, dict):
        low, high = _number(anchors.get('low'), positive=True), _number(anchors.get('high'), positive=True)
        if anchors.get('direction') != direction or low >= high:
            return []
        for key in ('low_time', 'high_time'):
            if key in anchors and _integer(anchors[key]) > fast[-1]['time']:
                return []
        end_key, start_key = ('high', 'low') if long else ('low', 'high')
        end_price, start_price = (high, low) if long else (low, high)
        ends = [(i, price) for i, price in _pivots(fast, end_key) if price == end_price
                and (end_key+'_time' not in anchors or fast[i]['time'] == _integer(anchors[end_key+'_time']))]
        if not ends:
            return []
        impulse_end = ends[-1][0]
        starts = [(i, price) for i, price in _pivots(fast, start_key) if i < impulse_end and price == start_price
                  and (start_key+'_time' not in anchors or fast[i]['time'] == _integer(anchors[start_key+'_time']))]
        if not starts:
            return []
    else:
        pivots = sorted([(i, 'low', price) for i, price in _pivots(fast, 'low')] +
                        [(i, 'high', price) for i, price in _pivots(fast, 'high')])
        if len(pivots) < 2:
            return []
        first, second = pivots[-2:]
        if (first[1], second[1]) != (('low', 'high') if long else ('high', 'low')):
            return []
        low, high = (first[2], second[2]) if long else (second[2], first[2])
        impulse_end = second[0]
        if low >= high:
            return []
    # A later close cannot rehabilitate an impulse whose anchor was already breached.
    if any(b['low'] <= low if long else b['high'] >= high for b in fast[impulse_end+1:]):
        return []
    span = high-low
    zone_low, zone_high = (high-span*D('.618'), high-span*D('.5')) if long else (
        low+span*D('.5'), low+span*D('.618'))
    last, ema9 = fast[-1], _number(context.get('ema9'), positive=True)
    if (long and last['low'] <= low) or (not long and last['high'] >= high):
        return []
    if last['low'] > zone_high or last['high'] < zone_low:
        return []
    if long and last['close'] > ema9 and last['close'] > last['open']:
        return [_setup('ema_fib', True, fast, last['low'], 60, fib_low=float(zone_low), fib_high=float(zone_high),
                       **({'entry_floor': ema9+tick} if long else {'entry_ceiling': ema9-tick}))]
    if not long and last['close'] < ema9 and last['close'] < last['open']:
        return [_setup('ema_fib', False, fast, last['high'], 60, fib_low=float(zone_low), fib_high=float(zone_high),
                       **({'entry_floor': ema9+tick} if long else {'entry_ceiling': ema9-tick}))]
    return []


def _action(state, settings, candidate):
    """Structural sibling of the EMA money policy, with no ATR clipping of the SL."""
    if state.get('connected') is not True:
        raise InvalidEvidence('Waiting for a connected verified account snapshot.')
    if state.get('position') or state.get('orders'):
        raise InvalidEvidence('An account position or order is already active.')
    product, ticker, sizing = state['product'], state['ticker'], state['sizing']
    tick, cv = _number(product['tick_size'], positive=True), _number(product['contract_value'], positive=True)
    leverage = _integer(settings['leverage'])
    if leverage > min(200, _number(product['max_leverage'], positive=True)):
        raise InvalidEvidence('Leverage exceeds the verified product limit.')
    bid, ask, mark = (_number(ticker[key], positive=True) for key in ('bid', 'ask', 'mark'))
    if bid > ask or bid % tick or ask % tick:
        raise InvalidEvidence('Invalid or off-tick maker quotes.')
    long = candidate['side'] == 'buy'
    entry, sign = (bid, D(1)) if long else (ask, D(-1))
    if entry < candidate.get('entry_floor', entry) or entry > candidate.get('entry_ceiling', entry):
        raise InvalidEvidence('Maker quote no longer holds the confirmed setup level.')
    atr, latest = candidate['atr'], candidate['latest']
    gap = (entry-latest['close']) * sign
    if gap > atr * D('.5') or gap < -atr:
        raise InvalidEvidence('Maker quote moved too far from the confirmed setup.')
    if (long and candidate['wick'] >= entry) or (not long and candidate['wick'] <= entry):
        raise InvalidEvidence('Maker quote is beyond the setup invalidation wick.')
    buffer=max(tick,atr*D('.25'))
    noise=max(atr,tick*3) if candidate['strategy_id']=='ema_three' else atr
    raw=min(candidate['wick']-buffer,entry-noise) if long else max(candidate['wick']+buffer,entry+noise)
    stop = (raw/tick).to_integral_value(
        rounding=ROUND_FLOOR if long else ROUND_CEILING)*tick
    risk = abs(entry-stop)
    target = entry+sign*2*risk
    _number(stop, positive=True)
    _number(target, positive=True)
    if stop <= 0 or target <= 0 or risk <= 0:
        raise InvalidEvidence('Stop or reference target is not positive.')
    if (not isinstance(sizing, dict) or sizing.get('currency') != 'USD' or
            not isinstance(sizing.get('version'), str) or not sizing['version']):
        raise InvalidEvidence('Waiting for verified standard USD fees and balance.')
    maker, taker, tax = (_number(sizing[key]) for key in ('maker_fee_rate', 'taker_fee_rate', 'fee_tax_rate'))
    available = _number(sizing['available_balance'])
    if any(value < 0 or value > 1 for value in (maker, taker, tax)) or available < 0:
        raise InvalidEvidence('Invalid standard fee or available balance evidence.')
    if abs(target-entry) < (entry*maker+target*taker)*(1+tax)+tick:
        raise InvalidEvidence('Reference target does not cover standard fees plus one tick.')
    cost = max(entry, mark, bid, ask)*cv*(1/D(leverage)+maker*(1+tax))
    affordable = int(available*D('.99')/cost)
    loss_per_lot = (risk+(entry*maker+stop*taker)*(1+tax))*cv*85
    risk_cap = int(D(20)/loss_per_lot)
    fraction = settings.get('balance_fraction')
    if fraction is None:
        size = _integer(settings['manual_quantity'])
        if size > risk_cap or size > affordable:
            raise InvalidEvidence('Manual quantity exceeds the INR20 risk cap or available margin.')
    else:
        fraction = _number(fraction, positive=True)
        if fraction not in (D('.1'), D('.25'), D('.5'), D('.75'), D(1)):
            raise InvalidEvidence('Unsupported balance fraction.')
        size = min(int(fraction*available*D('.99')/cost), risk_cap)
    if size < 1 or size > 9007199254740991:
        raise InvalidEvidence('Available balance or INR20 risk cap does not fund one contract.')
    action = dict(side=candidate['side'], size=size, order_type='limit_order', price=float(entry), leverage=leverage,
                  strategy_id=candidate['strategy_id'], strategy_version=VERSION,
                  setup_time=candidate.get('setup_time',candidate['source_time']),
                  setup_id=f"{candidate['strategy_id']}:{candidate['side']}:{candidate.get('setup_time',candidate['source_time'])}:{candidate.get('level','')}",
                  auto_protection=dict(stop=float(stop), target=float(target), source_time=candidate['source_time'],
                                       interval_seconds=candidate['interval_seconds'],
                                       reason=f"{candidate['strategy_id']} confirmed setup; structural wick SL and 2R reference."))
    if 'daily_key' in candidate:
        action['daily_key'] = candidate['daily_key']
    if fraction is not None:
        action.update(balance_fraction=float(fraction), sizing_version=sizing['version'])
    return action


def decide(state, histories, settings, observed_at, now):
    """Return context, at most one proposed maker action, and an inspectable reason."""
    histories = histories if isinstance(histories, dict) else {}
    result = ema.decide(state, histories.get('1m'), histories.get('5m'), settings, observed_at, now)
    context = dict(result['context'])
    context.update(ema_direction=context.get('direction', 'unavailable'),
                   higher_ema_direction=context.get('higher_direction', 'unavailable'))
    context.update(strategy_id='ensemble', strategy_version=VERSION, interval_seconds=60,
                   contributing_strategies=[], candidates=[])
    diagnostics, eligible, cache = context['candidates'], [], {}
    if result['action']:
        action = dict(result['action'], strategy_id='ema', strategy_version=VERSION)
        eligible.append(('ema', action))
    diagnostics.append(dict(strategy_id='ema', version=VERSION, eligible=bool(result['action']), reason=result['reason']))
    try:
        if not isinstance(settings, dict):
            raise InvalidEvidence('Invalid automation settings.')
        observed, current = _number(observed_at, positive=True), _number(now, positive=True)
        if observed > current or current-observed > 30:
            raise InvalidEvidence('Candle observation is stale or ahead of the current clock.')
        asof=_number(state.get('asof'),positive=True)
        if asof>current or current-asof>10:
            raise InvalidEvidence('Waiting for fresh nonfuture account quotes.')
        tick = _number(state['product']['tick_size'], positive=True)
        bid, ask = (_number(state['ticker'][key], positive=True) for key in ('bid', 'ask'))
        def bars(interval):
            if interval not in cache:
                cache[interval] = _segment(histories.get(interval), SECONDS[interval], observed, current)
            return cache[interval]
        detectors = {
            'ema_three': lambda: three_ema.detect(bars('1m'), bars('5m')),
            'liquidity_sweep': lambda: _liquidity(bars('1h'), bars('1d'), tick, current),
            'fvg': lambda: _fvg(bars('15m'), bars('1d'), _current_open(histories.get('4h'), current), tick, bid, ask),
            'breakout_retest': lambda: _breakout(bars('5m'), tick),
            'range_rsi': lambda: _range(bars('5m'), tick),
            'double_extrema': lambda: _double(bars('5m'), tick),
            'ema_fib': lambda: _fib(bars('1m'), context, settings, tick),
        }
        for module, detector in detectors.items():
            diagnostic = dict(strategy_id=module, version=VERSION, eligible=False, reason='Waiting for a confirmed setup.')
            try:
                setups = detector()
                if setups:
                    setup = setups[0]
                    evidence = {key: float(value) if isinstance(value, Decimal) else value
                                for key, value in setup.items() if key not in ('latest',)}
                    diagnostic['evidence'] = evidence
                    action = _action(state, settings, setup)
                    eligible.append((module, action))
                    context['patterns'] = [*context['patterns'], dict(name=module, time=setup['source_time'],
                                                                    direction='up' if action['side'] == 'buy' else 'down')]
                    diagnostic.update(eligible=True, side=action['side'], source_time=setups[0]['source_time'],
                                      interval_seconds=setups[0]['interval_seconds'], reason='Confirmed setup and standard risk checks passed.')
            except (InvalidEvidence, KeyError, TypeError, ValueError, InvalidOperation, OverflowError, ZeroDivisionError) as exc:
                diagnostic['reason'] = str(exc) if isinstance(exc, InvalidEvidence) else 'Missing or malformed module evidence.'
            diagnostics.append(diagnostic)
    except (InvalidEvidence, KeyError, TypeError, ValueError, InvalidOperation, OverflowError, ZeroDivisionError) as exc:
        return dict(context=context, action=None, reason=str(exc) if isinstance(exc, InvalidEvidence) else 'Missing or malformed ensemble evidence.')
    if not eligible:
        triple=next((item['reason'] for item in diagnostics if item['strategy_id']=='ema_three'),'Waiting for a fresh ordered alignment.')
        return dict(context=context, action=None, reason=result['reason']+' EMA9/15/21: '+triple)
    context['contributing_strategies'] = [module for module, _ in eligible]
    if len({action['side'] for _, action in eligible}) > 1:
        context['trend_summary'] = 'Conflicting eligible strategies: ' + ', '.join(f"{module} {action['side']}" for module, action in eligible)
        return dict(context=context, action=None, reason='Eligible strategies disagree; waiting for a single direction.')
    module, action = min(eligible, key=lambda item: PRIORITY.index(item[0]))
    protection = action['auto_protection']
    context.update(strategy_id=module, source_time=protection['source_time'], interval_seconds=protection['interval_seconds'])
    if module != 'ema':
        context.update(direction='up' if action['side'] == 'buy' else 'down',
                       trend_summary=f"{module} confirmed {action['side']} setup; " + context['trend_summary'])
    return dict(context=context, action=action, reason=f"{module} selected; agreeing strategies deduplicated into one maker proposal.")
