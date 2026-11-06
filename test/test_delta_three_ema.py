"""Prospective deterministic signal fixtures; no profitability claims."""
from decimal import Decimal as D

import pytest

from services.delta_chart import three_ema
from services.delta_chart import strategy_ensemble as ensemble
from test_delta_strategy_ensemble import bars, mirror, evaluate, eligible, SETTINGS, account
from test_delta_auto_strategy import NOW


def fixture(short=False):
    fast = bars(60)
    for i, bar in enumerate(fast):
        close = 110-i*.2 if i < 60 else 98+(i-59)*2
        bar.update(open=close-.4, high=close+.5, low=close-.5, close=close)
    higher = bars(300)
    for i, bar in enumerate(higher):
        close = 80+i*.3
        bar.update(open=close-.1, high=close+.5, low=close-.5, close=close)
    if short:
        fast, higher = mirror(fast, 300), mirror(higher, 300)
    return fast, higher


def decimals(series):
    return [{k: v if k == 'time' else D(str(v)) for k, v in bar.items()} for bar in series]


def first_signal(short=False):
    fast, higher = fixture(short)
    for end in range(55, len(fast)+1):
        found = three_ema.detect(decimals(fast[:end]), decimals(higher))
        if found:
            return fast[:end], higher, found[0]
    pytest.fail('fixture must contain a first qualifying transition')


@pytest.mark.parametrize('short', [False, True])
def test_first_qualifying_alignment_has_original_transition_identity_and_no_repeats(short):
    fast, higher, signal = first_signal(short)
    assert signal['side'] == ('sell' if short else 'buy')
    assert signal['source_time'] == fast[-1]['time']
    assert signal['setup_time'] <= signal['source_time']
    full, _ = fixture(short)
    assert len(fast) < len(full)
    for end in range(len(fast)+1, len(full)+1):
        assert three_ema.detect(decimals(full[:end]), decimals(higher)) == []
    assert three_ema.detect(decimals(fast), decimals(higher))[0] == signal  # deterministic restart


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('kind', ['flat', 'old_regime', 'wrong_filter', 'wrong_close', 'huge_atr'])
def test_unqualified_data_cannot_create_a_signal(short, kind):
    fast, higher, _ = first_signal(short)
    if kind == 'flat':
        fast = bars(60)
    if kind == 'old_regime':
        fast = [dict(b, open=80+i*.3-.1, high=80+i*.3+.5, low=80+i*.3-.5, close=80+i*.3)
                for i, b in enumerate(bars(60))]
        if short: fast = mirror(fast, 300)
    if kind == 'wrong_filter': higher = mirror(higher, 300)
    if kind == 'wrong_close':
        fast[-1]['close'] += 10 if short else -10
        fast[-1]['high'] = max(fast[-1]['high'], fast[-1]['close'])
        fast[-1]['low'] = min(fast[-1]['low'], fast[-1]['close'])
    if kind == 'huge_atr':
        for b in fast: b.update(high=400, low=1)
    assert three_ema.detect(decimals(fast), decimals(higher)) == []


@pytest.mark.parametrize('short', [False, True])
def test_ensemble_additional_strategy_uses_shared_risk_and_independent_diagnostics(short):
    fast, higher, signal = first_signal(short)
    delta = NOW//60*60-60-fast[-1]['time']
    fast = [dict(b, time=b['time']+delta) for b in fast]
    price = D(str(fast[-1]['close'])).quantize(D('1'))
    result = evaluate({'1m': fast, '5m': higher}, price, short)
    assert eligible(result, 'ema_three')['eligible'], result
    action = result['action']
    assert action['strategy_id'] == 'ema_three'
    assert action['strategy_version'] == 3
    assert action['setup_time'] == signal['setup_time']+delta
    assert action['auto_protection']['source_time'] == fast[-1]['time']
    stop = D(str(action['auto_protection']['stop']))
    assert stop > signal['wick'] if short else stop < signal['wick']
    risk = abs(price-stop)
    fees = (price*D('.0002')+stop*D('.0005'))*D('1.18')
    assert (risk+fees)*D('.001')*85*action['size'] <= 20
    assert ensemble.VERSION == 3


