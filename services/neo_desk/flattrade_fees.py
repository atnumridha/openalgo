"""Read-only option planning estimate from Flattrade's published calculator.

Verified 2026-11-03: https://flattrade.in/assets/js/brokerage-calc.js,
cal_options(). Round-trip components are rounded before GST and total.
Actual contract-note charges, exercise and other account charges are separate.
"""
from decimal import Decimal as D
from services.risk.option_costs import money


def flattrade_option_fees(buy, sell, quantity, exchange):
    if exchange not in ('NFO', 'BFO'):
        raise ValueError('Flattrade option fee profile is unavailable for this exchange.')
    turnover = money((buy + sell) * quantity)
    components = dict(
        brokerage=D('0.00'),
        stt=money(sell * quantity * D('.0015')),
        exchange=money(turnover * D('.0003553' if exchange == 'NFO' else '.000325')),
        sebi=money(turnover * D('.000001')),
        ipft=money(turnover * D('.000005')),
        stamp=money(buy * quantity * D('.00003')),
    )
    components['gst'] = money(sum(components[k] for k in ('brokerage', 'exchange', 'sebi', 'ipft')) * D('.18'))
    return dict(total=str(money(sum(components.values()))),
                breakdown={k: str(v) for k, v in components.items()},
                source='Flattrade zero-brokerage calculator estimate: https://flattrade.in/brokerage-calculator/',
                version='flattrade-options-calculator-20261103-v1')
