"""Profit protection checks use a fake broker and an isolated SQL store."""
import copy

import pytest

from services.risk.profit_protection import evaluate


def plan(side=1):
    return dict(side=side, entry=1000., initial_stop=1000.-side*100, stop=1000.-side*100,
                target=1000.+side*300, gap=50., tick=1., units=1., opening_cost=1.,
                funding=0., exit_rate=.001, exit_at=1740., window_end=1800.)


@pytest.mark.parametrize('side', [1, -1])
def test_profit_floor_only_tightens_and_preserves_initial_rr(side):
    p=plan(side)
    result=evaluate(p, 1000+side*20, 100, eligible=True)
    assert result['action']=='tighten'
    assert side*(result['stop']-1000)>0
    assert side*(1000+side*20-result['stop'])>=1
    p['stop']=result['stop']
    after=evaluate(p,1000+side*15,101,eligible=True)
    assert after['stop']==p['stop']
    assert after['target']==p['target']
    assert p['initial_stop']==1000-side*100


@pytest.mark.parametrize('side', [1,-1])
def test_loss_or_insufficient_fee_profit_cannot_claim_profit_protection(side):
    p=plan(side)
    assert evaluate(p,1000-side*10,100,eligible=True)['action']=='hold'
    assert evaluate(p,1000+side*1,100,eligible=True)['action']=='hold'


def test_fee_window_exit_is_early_positive_net_only_and_does_not_claim_late_waiver():
    p=plan()
    assert evaluate(p,1010,1739.99,eligible=True)['action']=='tighten'
    assert evaluate(p,1010,1740,eligible=True)['reason']=='fee_window'
    assert evaluate(p,1000,1740,eligible=True)['action']=='hold'
    assert evaluate(p,1010,1800,eligible=True)['action']!='exit'
    assert evaluate(p,1010,1740,eligible=False)['action']!='exit'


@pytest.mark.parametrize('side',[1,-1])
def test_original_fixed_target_is_not_recomputed_from_a_trailed_stop(side):
    p=plan(side)
    p['stop']=1000+side*100
    r=evaluate(p,p['target'],100,eligible=True)
    assert r['action']=='exit' and r['reason']=='target'
    assert r['target']==1000+side*300


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),0,-1])
def test_bad_prices_do_not_generate_actions(bad):
    with pytest.raises(ValueError):
        evaluate(plan(),bad,100,eligible=True)


def test_gap_trails_the_favourable_price_after_fee_floor_is_covered():
    p=plan()
    r=evaluate(p,1200,100,eligible=True)
    assert r['stop']==1150
    p['stop']=r['stop']
    assert evaluate(p,1190,101,eligible=True)['stop']==1150


class MemoryStore:
    def __init__(self): self.rows={}
    def get(self,user,symbol): return copy.deepcopy(self.rows.get((user,symbol)))
    def put(self,user,symbol,value): self.rows[user,symbol]=copy.deepcopy(value)


class FakeBroker:
    def __init__(self):
        self.calls=[]
        self.snapshot={**plan(), 'symbol':'BTCUSDFUT','quantity':1,'opened_at':'known',
                       'account':'test-account','stop_id':'old-stop','price':1020.,
                       'asof':100.,'eligible':True,'order_open':True,'added':False}
        self.fail=False
    def prepare(self,user,symbol): return copy.deepcopy(self.snapshot)
    def load(self,user,p): return copy.deepcopy(self.snapshot)
    def tighten(self,user,p,stop):
        self.calls.append(('tighten',stop))
        if self.fail: raise TimeoutError('unknown')
        self.snapshot['stop']=stop
        return stop
    def close(self,user,p,client_id):
        self.calls.append(('close',client_id))
        if self.fail: raise TimeoutError('unknown')
        return 'exit-order'
    def reconcile(self,user,p): return copy.deepcopy(self.snapshot)
    def exit_status(self,user,p): return {'state':'open'}