@pytest.mark.parametrize('kind', ['forming', 'stale', 'future', 'gap', 'exposure', 'fees', 'unaffordable'])
def test_shared_execution_gates_cannot_be_bypassed(kind):
    fast, higher, _ = first_signal()
    delta = NOW//60*60-60-fast[-1]['time']
    fast = [dict(b, time=b['time']+delta) for b in fast]
    price = D(str(fast[-1]['close'])).quantize(D('1'))
    snapshot, observed = account(price), NOW
    if kind == 'forming': fast[-1]['time'] += 60
    if kind == 'stale': observed -= 31
    if kind == 'future': observed += 1
    if kind == 'gap': del fast[-3]
    if kind == 'exposure': snapshot['position'] = {'size': 1}
    if kind == 'fees': del snapshot['sizing']['taker_fee_rate']
    if kind == 'unaffordable': snapshot['product']['contract_value'] = '100'
    result = ensemble.decide(snapshot, {'1m': fast[::-1], '5m': higher[::-1]}, SETTINGS, observed, NOW)
    assert result['action'] is None


def controlled_readings(monkeypatch, count=67, bad_slope=None, gap_scale=1):
    fast, higher = decimals(bars(60, count=count)), decimals(bars(300))
    for b in fast:
        b['open'] = D('99.5')
    values = {p: {b['time']: D(97) for b in fast} for p in ('9', '15', '21')}
    for i in range(65, count):
        for p, rate in [('9', '.2'), ('15', '.1'), ('21', '.05')]:
            values[p][fast[i]['time']] = D(97)+D(rate)*(i-64)*D(str(gap_scale))
    if bad_slope:
        values[bad_slope][fast[-4]['time']] = D(99)
    # Deliberately9>15 but21>9: the5m filter is solely the approved9/15 direction.
    hvalues = {p: {b['time']: D(v) for b in higher}
               for p, v in [('9', 102), ('15', 101), ('21', 105)]}
    monkeypatch.setattr(three_ema, '_series', lambda series: values if series is fast else hvalues)
    return fast, higher


def test_gap_improves_after_transition_but_identity_remains_original_alignment(monkeypatch):
    fast, higher = controlled_readings(monkeypatch)
    found = three_ema.detect(fast, higher)
    assert found and found[0]['setup_time'] == fast[65]['time']
    assert found[0]['source_time'] == fast[66]['time']
    fast, higher = controlled_readings(monkeypatch, count=70)
    assert three_ema.detect(fast, higher) == []


@pytest.mark.parametrize('period', ['9', '15', '21'])
def test_every_average_requires_supporting_three_bar_slope(monkeypatch, period):
    fast, higher = controlled_readings(monkeypatch, bad_slope=period)
    assert three_ema.detect(fast, higher) == []


def test_strict_ordering_without_both_minimum_gaps_cannot_signal(monkeypatch):
    fast, higher = controlled_readings(monkeypatch, gap_scale=.5)
    assert three_ema.detect(fast, higher) == []

@pytest.mark.parametrize('short', [False, True])
def test_three_ema_stop_keeps_inherited_three_tick_minimum_when_atr_is_tiny(short):
    price = D('100')
    candidate = dict(strategy_id='ema_three', side='sell' if short else 'buy',
        wick=D('100.1') if short else D('99.9'), atr=D('.2'), latest=dict(close=price),
        setup_time=60, source_time=120, interval_seconds=60)
    action = ensemble._action(account(price, short), SETTINGS, candidate)
    assert abs(D(str(action['auto_protection']['stop']))-D(str(action['price']))) >= D('1.5')


def test_waiting_status_mentions_additional_three_ema_setup():
    result = evaluate({'1m': bars(60), '5m': bars(300)}, D('100'))
    assert result['action'] is None
    assert 'EMA9/15/21' in result['reason']

@pytest.mark.parametrize('short', [False, True])
def test_signal_candle_color_is_optional_when_close_is_beyond_all_three(short):
    fast, higher, _ = first_signal(short)
    fast[-1]['open'] = fast[-1]['close'] + (D('-.2') if short else D('.2'))
    assert three_ema.detect(decimals(fast), decimals(higher))
