"""Pure completed-trade accounting from exact owned fills, excluding funding.

No I/O or order operations. Completeness is supplied by the caller's fill reader;
partial fills, missing fees or contradictory ownership leave money unavailable.
Reported actual all-in commissions include GST and fee credits once through the
existing actual_fill_fee provenance check. This is observed outcome memory, not
an estimate or a backtest. INR uses the desk's fixed USD85 conversion.
"""
import json
from decimal import Decimal, DecimalException

MAX_FILLS = 10000
MAX_CONTRACTS = 9007199254740991


def _identity(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('Missing or invalid owned identity.')
    identity = str(value)
    if not identity or identity.strip() != identity:
        raise ValueError('Missing or invalid owned identity.')
    return identity


def completed_trade_outcome(plan, product, fills, complete):
    """Return available plus exact Decimal strings only for a proven full round trip.

    plan is the raw plan row, including its dict or JSON payload. product provides
    id and linear contract_value. Foreign orders are ignored; an owned order with
    another product/side or conflicting duplicate fill identity invalidates proof.
    """
    from .service import Rejected, actual_fill_fee, number

    def unavailable(reason):
        return {'available': False, 'reason': reason}

    if complete is not True or not isinstance(fills, list) or len(fills) > MAX_FILLS:
        return unavailable('Complete bounded fill history is required.')
    try:
        if not isinstance(plan, dict) or plan.get('status') != 'completed':
            return unavailable('Only a completed owned plan has a closed-trade outcome.')
        if not isinstance(product, dict):
            return unavailable('Verified linear product metadata is required.')
        plan_id, pid = _identity(plan.get('id')), _identity(product.get('id'))
        if 'pid' in plan and _identity(plan['pid']) != pid:
            return unavailable('Plan and fill product binding do not agree.')
        if product.get('notional_type') not in (None, 'vanilla'):
            return unavailable('Only verified linear contract accounting is supported.')
        cv = number(product.get('contract_value'), True)
        payload = plan.get('payload')
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict) or payload.get('side') not in ('buy', 'sell'):
            return unavailable('The original owned entry direction is unavailable.')
        expected = number(payload.get('size'), True)
        if expected != expected.to_integral_value() or expected > MAX_CONTRACTS:
            return unavailable('The original owned whole-contract quantity is unavailable.')
        entry_order = _identity(plan.get('entry_order_id'))
        exits = [_identity(plan[key]) for key in ('stop_order_id', 'target_order_id', 'close_order_id')
                 if plan.get(key) is not None]
        if not exits or entry_order in exits or len(exits) != len(set(exits)):
            return unavailable('Exact distinct entry and exit ownership is required.')
        owned, entry_side = {entry_order, *exits}, payload['side']
        exit_side = 'sell' if entry_side == 'buy' else 'buy'
        evidence = {}
        for row in fills:
            if not isinstance(row, dict):
                return unavailable('Malformed fill evidence cannot prove ownership.')
            order = row.get('order_id')
            if order is None or str(order) not in owned:
                continue
            order = _identity(order)
            identity = _identity(row.get('id'))
            nested = row.get('product')
            row_pid = row.get('product_id', nested.get('id') if isinstance(nested, dict) else None)
            expected_side = entry_side if order == entry_order else exit_side
            if (_identity(row_pid) != pid or row.get('side') != expected_side
                    or row.get('fill_type') != 'normal'):
                return unavailable('Owned fill product, direction or fill type is inconsistent.')
            quantity, price = number(row.get('size'), True), number(row.get('price'), True)
            if quantity != quantity.to_integral_value() or quantity > MAX_CONTRACTS:
                return unavailable('Owned fills must contain positive whole-contract quantities.')
            fee = actual_fill_fee(row)
            if fee is None:
                return unavailable('Actual all-in fill fees, GST and credits are unverified.')
            # Compare economic evidence, allowing irrelevant private metadata to differ.
            signature = (order, expected_side, quantity, price, fee)
            if identity in evidence and evidence[identity] != signature:
                return unavailable('Duplicate fill identity has conflicting economic evidence.')
            evidence[identity] = signature
        entry_qty, exit_qty = Decimal(0), Decimal(0)
        entry_value, exit_value, fees = Decimal(0), Decimal(0), Decimal(0)
        used_orders = set()
        for order, _, quantity, price, fee in evidence.values():
            if order == entry_order:
                entry_qty += quantity
                entry_value += quantity * price
            else:
                exit_qty += quantity
                exit_value += quantity * price
            fees += fee
            used_orders.add(order)
        if entry_qty != expected or exit_qty != expected:
            return unavailable('Complete owned entry and exit quantities must each equal the original plan size.')
        gross = (exit_value-entry_value) * cv * (1 if entry_side == 'buy' else -1)
        net = gross-fees
        if not all(amount.is_finite() for amount in (gross, fees, net, net*85)):
            return unavailable('Outcome arithmetic is not finite.')
        return {'available': True, 'reason': 'Complete exact-owned fills; funding excluded.',
                'gross_usd': str(gross), 'fees_usd': str(fees), 'net_usd': str(net), 'net_inr': str(net*85),
                'plan_id': plan_id, 'order_ids': sorted(used_orders), 'fill_ids': sorted(evidence)}
    except (Rejected, ValueError, TypeError, KeyError, DecimalException, OverflowError):
        return unavailable('Missing or malformed owned trade evidence.')
