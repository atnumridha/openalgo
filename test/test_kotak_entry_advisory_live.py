from types import SimpleNamespace
from flask import Flask
from database.engine_factory import create_db_engine
from services.kotak_assistant.store import Store
from services.kotak_assistant import setup_live
from test_kotak_setup_data import epoch,window


def test_advisory_route_is_session_protected():
 from blueprints.kotak_assistant import kotak_assistant_bp
 a=Flask(__name__);a.secret_key='test';a.register_blueprint(kotak_assistant_bp)
 assert a.test_client().get('/kotak-assistant/api/entry-decisions').status_code==401


def fixture(tmp_path,monkeypatch,stale=False):
 from services.kotak_assistant.entry_advisory import read
 monkeypatch.setattr(setup_live,'session_window',window)
 now=epoch(23,10,0)
 calls=[]
 def history(symbol,exchange,interval):
  calls.append(('history',symbol,interval))
  if interval=='D':return [dict(time=epoch(22,5,30),open=100,high=110,low=90,close=100)]
  if interval=='5m':return []
  return [dict(time=now-(20-i)*60,open=100,high=101,low=99,close=100,volume=100) for i in range(20)]
 def quote(symbol,exchange):
  calls.append(('quote',symbol));return dict(ltp=100,bid=100,ask=100.03,time=now-(30 if stale else 0),source='Broker snapshot')
 g=SimpleNamespace(user='u',account='a',mode='live',cached=lambda key,ttl,load:load(),quote=quote,history=history,metadata=lambda *a:dict(lot=65,tick=.05,freeze=1800,underlying='NIFTY',expiry='2026-10-27'))
 c=SimpleNamespace(scope='u:a:live',g=g,clock=lambda:now,store=Store(create_db_engine(f'sqlite:///{tmp_path}/advisory.db')),state=lambda:{'settings':{'brokerage':10,'slippage':.1}})
 return read,c,calls


def test_read_only_advisory_persists_and_uses_selected_symbol(tmp_path,monkeypatch):
 read,c,calls=fixture(tmp_path,monkeypatch)
 result=read(c,'NIFTY','NIFTY27OCT2622700CE',2,2)
 assert result['plan']['quantity']==130 and result['plan']['net_rr']>=2
 assert result['symbol']=='NIFTY27OCT2622700CE'
 assert set(result['candidates'])=={'breakout_retest','daily_sweep','pivot_rejection','pivot_retest'}
 assert result['advisory_only'] and not any(k[0] not in ('quote','history') for k in calls)
 before=setup_live.repository(c).read(setup_live.scope_for(c,'NIFTY')+':entry-decisions')[0]
 again=read(c,'NIFTY','NIFTY27OCT2622700CE',2,2)
 after=setup_live.repository(c).read(setup_live.scope_for(c,'NIFTY')+':entry-decisions')[0]
 assert before['daily']==after['daily'] and again['plan']['quantity']==130


def test_stale_selected_quote_cannot_produce_an_entry_plan(tmp_path,monkeypatch):
 read,c,_=fixture(tmp_path,monkeypatch,stale=True)
 result=read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)
 assert result['plan'] is None and not result['plan_fresh']
 assert 'fresh' in result['plan_reason'].lower()
 assert all(not s['eligible'] for s in result['candidates'].values())


def test_index_quote_is_rechecked_after_option_history_load(tmp_path,monkeypatch):
 import services.kotak_assistant.entry_advisory as module
 read,c,_=fixture(tmp_path,monkeypatch)
 original_history=c.g.history;original_quote=c.g.quote;clock=[c.clock()];base=clock[0]
 c.clock=lambda:clock[0]
 def quote(symbol,exchange):
  q=original_quote(symbol,exchange);q['time']=base-4 if symbol=='NIFTY' else base;return q
 def history(symbol,exchange,interval):
  result=original_history(symbol,exchange,interval)
  if symbol.endswith('CE'):clock[0]+=2
  return result
 c.g.quote=quote;c.g.history=history
 monkeypatch.setattr(module,'breakout_retest',lambda *args:dict(strategy='breakout_retest',stage='ready',eligible=True,direction='CE',expires=base+60,reason='Confirmed'))
 result=read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)
 assert result['plan_fresh']
 assert result['candidates']['breakout_retest']['eligible'] is False


