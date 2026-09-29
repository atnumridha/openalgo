"""Sixteen Kotak-inspired option-basket topologies.

These are static leg shapes reconstructed from Kotak Neo's ready-made basket
screens. They are not Kotak's proprietary Strategy Bot entry, exit, POP, or
backtest rules. Twelve layouts match the supplied detail screenshots. Four
use conventional inferred layouts and are labeled as such.

Offsets are relative to the current ATM strike step, not dated screenshot
prices. Installation must leave every strategy stopped and sandbox-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["B", "S"]
OptionType = Literal["CE", "PE"]
Provenance = Literal["screenshot-detail", "conventional-inference"]

TEMPLATE_VERSION = "kotak-baskets-v1"
INFERRED_IDS = frozenset(
    {"bear-put-spread", "bear-call-spread", "put-ratio-spread", "long-strangle"}
)


@dataclass(frozen=True, slots=True)
class LegPattern:
    side: Side
    option_type: OptionType
    strike_offset: int
    lots: int


@dataclass(frozen=True, slots=True)
class BasketTemplate:
    id: str
    name: str
    category: str
    legs: tuple[LegPattern, ...]
    provenance: Provenance
    version: str = TEMPLATE_VERSION


def _atm_offset(option_type: OptionType, strike_offset: int) -> str:
    if strike_offset == 0:
        return "ATM"
    otm = strike_offset > 0 if option_type == "CE" else strike_offset < 0
    return f"{'OTM' if otm else 'ITM'}{abs(strike_offset)}"


def _leg(side: Side, option_type: OptionType, strike_offset: int, lots: int = 1) -> LegPattern:
    return LegPattern(side, option_type, strike_offset, lots)


def _template(template_id: str, name: str, category: str, *legs: LegPattern) -> BasketTemplate:
    provenance: Provenance = (
        "conventional-inference" if template_id in INFERRED_IDS else "screenshot-detail"
    )
    return BasketTemplate(template_id, name, category, legs, provenance)


TEMPLATES: tuple[BasketTemplate, ...] = (
    _template("buy-call", "Kotak Buy Call", "bullish", _leg("B", "CE", 0)),
    _template(
        "bull-call-spread",
        "Kotak Bull Call Spread",
        "bullish",
        _leg("B", "CE", 0),
        _leg("S", "CE", 1),
    ),
    _template(
        "bull-put-spread",
        "Kotak Bull Put Spread",
        "bullish",
        _leg("S", "PE", 0),
        _leg("B", "PE", -1),
    ),
    _template(
        "call-ratio-spread",
        "Kotak Call Ratio Spread",
        "bullish",
        _leg("B", "CE", 0),
        _leg("S", "CE", 1, 2),
    ),
    _template("buy-put", "Kotak Buy Put", "bearish", _leg("B", "PE", 0)),
    _template(
        "bear-put-spread",
        "Kotak Bear Put Spread",
        "bearish",
        _leg("B", "PE", 0),
        _leg("S", "PE", -1),
    ),
    _template(
        "bear-call-spread",
        "Kotak Bear Call Spread",
        "bearish",
        _leg("S", "CE", 0),
        _leg("B", "CE", 1),
    ),
    _template(
        "put-ratio-spread",
        "Kotak Put Ratio Spread",
        "bearish",
        _leg("B", "PE", 0),
        _leg("S", "PE", -1, 2),
    ),
    _template(
        "short-straddle",
        "Kotak Short Straddle",
        "neutral",
        _leg("S", "CE", 0),
        _leg("S", "PE", 0),
    ),
    _template(
        "short-strangle",
        "Kotak Short Strangle",
        "neutral",
        _leg("S", "PE", -1),
        _leg("S", "CE", 1),
    ),
    _template(
        "long-call-butterfly",
        "Kotak Long Call Butterfly",
        "neutral",
        _leg("B", "CE", -1),
        _leg("S", "CE", 0, 2),
        _leg("B", "CE", 1),
    ),
    _template(
        "short-iron-condor",
        "Kotak Short Iron Condor",
        "neutral",
        _leg("B", "PE", -2),
        _leg("S", "PE", -1),
        _leg("S", "CE", 1),
        _leg("B", "CE", 2),
    ),
    _template(
        "long-straddle",
        "Kotak Long Straddle",
        "volatile",
        _leg("B", "CE", 0),
        _leg("B", "PE", 0),
    ),
    _template(
        "long-strangle",
        "Kotak Long Strangle",
        "volatile",
        _leg("B", "PE", -1),
        _leg("B", "CE", 1),
    ),
    _template(
        "long-iron-butterfly",
        "Kotak Long Iron Butterfly",
        "volatile",
        _leg("B", "CE", 0),
        _leg("B", "PE", 0),
        _leg("S", "CE", 1),
        _leg("S", "PE", -1),
    ),
    _template(
        "long-iron-condor",
        "Kotak Long Iron Condor",
        "volatile",
        _leg("S", "PE", -2),
        _leg("B", "PE", -1),
        _leg("B", "CE", 1),
        _leg("S", "CE", 2),
    ),
)

_BY_ID = {row.id: row for row in TEMPLATES}


def all_templates() -> tuple[BasketTemplate, ...]:
    return TEMPLATES


def get_template(template_id: str) -> BasketTemplate:
    try:
        return _BY_ID[template_id]
    except KeyError as exc:
        raise ValueError(f"Unknown basket template {template_id!r}") from exc


def strategy_definition(template: BasketTemplate) -> dict:
    """A stopped, sandbox-only Strategy Module payload for one topology."""
    return {
        "name": template.name,
        "strategy_kind": "batch",
        "universe_tab": "weekly_monthly",
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "strategy_type": "intraday",
        "product": "MIS",
        "pricetype": "MARKET",
        "entry_time": "09:20",
        "exit_time": "15:20",
        "overall_sl_mtm": 300,
        "overall_target_mtm": None,
        "daily_loss_limit_inr": 2000,
        "scheduler": None,
        "legs": [
            {
                "id": index,
                "segment": "options",
                "position": leg.side,
                "lots": leg.lots,
                "option_type": leg.option_type,
                "strike_mode": "atm",
                "atm_offset": _atm_offset(leg.option_type, leg.strike_offset),
                "expiry": "weekly",
                "sl_pts": 20,
                "risk_unit": "points",
            }
            for index, leg in enumerate(template.legs, start=1)
        ],
    }
