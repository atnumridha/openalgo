from decimal import Decimal as D

from services.risk.option_costs import FeeSchedule, estimate_option_fees, money


def estimate(side, price, quantity, brokerage=D(0)):
    return estimate_option_fees(side, price, quantity, FeeSchedule(brokerage=brokerage))