def test_freshness_recovers_without_waiting_for_another_five_minute_candle(tmp_path,monkeypatch):
 import services.kotak_assistant.entry_advisory as module
 read,c,_=fixture(tmp_path,monkeypatch)
 base=c.clock();original=c.g.quote;stale=[True]
 def quote(symbol,exchange):
  q=original(symbol,exchange)
  if symbol=='NIFTY' and stale[0]:q['time']=base-30
  return q
 c.g.quote=quote
 monkeypatch.setattr(module,'breakout_retest',lambda *a:dict(strategy='breakout_retest',stage='ready',eligible=True,direction='CE',expires=base+60,reason='Confirmed'))
 assert not read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)['candidates']['breakout_retest']['eligible']
 stale[0]=False
 assert read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)['candidates']['breakout_retest']['eligible']


def test_pivots_use_previous_daily_close_and_never_the_current_day(tmp_path,monkeypatch):
 read,c,_=fixture(tmp_path,monkeypatch)
 original=c.g.history
 def history(symbol,exchange,interval):
  if interval=='D':return [dict(time=epoch(22,5,30),open=100,high=110,low=90,close=106),dict(time=epoch(23,5,30),open=500,high=600,low=400,close=550)]
  return original(symbol,exchange,interval)
 c.g.history=history
 result=read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)
 assert result['pivots']['levels']['P']==102
 assert result['pivots']['reference_date']=='2026-10-22'
 assert result['pivots']['session_date']=='2026-10-23'
 assert result['pivots']['previous']['close']==106
 assert result['candidates']['pivot_rejection']['directions']['CE']['eligible'] is False


def test_invalidated_pivot_cannot_revive_when_index_recovers(tmp_path,monkeypatch):
 import services.kotak_assistant.entry_advisory as module
 read,c,_=fixture(tmp_path,monkeypatch);base=c.clock();price=[89];quote=c.g.quote
 def current(symbol,exchange):
  q=quote(symbol,exchange)
  if symbol=='NIFTY':q['ltp']=price[0]
  return q
 c.g.quote=current
 ready=dict(strategy='pivot_rejection',stage='ready',eligible=True,direction='CE',confirmed_at=base-1,expires=base+59,index_entry=91.4,invalidation=89.7,index_target=100,setup_id='pivot-test',reason='Confirmed')
 monkeypatch.setattr(module,'pivot_setups',lambda *a:dict(pivot_rejection=dict(ready,directions={'CE':dict(ready)})))
 assert not read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)['candidates']['pivot_rejection']['directions']['CE']['eligible']
 price[0]=91.4
 assert not read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)['candidates']['pivot_rejection']['directions']['CE']['eligible']


def test_native_timeframe_cache_cannot_survive_canonical_history_upgrade(tmp_path,monkeypatch):
 import services.kotak_assistant.entry_advisory as module
 read,c,_=fixture(tmp_path,monkeypatch);base=c.clock()
 read(c,'NIFTY')
 repo=setup_live.repository(c);scope=setup_live.scope_for(c,'NIFTY')+':entry-decisions'
 body,version=repo.read(scope)
 body['signature']=None  #previous native-timeframe cache key
 body['retest']=dict(strategy='breakout_retest',stage='ready',eligible=True,direction='CE',expires=base+60,reason='Old native bars')
 assert repo.commit(scope,version,body,[])
 monkeypatch.setattr(module,'breakout_retest',lambda *a:dict(strategy='breakout_retest',stage='waiting_break',eligible=False,direction=None,reason='Recomputed canonical history'))
 result=read(c,'NIFTY')['candidates']['breakout_retest']
 assert result['eligible'] is False and result['reason']=='Recomputed canonical history'


