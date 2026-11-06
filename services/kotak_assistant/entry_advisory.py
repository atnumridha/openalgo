"""Account-scoped read-only decision assistant. Never reconciles or submits orders."""
import copy
import math
from datetime import datetime,timedelta
from .analysis import IST,validate_settings
from services.history_resample import HISTORY_CONTEXT_VERSION
from . import setup_live,setups
from .pivot_entries import standard_pivots,pivot_setups,observe_pivot
from .entry_decisions import breakout_retest,initial_daily_state,advance_daily,daily_result,premium_plan


def _fresh(q,now):
    try:return q.get('ltp',0)>0 and -3<=now-float(q.get('observed_time') or q.get('time') or 0)<=5
    except (TypeError,ValueError):return False


def _gate_after_loading(candidates, quote, now, window):
    """Loading can cross a cutoff or expire the original causal observation."""
    opened=bool(window and window['start_ms']/1000<=now<window['end_ms']/1000)
    fresh=_fresh(quote,now)
    for candidate in candidates.values():
        for signal in [candidate,*candidate.get('directions',{}).values()]:
            signal['chart_fresh']=fresh
            if not opened:
                signal.update(eligible=False,stage='market_closed',reason='Market closed; live entry decisions resume in the exchange session')
            elif datetime.fromtimestamp(now,IST).strftime('%H:%M')>='15:00':
                signal.update(eligible=False,reason='Research entry window ended at15:00; do not initiate a new candidate')
            elif not fresh:
                signal.update(eligible=False,reason='Fresh index observation required after loading the option plan')
            elif signal.get('eligible') and signal.get('expires') is not None and now>=signal['expires']:
                signal.update(eligible=False,stage='expired',reason='Entry watch window expired while loading; wait for a fresh setup')


def _previous_daily(c,underlying,ix,exchange,day,calendar):
    def load():
        try:
            expected=day-timedelta(days=1)
            for _ in range(10):
                if calendar(expected,exchange):break
                expected-=timedelta(days=1)
            for row in reversed(c.g.history(underlying,ix,'D')):
                t=float(row.get('time',row.get('timestamp')))
                if t>1e12:t/=1000
                if datetime.fromtimestamp(t,IST).date()==expected and not row.get('repaired'):
                    high=float(row['high']);low=float(row['low'])
                    if math.isfinite(high) and 0<low<high:
                        result=dict(time=t,high=high,low=low)
                        try:
                            close=float(row['close'])
                            if math.isfinite(close) and low<=close<=high:result['close']=close
                        except (KeyError,ValueError,TypeError):pass
                        return result
        except (ValueError,KeyError,TypeError):pass
        # Failed/missing context must not become a five-minute negative cache.
        raise ValueError('Previous completed daily context unavailable')
    try:
        return c.g.cached(('entry_decision_daily',HISTORY_CONTEXT_VERSION,underlying,day.isoformat()),300,load)
    except (ValueError,KeyError,TypeError):
        return None