def manager():
    from services.delta_profit_guard import Manager
    repo,broker=MemoryStore(),FakeBroker()
    return Manager(repo,broker,clock=lambda:100.),repo,broker


def enable(m):
    preview=m.preview('u','BTCUSDFUT',{})
    return m.enable('u','BTCUSDFUT',{},preview['preview_id'])


def test_preview_and_enable_never_place_an_order():
    m,repo,g=manager()
    p=enable(m)
    assert p['enabled'] and p['target']==1300
    assert repo.get('u','BTCUSDFUT')['enabled']
    assert not g.calls
    m.poll('u','BTCUSDFUT')
    assert g.calls[0][0]=='tighten'


@pytest.mark.parametrize('change',[{'quantity':-1},{'entry':1001},{'opened_at':'new'}, {'added':True}, {'account':'new'}, {'order_open':False}])
def test_changed_position_or_missing_stop_pauses_instead_of_touching_another_trade(change):
    m,repo,g=manager(); enable(m)
    g.snapshot.update(change)
    m.poll('u','BTCUSDFUT')
    assert not g.calls
    assert repo.get('u','BTCUSDFUT')['state']=='paused'


def test_stale_snapshot_never_moves_a_stop():
    m,repo,g=manager(); enable(m)
    g.snapshot['asof']=80
    m.poll('u','BTCUSDFUT')
    assert not g.calls and repo.get('u','BTCUSDFUT')['state']=='error'


def test_unknown_exit_is_persisted_and_not_resubmitted_after_restart():
    from services.delta_profit_guard import Manager
    m,repo,g=manager(); enable(m)
    g.snapshot['price']=1300
    g.fail=True
    m.poll('u','BTCUSDFUT')
    saved=repo.get('u','BTCUSDFUT')
    assert saved['exit_intent']['client_id']
    Manager(repo,g,clock=lambda:100.).poll('u','BTCUSDFUT')
    assert sum(call[0]=='close' for call in g.calls)==1


def test_partial_reduction_preserves_the_earned_stop_and_original_target():
    m,repo,g=manager(); enable(m)
    m.poll('u','BTCUSDFUT')
    old=repo.get('u','BTCUSDFUT')
    g.snapshot.update(quantity=.5,units=.5,opening_cost=.5,price=1015)
    m.poll('u','BTCUSDFUT')
    new=repo.get('u','BTCUSDFUT')
    assert new['stop']>=old['stop'] and new['target']==old['target']


def test_pausing_protection_does_not_cancel_the_existing_broker_stop():
    m,repo,g=manager(); enable(m)
    m.disable('u','BTCUSDFUT')
    m.poll('u','BTCUSDFUT')
    assert not g.calls and not repo.get('u','BTCUSDFUT')['enabled']


def test_enable_requires_the_displayed_position_and_settings():
    m,repo,g=manager()
    preview=m.preview('u','BTCUSDFUT',{})
    g.snapshot['quantity']=2
    with pytest.raises(ValueError,match='changed'):
        m.enable('u','BTCUSDFUT',{},preview['preview_id'])
    assert not g.calls


def test_paused_unknown_exit_still_reconciles_without_an_intact_stop():
    m,repo,g=manager(); enable(m)
    g.snapshot['price']=1300; g.fail=True
    m.poll('u','BTCUSDFUT'); m.disable('u','BTCUSDFUT')
    def invalid_stop(*args): raise AssertionError('Must not depend on stop')
    g.load=invalid_stop
    g.snapshot['quantity']=0
    g.exit_status=lambda *args: {'state':'closed'}
    m.poll('u','BTCUSDFUT')
    p=repo.get('u','BTCUSDFUT')
    assert p['state']=='closed' and not p.get('exit_intent')
    assert len(g.calls)==1


