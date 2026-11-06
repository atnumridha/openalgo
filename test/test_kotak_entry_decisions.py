import math
import pytest
from services.kotak_assistant.entry_decisions import (
    breakout_retest, retest_signals, research_features, premium_plan,
    initial_daily_state, advance_daily, daily_result,
)


def bars(n=280):
    return [dict(time=1792467900+i*300,open=100+i*.1,high=102+i*.1,low=99+i*.1,close=101+i*.1) for i in range(n)]


def test_features_and_retest_signals_match_frozen_research_rules():
    import json
    from pathlib import Path
    vector=json.loads((Path(__file__).parent/'fixtures/entry_decisions/retest-vectors.json').read_text())
    data=vector['bars'];actual=research_features(data)
    for key,expected in vector['features'].items():
        for a,e in zip(actual[key],expected):
            assert a is None and e is None or a==pytest.approx(e)
    wanted=[tuple(x) for x in vector['signals']]
    assert wanted
    assert [(s['signal_candle']['closed_at'],1 if s['direction']=='CE' else -1) for s in retest_signals(data)]==wanted
    cut=700
    assert retest_signals(data[:cut])==[s for s in retest_signals(data) if s['signal_candle']['closed_at']<=data[cut-1]['time']+300]


def test_retest_waits_for_completed_history_and_does_not_recommend_old_entries():
    now=bars()[-1]['time']+300
    assert breakout_retest(bars(100),now)['stage']=='waiting_history'
    assert breakout_retest([],now)['eligible'] is False


def test_daily_requires_fresh_cross_and_later_observed_break():
    start=1792467900;ref=dict(high=22590,low=22500,time=start-86400)
    state=initial_daily_state('day',start,ref)
    candle=dict(time=start,open=22615,high=22620,low=22608,close=22610)
    # Initial outside quote does not backfill a historical crossing.
    state=advance_daily(state,[],{'time':start+1,'price':22610,'source':'websocket','id':'1'},start+1,'day',start,ref)
    assert state['directions']['PE']['stage']=='waiting_break'
    for event in [dict(time=start+2,price=22589,id='2'),dict(time=start+3,price=22615,id='3')]:
        state=advance_daily(state,[],dict(event,source='websocket'),event['time'],'day',start,ref)
    state=advance_daily(state,[candle],None,start+60,'day',start,ref)
    assert state['directions']['PE']['trigger']==22608
    event=dict(time=start+61,price=22607.95,id='4',source='websocket')
    state=advance_daily(state,[candle],event,event['time'],'day',start,ref)
    result=daily_result(state,event['time'])
    assert result['directions']['PE']['eligible'] is True
    assert result['directions']['PE']['trigger']==22608
    assert daily_result(state,start+122)['directions']['PE']['eligible'] is False
    assert state['directions']['PE']['consumed']


def test_missing_daily_reference_is_not_replaced_with_an_old_or_invented_level():
    state=initial_daily_state('day',1000,None)
    assert daily_result(state,1010)['eligible'] is False
    assert 'previous' in daily_result(state,1010)['reason'].lower()


@pytest.mark.parametrize('quantity',[65,130])
def test_premium_plan_is_atr_based_and_target_is_net_two_r_after_costs(quantity):
    candles=[dict(time=i*60,open=100,high=101,low=99,close=100) for i in range(20)]
    p=premium_plan(100.03,candles,quantity,.05,65,'NFO',{'brokerage':10,'slippage':.1},2,'2026-10-23')
    assert p['entry']==100.05 and p['sl']==97.05
    assert p['net_rr']>=2 and p['risk']<=1000
    assert p['quantity']==quantity
    assert p['fee_breakdown']['brokerage']==20
    assert p['target']/.05==pytest.approx(round(p['target']/.05))
    assert p['source']=='Fresh ask · 1.5 × option ATR14 · net 2R target'


def test_premium_plan_refuses_gaps_and_excess_total_position_risk():
    candles=[dict(time=i*60,open=100,high=110,low=90,close=100) for i in range(20)]
    assert not premium_plan(100,candles,650,.05,65,'NFO',{},2,'2026-10-23')['fits']
    candles.pop(10)
    assert 'contiguous' in premium_plan(100,candles,65,.05,65,'NFO',{},2,'2026-10-23')['reason']


@pytest.mark.parametrize('ask,quantity,half_range',[(1000,65,1),(100,650,.05)])
def test_target_solver_brackets_large_charges_and_slippage(ask,quantity,half_range):
    candles=[dict(time=i*60,open=ask,high=ask+half_range,low=ask-half_range,close=ask,volume=100) for i in range(20)]
    p=premium_plan(ask,candles,quantity,.05,65,'NFO',{'brokerage':10,'slippage':.1},2,'2026-10-23')
    assert p['fits'] and p['net_rr']>=2


def test_option_warmup_explains_progress_without_manufacturing_prices():
 candles=[dict(time=i*60,open=100,high=101,low=99,close=100,volume=100) for i in range(7)]
 p=premium_plan(100,candles,65,.05,65,'NFO',{},2,'2026-10-23')
 assert not p['fits'] and '7 / 15' in p['reason']
 assert 'entry' not in p


def test_one_lot_over_budget_has_an_actionable_reason_and_keeps_the_calculated_prices():
 candles=[dict(time=i*60,open=100,high=110,low=90,close=100,volume=100) for i in range(20)]
 p=premium_plan(100,candles,65,.05,65,'NFO',{'brokerage':10,'slippage':.1},2,'2026-10-23')
 assert not p['fits'] and p['risk']>1000 and 0<p['sl']<p['entry']<p['target']
 assert '1 lot' in p['reason'] and 'another contract' in p['reason']
