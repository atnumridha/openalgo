"""Versioned planned-risk arithmetic shared by managed admission and ML replay."""

from decimal import Decimal

from services.research.costs import order_cost

ML_RISK_RECIPE = "strategy-admission-v1"


def planned_entry_risk(stop_distance: Decimal, premium: Decimal, costs: dict) -> Decimal:
    """Conservative long-option reserve: stop distance, both fees and two-sided slip.

    ``stop_distance`` is the configured premium-stop loss for the full quantity;
    ``premium`` is that quantity's current entry turnover. Existing Strategy
    Module admission used this exact arithmetic before it was extracted here.
    """
    entry_fee = order_cost(premium, "BUY", costs)
    exit_fee = order_cost(premium, "SELL", costs)
    slippage = premium * Decimal(str(costs["slippage_bps"])) / Decimal("10000") * 2
    return stop_distance + entry_fee + exit_fee + slippage
