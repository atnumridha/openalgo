"""Fee-aware stop ratchet and timed profit exit. Pure; no broker or clock I/O."""
import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def evaluate(plan, price, now, *, eligible):
    def finite(value):
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError('Finite protection inputs are required')
        return float(value)

    p = {k: finite(plan[k]) for k in (
        'side', 'entry', 'stop', 'target', 'gap', 'tick', 'units',
        'opening_cost', 'funding', 'exit_rate', 'exit_at', 'window_end',
    )}
    price, now = finite(price), finite(now)
    if (p['side'] not in (-1, 1) or min(price, p['entry'], p['stop'], p['target'],
            p['gap'], p['tick'], p['units']) <= 0 or not 0 <= p['exit_rate'] < 1
            or p['opening_cost'] < 0):
        raise ValueError('Valid positive protection inputs are required')
    sign, units, step = p['side'], p['units'], p['tick']
    rate_now = 0 if eligible and now < p['window_end'] else p['exit_rate']
    gross = sign * (price - p['entry']) * units
    net = gross - p['opening_cost'] - rate_now * price * units - step * units + p['funding']
    result = dict(action='hold', reason='waiting_for_net_profit', stop=p['stop'],
                  target=p['target'], net=round(net, 8))
    cash = plan.get('trailing_mode', 'price') == 'net_usd'
    if plan.get('trailing_mode', 'price') not in ('price', 'net_usd'):
        raise ValueError('Unknown trailing policy')
    if cash:
        arm, lock, gap = [finite(plan[k]) for k in ('profit_arm_usd', 'profit_lock_usd', 'profit_gap_usd')]
        previous_peak = finite(plan.get('peak_net_usd', 0))
        if not 0 < lock < arm or gap <= 0 or gap > arm-lock+1e-8 or previous_peak < 0:
            raise ValueError('Use a positive net-profit lock below activation and a valid trailing gap')
        # Ordinary closing fees remain reserved even while a free-close offer applies.
        net = gross - p['opening_cost'] - rate_now * price * units - step*units*(1-sign*rate_now) + p['funding']
        result['net'] = round(net, 8)
        conservative_net = round(gross - p['opening_cost'] - p['exit_rate'] * price * units - step*units*(1-sign*p['exit_rate']) + p['funding'], 8)
        peak = max(previous_peak, conservative_net, 0)
        armed = bool(plan.get('profit_armed')) or peak > arm
        protected = round(max(lock, peak-gap), 8) if armed else 0
        result.update(peak_net_usd=peak, profit_armed=armed, protected_net_usd=protected,
                      conservative_net_usd=conservative_net)
    if sign * (price - p['stop']) <= 0:
        return {**result, 'reason': 'broker_stop_reached'}
    if net > 0 and sign * (price - p['target']) >= 0:
        return {**result, 'action': 'exit', 'reason': 'target'}
    if net > 0 and eligible and p['exit_at'] <= now < p['window_end']:
        return {**result, 'action': 'exit', 'reason': 'fee_window'}
    if cash:
        if not armed:
            return {**result, 'reason': 'waiting_for_net_usd_activation'}
        # A failed/unacknowledged ratchet can leave the older broker stop behind.
        # Close only while still estimated positive; an already-crossed native stop
        # remains authoritative via the early broker_stop_reached return above.
        if 0 < conservative_net <= protected:
            return {**result, 'action': 'exit', 'reason': 'profit_trail'}
        desired = (protected + sign*p['entry']*units + p['opening_cost'] + step*units*(1-sign*p['exit_rate']) - p['funding']) / (units*(sign-p['exit_rate']))
        rounding = ROUND_CEILING if sign > 0 else ROUND_FLOOR
        desired = float((Decimal(str(desired))/Decimal(str(step))).to_integral_value(rounding=rounding)*Decimal(str(step)))
        candidate = max(p['stop'], desired) if sign > 0 else min(p['stop'], desired)
        if candidate > 0 and sign*(price-candidate) >= step and sign*(candidate-p['stop']) > 0:
            return {**result, 'action':'tighten', 'reason':'protecting_net_usd_profit', 'stop':candidate}
        return {**result, 'reason':'net_usd_trail_held'}
    # Budget ordinary taker fees even inside a temporary offer; a future fee
    # change may require a tighter floor, never a looser acknowledged stop.
    breakeven = (sign * p['entry'] + step + (p['opening_cost'] - p['funding']) / units) / (sign - p['exit_rate'])
    rounding = ROUND_CEILING if sign > 0 else ROUND_FLOOR
    rounded = lambda value: float((Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=rounding) * Decimal(str(step)))
    floor = rounded(breakeven) + sign * step
    candidate = max(p['stop'], floor, rounded(price-p['gap'])) if sign > 0 else min(p['stop'], floor, rounded(price+p['gap']))
    if net > 0 and candidate > 0 and sign * (price-candidate) >= step and sign * (candidate-p['stop']) > 0:
        return {**result, 'action': 'tighten', 'reason': 'protecting_net_profit', 'stop': candidate}
    return result
