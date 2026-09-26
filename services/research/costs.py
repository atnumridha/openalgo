"""Explicit dated fee assumptions, shared by replay and live admission."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

RATE_FIELDS = ("exchange_rate", "sebi_rate", "gst_rate", "stamp_buy_rate", "stt_sell_rate")
NUMERIC_FIELDS = ("brokerage_per_order", *RATE_FIELDS, "slippage_bps")


def decimal_value(value, name, *, minimum=0, maximum=None):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a finite number") from None
    if (
        not number.is_finite()
        or number < Decimal(str(minimum))
        or (maximum is not None and number > Decimal(str(maximum)))
    ):
        raise ValueError(f"{name} is outside the supported range")
    return number


def validate_cost_schedule(payload):
    """Require every cost field; explicit zero differs from missing evidence."""
    if not isinstance(payload, dict):
        raise ValueError("A dated cost schedule is required")
    result = {}
    for key in ("schedule_id", "source"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise ValueError(f"Cost schedule {key} is required")
        result[key] = value.strip()
    for key in ("effective_from", "effective_to"):
        try:
            result[key] = date.fromisoformat(payload[key]).isoformat()
        except (KeyError, ValueError, TypeError):
            raise ValueError(f"Cost schedule {key} must be an ISO date") from None
    if result["effective_from"] > result["effective_to"]:
        raise ValueError("Cost schedule date range is reversed")
    for key in NUMERIC_FIELDS:
        maximum = 1 if key in RATE_FIELDS else (1000 if key == "slippage_bps" else 100000)
        result[key] = float(decimal_value(payload.get(key), key, maximum=maximum))
    if set(payload) - set(result):
        raise ValueError("Unrecognized cost schedule fields")
    return result


def validate_cost_dates(schedule, days):
    if any(day < schedule["effective_from"] or day > schedule["effective_to"] for day in days):
        raise ValueError("Cost schedule must cover every selected session date")


def order_cost(notional: Decimal, side: str, schedule: dict) -> Decimal:
    """Fees for one filled order. Rates are fractions of turnover, not percent."""
    turnover = decimal_value(notional, "notional")
    if side.upper() not in ("BUY", "SELL"):
        raise ValueError("Cost side must be BUY or SELL")
    brokerage = Decimal(str(schedule["brokerage_per_order"]))
    exchange = turnover * Decimal(str(schedule["exchange_rate"]))
    sebi = turnover * Decimal(str(schedule["sebi_rate"]))
    gst = (brokerage + exchange + sebi) * Decimal(str(schedule["gst_rate"]))
    tax_key = "stamp_buy_rate" if side.upper() == "BUY" else "stt_sell_rate"
    return (
        brokerage + exchange + sebi + gst + turnover * Decimal(str(schedule[tax_key]))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
