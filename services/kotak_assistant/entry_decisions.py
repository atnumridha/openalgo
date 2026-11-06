"""Pure advisory candidates and premium plans. No broker order functions."""
import copy
import math
from datetime import datetime
from . import setups
from .analysis import IST,fees,number,plan,snap,validate_settings

STRATEGIES=('breakout_retest','daily_sweep')
VERSION='entry-research-1.0'


def _wilder(values,n=14):
    out=[None]*len(values)
    first=next((i for i,v in enumerate(values) if v is not None),len(values))
    end=first+n-1
    if end>=len(values):return out
    out[end]=sum(values[first:end+1])/n
    for i in range(end+1,len(values)):
        out[i]=(out[i-1]*(n-1)+values[i])/n
    return out


def research_features(bars):
    """Match the frozen research EMA/Wilder seeds, without pandas in the request path."""
    n=len(bars);tr=[];plus=[];minus=[];emas={20:[],50:[]}
    for i,b in enumerate(bars):
        prev=bars[i-1] if i else b
        tr.append(max(b['high']-b['low'],abs(b['high']-prev['close']),abs(b['low']-prev['close'])))
        up=b['high']-prev['high'];down=prev['low']-b['low']
        plus.append(up if up>down and up>0 else 0.)
        minus.append(down if down>up and down>0 else 0.)
        for span in emas:
            emas[span].append(b['close'] if i==0 else emas[span][-1]+2/(span+1)*(b['close']-emas[span][-1]))
    pos,neg=_wilder(plus),_wilder(minus)
    dx=[None if a is None else 100*abs(a-b)/(a+b) if a+b>0 else 0. for a,b in zip(pos,neg)]
    return dict(atr=_wilder(tr),adx=_wilder(dx),ema20=[v if i>=19 else None for i,v in enumerate(emas[20])],ema50=[v if i>=49 else None for i,v in enumerate(emas[50])],slope=[emas[20][i]-emas[20][i-3] if i>=22 else None for i in range(n)])


def _scan_retests(bars):
    f=research_features(bars);signals=[];pending=None
    for i,b in enumerate(bars):
        if i and b['time']!=bars[i-1]['time']+300:pending=None
        atr=f['atr'][i];e20=f['ema20'][i];e50=f['ema50'][i];slope=f['slope'][i]
        if None in (atr,e20,e50,slope) or i<20 or atr<=0:continue
        up=b['close']>e20>e50 and slope>0
        down=b['close']<e20<e50 and slope<0
        direction=None;reference=None
        if pending:
            side,level,index,known=pending
            if i-index>3 or (b['close']<level-.3*atr if side=='CE' else b['close']>level+.3*atr):pending=None
            elif (b['low']<=level+.15*atr and b['close']>level and up if side=='CE' else b['high']>=level-.15*atr and b['close']<level and down):
                direction=side;reference=dict(price=level,time=known-300,known_at=known,source='20 completed 5m candles');pending=None
        if pending is None and direction is None:
            high=max(x['high'] for x in bars[i-20:i]);low=min(x['low'] for x in bars[i-20:i])
            adx=f['adx'][i] or 0
            if b['close']>high+.1*atr and up and adx>=20:pending=('CE',high,i,b['time']+300)
            elif b['close']<low-.1*atr and down and adx>=20:pending=('PE',low,i,b['time']+300)
        # The research signal function excludes overnight-boundary signals.
        if direction and i>=250 and i and b['time']==bars[i-1]['time']+300:
            closed=b['time']+300
            signals.append(dict(strategy='breakout_retest',version=VERSION,mode='confirmed',stage='ready',direction=direction,eligible=True,reference=reference,trigger=b['close'],index_entry=b['close'],signal_candle=dict(b,closed_at=closed),expires=closed+60,setup_id=f'breakout_retest:{VERSION}:{direction}:{closed}:{reference["price"]}',evidence=['Completed5m EMA20/50 direction and ADX≥20 at breakout','First successful retest of the frozen20-bar level within3 candles','Entry window: first minute after the confirming5m close; price is indicative, not a fill'],reason='Retest confirmed; review the selected option premium before entry'))
    return signals,pending,f


def retest_signals(bars):return _scan_retests(bars)[0]


def breakout_retest(five,now):
    bars=setups._completed([b for b in five if not b.get('repaired')],now,300)
    base=dict(strategy='breakout_retest',version=VERSION,mode='confirmed',stage='waiting_history',direction=None,eligible=False,evidence=[],reason='Need250 completed5m candles for the backtested trend context',expires=None,reference=None,trigger=None)
    if len(bars)<251:return base
    if any(datetime.fromtimestamp(a['time'],IST).date()==datetime.fromtimestamp(b['time'],IST).date() and b['time']-a['time']!=300 for a,b in zip(bars,bars[1:])):
        return dict(base,reason='Gap in completed5m history; waiting for continuous data')
    signals,pending,f=_scan_retests(bars)
    if signals and signals[-1]['expires']>now:return signals[-1]
    if pending:
        side,level,index,known=pending
        return dict(base,stage='waiting_retest',direction=side,reference=dict(price=level,known_at=known),trigger=level,expires=known+900,reason=f'Breakout formed. Wait for a completed5m retest holding {level:.2f}; breakout alone is not an entry')
    return dict(base,stage='waiting_break',reason='Wait for an EMA-aligned5m breakout beyond a known20-bar level, then its first retest',evidence=['Latest confirmation is expired; do not chase it'] if signals else [])


