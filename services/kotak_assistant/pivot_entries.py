"""Traditional daily pivot context and completed-candle advisory entries.

Pivot formulas: TradingView Pivot Points Standard, Traditional type.
Rejection/retest buffers, confirmation, expiry and room rules are app assumptions.
No broker submission functions are imported.
"""
import math
import copy
from . import setups

VERSION = 'daily-pivots-1.0'
STRATEGIES = ('pivot_rejection', 'pivot_retest')


def standard_pivots(previous):
    try:
        h, l, c = (float(previous[k]) for k in ('high', 'low', 'close'))
        if not all(math.isfinite(x) for x in (h, l, c)) or not 0 < l <= c <= h or h == l:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    p = (h+l+c)/3
    return dict(P=p, R1=2*p-l, S1=2*p-h, R2=p+h-l, S2=p-h+l,
                R3=2*p+h-2*l, S3=2*p-2*h+l)


def _base(strategy, side, reason, stage='waiting_pattern'):
    return dict(strategy=strategy, version=VERSION, direction=side, stage=stage,
                eligible=False, reason=reason, reference=None, trigger=None, expires=None)


def _ready(strategy, side, watch, bar, atr, levels, ratio):
    up = side == 'CE'; entry = bar['close']; closed = bar['time']+60
    extreme = min(watch['extreme'], bar['low']) if up else max(watch['extreme'], bar['high'])
    stop = extreme-.1*atr if up else extreme+.1*atr
    targets = [v for v in levels.values() if v > entry] if up else [v for v in levels.values() if v < entry]
    target = (min(targets) if up else max(targets)) if targets else None
    risk = abs(entry-stop)
    room = abs(target-entry)/risk if target is not None and risk > 0 else 0
    fits = room >= ratio
    return dict(strategy=strategy, version=VERSION, pattern='Rejection + confirmation' if strategy=='pivot_rejection' else 'Breakout + retest',
                stage='ready' if fits else 'insufficient_room', direction=side, eligible=fits,
                reason='Pivot entry confirmed on a completed 1m candle; review the option plan' if fits else f'Insufficient room to the next pivot for {ratio:g}R; wait for another setup',
                reference=dict(price=watch['price'], name=watch['name'], known_at=watch['known_at']),
                trigger=entry, index_entry=entry, invalidation=stop, index_target=target,
                index_rr=room, signal_candle=bar, confirmed_at=closed, expires=closed+60,
                setup_id=f'{VERSION}:{strategy}:{side}:{watch["name"]}:{closed}',
                evidence=['Prior completed daily H/L/C only; fixed levels for this session',
                          'Completed 1m confirmation; no entry on a pivot touch alone',
                          'Index invalidation/next pivot and option premium SL/target are separate'])


def _scan(one, previous, start, now, ratio):
    levels = standard_pivots(previous)
    if not levels:return [], {}, levels
    bars = [b for b in setups._completed([b for b in one if not b.get("repaired")], now, 60) if b['time'] >= start]
    pending = {}; records = []; used = set(); run = []; atr = None
    for b in bars:
        if b.get('repaired') or run and b['time'] != run[-1]['time']+60:
            pending = {}; run = []; atr = None
        if b.get('repaired'):continue
        prev = run[-1] if run else b
        tr = max(b['high']-b['low'], abs(b['high']-prev['close']), abs(b['low']-prev['close']))
        run.append(b)
        if len(run)==14:
            atr=sum(max(x['high']-x['low'],abs(x['high']-y['close']),abs(x['low']-y['close'])) for x,y in zip(run,[run[0],*run[:-1]]))/14
        elif len(run)>14:atr=(atr*13+tr)/14
        if atr is None or atr<=0 or len(run)<15:continue
        for strategy in STRATEGIES:
            for side in ('CE','PE'):
                up=side=='CE'; key=(strategy,side); watch=pending.get(key)
                if watch:
                    age=(b['time']-watch['time'])/60
                    invalid=b['close']<watch['extreme']-.1*watch['atr'] if up else b['close']>watch['extreme']+.1*watch['atr']
                    if age>3 or invalid:
                        pending.pop(key);watch=None
                    elif age>0:
                        colour=b['close']>b['open'] if up else b['close']<b['open']
                        confirmed=(b['close']>watch['trigger'] if up else b['close']<watch['trigger']) if strategy=='pivot_rejection' else (b['low']<=watch['price']+.1*atr and b['close']>watch['price'] if up else b['high']>=watch['price']-.1*atr and b['close']<watch['price'])
                        if colour and confirmed:
                            records.append(_ready(strategy,side,watch,b,atr,levels,ratio))
                            used.add((strategy,side,watch['name']));pending.pop(key);continue
                if watch:continue
                choices=[]
                for name,price in levels.items():
                    if (strategy,side,name) in used:continue
                    if strategy=='pivot_rejection':
                        if not name.startswith('S' if up else 'R'):continue
                        qualifies=(prev['close']>price and b['low']<price and b['close']>price and b['close']>b['open']) if up else (prev['close']<price and b['high']>price and b['close']<price and b['close']<b['open'])
                    else:
                        qualifies=(prev['close']<=price and b['close']>price+.1*atr) if up else (prev['close']>=price and b['close']<price-.1*atr)
                    if qualifies:choices.append((name,price))
                if choices:
                    name,price=min(choices,key=lambda x:abs(b['close']-x[1]))
                    pending[key]=dict(name=name,price=price,time=b['time'],known_at=start,atr=atr,
                                      extreme=b['low'] if up else b['high'],
                                      trigger=b['high'] if up else b['low'],bar=b)
    return records,pending,levels