@pytest.mark.parametrize('state',['cancelled','rejected','closed'])
def test_resolved_exit_with_remainder_can_be_deliberately_readopted(state):
    m,repo,g=manager(); enable(m)
    g.snapshot['price']=1300; g.fail=True
    m.poll('u','BTCUSDFUT')
    g.exit_status=lambda *args: {'state':state}
    m.poll('u','BTCUSDFUT')
    assert not repo.get('u','BTCUSDFUT').get('exit_intent')
    enable(m)
    assert len(g.calls)==1  # enabling still does not submit


def test_ownership_conflict_requires_explicit_readoption():
    from services.delta_profit_guard import ProtectionChanged
    m,repo,g=manager(); enable(m)
    def conflict(*args): raise ProtectionChanged('Another controller owns the contract')
    load=g.load; g.load=conflict
    m.poll('u','BTCUSDFUT'); g.load=load; m.poll('u','BTCUSDFUT')
    assert not repo.get('u','BTCUSDFUT')['enabled'] and not g.calls


@pytest.mark.parametrize('change',[{'exit_rate':.002},{'eligible':False},{'window_end':1000},{'opening_cost':2}])
def test_preview_invalidates_on_fee_policy_change(change):
    m,repo,g=manager(); preview=m.preview('u','BTCUSDFUT',{})
    g.snapshot.update(change)
    with pytest.raises(ValueError,match='changed'):
        m.enable('u','BTCUSDFUT',{},preview['preview_id'])
    assert not g.calls


def test_current_fee_rate_is_used_before_target_exit():
    m,repo,g=manager(); enable(m)
    g.snapshot.update(price=1300,exit_rate=.3,eligible=False)
    m.poll('u','BTCUSDFUT')
    assert not any(c[0]=='close' for c in g.calls)
    assert repo.get('u','BTCUSDFUT')['exit_rate']==.3


def test_known_failed_preflight_is_not_an_unknown_submission():
    from services.delta_profit_guard import NotSubmitted
    m,repo,g=manager(); enable(m); g.snapshot['price']=1300
    def no_submit(*args): raise NotSubmitted('Quote changed')
    g.close=no_submit; m.poll('u','BTCUSDFUT')
    assert not repo.get('u','BTCUSDFUT').get('exit_intent')
    assert not g.calls


def test_repository_restart_and_migration_preserve_pending_intent_without_resource_growth(tmp_path):
    import psutil
    from database.engine_factory import create_db_engine
    from services.delta_profit_guard import Repository, Manager
    from upgrade.migrate_delta_profit_protection import migrate
    engine=create_db_engine('sqlite:///'+str(tmp_path/'guard.db'))
    try:
        assert not migrate(engine,status=True)
        assert not migrate(engine)
        repo=Repository(engine); g=FakeBroker(); m=Manager(repo,g,clock=lambda:100)
        enable(m); g.snapshot['price']=1300; g.fail=True
        m.poll('u','BTCUSDFUT'); m.disable('u','BTCUSDFUT')
        assert repo.list(active=True)  # pending reconciliation survives pause
        assert migrate(engine)
        g.snapshot['quantity']=0
        g.exit_status=lambda *args: {'state':'closed'}
        Manager(Repository(engine),g,clock=lambda:100).poll('u','BTCUSDFUT')
        assert not repo.list(active=True)
        process=psutil.Process(); before=process.num_fds()
        for _ in range(200):
            p=repo.get('u','BTCUSDFUT'); repo.put('u','BTCUSDFUT',p); repo.list(active=True)
        assert process.num_fds() <= before+2
    finally: engine.dispose()


