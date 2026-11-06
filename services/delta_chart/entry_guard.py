"""Read-only closed-candle evidence and anti-chase checks for reviewed entries."""

from decimal import Decimal

from .service import Rejected, number

INTERVAL_RESOLUTIONS = {
    60: "1m",
    180: "3m",
    300: "5m",
    900: "15m",
    1800: "30m",
    3600: "1h",
    86400: "1d",
}
WAIT = "Sharp move. Wait for pullback or another confirmed candle."
EVIDENCE = "Fresh contiguous closed-candle evidence changed; refresh and review the entry."


def validate_entry_candles(data: dict, candles: list, nowSeconds: float) -> None:
    """Validate raw Delta UTC-second OHLC rows; forming candles never authorize entry.

    The reviewed source is the START timestamp of the latest completed interval.
    All supplied closed rows are validated, while ATR uses the last 15 rows.
    Two-left/two-right pivots require closed right-hand candles; only a later
    closed candle beyond a pivot confirms a breakout through that level.
    """
    try:
        levels = data.get("auto_protection")
        if not isinstance(levels, dict) or data.get("side") not in ("buy", "sell"):
            raise Rejected(EVIDENCE)
        span = number(levels.get("interval_seconds"), True)
        source = number(levels.get("source_time"), True)
        now = number(nowSeconds, True)
        price = number(data.get("price"), True)
        if span not in INTERVAL_RESOLUTIONS or source != source.to_integral_value():
            raise Rejected(EVIDENCE)
        if source != (now // span - 1) * span or not isinstance(candles, list):
            raise Rejected(EVIDENCE)
        bars = []
        for row in candles:
            if not isinstance(row, dict):
                raise Rejected(EVIDENCE)
            stamp = number(row.get("time"), True)
            if stamp != stamp.to_integral_value() or stamp % span:
                raise Rejected(EVIDENCE)
            if stamp + span > now:
                continue
            o, h, low, close = (
                number(row.get(key), True) for key in ("open", "high", "low", "close")
            )
            if h < max(o, low, close) or low > min(o, close):
                raise Rejected(EVIDENCE)
            bars.append((stamp, o, h, low, close))
        bars.sort(key=lambda row: row[0])
        if (
            len(bars) < 15
            or bars[-1][0] != source
            or any(b[0] - a[0] != span for a, b in zip(bars, bars[1:], strict=False))
        ):
            raise Rejected(EVIDENCE)
        recent = bars[-15:]
        atr = sum(
            max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4]))
            for a, b in zip(recent, recent[1:], strict=False)
        ) / Decimal(14)
        if atr <= 0:
            raise Rejected(EVIDENCE)
        last = recent[-1]
        # Explicit manual choice overrides only these two strategy vetoes.
        # Freshness, valid OHLC/ATR and closed-breakout checks still apply.
        manual_override = data.get("entry_mode") == "manual"
        if not manual_override and (
            last[2] - last[3] > atr * 2 or abs(last[4] - last[1]) > atr * Decimal("1.5")
        ):
            raise Rejected(WAIT)
        long = data["side"] == "buy"
        directional_gap = price - last[4] if long else last[4] - price
        if not manual_override and (
            directional_gap > atr * Decimal(".5") or directional_gap < -atr
        ):
            raise Rejected(WAIT)
        levels_ahead = []
        for i in range(2, len(bars) - 2):
            pivot = bars[i][2 if long else 3]
            neighbors = bars[i - 2 : i] + bars[i + 1 : i + 3]
            confirmed = (
                all(pivot > row[2] for row in neighbors)
                if long
                else all(pivot < row[3] for row in neighbors)
            )
            ahead = pivot > last[4] if long else pivot < last[4]
            broken = any(row[4] >= pivot if long else row[4] <= pivot for row in bars[i + 1 :])
            if confirmed and ahead and not broken:
                levels_ahead.append(pivot)
        if levels_ahead:
            nearest = min(levels_ahead) if long else max(levels_ahead)
            if price >= nearest if long else price <= nearest:
                raise Rejected("Wait for another confirmed candle beyond support or resistance.")
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, Rejected):
            raise
        raise Rejected(EVIDENCE) from None
