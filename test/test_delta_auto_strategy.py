"""Pure offline strategy fixtures: catches unsafe evidence, risk and sizing changes."""
import copy
import json
from decimal import Decimal

import pytest

from services.delta_chart import auto_strategy

NOW = 1800000305


def candles(seconds=60, side=1, count=70):
    end = (NOW // seconds - 1) * seconds
    bars = []
    for i in range(count):
        close = Decimal('10000') + side * Decimal(i)
        bars.append(dict(time=end - (count - 1 - i) * seconds,
                         open=str(close - side * Decimal('.2')), high=str(close + 5),
                         low=str(close - 5), close=str(close)))
    return bars[::-1]


def state(side=1):
    price = 10000 + side * 69
    return dict(connected=True, asof=NOW, product=dict(tick_size='.5', contract_value='.001', max_leverage=100),
                ticker=dict(bid=str(price), ask=str(price + .5), mark=str(price)),
                position=None, orders=[], sizing=dict(currency='USD', available_balance='100',
                maker_fee_rate='.0002', taker_fee_rate='.0005', fee_tax_rate='.18', version='fees-v1'))


def run(s=None, fast=None, slow=None, settings=None, observed=NOW, now=NOW):
    return auto_strategy.decide(s or pullback_state(), pullback_candles() if fast is None else fast,
                               candles(300) if slow is None else slow,
                               dict(leverage=50, balance_fraction=1) if settings is None else settings,
                               observed, now)


@pytest.mark.parametrize('side,want', [(1, 'buy'), (-1, 'sell')])
def test_aligned_ema_without_pattern_enters_maker_with_exact_two_r(side, want):
    result = run(pullback_state(side), pullback_candles(side), candles(300, side))
    action = result['action']
    assert action and action['side'] == want
    assert action['order_type'] == 'limit_order'
    assert action['size'] == 9  # True pullback wick + .25ATR buffer + standard fees => <= INR20.
    entry = Decimal(str(action['price']))
    plan = action['auto_protection']
    assert abs(Decimal(str(plan['target'])) - entry) == 2 * abs(entry - Decimal(str(plan['stop'])))
    assert plan['source_time'] == (NOW // 60 - 1) * 60
    assert result['context']['direction'] == ('up' if side == 1 else 'down')
    assert result['context']['ema9'] == pytest.approx(10000 + side * 65.28)
    assert result['context']['ema15'] == pytest.approx(10000 + side * 62.15625)
    assert action['sizing_version'] == 'fees-v1'
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('observed,now', [(NOW - 31, NOW), (NOW + 1, NOW), (NOW-6, NOW+60)])
def test_stale_future_or_clock_advanced_observation_cannot_authorize(observed, now):
    assert run(observed=observed, now=now)['action'] is None


@pytest.mark.parametrize('kind', ['short', 'gap', 'duplicate', 'bad_ohlc', 'nan', 'late', 'misaligned'])
def test_invalid_recent_candle_evidence_waits(kind):
    fast = pullback_candles()
    if kind == 'short': fast = fast[:54]
    if kind == 'gap': del fast[20]
    if kind == 'duplicate': fast[20]['time'] = fast[19]['time']
    if kind == 'bad_ohlc': fast[0]['high'] = '1'
    if kind == 'nan': fast[0]['close'] = 'NaN'
    if kind == 'late': fast = fast[1:]
    if kind == 'misaligned': fast[0]['time'] += 1
    assert run(fast=fast)['action'] is None


def test_forming_bar_does_not_confirm_and_old_gap_recovers_with_55_bars():
    fast = pullback_candles()
    forming = dict(fast[0], time=(NOW // 60) * 60, close='50000', high='50000')
    assert run(fast=[forming] + fast)['action']
    fast[60]['time'] -= 60
    assert run(fast=fast)['action']


def test_higher_timeframe_disagreement_waits_with_visible_context():
    result = run(slow=candles(300, -1))
    assert result['action'] is None
    assert result['context']['higher_direction'] == 'down'


@pytest.mark.parametrize('price', ['10080', '10058'])
def test_anti_chase_blocks_both_favorable_and_adverse_gap(price):
    s = pullback_state(); s['ticker'].update(bid=price, ask=str(Decimal(price)+Decimal('.5')))
    result = run(s)
    assert result['action'] is None
    assert 'Price moved' in result['reason']


def test_sharp_completed_move_waits():
    fast = pullback_candles(); fast[0].update(open='10040', low='10039')
    assert run(fast=fast)['action'] is None


@pytest.mark.parametrize('field,value', [('maker_fee_rate', '-.1'), ('taker_fee_rate', None), ('fee_tax_rate', 'NaN'), ('available_balance', '-1'), ('version', ''), ('currency', 'INR')])
def test_unverified_fees_and_balance_reject(field, value):
    s = pullback_state(); s['sizing'][field] = value
    assert run(s)['action'] is None


@pytest.mark.parametrize('settings', [dict(leverage=201,balance_fraction=1), dict(leverage=101,balance_fraction=1), dict(leverage=50,balance_fraction=.2), dict(leverage=True,balance_fraction=1), dict(leverage=50,balance_fraction=None,manual_quantity=13)])
def test_invalid_settings_and_manual_quantity_over_risk_cap_reject(settings):
    assert run(settings=settings)['action'] is None


def test_manual_quantity_preserved_and_conservative_balance_sizing():
    result = run(settings=dict(leverage=50,balance_fraction=None,manual_quantity=2))
    assert result['action']['size'] == 2
    assert 'balance_fraction' not in result['action']
    s = pullback_state(); s['sizing']['available_balance'] = '.22'
    assert run(s)['action']['size'] == 1
    s['ticker']['mark'] = '20000'
    assert run(s)['action'] is None


def test_inputs_are_not_mutated_and_context_memory_is_bounded():
    s, fast, slow = pullback_state(), pullback_candles(count=400), candles(300,count=400)
    # Keep price near the latest close.
    s['ticker'].update(bid='10399', ask='10399.5', mark='10399')
    before = copy.deepcopy((s,fast,slow))
    result = run(s,fast,slow)
    assert (s,fast,slow) == before
    assert len(result['context'].get('bars', [])) <= 55


def test_account_activity_blocks_pure_action():
    s = pullback_state(); s['orders'] = [{'id':'other-account-order'}]
    assert run(s)['action'] is None


def test_confirmed_support_selects_structural_stop_and_broken_level_is_discarded():
    fast = pullback_candles()
    fast[4]['low'] = '10045'  # Confirmed swing below the recent pullback wick.
    result = run(fast=fast)
    assert result['context']['support'] == 10045
    assert result['action']['auto_protection']['stop'] == 10042.0
    assert result['action']['auto_protection']['target'] == 10132
    broken = pullback_candles()
    broken[10]['low'] = '10055'
    broken[7].update(close='10054',low='10050',open='10054')
    assert run(fast=broken)['context']['support'] != 10055


def test_unclosed_breakout_is_not_authorized():
    fast = pullback_candles()
    fast[3]['high'] = '10073'
    # Strict left highs10069/10070, equal right high10073 is allowed by frontend.
    s = pullback_state(); s['ticker'].update(bid='10073',ask='10073.5',mark='10073')
    result = run(s, fast)
    assert result['context']['resistance'] == 10073
    assert result['action'] is None
    assert 'breakout' in result['reason']


def test_target_must_cover_standard_fees_even_if_balance_is_large():
    s = pullback_state(); s['sizing'].update(maker_fee_rate='.001',taker_fee_rate='.003',available_balance='10000')
    result = run(s)
    assert result['action'] is None
    assert 'target' in result['reason'].lower()


def test_decimal_tick_floor_stop_and_exact_target():
    s = pullback_state(); s['product']['tick_size'] = '.05'
    s['ticker'].update(bid='10072.05',ask='10072.10',mark='10072.05')
    fast = pullback_candles(); fast[4]['low'] = '10045.03'
    result = run(s,fast)
    assert result['action']['auto_protection']['stop'] == 10042.25
    assert result['action']['auto_protection']['target'] == 10131.65


@pytest.mark.parametrize('kind', ['position','fees','quotes','tick','empty_history'])
def test_missing_or_active_execution_evidence_fails_closed(kind):
    s = pullback_state(); fast = pullback_candles()
    if kind == 'position': s['position'] = {'size':1}
    if kind == 'fees': s['sizing'] = None
    if kind == 'quotes': del s['ticker']['bid']
    if kind == 'tick': s['ticker']['bid'] = '10069.01'
    if kind == 'empty_history': fast = []
    assert run(s,fast)['action'] is None


def test_extreme_finite_decimal_evidence_never_leaks_nonfinite_json():
    fast = pullback_candles(); fast[0]['high'] = '1e999'
    result = run(fast=fast)
    assert result['action'] is None
    json.dumps(result, allow_nan=False)


def test_ema_overflow_rejects_without_nonfinite_context():
    fast = pullback_candles()
    for bar in fast:
        bar.update(open='1e308', high='1e308', low='1e308', close='1e308')
    result = run(fast=fast)
    assert result['action'] is None
    json.dumps(result, allow_nan=False)


def pullback_candles(side=1, count=70):
    """A completed EMA-zone pullback, then a fresh trend-colored continuation."""
    fast = candles(60, 1, count)
    shift = Decimal(count-70)
    fast[1].update(open=str(Decimal('10067.5')+shift), high=str(Decimal(10068)+shift),
                   low=str(Decimal(10057)+shift), close=str(Decimal(10066)+shift))
    fast[0].update(open=str(Decimal(10068)+shift), high=str(Decimal(10074)+shift),
                   low=str(Decimal(10066)+shift), close=str(Decimal(10072)+shift))
    if side < 0:
        for bar in fast:
            old = {key: Decimal(bar[key]) for key in ('open', 'high', 'low', 'close')}
            bar.update(open=str(20000-old['open']), high=str(20000-old['low']),
                       low=str(20000-old['high']), close=str(20000-old['close']))
    return fast


def pullback_state(side=1):
    current = state(side)
    price = Decimal(10000+side*72)
    current['ticker'].update(bid=str(price if side > 0 else price-Decimal('.5')),
                             ask=str(price+Decimal('.5') if side > 0 else price), mark=str(price))
    return current


@pytest.mark.parametrize('side', [1, -1])
def test_structural_stop_never_clips_inside_known_confirmed_swing(side):
    fast = pullback_candles(side)
    fast[3]['low' if side > 0 else 'high'] = '10045' if side > 0 else '9955'
    result = run(pullback_state(side), fast, candles(300, side))
    assert result['action']
    stop = Decimal(str(result['action']['auto_protection']['stop']))
    assert stop <= Decimal('10042.5') if side > 0 else stop >= Decimal('9957.5')
    assert result['action']['size'] <= 6  # Full invalidation reduces lots, never tightens SL.


@pytest.mark.parametrize('side', [1, -1])
def test_fresh_pullback_continuation_has_stable_setup_identity_and_wick_stop(side):
    fast, current = pullback_candles(side), pullback_state(side)
    result = run(current, fast, candles(300, side))
    action = result['action']
    assert action and action['strategy_id'] == 'ema'
    assert action['setup_time'] == fast[1]['time']
    assert action['setup_id'] == f"ema:{'buy' if side > 0 else 'sell'}:{fast[1]['time']}"
    assert result['context']['stop_source'] == 'completed_pullback_wick'
    assert result['context']['setup_status'] == 'confirmed_continuation'
    assert Decimal(str(action['auto_protection']['stop'])) < Decimal(fast[1]['low']) if side > 0 else Decimal(str(action['auto_protection']['stop'])) > Decimal(fast[1]['high'])
    current['ticker']['bid' if side > 0 else 'ask'] = str(Decimal(action['price']) + Decimal('.5')*side)
    if side > 0: current['ticker']['ask'] = current['ticker']['bid']
    else: current['ticker']['bid'] = current['ticker']['ask']
    again = run(current, fast, candles(300, side))
    assert again['action']['setup_id'] == action['setup_id']


@pytest.mark.parametrize('side', [1, -1])
def test_aligned_ema_regime_alone_is_not_a_new_entry_setup(side):
    result = run(state(side), candles(side=side), candles(300, side))
    assert result['action'] is None
    assert 'pullback' in result['reason'].lower()


@pytest.mark.parametrize('side', [1, -1])
def test_pullback_without_closed_break_of_previous_extreme_cannot_enter(side):
    fast, current = pullback_candles(side), pullback_state(side)
    if side > 0:
        fast[0].update(close='10068', open='10067', low='10066', high='10070')
        current['ticker'].update(bid='10068', ask='10068.5', mark='10068')
    else:
        fast[0].update(close='9932', open='9933', low='9930', high='9934')
        current['ticker'].update(bid='9931.5', ask='9932', mark='9932')
    result = run(current, fast, candles(300, side))
    assert result['action'] is None
    assert 'continuation' in result['reason'].lower()


@pytest.mark.parametrize('side', [1, -1])
def test_aligned_but_falling_higher_ema_slopes_wait(side):
    slow = candles(300, side)
    for bar in slow[:3]:
        price = 10055 if side > 0 else 9945
        bar.update(open=str(price), close=str(price), high=str(price+5), low=str(price-5))
    result = run(pullback_state(side), pullback_candles(side), slow)
    assert result['context']['higher_direction'] == ('up' if side > 0 else 'down')
    assert result['action'] is None
    assert 'slope' in result['reason'].lower()


@pytest.mark.parametrize('side', [1, -1])
def test_choppy_ema_separation_below_one_tenth_atr_waits(side):
    fast, slow = pullback_candles(side), candles(300, side)
    for bar in fast+slow:
        close = Decimal(bar['close'])
        bar.update(high=str(close+50), low=str(close-50))
    result = run(pullback_state(side), fast, slow)
    assert result['action'] is None
    assert 'separation' in result['reason'].lower()


@pytest.mark.parametrize('side', [1, -1])
def test_quote_must_still_hold_the_closed_continuation_break(side):
    current = pullback_state(side)
    current['ticker'].update(bid='10068' if side > 0 else '9931.5',
                             ask='10068.5' if side > 0 else '9932',
                             mark='10068' if side > 0 else '9932')
    result = run(current, pullback_candles(side), candles(300, side))
    assert result['action'] is None
    assert 'continuation' in result['reason'].lower()


@pytest.mark.parametrize('side', [1, -1])
def test_true_swing_stop_that_cannot_fund_one_contract_waits_without_clipping(side):
    fast, current = pullback_candles(side), pullback_state(side)
    fast[3]['low' if side > 0 else 'high'] = '10045' if side > 0 else '9955'
    current['product']['contract_value'] = '.01'
    result = run(current, fast, candles(300, side))
    assert result['action'] is None
    assert 'risk cap' in result['reason']
    assert result['context']['structural_stop'] <= 10042.5 if side > 0 else result['context']['structural_stop'] >= 9957.5


def test_pullback_cannot_be_reused_for_another_continuation_candle():
    fast, current = pullback_candles(), pullback_state()
    fast[2] = dict(fast[1], time=fast[2]['time'])
    fast[1] = dict(fast[0], time=fast[1]['time'])
    fast[0].update(open='10073', high='10078', low='10071', close='10076')
    current['ticker'].update(bid='10076', ask='10076.5', mark='10076')
    result = run(current, fast)
    assert result['action'] is None
    assert 'already had its continuation' in result['reason']


def test_a_pullback_older_than_five_completed_bars_is_not_a_fresh_setup():
    fast, current = pullback_candles(), pullback_state()
    fast[6] = dict(fast[1], time=fast[6]['time'])
    fast[1] = candles()[1]
    fast[0].update(open='10072', high='10078', low='10070', close='10076')
    current['ticker'].update(bid='10076', ask='10076.5', mark='10076')
    result = run(current, fast)
    assert result['action'] is None
    assert 'pullback' in result['reason'].lower()


def test_same_color_continuation_body_is_required_even_above_previous_high():
    fast = pullback_candles()
    fast[0].update(open='10073', high='10074', low='10070')
    result = run(pullback_state(), fast)
    assert result['action'] is None
    assert 'continuation' in result['reason'].lower()


def test_outward_decimal_tick_ceiling_preserves_short_structural_invalidation():
    fast, current = pullback_candles(-1), pullback_state(-1)
    fast[4]['high'] = '9954.97'
    current['product']['tick_size'] = '.05'
    current['ticker'].update(bid='9927.90', ask='9927.95', mark='9927.95')
    result = run(current, fast, candles(300, -1))
    assert result['action']['auto_protection']['stop'] == 9957.75
    assert result['action']['auto_protection']['target'] == 9868.35


@pytest.mark.parametrize('asof', [NOW-600, NOW+3600, NOW-10.001, NOW+.001, None, True, 'NaN', 'invalid'])
def test_account_snapshot_must_be_numeric_nonfuture_and_at_most_ten_seconds_old(asof):
    current = pullback_state()
    current['asof'] = asof
    result = run(current)
    assert result['action'] is None
    assert 'snapshot' in result['reason'].lower()


def test_missing_account_snapshot_time_fails_closed():
    current = pullback_state()
    del current['asof']
    result = run(current)
    assert result['action'] is None
    assert 'snapshot' in result['reason'].lower()


@pytest.mark.parametrize('age', [0, 10])
def test_fresh_account_snapshot_age_inclusive_boundary_allows_valid_setup(age):
    current = pullback_state()
    current['asof'] = NOW-age
    assert run(current)['action']
