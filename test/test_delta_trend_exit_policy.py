"""Offline plan lifecycle tests; fake client only, no account or network access."""
import json
import time

import pytest

import test_delta_chart_plans as fixtures
from services.delta_chart.plans import ManagedPlans
from services.delta_chart.service import Rejected


@pytest.fixture
def harness():
    h = fixtures.ManagedPlanTests('runTest')
    h.setUp()
    # Test the plan lifecycle independently of coordinator authorization. The
    # coordinator/service tests own permission, generation and digest binding.
    if hasattr(h.service, 'automation'):
        del h.service.automation
    try:
        yield h
    finally:
        h.doCleanups()


def trend_entry(h, seconds=60):
    h.source = int(time.time()) // seconds * seconds - seconds
    return h.entry(target_mode='trend', automation_generation='offline-test-generation',
                   auto_protection=dict(stop=95,target=110,source_time=h.source,
                                        interval_seconds=seconds,reason='Reviewed trend levels'))


def test_trend_entry_has_market_stop_only_and_becomes_active(harness):
    h = harness
    trend_entry(h)
    h.filled()
    h.manage()
    result = h.manage()
    assert result['plan_status'] == 'active'
    protection = [row for row in h.client.orders if row.get('stop_order_type')]
    assert len(protection) == 1
    assert protection[0]['stop_order_type'] == 'stop_loss_order'
    assert protection[0]['order_type'] == 'market_order'
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'trend'
    assert listed['target_order_id'] is None
    assert listed['stop_order_id'] is not None


def test_trend_mode_and_backend_tracking_persist_for_non_one_minute_plan(harness):
    h = harness
    trend_entry(h, 900)
    h.service.plans = ManagedPlans(h.service)
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'trend'
    assert listed['smart_profit_tracking'] is True
    payload = json.loads(h.service.plans.get('alice',listed['id'])['payload'])
    assert payload['entry_ttl_seconds'] == 15
    assert payload['automation_generation'] == 'offline-test-generation'
    h.parent['created_at'] = str(time.time()-16)
    h.service.plans.manage('alice',dict(plan_id=listed['id'],decision='sync'),protection_only=True)
    assert h.parent['state'] == 'cancelled'


