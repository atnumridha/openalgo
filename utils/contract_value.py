"""Broker-specific quote units for the general strategy accounting book.

This book also consumes external/manual fills. Missing metadata must not discard
an actual fill or leave a closed position open. Preserve its historical factor
of one when metadata is unavailable; managed MCX entry admission separately
requires verified units before it can place an order.
"""

from math import isfinite

from database.token_db import get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)


def accounting_multiplier(symbol: str, exchange: str) -> float:
    try:
        info = get_symbol_info(symbol, exchange)
        value = getattr(info, "contract_value", None)
        if value is not None and not isinstance(value, bool):
            factor = float(value)
            if isfinite(factor) and factor > 0:
                return factor
    except Exception:
        logger.warning("Contract units unavailable for %s on %s", symbol, exchange)
    if exchange == "MCX":
        logger.warning(
            "Accounting %s with legacy unit value; contract metadata is unverified", symbol
        )
    return 1.0