@pytest.mark.parametrize('change',[{'exit_rate':.3,'eligible':False}, {'window_end':99,'exit_at':39,'price':1010}])
def test_gateway_exit_rechecks_current_fee_or_deadline(monkeypatch,change):
    from services.delta_profit_gateway import Gateway
    from services.delta_profit_guard import NotSubmitted
    m,_,g=manager(); p=enable(m)
    p.update(product_id=27,price=1300)
    current={**p,'price':1300,'funding':0,**change}
    gateway=Gateway(); calls=[]
    monkeypatch.setattr(gateway,'load',lambda *args:current)
    monkeypatch.setattr(gateway,'call',lambda *args,**kw:calls.append(kw))
    monkeypatch.setattr('services.delta_profit_gateway.time.time',lambda:100)
    with pytest.raises(NotSubmitted): gateway.close('u',p,'test-client')
    assert not calls


def test_gateway_exit_is_reduce_only_and_uses_current_residual_quantity(monkeypatch):
    from services.delta_profit_gateway import Gateway
    m,_,g=manager(); p=enable(m); p['product_id']=27
    gateway=Gateway(); calls=[]
    monkeypatch.setattr(gateway,'load',lambda *args:{**p,'quantity':.5,'units':.5,'price':1300})
    monkeypatch.setattr(gateway,'auth',lambda *args:'fake')
    def call(*args,**kw): calls.append(kw); return {'result':{'id':123}}
    monkeypatch.setattr(gateway,'call',call)
    monkeypatch.setattr('services.delta_profit_gateway.time.time',lambda:100)
    # Real Delta whole-contract residuals are enforced by snapshot; test uses 2 -> 1.
    p['quantity']=2; p['remaining_quantity']=2
    monkeypatch.setattr(gateway,'load',lambda *args:{**p,'quantity':1,'units':1,'price':1300})
    assert gateway.close('u',p,'persisted-client')=='123'
    assert calls[0]['method']=='POST'
    assert calls[0]['body']==dict(product_id=27,size=1,side='sell',order_type='market_order',reduce_only=True,client_order_id='persisted-client')


def test_pending_flat_from_different_account_cannot_clear_exit_identity():
    m,repo,g=manager(); enable(m); g.snapshot['price']=1300; g.fail=True
    m.poll('u','BTCUSDFUT')
    g.snapshot.update(quantity=0,account='other')
    m.poll('u','BTCUSDFUT')
    p=repo.get('u','BTCUSDFUT')
    assert p['state']=='paused' and p['exit_intent']


def test_gateway_snapshot_filters_and_paginates_fills_without_mutations(monkeypatch):
    from types import SimpleNamespace
    from services.delta_profit_gateway import Gateway
    from services.crypto_fees import FeeProfile
    g=Gateway(); calls=[]
    monkeypatch.setattr(g,'auth',lambda *a:'fake-auth')
    monkeypatch.setattr(g,'conflict',lambda *a:None)
    monkeypatch.setattr(g,'info',lambda *a:(27,1,.001,'BTCUSD'))
    monkeypatch.setattr(g,'position',lambda *a:dict(size=15,entry_price=1000,created_at=10,commission=.01))
    monkeypatch.setattr('services.delta_profit_gateway.time.time',lambda:100)
    monkeypatch.setattr('services.crypto_fee_service.fee_profile',lambda:FeeProfile())
    monkeypatch.setattr('services.crypto_fee_service.contract_fees',lambda *a:(SimpleNamespace(rate=lambda *a:.001),None))
    monkeypatch.setattr('services.crypto_fees.scalper_window_minutes',lambda *a:30)
    stop=dict(id=123,product_id=27,side='sell',reduce_only=True,stop_order_type='stop_loss_order',
              order_type='market_order',size=15,unfilled_size=15,state='open',stop_price='900',stop_trigger_method='mark_price')
    def call(auth,path,**kw):
        calls.append((path,kw))
        assert kw.get('method','GET')=='GET'
        if path=='/v2/orders':
            assert kw['params']['states']=='open,pending' and kw['params']['product_ids']=='27'
            return dict(result=[stop])
        if path=='/v2/orders/123': return dict(result=stop)
        if path=='/v2/tickers/BTCUSD': return dict(result=dict(quotes=dict(best_bid=1020,best_ask=1021),mark_price=1020))
        assert path=='/v2/fills' and kw['params']['product_ids']=='27'
        return dict(result=[dict(product_id=27,side='sell',created_at=99)],meta={} if kw['params'].get('after') else {'after':'second'})
    monkeypatch.setattr(g,'call',call)
    p=g.snapshot('u','BTCUSDFUT',enabled_at=90)
    assert p['eligible'] and p['exit_at']==1750 and p['window_end']==1810
    assert not p['added'] and len([c for c in calls if c[0]=='/v2/fills'])==2