def read(c,underlying,symbol='',lots=1,ratio=2):
    if underlying not in ('NIFTY','BANKNIFTY','SENSEX'):raise ValueError('Choose NIFTY, BANKNIFTY or SENSEX')
    if isinstance(lots,bool) or not isinstance(lots,int) or not 1<=lots<=100:raise ValueError('Choose1–100 whole lots')
    if ratio not in (2,3):raise ValueError('Choose net2R or3R')
    now=c.clock();day=datetime.fromtimestamp(now,IST).date();exchange='BSE' if underlying=='SENSEX' else 'NSE';ix=exchange+'_INDEX';fo='BFO' if underlying=='SENSEX' else 'NFO'
    calendar=setup_live._calendar(c,exchange);window=calendar(day,exchange)
    start=window['start_ms']/1000 if window else now;end=window['end_ms']/1000 if window else now
    one=setup_live.session_bars(c.g.history(underlying,ix,'1m'),60,now,exchange,calendar)
    five=setup_live.session_bars(c.g.history(underlying,ix,'5m'),300,now,exchange,calendar)
    quote=c.g.quote(underlying,ix);previous=_previous_daily(c,underlying,ix,exchange,day,calendar)
    now=c.clock();opened=bool(window and start<=now<end);fresh=_fresh(quote,now)
    base_scope=setup_live.scope_for(c,underlying);scope=base_scope+':entry-decisions';repo=setup_live.repository(c)
    session_id=f'{exchange}:{day.isoformat()}'
    with setup_live._locks.hold(scope):
        body,version=repo.read(scope)
        same=body.get('session_id')==session_id
        state=body.get('daily') if same else None
        cursor=body.get('cursor',now) if same else now
        events=repo.events(base_scope,max(start,cursor),now,limit=10001) if opened else []
        if len(events)>10000:
            state=setups.reset_observation(state,now,'Recorded event backlog; wait for a fresh reference cross') if state else None
            events=[];cursor=now
        observed=float(quote.get('observed_time') or quote.get('time') or 0)
        if opened and fresh and observed>=cursor:
            events.append(dict(time=observed,price=float(quote['ltp']),id=f'entry_quote:{observed:.6f}',source='rest_snapshot' if quote.get('source')!='Live feed' else 'websocket'))
        seen=set(body.get('last_ids',[])) if same else set();processed=[]
        for event in sorted(events,key=lambda e:(e['time'],e.get('id',''))):
            if event.get('id') in seen or event.get('live_eligible') is False:continue
            if event.get('type')=='reset':
                if state:state=setups.reset_observation(state,event['time'],event.get('reason','Feed continuity interrupted'))
            else:
                if state and state.get('last_event') and event['time']-state['last_event']['time']>10:
                    state=setups.reset_observation(state,event['time'],'Observed-price gap; fresh reference crossing required')
                state=advance_daily(state,one,event,event['time'],session_id,start,previous)
            processed.append(event)
        state=advance_daily(state,one,None,now,session_id,start,previous)
        signature=[HISTORY_CONTEXT_VERSION,five[-1]['time'] if five else None]
        retest=body.get('retest') if same and body.get('signature')==signature else None
        if retest is None:retest=breakout_retest(five,now)
        else:retest=copy.deepcopy(retest)
        if retest.get('expires') and now>=retest['expires']:
            retest.update(eligible=False,stage='expired',reason='Entry watch window expired; wait for a new breakout and retest')
        # Freshness is a presentation gate, not part of the cached causal setup.
        candidates=dict(breakout_retest=copy.deepcopy(retest),daily_sweep=daily_result(state,now))
        candidates.update(pivot_setups(one,previous,start,now,ratio))
        terminals={k:v for k,v in body.get('pivot_terminals',{}).items() if v['expires']>now} if same else {}
        pivot_signals=[signal for key,candidate in candidates.items() if key.startswith('pivot_') for signal in candidate.get('directions',{}).values() if signal.get('eligible')]
        observations=[]
        if opened and fresh and pivot_signals:
            since=min(s['confirmed_at'] for s in pivot_signals)
            observations=repo.events(base_scope,since,now,limit=10001)
            observations += [dict(time=observed,price=float(quote['ltp']))]
            for candidate in candidates.values():
                if not candidate.get('strategy','').startswith('pivot_'):continue
                for direction,signal in candidate.get('directions',{}).items():
                    if not signal.get('eligible'):continue
                    key=signal.get('setup_id')
                    if key in terminals:signal.update(terminals[key]);continue
                    if len(observations)>10001:
                        signal.update(eligible=False,stage='blocked',reason='Observation backlog; wait for a new pivot setup',terminal_at=now)
                    elif not any(signal['confirmed_at']<=e['time']<=now for e in observations):
                        signal.update(eligible=False,stage='waiting_observation',reason='Wait for a fresh index observation after confirmation')
                    else:
                        signal=observe_pivot(signal,observations,ratio,now)
                    candidate['directions'][direction]=signal
                    if key and signal.get('terminal_at') is not None:
                        terminals[key]={k:signal[k] for k in ('eligible','stage','reason','terminal_at','expires')}
        for candidate in candidates.values():
            for s in [candidate,*candidate.get('directions',{}).values()]:
                s['chart_fresh']=fresh
                if not opened:s.update(eligible=False,stage='market_closed',reason='Market closed; live entry decisions resume in the exchange session')
                elif not fresh:s.update(eligible=False,reason='Fresh index observation unavailable; wait for live data')
                elif datetime.fromtimestamp(now,IST).strftime('%H:%M')>='15:00':s.update(eligible=False,reason='Research entry window ended at15:00; do not initiate a new candidate')
        last=max([cursor,*[e['time'] for e in processed]])
        ids=[e.get('id') for e in processed if e['time']==last]
        if last==cursor:ids=list(set(ids)|seen)
        saved=dict(session_id=session_id,pivot_terminals=terminals,daily=state,retest=retest,signature=signature,cursor=last,last_ids=ids,updated=now,kind='entry_decisions',last_view=0)
        if not repo.commit(scope,version,saved,[]):raise ValueError('Decision state changed; refresh again')
    response=dict(advisory_only=True,underlying=underlying,symbol=symbol,side='PE' if symbol.endswith('PE') else 'CE' if symbol.endswith('CE') else None,candidates=candidates,plan=None,plan_fresh=False,plan_reason='Select a strike to calculate its premium entry, SL and target',generated_at=now,lots=lots,ratio=ratio,study='NIFTY research ·23Sep–22Oct2026 · limited option coverage',evidence='Retest2R:11 resolved trades across6 dates; longer development failed. Daily sweep2R:3 resolved trades. Positive short samples do not establish live profitability.')
    response['pivot_evidence']='NIFTY · 23 Sep–22 Oct 2026 · limited archived options: pivot retest 2R +₹1,265.73 net, 12 resolved trades across 8 dates, 41.7% wins. Rejection 2R −₹2,480.21; rejection 3R −₹2,676.46; retest 3R −₹2,011.39. Includes estimated ₹10/order brokerage, taxes and slippage. Small reused samples are not proof of a live edge.'
    response['pivots']=dict(underlying=underlying,session_date=day.isoformat(),reference_date=datetime.fromtimestamp(previous['time'],IST).date().isoformat(),previous=previous,levels=standard_pivots(previous)) if previous and standard_pivots(previous) else None
    if not symbol:return response
    meta=c.g.metadata(symbol,fo)
    if meta['underlying']!=underlying or meta['expiry']<day.isoformat():raise ValueError('Choose an unexpired contract for the selected index')
    quantity=lots*meta['lot']
    if quantity>meta['freeze']:raise ValueError('Selected quantity exceeds the contract freeze limit')
    response['quantity']=quantity
    q=c.g.quote(symbol,fo);now=c.clock();response['quote']=q;response['generated_at']=now
    _gate_after_loading(candidates,quote,now,window)
    if not opened:response['plan_reason']='Market closed; a fresh executable premium is unavailable';return response
    if not _fresh(q,now) or not 0<q.get('bid',0)<=q.get('ask',0):response['plan_reason']='Fresh two-sided option quote unavailable';return response
    settings=validate_settings(c.state()['settings'],day.isoformat())
    if (q['ask']-q['bid'])/q['ask']*100>settings['spread']:response['plan_reason']='Option spread exceeds the configured limit';return response
    candles=setup_live.session_bars(c.g.history(symbol,fo,'1m'),60,now,exchange,calendar)
    now=c.clock()
    # A cold history read can outlive the quote captured before it. Refresh
    # executable observations after loading, then apply the same age gates.
    if not _fresh(q,now):
        q=c.g.quote(symbol,fo);now=c.clock();response['quote']=q
    response['generated_at']=now
    _gate_after_loading(candidates,quote,now,window)
    if not _fresh(q,now) or not candles or now-candles[-1]['time']>125:response['plan_reason']='Fresh completed option candles and quote are required';return response
    if not 0<q.get('bid',0)<=q.get('ask',0):response['plan_reason']='Fresh two-sided option quote unavailable';return response
    if (q['ask']-q['bid'])/q['ask']*100>settings['spread']:response['plan_reason']='Option spread exceeds the configured limit';return response
    # A refreshed index requires a new causal evaluation on the next poll.
    p=premium_plan(q['ask'],candles,quantity,meta['tick'],meta['lot'],fo,settings,ratio,day.isoformat())
    response.update(plan=p,plan_fresh=True,plan_reason=p['reason'] or 'Indicative fresh ask; premiums can move before an order fills',generated_at=now)
    return response
