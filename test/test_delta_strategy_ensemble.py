"""Offline deterministic fixtures, not evidence of live/source/backtest profitability."""
from decimal import Decimal as D

import pytest

from services.delta_chart import strategy_ensemble as ensemble
from test_delta_auto_strategy import NOW, candles, state, pullback_candles, pullback_state

SETTINGS = dict(leverage=50, balance_fraction=1)


def test_ema_baseline_survives_missing_other_timeframes():
    result = ensemble.decide(pullback_state(), {'1m': pullback_candles(), '5m': candles(300)}, SETTINGS, NOW, NOW)
    assert result['action']['side'] == 'buy'
    assert result['context']['strategy_id'] == 'ema'
    assert result['context']['ema9'] == pytest.approx(10065.28)
    assert result['context']['contributing_strategies'] == ['ema']
    assert all(not item['eligible'] for item in result['context']['candidates'] if item['strategy_id'] != 'ema')


def bars(seconds=300, count=70, now=NOW):
    end = (now // seconds - 1) * seconds
    return [dict(time=end-(count-1-i)*seconds, open=100, high=100.5, low=99.5, close=100)
            for i in range(count)]


def mirror(series, center=200):
    return [dict(time=b['time'], open=center-b['open'], high=center-b['low'],
                 low=center-b['high'], close=center-b['close']) for b in series]


def account(price, short=False):
    s = state()
    s['ticker'] = dict(bid=str(price-D('.5') if short else price),
                       ask=str(price if short else price+D('.5')), mark=str(price))
    return s


def evaluate(histories, price, short=False, settings=None, now=NOW):
    snapshot=account(D(str(price)), short);snapshot['asof']=now
    return ensemble.decide(snapshot, {k: v[::-1] for k, v in histories.items()},
                           settings or SETTINGS, now, now)


def eligible(result, name):
    return next(item for item in result['context']['candidates'] if item['strategy_id'] == name)


def range_fixture():
    series = bars()
    series[30]['high'] = 110
    for i in range(54, 69):
        close = 106-(i-54)
        series[i].update(open=close+.5, high=close+1, low=close-.5, close=close)
    series[68]['low'] = 90
    series[69].update(open=90.5, high=91.5, low=89.5, close=91)
    return series, D(91)


def breakout_fixture():
    series = bars()
    series[-2].update(open=100.5, high=102.5, low=100, close=102)
    series[-1].update(open=101, high=102, low=100.5, close=101.5)
    return series, D('101.5')


def double_fixture():
    series, price = breakout_fixture()
    series[50]['low'] = 96
    series[60]['low'] = 96.1
    series[65]['high'] = 104  # Prevent a separate 20-bar breakout while retaining the old neckline.
    return series, price


@pytest.mark.parametrize('factory,name,expected_stop', [
    (range_fixture, 'range_rsi', D(89)),
    (breakout_fixture, 'breakout_retest', D(100)),
    (double_fixture, 'double_extrema', D('95.5')),
])
@pytest.mark.parametrize('short', [False, True])
def test_five_minute_setups_require_completed_rejection_or_retest_and_keep_wick_stop(factory, name, expected_stop, short):
    series, price = factory()
    if short:
        series, price, expected_stop = mirror(series), 200-price, 200-expected_stop
    result = evaluate({'5m': series}, price, short)
    assert eligible(result, name)['eligible'], result
    action = result['action']
    assert action['strategy_id'] == name
    assert action['side'] == ('sell' if short else 'buy')
    assert D(str(action['auto_protection']['stop'])) == expected_stop
    assert action['auto_protection']['interval_seconds'] == 300
    assert action['auto_protection']['source_time'] == series[-1]['time']
    assert abs(D(str(action['auto_protection']['target']))-price) == 2*abs(price-expected_stop)


def daily_trend():
    series = bars(86400)
    series[40]['high'] = 105
    series[45]['low'] = 95
    series[50]['high'] = 110
    series[55]['low'] = 97
    return series


def liquidity_fixture():
    series = bars(3600)
    series[-2].update(open=100, high=100.5, low=98, close=100)
    series[-1].update(open=100, high=102.5, low=99.5, close=102)
    return series, bars(86400), D(102)


@pytest.mark.parametrize('short', [False, True])
def test_hourly_previous_day_sweep_needs_next_candle_and_emits_daily_reservation_metadata(short):
    hourly, daily, price = liquidity_fixture()
    if short:
        hourly, daily, price = mirror(hourly), mirror(daily), 200-price
    result = evaluate({'1h': hourly, '1d': daily}, price, short)
    assert result['action']['strategy_id'] == 'liquidity_sweep', result
    assert result['action']['daily_key'] == '2027-01-15:' + ('sell' if short else 'buy')
    assert result['action']['auto_protection']['stop'] == (102.5 if short else 97.5)
    assert result['action']['auto_protection']['interval_seconds'] == 3600


def fvg_fixture():
    series = bars(900)
    series[56].update(open=99, high=100, low=97, close=99)
    series[59].update(open=101, high=103, low=100, close=101)
    series[63].update(open=98, high=99, low=96, close=98)
    series[64].update(open=100, high=104.5, low=99, close=104)
    series[65].update(open=103, high=104.5, low=102.5, close=104)
    series[66].update(open=104, high=106.5, low=103.5, close=106)
    series[67].update(open=106, high=107, low=105, close=106)
    for i in (68, 69):
        series[i].update(open=106.5, high=107, low=106, close=106.5)
    # Future OHLC is deliberately invalid: ONLY a known forming open is relevant.
    opening = [dict(time=NOW//14400*14400, open=110, high='future', low=None, close='NaN')]
    return series, daily_trend(), opening, D(105)


@pytest.mark.parametrize('short', [False, True])
def test_fvg_requires_daily_pivots_known_4h_open_sweep_mss_and_current_quote_in_gap(short):
    series, daily, opening, price = fvg_fixture()
    if short:
        series, daily, price = mirror(series), mirror(daily), 200-price
        opening[0]['open'] = 90
    result = evaluate({'15m': series, '1d': daily, '4h': opening}, price, short)
    assert result['action']['strategy_id'] == 'fvg', result
    assert result['action']['auto_protection']['stop'] == (104.5 if short else 95.5)
    assert result['action']['auto_protection']['interval_seconds'] == 900


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('anchors', ['automatic', 'explicit_prices', 'explicit_times'])
def test_ema_fib_derives_only_confirmed_opposite_swings_and_reaction_zone(short, anchors):
    fast, slow = list(reversed(candles())), list(reversed(candles(300)))
    fast[58]['low'] = '10043'
    fast[64]['high'] = '10080'
    fast[-1].update(open='10065', high='10074', low='10059', close='10069')
    # Float conversion is confined to offline fixture mirroring.
    fast = [{k: float(v) if k != 'time' else v for k, v in b.items()} for b in fast]
    slow = [{k: float(v) if k != 'time' else v for k, v in b.items()} for b in slow]
    price = D(10069)
    if short:
        fast, slow, price = mirror(fast, 20000), mirror(slow, 20000), 20000-price
    settings = dict(SETTINGS)
    if anchors != 'automatic':
        settings['fib_anchors'] = dict(low=9920 if short else 10043, high=9957 if short else 10080,
                                       direction='down' if short else 'up')
        if anchors == 'explicit_times':
            settings['fib_anchors'].update(low_time=fast[64 if short else 58]['time'],
                                            high_time=fast[58 if short else 64]['time'])
    result = evaluate({'1m': fast, '5m': slow}, price, short, settings)
    assert eligible(result, 'ema_fib')['eligible'], result
    assert result['action']['strategy_id'] == 'ema_fib'  # Regime-only EMA no longer qualifies without a fresh continuation.
    assert 'ema_fib' in result['context']['contributing_strategies']


def test_opposite_eligible_setups_wait_with_visible_conflict_instead_of_selecting_priority_winner(monkeypatch):
    fast=list(reversed(pullback_candles()));slow=list(reversed(candles(300)))
    candidate=ensemble._setup('range_rsi',False,[{k:D(str(v)) if k!='time' else v for k,v in b.items()}for b in slow],D('10085'),300)
    monkeypatch.setattr(ensemble,'_range',lambda *args:[candidate])
    result=evaluate({'1m':fast,'5m':slow},D('10072'))
    assert eligible(result,'ema')['eligible']
    assert eligible(result,'range_rsi')['eligible']
    assert result['action'] is None
    assert 'disagree' in result['reason']
    assert 'Conflicting' in result['context']['trend_summary']


@pytest.mark.parametrize('factory,name', [(breakout_fixture, 'breakout_retest'), (double_fixture, 'double_extrema')])
def test_quote_back_below_reclaimed_level_cannot_authorize_a_long(factory, name):
    series, _ = factory()
    result = evaluate({'5m': series}, 100.5)
    assert not eligible(result, name)['eligible']
    assert result['action'] is None


def test_double_bottom_invalidated_before_neckline_confirmation_is_not_reused():
    series, price = double_fixture()
    series[65]['low'] = 95
    result = evaluate({'5m': series}, price)
    assert not eligible(result, 'double_extrema')['eligible']


@pytest.mark.parametrize('kind', ['no_trend', 'mitigated', 'expired', 'no_open', 'wrong_side', 'unconfirmed_mss', 'forming_third', 'gap'])
def test_fvg_does_not_invent_confirmations_or_reuse_expired_mitigated_gap(kind):
    series, daily, opening, price = fvg_fixture()
    if kind == 'no_trend': daily = bars(86400)
    if kind == 'mitigated': series[-1]['low'] = 104.5
    if kind == 'expired':
        # Shift the entire setup three bars back, keeping contiguous recent data.
        for i in range(53, 67): series[i] = dict(series[i+3], time=series[i]['time'])
        for i in range(67, 70): series[i].update(open=106.5, high=107, low=106, close=106.5)
    if kind == 'no_open': opening = []
    if kind == 'wrong_side': opening[0]['open'] = 104
    if kind == 'unconfirmed_mss':
        series[64].update(close=102, high=102.5)
        series[65]['close'] = 102
    if kind == 'forming_third':
        # A tempting future gap cannot replace the actual unconfirmed setup.
        series[67]['low'] = 104
        series.append(dict(time=NOW//900*900, open=106, high=110, low=105, close=109))
    if kind == 'gap': del series[61]
    result = evaluate({'15m': series, '1d': daily, '4h': opening}, price)
    assert not eligible(result, 'fvg')['eligible'], result
    assert result['action'] is None


@pytest.mark.parametrize('kind', ['red_confirm', 'no_break_sweep', 'same_candle', 'outside_session'])
def test_liquidity_confirmation_is_sequential_directional_and_session_bounded(kind):
    hourly, daily, price = liquidity_fixture()
    if kind == 'red_confirm': hourly[-1]['open'] = 102.5
    if kind == 'no_break_sweep': hourly[-1]['close'] = 100.5; price = D('100.5')
    if kind == 'same_candle': hourly[-2]['low'] = 99.5; hourly[-1]['low'] = 98
    now = NOW
    if kind == 'outside_session':
        delta = 12*3600
        now += delta
        hourly = [dict(b, time=b['time']+delta) for b in hourly]
        # Current UTC day has not changed, so the daily evidence is identical.
    result = evaluate({'1h': hourly, '1d': daily}, price, now=now)
    assert not eligible(result, 'liquidity_sweep')['eligible']


@pytest.mark.parametrize('kind', ['tiny_balance', 'manual_risk', 'missing_fees', 'huge_fee', 'off_tick', 'crossed', 'wick_breached'])
def test_standard_fee_margin_tick_and_true_wick_risk_checks_fail_closed(kind):
    series, price = range_fixture()
    s = account(price)
    settings = dict(SETTINGS)
    if kind == 'tiny_balance': s['sizing']['available_balance'] = '.00001'
    if kind == 'manual_risk': settings.update(balance_fraction=None, manual_quantity=10000)
    if kind == 'missing_fees': del s['sizing']['taker_fee_rate']
    if kind == 'huge_fee': s['sizing']['taker_fee_rate'] = '.5'
    if kind == 'off_tick': s['ticker']['bid'] = '91.01'
    if kind == 'crossed': s['ticker']['ask'] = '90.5'
    if kind == 'wick_breached': s['ticker'].update(bid='89', ask='89.5', mark='89')
    result = ensemble.decide(s, {'5m': series[::-1]}, settings, NOW, NOW)
    assert result['action'] is None


def test_stop_is_never_clipped_to_allow_one_unaffordable_contract():
    series, price = double_fixture()
    s = account(price)
    s['product']['contract_value'] = '1'
    result = ensemble.decide(s, {'5m': series[::-1]}, SETTINGS, NOW, NOW)
    assert result['action'] is None
    assert 'risk cap' in eligible(result, 'double_extrema')['reason']


def test_fully_formed_range_signal_disappears_if_only_rejection_bar_is_forming():
    series, price = range_fixture()
    series[-1]['time'] += 300
    result = evaluate({'5m': series}, price)
    assert result['action'] is None


def test_context_and_actions_remain_json_safe_and_inputs_unchanged():
    import copy
    import json
    series, price = range_fixture()
    histories = {'5m': series[::-1]}
    s = account(price)
    before = copy.deepcopy((s, histories, SETTINGS))
    result = ensemble.decide(s, histories, SETTINGS, NOW, NOW)
    assert before == (s, histories, SETTINGS)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('settings', [None, [], 'invalid'])
def test_malformed_settings_cannot_escape_fail_closed_result(settings):
    result = ensemble.decide(state(), {'1m': candles(), '5m': candles(300)}, settings, NOW, NOW)
    assert result['action'] is None


def test_context_records_structural_evidence_for_inspectable_memory():
    series, price = range_fixture()
    result = evaluate({'5m': series}, price)
    proof = eligible(result, 'range_rsi')['evidence']
    assert proof['wick'] == 89.5
    assert proof['entry_floor'] == 90.5
    assert result['context']['patterns'][-1]['name'] == 'range_rsi'
    assert result['context']['patterns'][-1]['direction'] == 'up'


def test_conservative_fee_aware_whole_lot_sizing_and_margin_boundary():
    series, price = range_fixture()
    result = evaluate({'5m': series}, price)
    assert result['action']['size'] == 113  # INR20 / (2 + .073986 fees) / .001 / 85.
    for available, funded in [('.001870', False), ('.001871', True)]:
        s = account(price)
        s['sizing']['available_balance'] = available
        result = ensemble.decide(s, {'5m': series[::-1]}, SETTINGS, NOW, NOW)
        assert bool(result['action']) is funded  # max quote 91.5, exact .99 balance headroom.
        if funded:
            assert result['action']['size'] == 1


@pytest.mark.parametrize('kind', ['stale', 'future', 'account_order', 'position', 'invalid_leverage'])
def test_execution_and_observation_guards_apply_to_non_ema_setups(kind):
    series, price = range_fixture()
    s, settings, observed = account(price), dict(SETTINGS), NOW
    if kind == 'stale': observed -= 31
    if kind == 'future': observed += 1
    if kind == 'account_order': s['orders'] = [{'id': 'another-order'}]
    if kind == 'position': s['position'] = {'size': 1}
    if kind == 'invalid_leverage': settings['leverage'] = 201
    assert ensemble.decide(s, {'5m': series[::-1]}, settings, observed, NOW)['action'] is None


@pytest.mark.parametrize('kind', ['late_retest', 'forming_break', 'unclosed_return'])
def test_breakout_requires_ordered_closed_break_then_timely_retest(kind):
    series, price = breakout_fixture()
    if kind == 'late_retest':
        series[-6] = dict(series[-2], time=series[-6]['time'])
        for i in range(65, 69): series[i].update(open=102, high=103, low=101.5, close=102)
    if kind == 'forming_break':
        series[-2].update(close=100, high=100.5, open=100)
        series.append(dict(time=NOW//300*300, open=100, high=103, low=99.5, close=102))
    if kind == 'unclosed_return': series[-1]['close'] = 100
    result = evaluate({'5m': series}, price)
    assert not eligible(result, 'breakout_retest')['eligible']


def test_fibonacci_no_confirmed_swings_does_not_invent_anchors():
    result = ensemble.decide(state(), {'1m': candles(), '5m': candles(300)}, SETTINGS, NOW, NOW)
    assert not eligible(result, 'ema_fib')['eligible']
    assert result['action'] is None  # Neither invented anchors nor an untriggered EMA regime authorizes entry.


def test_missing_higher_timeframes_do_not_block_valid_five_minute_strategy():
    series, price = range_fixture()
    result = evaluate({'5m': series}, price)
    assert result['action']['strategy_id'] == 'range_rsi'
    assert not eligible(result, 'liquidity_sweep')['eligible']
    assert not eligible(result, 'fvg')['eligible']


def test_selected_reversal_preserves_independent_baseline_ema_direction_for_exit_coordination():
    series, price = range_fixture()
    fast = bars(60)
    for i, b in enumerate(fast):
        close = 96-i*.1
        b.update(open=close+.05, high=close+.5, low=close-.5, close=close)
    # EMA short quote is far from its 1m close, while the completed range rejection is valid.
    result = evaluate({'1m': fast, '5m': series}, price)
    assert result['action']['strategy_id'] == 'range_rsi'
    assert result['context']['direction'] == 'up'
    assert result['context']['ema_direction'] == 'down'
    assert result['context']['higher_ema_direction'] == 'down'


def test_extreme_structural_reference_target_cannot_emit_infinite_json_numbers():
    s = account(D('1e308'))
    s['product'].update(tick_size='1e305', contract_value='1e-309')
    s['ticker'].update(ask='1.001e308')
    candidate = dict(side='buy', strategy_id='range_rsi', wick=D('1e307'), atr=D('1e308'),
                     latest=dict(close=D('1e308')), source_time=NOW//300*300-300, interval_seconds=300)
    with pytest.raises(ensemble.InvalidEvidence):
        ensemble._action(s, SETTINGS, candidate)


@pytest.mark.parametrize('short', [False, True])
def test_liquidity_next_confirmation_cannot_breach_the_original_sweep_wick(short):
    hourly, daily, price = liquidity_fixture()
    hourly[-1]['low'] = 97  # Original sweep invalidates at 98 before confirmation closes.
    if short:
        hourly, daily, price = mirror(hourly), mirror(daily), 200-price
    result = evaluate({'1h': hourly, '1d': daily}, price, short)
    assert not eligible(result, 'liquidity_sweep')['eligible']
    assert result['action'] is None


@pytest.mark.parametrize('short', [False, True])
def test_double_extrema_cannot_skip_a_more_extreme_intervening_wick(short):
    series, price = double_fixture()
    series[55]['low'] = 94  # A deeper low invalidates the selected equal 96/96.1 pair.
    if short:
        series, price = mirror(series), 200-price
    result = evaluate({'5m': series}, price, short)
    assert not eligible(result, 'double_extrema')['eligible']
    assert result['action'] is None


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('explicit', [False, True, 'timestamped'])
def test_fibonacci_rejects_any_post_impulse_anchor_breach_before_latest_reaction(short, explicit):
    fast, slow = list(reversed(candles())), list(reversed(candles(300)))
    fast[58]['low'] = '10043'
    fast[64]['high'] = '10080'
    fast[-2].update(open='10060', high='10073', low='10040', close='10065')
    fast[-1].update(open='10065', high='10074', low='10059', close='10069')
    fast = [{k: float(v) if k != 'time' else v for k, v in b.items()} for b in fast]
    slow = [{k: float(v) if k != 'time' else v for k, v in b.items()} for b in slow]
    settings, price = dict(SETTINGS), D(10069)
    if short:
        fast, slow, price = mirror(fast, 20000), mirror(slow, 20000), 20000-price
    if explicit:
        settings['fib_anchors'] = dict(low=9920 if short else 10043, high=9957 if short else 10080,
                                       direction='down' if short else 'up')
    if explicit == 'timestamped':
        settings['fib_anchors'].update(low_time=fast[64 if short else 58]['time'],
                                        high_time=fast[58 if short else 64]['time'])
    result = evaluate({'1m': fast, '5m': slow}, price, short, settings)
    assert not eligible(result, 'ema_fib')['eligible']
