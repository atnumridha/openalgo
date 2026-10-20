"""Inputs for the crypto fee core: the operator's fee profile and each contract's rates.

``services/crypto_fees.py`` decides; this module only reads what it decides
from. The profile comes from ML settings. A contract's maker and taker rates
come from Delta's public product endpoint, cached per symbol for a day: the
master contract keeps the contract value but not the rates, and the schedule
changes rarely.
"""

from __future__ import annotations

from typing import Any

from services.crypto_fees import ContractFees, FeeProfile
from utils.logging import get_logger
from utils.thread_safe_cache import MISSING, LockedTTLCache

logger = get_logger(__name__)

PRODUCT_URL = "https://api.india.delta.exchange/v2/products/{symbol}"
REQUEST_TIMEOUT_SECONDS = 5.0

_rates_cache = LockedTTLCache(maxsize=512, ttl=24 * 3600)

#: OpenAlgo instrument types back to Delta contract types.
_INSTRUMENT_TO_CONTRACT = {
    "PERPFUT": "perpetual_futures",
    "FUT": "futures",
    "CE": "call_options",
    "PE": "put_options",
    "SPOT": "spot",
    "MOVE": "move_options",
    "SPREAD": "spreads",
    "COMBO": "options_combos",
    "TCE": "turbo_call_options",
    "TPE": "turbo_put_options",
}


def fee_profile(settings: dict[str, Any] | None = None) -> FeeProfile:
    """The operator's fee profile from ML settings."""
    if settings is None:
        from database.ml_settings_db import get_settings

        settings = get_settings()
    return FeeProfile(
        gst_pct=float(settings.get("fee_gst_pct", 18.0)),
        scalper_offer=bool(settings.get("fee_scalper_offer", True)),
        scalper_minutes_major=float(settings.get("fee_scalper_minutes_major", 30.0)),
        scalper_minutes_other=float(settings.get("fee_scalper_minutes_other", 15.0)),
        diwali_offer=bool(settings.get("fee_diwali_offer", False)),
        premium_cap_pct=float(settings.get("fee_premium_cap_pct", 3.5)),
    )


def voucher_earned_this_month(settings: dict[str, Any] | None = None) -> float:
    """Fee Vouchers already credited this IST calendar month, as the operator entered it.

    Delta's API does not report vouchers, and the $100 cap is shared with any
    sub-accounts, so this figure is the operator's to keep current.
    """
    if settings is None:
        from database.ml_settings_db import get_settings

        settings = get_settings()
    return max(0.0, float(settings.get("fee_voucher_earned_month", 0.0) or 0.0))


def profile_dict(profile: FeeProfile, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gst_pct": profile.gst_pct,
        "scalper_offer": profile.scalper_offer,
        "scalper_minutes_major": profile.scalper_minutes_major,
        "scalper_minutes_other": profile.scalper_minutes_other,
        "scalper_majors": list(profile.scalper_majors),
        "scalper_excluded": list(profile.scalper_excluded),
        "diwali_offer": profile.diwali_offer,
        "diwali_symbols": list(profile.diwali_symbols),
        "diwali_window_minutes": profile.diwali_window_minutes,
        "voucher_monthly_cap": profile.voucher_monthly_cap,
        "voucher_earned_month": voucher_earned_this_month(settings),
        "premium_cap_pct": profile.premium_cap_pct,
    }


def _product_rates(br_symbol: str) -> tuple[float | None, float | None, str | None]:
    cached = _rates_cache.get(br_symbol, MISSING)
    if cached is not MISSING:
        return cached
    generation = _rates_cache.generation
    rates: tuple[float | None, float | None, str | None] = (None, None, None)
    try:
        from utils.httpx_client import get_httpx_client

        response = get_httpx_client().get(
            PRODUCT_URL.format(symbol=br_symbol), timeout=REQUEST_TIMEOUT_SECONDS
        )
        if response.status_code == 200:
            product = (response.json() or {}).get("result") or {}
            rates = (
                float(product["maker_commission_rate"])
                if product.get("maker_commission_rate")
                else None,
                float(product["taker_commission_rate"])
                if product.get("taker_commission_rate")
                else None,
                product.get("contract_type"),
            )
    except Exception as exc:
        logger.warning("Could not read Delta fee rates for %s: %s", br_symbol, exc)
        return rates
    _rates_cache.fill(br_symbol, rates, generation)
    return rates


def contract_fees(symbol: str, exchange: str = "CRYPTO") -> tuple[ContractFees, float]:
    """A contract's fee inputs and its contract value, from the master contract and Delta.

    Falls back to the published defaults for the contract type when the rates
    cannot be read, and to a contract value of 1 when the symbol is unknown.
    """
    from database.token_db_enhanced import get_symbol_info

    info = None
    try:
        info = get_symbol_info(symbol, exchange)
    except Exception:
        logger.exception("Symbol lookup failed for %s %s", symbol, exchange)
    br_symbol = (getattr(info, "brsymbol", None) or symbol).upper()
    contract_value = float(getattr(info, "contract_value", None) or 1.0)
    contract_type = _INSTRUMENT_TO_CONTRACT.get(
        str(getattr(info, "instrumenttype", "") or "").upper(), "perpetual_futures"
    )
    maker, taker, reported_type = _product_rates(br_symbol)
    return (
        ContractFees(
            symbol=br_symbol,
            contract_type=reported_type or contract_type,
            maker_rate=maker,
            taker_rate=taker,
        ),
        contract_value,
    )