def pivot_signals(one, previous, start, now, ratio=2):
    return _scan(one, previous, start, now, ratio)[0]


def pivot_setups(one, previous, start, now, ratio=2):
    if ratio not in (2,3):raise ValueError('Choose net 2R or 3R')
    records,pending,levels=_scan(one,previous,start,now,ratio)
    result={}
    for strategy in STRATEGIES:
        directions={}
        for side in ('CE','PE'):
            r=_base(strategy,side,'Wait for a pivot rejection and later close beyond its signal candle' if strategy=='pivot_rejection' else 'Wait for a buffered pivot breakout and later completed retest')
            if levels is None:r.update(stage='waiting_reference',reason='Previous completed daily high, low and close unavailable; no substitute pivot used')
            recent=next((x for x in reversed(records) if x['strategy']==strategy and x['direction']==side),None)
            watch=pending.get((strategy,side))
            if recent and recent['expires']>now:r=recent
            elif watch and now<watch['time']+240:
                r.update(stage='waiting_trigger' if strategy=='pivot_rejection' else 'waiting_retest',
                         reference=dict(price=watch['price'],name=watch['name'],known_at=start),trigger=watch['trigger'] if strategy=='pivot_rejection' else watch['price'],
                         expires=watch['time']+240,reason=f'{side}: wait for completed 1m confirmation at {watch["name"]}; a touch is not entry')
            elif recent:r=dict(recent,eligible=False,stage='expired',reason='Pivot entry window expired; wait for a fresh setup')
            directions[side]=r
        result[strategy]=dict(_base(strategy,None,'Select a CE or PE strike to view its pivot sequence'),directions=directions)
        if levels is None:result[strategy].update(stage='waiting_reference',reason='Previous completed daily high, low and close unavailable; no substitute pivot used')
    return result


def observe_pivot(signal, events, ratio, now):
    """Make a frozen setup terminal if an observed postconfirmation price fails it."""
    result=copy.deepcopy(signal)
    if not result.get('eligible') or result.get('stage')!='ready':return result
    side=1 if result['direction']=='CE' else -1
    for event in sorted(events,key=lambda e:e['time']):
        at=event['time']
        if not result['confirmed_at']<=at<=now or at>=result['expires']:continue
        stage=reason=None
        if event.get('type')=='reset':
            stage='blocked';reason='Feed continuity interrupted after confirmation; wait for a fresh setup'
        else:
            price=event.get('price')
            if price is None or not math.isfinite(price) or price<=0:continue
            risk=side*(price-result['invalidation']);reward=side*(result['index_target']-price)
            if risk<=0:
                stage='blocked';reason='Observed index price breached the frozen pivot invalidation'
            elif reward<=0 or reward/risk+1e-9<ratio:
                stage='missed';reason='Observed index price leaves insufficient room to the next pivot; do not chase'
        if stage:
            result.update(stage=stage,eligible=False,reason=reason,terminal_at=at);break
    return result