def post_fill_history(h, span=60):
    # Model a position filled before the three complete trailing candles.
    for fill in h.client.rows:
        fill['created_at']=str(int(time.time())//span*span-4*span)


def plan_candles(h, center, *, empty=False, stale=False):
    original = h.client.request
    def request(method,path,**kwargs):
        if method == 'GET' and path == '/v2/history/candles':
            if empty: return []
            span = {'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1h':3600,'4h':14400,'1d':86400}[kwargs['params']['resolution']]
            end = (int(time.time())//span-1)*span - (span if stale else 0)
            return [dict(time=end-i*span,open=center-1,high=center+5,low=center-5,close=center)
                    for i in range(20)]
        return original(method,path,**kwargs)
    h.client.request = request


def test_trend_profit_trails_without_target_and_never_loosen_after_reload(harness):
    h = harness
    trend_entry(h)
    h.filled()
    h.manage()
    h.manage()
    h.profit_mark(500)
    plan_candles(h,480)
    post_fill_history(h)
    result = h.manage()
    assert result['status'] == 'confirmed'
    assert h.mutations()[-1][0] == 'PUT'
    before = h.service.plans.list('alice','BTCUSD')[0]
    assert before['peak_net_inr'] > 15
    assert before['stop'] > 99.5
    assert before['target_order_id'] is None
    h.service.plans = ManagedPlans(h.service)
    h.manage()
    after = h.service.plans.list('alice','BTCUSD')[0]
    assert after['stop'] >= before['stop']
    assert after['target_order_id'] is None


@pytest.mark.parametrize('changes', [dict(target_mode='other'),dict(target_mode='trend')])
def test_trend_mode_requires_backend_entry_marker_and_valid_mode(harness,changes):
    with pytest.raises(Rejected):
        harness.entry(**changes)
    assert harness.mutations() == []


def test_existing_manual_fixed_target_and_tracking_semantics_unchanged(harness):
    h = harness
    seconds = 900
    h.source = int(time.time())//seconds*seconds-seconds
    h.entry(entry_mode='manual',auto_protection=dict(stop=95,target=110,source_time=h.source,
                                                   interval_seconds=seconds,reason='Manual levels'))
    h.filled(); h.manage(); h.manage(); h.manage()
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'fixed'
    assert listed['target_order_id'] is not None
    assert listed['smart_profit_tracking'] is False
    payload = json.loads(h.service.plans.get('alice',listed['id'])['payload'])
    assert 'entry_ttl_seconds' not in payload


def test_explicit_manual_trend_mode_keeps_stop_without_fixed_target(harness):
    h = harness
    h.entry(entry_mode='manual',target_mode='trend')
    h.filled(); h.manage(); h.manage()
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'trend'
    assert listed['stop_order_id'] is not None
    assert listed['target_order_id'] is None
    payload = json.loads(h.service.plans.get('alice',listed['id'])['payload'])
    assert 'entry_ttl_seconds' not in payload


def fixed_active(h):
    h.entry()
    h.filled()
    h.manage(); h.manage(); h.manage()
    return h.service.plans.list('alice','BTCUSD')[0]


def test_let_run_cancels_only_owned_target_keeps_stop_and_persists(harness):
    h = harness
    before = fixed_active(h)
    stop = next(row for row in h.client.orders if str(row['id']) == before['stop_order_id'])
    stop_before = dict(stop)
    target = next(row for row in h.client.orders if str(row['id']) == before['target_order_id'])
    foreign = dict(target,id=999,client_order_id='foreign-order')
    h.client.orders.append(foreign)
    mutations = len(h.mutations())
    result = h.manage('let_run')
    assert result['status'] == 'confirmed'
    assert h.mutations()[mutations:][0][0] == 'DELETE'
    assert len(h.mutations()[mutations:]) == 1
    assert h.mutations()[-1][2]['id'] == target['id']
    assert stop == stop_before
    assert foreign['state'] == 'pending'
    assert target['state'] == 'cancelled'
    h.service.plans = ManagedPlans(h.service)
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'trend'
    assert listed['target_order_id'] is None
    assert listed['stop_order_id'] == before['stop_order_id']
    h.manage()
    assert h.service.plans.list('alice','BTCUSD')[0]['target_order_id'] is None
    assert len(h.mutations()) == mutations + 1


def test_let_run_unknown_cancel_waits_then_reconciles_without_second_delete(harness):
    h = harness
    before = fixed_active(h)
    target = next(row for row in h.client.orders if str(row['id']) == before['target_order_id'])
    h.client.timeout_next = True
    count = len(h.mutations())
    result = h.manage('let_run')
    assert result['status'] == 'pending'
    assert h.service.plans.list('alice','BTCUSD')[0]['target_mode'] == 'fixed'
    h.service.plans = ManagedPlans(h.service)
    assert h.manage()['status'] == 'pending'
    assert len(h.mutations()) == count + 1
    target['state'] = 'cancelled'  # Fake broker proves the first request completed.
    result = h.manage()
    assert result['status'] == 'confirmed'
    assert h.service.plans.list('alice','BTCUSD')[0]['target_mode'] == 'trend'
    assert h.service.plans.list('alice','BTCUSD')[0]['target_order_id'] is None
    assert len(h.mutations()) == count + 1


@pytest.mark.parametrize('invalid',['missing','wrong_size','foreign','closed','limit','wrong_stop'])
def test_let_run_never_removes_target_without_exact_owned_market_stop(harness,invalid):
    h = harness
    before = fixed_active(h)
    stop = next(row for row in h.client.orders if str(row['id']) == before['stop_order_id'])
    if invalid == 'missing':
        h.service.plans.update(before['id'],stop_order_id=None)
        h.client.orders.remove(stop)
    if invalid == 'wrong_size': stop['size'] = 2
    if invalid == 'foreign': stop['client_order_id'] = 'foreign'
    if invalid == 'closed': stop['state'] = 'closed'
    if invalid == 'limit': stop['order_type'] = 'limit_order'
    if invalid == 'wrong_stop': stop['stop_price'] = 94
    count = len(h.mutations())
    result = h.manage('let_run')
    assert result['status'] in ('rejected','pending')
    assert len(h.mutations()) == count
    assert h.service.plans.list('alice','BTCUSD')[0]['target_mode'] == 'fixed'


def test_let_run_refuses_foreign_target_even_with_owned_stop(harness):
    h = harness
    before = fixed_active(h)
    target = next(row for row in h.client.orders if str(row['id']) == before['target_order_id'])
    target['client_order_id'] = 'foreign-target'
    count = len(h.mutations())
    result = h.manage('let_run')
    assert result['status'] == 'rejected'
    assert len(h.mutations()) == count
    assert target['state'] == 'pending'
    assert h.service.plans.list('alice','BTCUSD')[0]['target_mode'] == 'fixed'


def test_let_run_accepts_exact_proven_cancelled_target_without_another_cancel(harness):
    h = harness
    before = fixed_active(h)
    target = next(row for row in h.client.orders if str(row['id']) == before['target_order_id'])
    target['state'] = 'cancelled'
    count = len(h.mutations())
    result = h.manage('let_run')
    assert result['status'] == 'confirmed'
    assert len(h.mutations()) == count
    h.service.plans = ManagedPlans(h.service)
    h.manage()
    assert h.service.plans.list('alice','BTCUSD')[0]['target_mode'] == 'trend'
    assert h.service.plans.list('alice','BTCUSD')[0]['target_order_id'] is None


def nonterminal_cancel_ack(h, target):
    original = h.client.request
    def request(method, path, **kwargs):
        if method == 'DELETE' and path == '/v2/orders':
            h.client.calls.append((method,path,kwargs['payload']))
            return dict(target)  # Acknowledged request, still executable at broker.
        return original(method,path,**kwargs)
    h.client.request = request


def test_let_run_nonterminal_ack_retains_target_until_fresh_terminal_read(harness):
    h = harness
    before = fixed_active(h)
    target = next(row for row in h.client.orders if str(row['id']) == before['target_order_id'])
    stop = next(row for row in h.client.orders if str(row['id']) == before['stop_order_id'])
    stop_before = dict(stop)
    nonterminal_cancel_ack(h,target)
    count = len(h.mutations())
    result = h.manage('let_run')
    assert result['status'] == 'pending'
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'fixed'
    assert listed['target_order_id'] == str(target['id'])
    h.service.plans = ManagedPlans(h.service)
    assert h.manage()['status'] == 'pending'
    assert h.manage('let_run')['status'] == 'pending'
    assert len(h.mutations()) == count + 1
    assert stop == stop_before
    target['state'] = 'cancelled'
    assert h.manage()['status'] == 'confirmed'
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'trend'
    assert listed['target_order_id'] is None
    assert len(h.mutations()) == count + 1
    assert stop == stop_before


def test_let_run_replay_blocks_foreign_terminal_order_after_nonterminal_ack(harness):
    h = harness
    before = fixed_active(h)
    target = next(row for row in h.client.orders if str(row['id']) == before['target_order_id'])
    nonterminal_cancel_ack(h,target)
    h.manage('let_run')
    count = len(h.mutations())
    target.update(state='cancelled',client_order_id='foreign-order')
    h.service.plans = ManagedPlans(h.service)
    result = h.manage()
    assert result['status'] in ('rejected','pending')
    listed = h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode'] == 'fixed'
    assert listed['target_order_id'] == str(target['id'])
    assert len(h.mutations()) == count


def test_adaptive_plan_waits_for_postfill_candles_and_preserves_stop_without_data(harness):
    h = harness
    trend_entry(h); h.filled(); h.manage(); h.manage()
    h.profit_mark(150)
    plan_candles(h,110)
    count = len(h.mutations())
    result = h.manage()
    assert result['status'] == 'confirmed'
    assert len(h.mutations()) == count
    assert 'post-fill' in result['message'].lower()
    assert 'waiting' in result['message'].lower()
    h.profit_mark(500)
    plan_candles(h,480,empty=True)
    result=h.manage()
    assert len(h.mutations()) == count
    assert 'waiting' in result['message'].lower()
    assert h.service.plans.list('alice','BTCUSD')[0]['stop'] == 95


def test_adaptive_plan_retrace_has_no_fixed_rupee_close_and_stop_never_loosens(harness):
    h = harness
    trend_entry(h); h.filled(); h.manage(); h.manage()
    h.profit_mark(500); plan_candles(h,480)
    post_fill_history(h)
    h.manage()
    before=h.service.plans.list('alice','BTCUSD')[0]
    assert before['stop'] == 472.5
    count=len(h.mutations())
    h.profit_mark(350); plan_candles(h,330)
    result=h.manage()
    assert result['plan_status'] == 'active'
    assert len(h.mutations()) == count
    assert h.service.plans.list('alice','BTCUSD')[0]['stop'] == 472.5


def test_entry_strategy_and_initial_direction_survive_reload(harness):
    h=harness
    h.entry(target_mode='trend',automation_generation='test',strategy_id='pd_sweep',
            strategy_version='test-v1',daily_key='2026-11-02:buy',entry_trend_direction='down')
    h.service.plans=ManagedPlans(h.service)
    listed=h.service.plans.list('alice','BTCUSD')[0]
    assert listed['strategy_id'] == 'pd_sweep'
    assert listed['entry_trend_direction'] == 'down'
    payload=json.loads(h.service.plans.get('alice',listed['id'])['payload'])
    assert payload['strategy_version'] == 'test-v1'
    assert payload['daily_key'] == '2026-11-02:buy'


@pytest.mark.parametrize('invalid',['empty','stale','gap'])
def test_adaptive_plan_invalid_history_never_edits_or_synthetically_closes(harness,invalid):
    h=harness
    trend_entry(h); h.filled(); h.manage(); h.manage()
    h.profit_mark(500)
    plan_candles(h,480,empty=invalid=='empty',stale=invalid=='stale')
    original=h.client.request
    def request(method,path,**kwargs):
        result=original(method,path,**kwargs)
        if path=='/v2/history/candles' and invalid=='gap': del result[3]
        return result
    h.client.request=request
    count=len(h.mutations())
    result=h.manage()
    assert result['status'] == 'confirmed'
    assert 'waiting' in result['message'].lower()
    assert len(h.mutations()) == count
    assert h.service.plans.list('alice','BTCUSD')[0]['stop'] == 95


def test_adaptive_reads_own_plan_interval_outside_db_write_transaction(harness):
    import sqlite3
    h=harness
    trend_entry(h,900); h.filled(); h.manage(); h.manage()
    h.profit_mark(500); plan_candles(h,480)
    post_fill_history(h,900)
    original=h.client.request
    reads=[]
    def request(method,path,**kwargs):
        if path=='/v2/history/candles':
            # Another writer must acquire a SQLite reservation while OHLC loads.
            # A network read inside BEGIN IMMEDIATE would lock this out.
            with sqlite3.connect(str(h.service.store.path),timeout=0) as db:
                db.execute('BEGIN IMMEDIATE')
                db.rollback()
            reads.append((kwargs['params']['resolution'],kwargs.get('private')))
        return original(method,path,**kwargs)
    h.client.request=request
    result=h.manage()
    assert result['status'] == 'confirmed'
    assert reads == [('15m',False)]
    assert h.service.plans.list('alice','BTCUSD')[0]['stop'] == 472.5


@pytest.mark.parametrize('delayed',[False,True])
def test_let_run_partial_entry_binds_terminal_proof_to_reviewed_exposure(harness,delayed):
    h=harness
    h.entry(size=4)
    h.filled()
    h.parent.update(unfilled_size=3,state='cancelled')
    h.manage(); h.manage(); h.manage()
    before=h.service.plans.list('alice','BTCUSD')[0]
    assert before['status']=='active'
    target=next(row for row in h.client.orders if str(row['id'])==before['target_order_id'])
    stop=next(row for row in h.client.orders if str(row['id'])==before['stop_order_id'])
    assert target['size']==stop['size']==1
    stop_before=dict(stop)
    if delayed: nonterminal_cancel_ack(h,target)
    count=len(h.mutations())
    result=h.manage('let_run')
    if delayed:
        assert result['status']=='pending'
        h.service.plans=ManagedPlans(h.service)
        assert h.manage()['status']=='pending'
        target['state']='cancelled'
        result=h.manage()
    assert result['status']=='confirmed'
    listed=h.service.plans.list('alice','BTCUSD')[0]
    assert listed['target_mode']=='trend'
    assert listed['target_order_id'] is None
    assert stop==stop_before
    assert len(h.mutations())==count+1
    operations=h.service.plans.operations(h.service.plans.get('alice',before['id']))
    conversion=next(json.loads(row['payload']) for row in operations if row['kind']=='let_run_cancel_target')
    assert conversion['reviewed_target_size']==1


def test_staged_structural_plan_reduces_risk_before_fifteen_and_preserves_manual_trail(harness):
    h=harness
    trend_entry(h); h.filled(); h.manage(); h.manage()
    post_fill_history(h)
    h.profit_mark(110); plan_candles(h,103)
    result=h.manage()
    assert result['status']=='confirmed'
    listed=h.service.plans.list('alice','BTCUSD')[0]
    assert listed['peak_net_inr']<15
    assert listed['stop']==95.5
    assert h.mutations()[-1][0]=='PUT'
    assert h.mutations()[-1][2]['stop_price']=='95.5'
    # Public explicit manual trail still requires fees and profit coverage.
    with pytest.raises(Rejected): h.manage('trail',stop=96)


def test_staged_structural_plan_does_not_move_until_three_postfill_bars(harness):
    h=harness
    trend_entry(h); h.filled(); h.manage(); h.manage()
    h.profit_mark(500); plan_candles(h,480)
    count=len(h.mutations())
    result=h.manage()
    assert len(h.mutations())==count
    assert h.service.plans.list('alice','BTCUSD')[0]['stop']==95
    assert 'post-fill' in result['message'].lower()


def test_setup_identity_is_durable_in_plan_payload_and_listing(harness):
    h=harness
    h.entry(target_mode='trend',automation_generation='test',setup_id='sweep:123',setup_time=123)
    h.service.plans=ManagedPlans(h.service)
    listed=h.service.plans.list('alice','BTCUSD')[0]
    assert listed['setup_id']=='sweep:123'
    assert listed['setup_time']==123


def owned_trend(h,side):
    if side=='buy':
        trend_entry(h); h.filled()
    else:
        h.entry(side='sell',price=100.5,target_mode='trend',automation_generation='test',
                auto_protection=dict(stop=105,target=90,source_time=h.source,interval_seconds=60,reason='Short levels'))
        h.filled()
        h.client.size=-1; h.client.entry='100.5'
        row=fixtures.fill('short1','sell',1,-1,price='100.5',fee='.000023718')
        row['meta_data']['rack_commision']='.000023718'
        row['meta_data']['rack_commission_without_gst']='.0000201'
        row.update(order_id=h.parent['id'],created_at=str(int(time.time())-5))
        h.client.rows=[row]
    h.manage(); h.manage()
    listed=h.service.plans.list('alice','BTCUSD')[0]
    stop=next(row for row in h.client.orders if str(row['id'])==listed['stop_order_id'])
    return listed,stop


@pytest.mark.parametrize('side,new_stop,mark',[('buy',110,120),('sell',90,80)])
def test_exact_broker_manual_tightening_is_synced_and_survives_restart(harness,side,new_stop,mark):
    h=harness
    before,stop=owned_trend(h,side)
    stop['stop_price']=str(new_stop)
    h.profit_mark(mark)
    count=len(h.mutations())
    result=h.manage()
    assert result['status']=='confirmed'
    assert h.service.plans.list('alice','BTCUSD')[0]['stop']==new_stop
    h.service.plans=ManagedPlans(h.service)
    h.manage()
    assert h.service.plans.list('alice','BTCUSD')[0]['stop']==new_stop
    assert len(h.mutations())==count


@pytest.mark.parametrize('kind',['widen','quantity','foreign','cancelled','replaced'])
def test_external_stop_with_invalid_proof_is_visible_and_never_adopted(harness,kind):
    h=harness
    before,stop=owned_trend(h,'buy')
    h.profit_mark(120)
    stop['stop_price']='110'
    if kind=='widen': stop['stop_price']='94'
    if kind=='quantity': stop['size']=2
    if kind=='foreign': stop['client_order_id']='foreign'
    if kind=='cancelled': stop['state']='cancelled'
    if kind=='replaced':
        stop['state']='cancelled'
        h.client.orders.append(dict(stop,id=999,state='pending',client_order_id='foreign'))
    count=len(h.mutations())
    result=h.manage()
    assert result['status']=='rejected'
    assert result['plan_status']=='blocked'
    assert h.service.plans.list('alice','BTCUSD')[0]['stop']==before['stop']
    assert len(h.mutations())==count


def test_historical_trail_ack_cannot_erase_external_tightening_before_widen_check(harness):
    h=harness
    owned_trend(h,'buy')
    post_fill_history(h); h.profit_mark(500); plan_candles(h,480)
    h.manage()
    listed=h.service.plans.list('alice','BTCUSD')[0]
    assert listed['stop']==472.5
    stop=next(row for row in h.client.orders if str(row['id'])==listed['stop_order_id'])
    stop['stop_price']='480'
    count=len(h.mutations())
    assert h.manage()['status']=='confirmed'
    assert h.service.plans.list('alice','BTCUSD')[0]['stop']==480
    h.service.plans=ManagedPlans(h.service)
    # Still tighter than the historical automatic472.5, but wider than the
    # acknowledged external480: old operation replay must not legitimize it.
    stop['stop_price']='475'
    result=h.manage()
    assert result['status']=='rejected' and result['plan_status']=='blocked'
    assert h.service.plans.list('alice','BTCUSD')[0]['stop']==480
    assert len(h.mutations())==count


def test_final_owned_partial_fill_growth_resizes_stop_before_strict_manual_sync(harness):
    h=harness
    h.entry(size=2,target_mode='trend',automation_generation='test')
    h.parent.update(unfilled_size=1,state='open')
    h.client.size=1
    first=fixtures.fill('first','buy',1,1,price='99.5',when=str(int(time.time())-10))
    first['order_id']=h.parent['id'];h.client.rows=[first]
    h.manage()
    listed=h.service.plans.list('alice','BTCUSD')[0]
    stop=next(row for row in h.client.orders if str(row['id'])==listed['stop_order_id'])
    assert stop['size']==1
    h.parent.update(unfilled_size=0,state='closed');h.client.size=2
    second=fixtures.fill('second','buy',1,2,price='99.5',when=str(int(time.time())-5))
    second['order_id']=h.parent['id'];h.client.rows.append(second)
    count=len(h.mutations())
    result=h.manage()
    assert result['status']=='confirmed'
    assert stop['size']==2
    assert len(h.mutations())==count+1
    assert h.mutations()[-1][0]=='PUT'
    assert h.mutations()[-1][2]['stop_price']=='95'


def test_manual_quantity_shrink_is_not_mistaken_for_owned_fill_growth(harness):
    h=harness
    test_final_owned_partial_fill_growth_resizes_stop_before_strict_manual_sync(h)
    stop=next(row for row in h.client.orders if row.get('stop_order_type')=='stop_loss_order')
    stop['size']=1
    count=len(h.mutations())
    result=h.manage()
    assert result['status']=='rejected' and result['plan_status']=='blocked'
    assert len(h.mutations())==count


def adopted_trend(h):
    h.adopt()
    for _ in range(4): h.manage()
    assert h.service.plans.list('alice','BTCUSD')[0]['status']=='active'
    h.manage('let_run')
    assert h.service.plans.list('alice','BTCUSD')[0]['target_mode']=='trend'


def test_adopted_trend_uses_durable_observation_anchor_without_faking_first_fill(harness):
    from unittest.mock import patch
    h=harness
    adopted_trend(h)
    h.manage()
    before=h.service.plans.list('alice','BTCUSD')[0]
    assert before['first_fill_at'] is None
    assert before['trailing_observed_at'] is not None
    anchor=before['trailing_observed_at']
    h.service.plans=ManagedPlans(h.service)
    assert h.service.plans.list('alice','BTCUSD')[0]['trailing_observed_at']==anchor
    future=time.time()+600
    with patch('services.delta_chart.plans.time.time',return_value=future):
        h.profit_mark(500);plan_candles(h,480)
        result=h.manage(source_time=int(future)//60*60-60)
    assert result['status']=='confirmed'
    listed=h.service.plans.list('alice','BTCUSD')[0]
    assert listed['stop']==472.5
    assert listed['first_fill_at'] is None
    assert listed['trailing_observed_at']==anchor
    with h.service.store.db() as db:
        assert db.execute('SELECT 1 FROM delta_plan_fill_timing WHERE plan_id=?',(listed['id'],)).fetchone() is None


def test_adoption_cannot_create_trailing_observation_anchor_without_owned_live_sl(harness):
    h=harness
    adopted_trend(h)
    listed=h.service.plans.list('alice','BTCUSD')[0]
    stop=next(row for row in h.client.orders if str(row['id'])==listed['stop_order_id'])
    stop['state']='cancelled'
    h.manage()
    listed=h.service.plans.list('alice','BTCUSD')[0]
    assert listed['first_fill_at'] is None
    assert listed['trailing_observed_at'] is None