@pytest.mark.parametrize('bad',[{'reduce_only':False},{'size':1},{'filled_size':1,'unfilled_size':14},{'trail_amount':2},{'side':'buy'}])
def test_gateway_rejects_unsafe_native_stops(monkeypatch,bad):
    from services.delta_profit_gateway import Gateway
    from services.delta_profit_guard import ProtectionChanged
    g=Gateway()
    row=dict(product_id=27,side='sell',reduce_only=True,stop_order_type='stop_loss_order',
             order_type='market_order',size=15,unfilled_size=15,**{})
    row.update(bad)
    monkeypatch.setattr(g,'call',lambda *a,**k:dict(result=row))
    with pytest.raises(ProtectionChanged): g.order('fake',27,'123',1,15)


def test_guard_routes_require_delta_session_live_mode_and_do_not_adopt_on_get(monkeypatch):
    from flask import Flask
    from blueprints.delta_profit_guard import delta_profit_guard_bp
    from services import delta_profit_guard as service
    from types import SimpleNamespace
    app=Flask(__name__); app.secret_key='isolated-test'; app.register_blueprint(delta_profit_guard_bp)
    client=app.test_client(); calls=[]
    monkeypatch.setattr(service,'repository',lambda:SimpleNamespace(list=lambda **k:[]))
    monkeypatch.setattr(service,'manager',lambda:SimpleNamespace(preview=lambda *a: calls.append(a) or {'account':'secret','stop':900}))
    assert client.get('/delta-profit-protection/api/status').status_code==401
    with client.session_transaction() as session: session.update(user='u',broker='kotak')
    assert client.get('/delta-profit-protection/api/status').status_code==403
    with client.session_transaction() as session: session['broker']='deltaexchange'
    assert client.get('/delta-profit-protection/api/status').status_code==200 and not calls
    assert client.post('/delta-profit-protection/api/preview',json={'symbol':'BTCUSDFUT','mode':'paper'}).status_code==409
    response=client.post('/delta-profit-protection/api/preview',json={'symbol':'BTCUSDFUT','mode':'live'})
    assert response.status_code==200 and 'account' not in response.json['data'] and len(calls)==1


def test_flat_with_still_pending_exit_retains_identity_until_terminal_ack():
    m,repo,g=manager(); enable(m); g.snapshot['price']=1300; g.fail=True
    m.poll('u','BTCUSDFUT'); g.snapshot['quantity']=0
    m.poll('u','BTCUSDFUT')
    assert repo.get('u','BTCUSDFUT')['exit_intent']
    g.exit_status=lambda *args: {'state':'closed'}
    m.poll('u','BTCUSDFUT')
    assert not repo.get('u','BTCUSDFUT').get('exit_intent')


def test_ownership_change_during_exit_preflight_pauses_and_clears_unsent_intent():
    from services.delta_profit_gateway import Gateway
    from services.delta_profit_guard import ProtectionChanged
    m,repo,g=manager(); enable(m); g.snapshot['price']=1300
    gateway=Gateway()
    def changed(*args): raise ProtectionChanged('Controller changed')
    gateway.load=changed
    g.close=gateway.close
    m.poll('u','BTCUSDFUT')
    saved=repo.get('u','BTCUSDFUT')
    assert not saved['enabled'] and not saved.get('exit_intent') and saved['state']=='paused'
    assert not g.calls