def initial_daily_state(session_id,start,reference):
    state=setups.initial_opening_state(session_id);state['reference_missing']=not bool(reference)
    if reference:
        for direction,kind in [('CE','low'),('PE','high')]:
            state['directions'][direction].update(reference=dict(price=reference[kind],time=reference['time'],known_at=start,kind=kind,source='Previous completed daily candle'),stage='waiting_break',rearm_needed=True,reset_observed=False)
    return state


def advance_daily(state,bars,event,now,session_id,start,reference):
    if not state or state.get('session_id')!=str(session_id) or state.get('reference_missing') and reference:
        state=initial_daily_state(session_id,start,reference)
    if state.get('reference_missing'):return copy.deepcopy(state)
    return setups.advance_opening(state,bars,event,now,session_id,start)


def daily_result(state,now):
    result=setups.opening_result(state,now)
    for r in [result,*result.get('directions',{}).values()]:
        r.update(strategy='daily_sweep',version=VERSION)
        if state.get('reference_missing'):
            r.update(stage='waiting_reference',eligible=False,reason='Previous completed daily high/low unavailable; no substitute level used')
        if r.get('stage')=='waiting_break' and r.get('rearm_needed') and not r.get('reset_observed'):
            r['reason']='Wait for price at/inside the daily reference, then a fresh crossing; an earlier unobserved break is not an entry'
        if r.get('triggered_at') is not None:
            r['expires']=min(r.get('expires') or now,r['triggered_at']+60)
            if now>=r['expires']:r.update(eligible=False,reason='Observed trigger recorded; its one-minute entry window has expired')
    result['evidence']=[*result.get('evidence',[]),'Research candidate: only3 resolved option trades in the available comparison; not a proven live edge','Fresh recross required after initial connection; historical crossings are not entries']
    return result


def premium_plan(ask,candles,quantity,tick,lot,exchange,settings,ratio,day):
    ratio=max(2,number(ratio))
    if ratio not in (2,3):raise ValueError('Research entry targets support net2R or3R')
    settings=validate_settings(settings,day);entry=snap(ask,tick,True)
    if not isinstance(quantity,int) or quantity<=0 or quantity%lot:raise ValueError('Choose whole lots')
    # Reset the option ATR run across missing minutes or zero traded volume.
    run=[]
    for b in sorted(candles,key=lambda b:b['time']):
        if b.get('repaired') or 'volume' in b and b['volume']<=0 or run and b['time']!=run[-1]['time']+60:run=[]
        if not b.get('repaired') and ('volume' not in b or b['volume']>0):run.append(b)
    if len(run)<15:return dict(fits=False,reason=f'Option ATR warm-up: {len(run)} / 15 completed contiguous traded candles; waiting for valid history')
    distance=setups.indicators(run)['atr14'][-1]
    if not distance or distance<=0:return dict(fits=False,reason='Option ATR14 unavailable')
    sl=snap(entry-1.5*distance,tick,True)
    if not 0<sl<entry:return dict(fits=False,reason='No valid positive option stop at1.5ATR')
    slip=settings['slippage'];stop_fill=max(0,sl-slip)
    charge=lambda sell:fees(entry*quantity,sell*quantity,exchange,settings['brokerage'],day)['total']
    risk=(entry-stop_fill)*quantity+charge(stop_fill)
    net=lambda price:(max(0,price-slip)-entry)*quantity-charge(max(0,price-slip))
    low=entry;high=entry+(ratio*risk+100)/quantity+tick
    # Fees depend on turnover; bracket the net reward before solving its price.
    for _ in range(64):
        if net(high)>=ratio*risk:break
        high=entry+2*(high-entry)
    else:return dict(fits=False,reason='Unable to calculate a valid fee-adjusted target')
    for _ in range(64):
        mid=(low+high)/2
        if net(mid)>=ratio*risk:high=mid
        else:low=mid
    target=snap(high,tick,True)
    p=plan(entry,sl,target,quantity,exchange,settings,tick,lot,day)
    p.update(option_atr=distance,source=f'Fresh ask · 1.5 × option ATR14 · net {ratio:g}R target',study_risk_cap=1000,ratio=ratio)
    if p['risk']>1000:p.update(fits=False,reason='Even 1 lot exceeds the ₹1,000 risk limit after charges; wait for lower volatility or select another contract' if quantity==lot else 'Planned total-position loss exceeds ₹1,000 after charges; reduce lots')
    return p
