"""Convert price quotes to rupees without changing broker order quantities.

Kotak's MCX master expresses GOLDM quantity in grams (100 per contract),
but its price is quoted per 10 grams. Other supported mini contracts quote
per physical unit. See docs/mcx-contract-units.md for dated source evidence.
Only verified contracts are supported; an unknown MCX symbol fails closed.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

_MCX_UNITS = {
    "GOLDM": (100, 0.1),
    "CRUDEOILM": (10, 1.0),
    "SILVERM": (5, 1.0),
    "NATGASMINI": (250, 1.0),
}
SUPPORTED_MCX_ROOTS = frozenset(_MCX_UNITS)
_MCX_SYMBOL = re.compile(
    r"^(GOLDM|CRUDEOILM|SILVERM|NATGASMINI)\d{2}[A-Z]{3}\d{2}(?:\d+(?:\.\d+)?(?:CE|PE)|FUT)$"
)


def _positive(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Contract units must be positive finite numbers")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Contract units are missing or invalid") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Contract units must be positive finite numbers")
    return result


def mcx_contract_multiplier(name: str, lot_size: Any) -> float:
    """Verify the broker's physical lot size before returning rupees/quote/unit."""
    units = _MCX_UNITS.get(str(name).upper())
    if units is None or _positive(lot_size) != units[0]:
        raise ValueError("MCX contract units are unsupported or the master lot size does not match")
    return units[1]


def price_multiplier(leg: Mapping[str, Any]) -> float:
    """Resolve immutable quote units for a position, including legacy recovery.

    Admission additionally requires explicit resolver evidence and lot size.
    Durable order recovery may only have the canonical symbol and exchange;
    these four contract identities suffice to recover their price quote units.
    A supplied multiplier must agree, so corrupt snapshots cannot understate risk.
    """
    exchange = str(leg.get("exchange") or "").upper()
    factor = 1.0
    if exchange == "MCX":
        match = _MCX_SYMBOL.fullmatch(str(leg.get("symbol") or "").upper())
        if match is None:
            raise ValueError("MCX contract value conversion is not verified for this symbol")
        name = match.group(1)
        lot = leg.get("lot_size", leg.get("lotsize"))
        factor = _MCX_UNITS[name][1] if lot is None else mcx_contract_multiplier(name, lot)
    supplied = leg.get("price_multiplier")
    if supplied is not None and _positive(supplied) != factor:
        raise ValueError("Contract price multiplier conflicts with verified quote units")
    return factor