def test_readonly_broker_risk_uses_product_leverage_and_native_protection(monkeypatch):
    from services.delta_profit_gateway import Gateway
    from database import token_db
    g=Gateway(); calls=[]
    monkeypatch.setattr(g,'auth',lambda *a:'fake')
    monkeypatch.setattr(token_db,'get_symbol',lambda *a:'BTCUSDFUT')
    def call(auth,path,**kw):
        calls.append((path,kw)); assert kw.get('method','GET')=='GET'
        if path=='/v2/positions/margined': return {'result':[dict(product_id=27,size=-18,entry_price=81824)]}
        if path.endswith('/orders/leverage'): return {'result':{'leverage':'5'}}
        return {'result':[
            dict(product_id=27,id=1,state='pending',side='buy',reduce_only=True,size=18,stop_order_type='stop_loss_order',stop_price='81920'),
            dict(product_id=27,id=2,state='pending',side='buy',reduce_only=True,size=18,stop_order_type='take_profit_order',stop_price='81538.5'),
            dict(product_id=27,id=3,state='pending',side='sell',reduce_only=False,size=18,stop_order_type='stop_loss_order',stop_price='83000')
        ]}
    monkeypatch.setattr(g,'call',call)
    row=g.view('u')[0]
    assert row['leverage']==5 and row['stops']==[81920] and row['targets']==[81538.5]
    assert len(calls)==3


def cash_plan(side=1):
    return {**plan(side), 'tick':.01, 'trailing_mode':'net_usd', 'profit_arm_usd':2.,
            'profit_lock_usd':1.5, 'profit_gap_usd':.5}


def price_for_net(p, net):
    return (net+p['side']*p['entry']*p['units']+p['opening_cost']+p['tick']*p['units']*(1-p['side']*p['exit_rate'])-p['funding'])/(p['units']*(p['side']-p['exit_rate']))


def ordinary_net(p, price):
    fill = price-p['side']*p['tick']
    return p['side']*(fill-p['entry'])*p['units']-p['opening_cost']-p['exit_rate']*fill*p['units']+p['funding']


@pytest.mark.parametrize('side',[1,-1])
def test_cash_trail_arms_strictly_above_two_net_and_locks_one_fifty(side):
    p=cash_plan(side)
    assert evaluate(p,price_for_net(p,2),100,eligible=True)['action']=='hold'
    r=evaluate(p,price_for_net(p,2.1),100,eligible=True)
    assert r['action']=='tighten'
    assert r['profit_armed'] is True
    assert r['protected_net_usd']==pytest.approx(1.6)
    assert ordinary_net(p,r['stop'])>=1.6-1e-8
    assert side*(r['stop']-p['stop'])>0


@pytest.mark.parametrize('side',[1,-1])
def test_cash_peak_survives_pullback_and_stop_never_moves_backwards(side):
    p=cash_plan(side)
    r=evaluate(p,price_for_net(p,5),100,eligible=False)
    p.update({k:r[k] for k in ('peak_net_usd','profit_armed','protected_net_usd','stop')})
    after=evaluate(p,price_for_net(p,4.9),101,eligible=False)
    assert after['stop']==p['stop']
    assert after['peak_net_usd']==5
    assert after['protected_net_usd']==4.5
    assert after['target']==p['target']


@pytest.mark.parametrize('side',[1,-1])
def test_cash_trail_uses_normal_fees_funding_and_position_size_not_price_points(side):
    p={**cash_plan(side),'units':.019,'tick':.5,'entry':80000.,'stop':79000. if side>0 else 81000.,'target':85000. if side>0 else 75000.,'opening_cost':.9,'funding':-.2}
    r=evaluate(p,price_for_net(p,2.1),100,eligible=True)
    assert r['action']=='tighten'
    assert ordinary_net(p,r['stop'])>=1.6-1e-8
    # A free-close promotion must not arm on a gross/discounted $2 figure.
    assert evaluate(p,price_for_net(p,1.9),100,eligible=True)['action']=='hold'