def test_previous_daily_recovers_immediately_after_a_transient_read_failure(tmp_path, monkeypatch):
 from services.kotak_assistant.broker import Gateway
 from services.kotak_assistant.entry_advisory import _previous_daily
 import threading
 from datetime import date
 read,c,_=fixture(tmp_path,monkeypatch)
 cache=Gateway.__new__(Gateway);cache._cache={};cache._flights={};cache._lock=threading.RLock()
 c.g.cached=cache.cached
 history=c.g.history;failed=[True]
 def flaky(symbol,exchange,interval):
  if failed[0]:raise ValueError('Temporary broker history failure')
  return history(symbol,exchange,interval)
 c.g.history=flaky
 assert _previous_daily(c,'NIFTY','NSE_INDEX','NSE',date(2026,10,23),window) is None
 failed[0]=False
 recovered=_previous_daily(c,'NIFTY','NSE_INDEX','NSE',date(2026,10,23),window)
 assert recovered is not None and recovered['close']==100


def test_slow_option_history_refreshes_quotes_before_publishing_plan(tmp_path,monkeypatch):
 import services.kotak_assistant.entry_advisory as module
 read,c,_=fixture(tmp_path,monkeypatch)
 history=c.g.history;clock=[c.clock()];base=clock[0]
 c.clock=lambda:clock[0]
 def quote(symbol,exchange):return dict(ltp=100,bid=100,ask=100.03,time=clock[0],source='Broker snapshot')
 def slow(symbol,exchange,interval):
  result=history(symbol,exchange,interval)
  if symbol.endswith('CE'):clock[0]+=6
  return result
 c.g.quote=quote;c.g.history=slow
 monkeypatch.setattr(module,'breakout_retest',lambda *a:dict(strategy='breakout_retest',stage='ready',eligible=True,direction='CE',expires=base+60,reason='Confirmed'))
 result=read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)
 assert result['plan_fresh'] and result['plan']['entry']==100.05
 assert result['quote']['time']==base+6
 assert not result['candidates']['breakout_retest']['eligible']
 c.g.history=history
 assert read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)['candidates']['breakout_retest']['eligible']


def test_widened_quote_after_cold_history_does_not_publish_a_plan(tmp_path,monkeypatch):
 read,c,_=fixture(tmp_path,monkeypatch)
 history=c.g.history;clock=[c.clock()];base=clock[0]
 c.clock=lambda:clock[0]
 def quote(symbol,exchange):
  return dict(ltp=100,bid=90 if clock[0]>base and symbol.endswith('CE') else 100,ask=100.03,time=clock[0],source='Broker snapshot')
 def slow(symbol,exchange,interval):
  result=history(symbol,exchange,interval)
  if symbol.endswith('CE'):clock[0]+=6
  return result
 c.g.quote=quote;c.g.history=slow
 result=read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)
 assert result['plan'] is None and not result['plan_fresh']
 assert 'spread' in result['plan_reason'].lower()


def test_slow_plan_cannot_preserve_readiness_across_the_entry_cutoff(tmp_path,monkeypatch):
 import services.kotak_assistant.entry_advisory as module
 read,c,_=fixture(tmp_path,monkeypatch)
 clock=[epoch(23,14,59)+59];base=clock[0];original=c.g.history
 c.clock=lambda:clock[0]
 def history(symbol,exchange,interval):
  if interval=='D':return original(symbol,exchange,interval)
  if interval=='5m':return []
  result=[dict(time=base-(20-i)*60,open=100,high=101,low=99,close=100,volume=100) for i in range(20)]
  if symbol.endswith('CE'):clock[0]+=3
  return result
 c.g.history=history
 c.g.quote=lambda *a:dict(ltp=100,bid=100,ask=100.03,time=clock[0],source='Broker snapshot')
 monkeypatch.setattr(module,'breakout_retest',lambda *a:dict(strategy='breakout_retest',stage='ready',eligible=True,direction='CE',expires=base+60,reason='Confirmed'))
 result=read(c,'NIFTY','NIFTY27OCT2622700CE',1,2)
 assert not result['candidates']['breakout_retest']['eligible']
 assert '15:00' in result['candidates']['breakout_retest']['reason']
