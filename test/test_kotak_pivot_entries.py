import importlib
import importlib.util
import pytest


def engine():
    assert importlib.util.find_spec('services.kotak_assistant.pivot_entries') is not None, 'Pivot entry evaluator not implemented'
    return importlib.import_module('services.kotak_assistant.pivot_entries')


def bars(price):
    return [dict(time=i*60,open=price,high=price+.1,low=price-.1,close=price) for i in range(20)]


def test_standard_pivots_pin_supplied_example_and_reject_bad_daily_close():
    e=engine();p=e.standard_pivots(dict(high=23120.90,low=22649.90,close=22811.35))
    assert p['P']==pytest.approx(22860.7166666667)
    assert p['R1']==pytest.approx(23071.5333333333)
    assert p['S1']==pytest.approx(22600.5333333333)
    assert p['R2']==pytest.approx(23331.7166666667)
    assert p['S2']==pytest.approx(22389.7166666667)
    assert p['R3']==pytest.approx(23542.5333333333)
    assert p['S3']==pytest.approx(22129.5333333333)
    for previous in [None,dict(high=110,low=90),dict(high=110,low=90,close=120),dict(high=float('inf'),low=90,close=100)]:
        assert e.standard_pivots(previous) is None


@pytest.mark.parametrize('side,price,signal,confirm,level,stop',[
 ('CE',90.5,(90.4,91,89.8,90.8),(90.8,91.5,90.7,91.4),'S1',89.8),
 ('PE',109.5,(109.6,110.2,109,109.2),(109.2,109.3,108.5,108.6),'R1',110.2),
])
def test_rejection_requires_completed_confirmation_and_pins_both_directions(side,price,signal,confirm,level,stop):
    e=engine();b=bars(price)
    for t,v in [(1200,signal),(1260,confirm)]:b.append(dict(time=t,**dict(zip(('open','high','low','close'),v))))
    previous=dict(high=110,low=90,close=100)
    watch=e.pivot_setups(b,previous,0,1260,2)['pivot_rejection']['directions'][side]
    assert watch['stage']=='waiting_trigger' and not watch['eligible']
    ready=e.pivot_setups(b,previous,0,1320,2)['pivot_rejection']['directions'][side]
    assert ready['eligible'] and ready['stage']=='ready' and ready['reference']['name']==level
    assert ready['index_entry']==confirm[3] and ready['expires']==1380
    assert ready['index_target']==100
    assert ready['invalidation']<stop if side=='CE' else ready['invalidation']>stop
    expired=e.pivot_setups(b,previous,0,1380,2)['pivot_rejection']['directions'][side]
    assert not expired['eligible']
    assert ready==e.pivot_setups(b+[dict(time=1380,open=20,high=300,low=1,close=200)],previous,0,1320,2)['pivot_rejection']['directions'][side]


def test_touch_doji_equality_and_gap_are_not_confirmations():
    e=engine();prev=dict(high=110,low=90,close=100);b=bars(90.5)
    b += [dict(time=1200,open=90.4,high=91,low=89.8,close=90.8),dict(time=1260,open=90.8,high=91.3,low=90.7,close=91)]
    assert not e.pivot_setups(b,prev,0,1320,2)['pivot_rejection']['directions']['CE']['eligible']
    b[20]['close']=b[20]['open']
    b[21]['close']=91.2
    assert not e.pivot_setups(b,prev,0,1320,2)['pivot_rejection']['directions']['CE']['eligible']
    b[20]['close']=90.8;b[21]['time']=1380
    assert not e.pivot_setups(b,prev,0,1440,2)['pivot_rejection']['directions']['CE']['eligible']


def test_pivot_breakout_waits_for_later_retest_and_requires_target_room():
    e=engine();prev=dict(high=110,low=90,close=100);b=bars(99.5)
    b += [dict(time=1200,open=99.5,high=100.8,low=99.4,close=100.6),dict(time=1260,open=100.2,high=100.8,low=100,close=100.7)]
    watch=e.pivot_setups(b,prev,0,1260,2)['pivot_retest']['directions']['CE']
    assert not watch['eligible'] and watch['stage']=='waiting_retest'
    ready=e.pivot_setups(b,prev,0,1320,2)['pivot_retest']['directions']['CE']
    assert ready['eligible'] and ready['reference']['name']=='P' and ready['index_target']==110
    b[21].update(high=109.5,close=109)
    rejected=e.pivot_setups(b,prev,0,1320,2)['pivot_retest']['directions']['CE']
    assert not rejected['eligible'] and 'room' in rejected['reason'].lower()


def test_missing_previous_daily_does_not_use_current_session_extremes():
    e=engine();r=e.pivot_setups(bars(100),None,0,1200,2)
    assert all(not x['eligible'] and x['stage']=='waiting_reference' for x in r.values())


def test_repaired_signal_is_not_used_as_pivot_evidence():
    e=engine();b=bars(90.5)
    b += [dict(time=1200,open=90.4,high=91,low=89.8,close=90.8,repaired=True),dict(time=1260,open=90.8,high=91.5,low=90.7,close=91.4)]
    assert not e.pivot_setups(b,dict(high=110,low=90,close=100),0,1320,2)['pivot_rejection']['directions']['CE']['eligible']


@pytest.mark.parametrize('side,price,stage', [('CE',89,'blocked'),('CE',105,'missed'),('CE',95,'missed'),('PE',111,'blocked'),('PE',95,'missed')])
def test_observed_pivot_breach_or_insufficient_remaining_room_cannot_stay_ready(side,price,stage):
    e=engine()
    assert hasattr(e,'observe_pivot'), 'Observed pivot readiness checks not implemented'
    signal=dict(stage='ready',eligible=True,direction=side,confirmed_at=1320,expires=1380,index_entry=91.4 if side=='CE' else 108.6,invalidation=89.7 if side=='CE' else 110.3,index_target=100)
    result=e.observe_pivot(signal,[dict(time=1321,price=price)],2,1322)
    assert not result['eligible'] and result['stage']==stage
    assert signal['eligible']


def test_observation_before_confirmation_cannot_invalidate_a_pivot_entry():
    e=engine();assert hasattr(e,'observe_pivot')
    signal=dict(stage='ready',eligible=True,direction='CE',confirmed_at=1320,expires=1380,index_entry=91.4,invalidation=89.7,index_target=100)
    assert e.observe_pivot(signal,[dict(time=1319,price=80)],2,1322)['eligible']