def test_failed_cash_ratchet_can_exit_positive_after_pullback_before_acknowledgement():
    p=cash_plan();p.update(peak_net_usd=5.,profit_armed=True)
    r=evaluate(p,price_for_net(p,4),100,eligible=False)
    assert r['action']=='exit' and r['reason']=='profit_trail'
    assert r['net']>0


@pytest.mark.parametrize('bad',[{'profit_arm_usd':0},{'profit_lock_usd':3},{'profit_gap_usd':0},{'peak_net_usd':float('nan')}])
def test_cash_policy_rejects_impossible_or_nonfinite_values(bad):
    with pytest.raises(ValueError): evaluate({**cash_plan(),**bad},1010,100,eligible=False)


def test_cash_settings_are_preview_bound_and_peak_persists_through_manager_restart():
    m,repo,g=manager()
    g.snapshot['tick']=.01
    config={'trailing_mode':'net_usd','profit_arm_usd':2,'profit_lock_usd':1.5,'profit_gap_usd':.5}
    preview=m.preview('u','BTCUSDFUT',config)
    assert preview['profit_arm_usd']==2
    with pytest.raises(ValueError,match='changed'):
        m.enable('u','BTCUSDFUT',{**config,'profit_lock_usd':1.4},preview['preview_id'])
    m.enable('u','BTCUSDFUT',config,preview['preview_id'])
    g.snapshot.update(price=price_for_net(cash_plan(),5))
    m.poll('u','BTCUSDFUT')
    p=repo.get('u','BTCUSDFUT')
    assert p['peak_net_usd']==5
    assert p['profit_armed'] is True
    from services.delta_profit_guard import Manager
    restored=Manager(repo,g,clock=lambda:100)
    g.snapshot.update(price=price_for_net(cash_plan(),4.9),stop=p['stop'])
    restored.poll('u','BTCUSDFUT')
    assert repo.get('u','BTCUSDFUT')['stop']==p['stop']
    assert repo.get('u','BTCUSDFUT')['peak_net_usd']==5


def test_cash_peak_is_durable_before_broker_io_even_if_process_dies():
    m,repo,g=manager();g.snapshot['tick']=.01
    config={'trailing_mode':'net_usd','profit_arm_usd':2,'profit_lock_usd':1.5,'profit_gap_usd':.5}
    preview=m.preview('u','BTCUSDFUT',config)
    m.enable('u','BTCUSDFUT',config,preview['preview_id'])
    g.snapshot['price']=price_for_net(cash_plan(),5)
    def die(*args):raise SystemExit('process died during broker request')
    g.tighten=die
    with pytest.raises(SystemExit):m.poll('u','BTCUSDFUT')
    saved=repo.get('u','BTCUSDFUT')
    assert saved['peak_net_usd']==5 and saved['profit_armed'] is True
    assert saved['stop']==cash_plan()['stop']
    g.snapshot['price']=price_for_net(cash_plan(),4)
    from services.delta_profit_guard import Manager
    Manager(repo,g,clock=lambda:100).poll('u','BTCUSDFUT')
    assert repo.get('u','BTCUSDFUT')['exit_intent']['reason']=='profit_trail'


def test_short_tick_aligned_stop_reserves_fees_on_the_actual_adverse_fill():
    p={**cash_plan(-1), 'entry':80000., 'stop':81000., 'target':75000., 'units':.019, 'tick':.5, 'opening_cost':.9}
    p.update(peak_net_usd=3.7762,profit_armed=True)
    r=evaluate(p,price_for_net(p,3.7762),100,eligible=False)
    assert r['action']=='tighten'
    actual_fill=r['stop']+.5
    actual_net=(80000.-actual_fill)*.019-.9-p['exit_rate']*actual_fill*.019
    assert actual_net>=r['protected_net_usd']-1e-10
