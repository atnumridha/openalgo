"""Exact-owned completed outcome fixtures; no live execution or estimated fees."""
import copy
import json
from decimal import Decimal

import pytest

from services.delta_chart.auto_outcomes import completed_trade_outcome

PRODUCT = {'id': 27, 'contract_value': '.001', 'notional_type': 'vanilla'}
PLAN = {'id': 'owned-plan', 'pid': '27', 'status': 'completed', 'entry_order_id': 'entry',
        'stop_order_id': 'stop', 'target_order_id': 'target', 'close_order_id': 'close',
        'payload': json.dumps({'side': 'buy', 'size': 2, 'private': 'never-return-this'})}


def fill(identity, order, side, size, price, fee='.0236', credit='0', product=27):
    return {'id': identity, 'order_id': order, 'product_id': product, 'fill_type': 'normal',
            'side': side, 'size': str(size), 'price': str(price), 'settling_asset_symbol': 'USD',
            'commission': str(Decimal(fee)-Decimal(credit)),
            'meta_data': {'total_commission_in_settling_asset': fee, 'tfc_used_for_commission': credit,
                          'rack_commision': '.0236', 'rack_commission_without_gst': '.02',
                          'private': 'never-return-this'}}


def rows(short=False):
    entry, exit = ('sell', 'buy') if short else ('buy', 'sell')
    return [fill('a', 'entry', entry, 1, 100), fill('b', 'entry', entry, 1, 102, credit='.01'),
            fill('c', 'target', exit, 1, 110), fill('d', 'close', exit, 1, 108)]


@pytest.mark.parametrize('short', [False, True])
def test_complete_owned_trade_uses_weighted_actual_fills_gst_and_credits_once(short):
    plan = copy.deepcopy(PLAN)
    plan['payload'] = {'side': 'sell' if short else 'buy', 'size': 2}
    result = completed_trade_outcome(plan, PRODUCT, rows(short), True)
    assert result['available'] is True
    assert Decimal(result['gross_usd']) == (Decimal('-.016') if short else Decimal('.016'))
    assert Decimal(result['fees_usd']) == Decimal('.0944')
    assert Decimal(result['net_usd']) == (Decimal('-.1104') if short else Decimal('-.0784'))
    assert Decimal(result['net_inr']) == (Decimal('-9.3840') if short else Decimal('-6.6640'))
    assert result['plan_id'] == 'owned-plan'
    assert result['order_ids'] == ['close', 'entry', 'target']
    assert result['fill_ids'] == ['a', 'b', 'c', 'd']
    assert 'never-return-this' not in json.dumps(result)
    assert 'funding' not in result


def test_identical_duplicates_and_foreign_orders_do_not_change_owned_result():
    evidence = rows()
    expected = completed_trade_outcome(PLAN, PRODUCT, evidence, True)
    observed = evidence + [copy.deepcopy(evidence[0]), fill('foreign', 'not-owned', 'buy', 900, 999)]
    assert completed_trade_outcome(PLAN, PRODUCT, observed, True) == expected


@pytest.mark.parametrize('kind', ['incomplete', 'missing_entry', 'missing_exit', 'partial_exit', 'excess_exit',
                                 'wrong_side', 'wrong_product', 'conflicting_duplicate', 'missing_fee',
                                 'bad_gst', 'bad_credit', 'not_completed', 'overlapping_ids', 'bad_size',
                                 'missing_id', 'unknown_fill_type', 'wrong_product_binding'])
def test_incomplete_mixed_or_unverified_evidence_never_fabricates_pnl(kind):
    plan, product, evidence, complete = copy.deepcopy(PLAN), dict(PRODUCT), rows(), True
    if kind == 'incomplete': complete = False
    if kind == 'missing_entry': evidence = evidence[2:]
    if kind == 'missing_exit': evidence = evidence[:2]
    if kind == 'partial_exit': evidence = evidence[:-1]
    if kind == 'excess_exit': evidence[-1]['size'] = '2'
    if kind == 'wrong_side': evidence[-1]['side'] = 'buy'
    if kind == 'wrong_product': evidence[-1]['product_id'] = 99
    if kind == 'conflicting_duplicate': evidence.append(dict(evidence[0], price='999'))
    if kind == 'missing_fee': del evidence[0]['meta_data']['total_commission_in_settling_asset']
    if kind == 'bad_gst': evidence[0]['meta_data']['rack_commision'] = '.02'
    if kind == 'bad_credit': evidence[0]['meta_data']['tfc_used_for_commission'] = '.1'
    if kind == 'not_completed': plan['status'] = 'active'
    if kind == 'overlapping_ids': plan['stop_order_id'] = 'entry'
    if kind == 'bad_size': evidence[-1]['size'] = '.5'
    if kind == 'missing_id': del evidence[0]['id']
    if kind == 'unknown_fill_type': evidence[0]['fill_type'] = 'liquidation'
    if kind == 'wrong_product_binding': product['id'] = 99
    result = completed_trade_outcome(plan, product, evidence, complete)
    assert result['available'] is False
    assert result['reason']
    assert 'gross_usd' not in result and 'net_usd' not in result


def test_input_payload_and_fills_remain_unmodified():
    plan, evidence = copy.deepcopy(PLAN), rows()
    before = copy.deepcopy((plan, PRODUCT, evidence))
    completed_trade_outcome(plan, PRODUCT, evidence, True)
    assert before == (plan, PRODUCT, evidence)


def test_verified_zero_actual_commission_stays_zero_without_adding_rack_gst_again():
    evidence = rows()
    for row in evidence:
        row['commission'] = '0'
        row['meta_data'].update(total_commission_in_settling_asset='0', tfc_used_for_commission='0')
    result = completed_trade_outcome(PLAN, PRODUCT, evidence, True)
    assert result['available']
    assert Decimal(result['fees_usd']) == 0
    assert Decimal(result['net_usd']) == Decimal('.016')


def test_only_stop_exit_is_sufficient_when_all_owned_exit_quantity_is_proven():
    evidence = rows()[:2] + [fill('stop-filled', 'stop', 'sell', 2, 95)]
    result = completed_trade_outcome(PLAN, PRODUCT, evidence, True)
    assert result['available']
    assert result['order_ids'] == ['entry', 'stop']
    assert Decimal(result['gross_usd']) == Decimal('-.012')


def test_oversized_history_and_inverse_contracts_are_unavailable():
    assert not completed_trade_outcome(PLAN, PRODUCT, [{}]*10001, True)['available']
    assert not completed_trade_outcome(PLAN, dict(PRODUCT, notional_type='inverse'), rows(), True)['available']
