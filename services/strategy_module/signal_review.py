"""Explanations from the same closed bars used by the signal evaluator.

The evaluator's direction is authoritative. Component checks are diagnostics,
not a second entry engine; recording failure must never alter an order decision.
"""

from math import isfinite

import pandas as pd

from services.research.ema_scalp import indicators
from services.research.groww_algorithmic import features as regime_features
from services.research.scalp_strategies import aggregate_fifteen, macd_features

RULES = {
    "receiver_trend": [
        "35 completed five-minute bars: EMA 9/15 aligned with both slopes over three bars; current candle touches their band and rejects in trend direction.",
        "Bullish close above EMA 9 buys CE; bearish close below EMA 9 buys PE. The latest closed fifteen-minute candle must agree in body and close-to-close direction.",
    ],
    "receiver_retest": [
        "A completed five-minute candle breaks the preceding six-bar high/low with a body of at least half its range.",
        "Only the first later retest within three completed bars may enter: touch the broken level and close beyond it with matching body. A close back through the level invalidates the setup.",
        "Fifteen-minute confirmation must agree. Buy CE for a bullish retest or PE for a bearish retest; never short an option.",
    ],
    "receiver_momentum": [
        "Completed five-minute close breaks the previous six-bar high/low, body at least 70% of its range, and range at least 1.2 times the preceding six-bar median range.",
        "Latest completed fifteen-minute body and close-to-close direction must confirm. Buy CE for bullish momentum and PE for bearish momentum.",
    ],
    "ema915": [
        "5-minute NIFTY: EMA 9 above/below EMA 15; both 3-bar slopes at least +0.10 / at most −0.10 ATR per bar.",
        "Candle intersects the EMA band and closes bullish above EMA 9 for CE, bearish below EMA 9 for PE.",
        "At least 75 candles and three consecutive 5-minute intervals are required for indicator warm-up and data integrity.",
    ],
    "macd200": [
        "5-minute MACD (12,26,9) must cross its signal now: upward below zero for CE; downward above zero for PE.",
        "Close above EMA 200 for CE / below for PE; confirmed support/resistance retest within the last three bars, within 0.25 ATR with matching candle direction.",
        "Support/resistance is a strict 2-left/2-right pivot confirmed two bars later. At least 604 completed 5-minute candles.",
    ],
    "ema5": [
        "PE alert: entire completed 5-minute candle above EMA 5. CE alert: entire completed 15-minute candle below EMA 5. EMA requires 25 bars.",
        "A subsequent completed 1-minute candle must break the active alert low (PE) or high (CE). Entry uses the next observable quote, never the alert candle retrospectively.",
        "New alerts replace older same-side alerts; gaps/session changes clear alerts. Simultaneous CE and PE breaks are rejected.",
    ],
    "regime50200": [
        "5-minute EMA 50 minus EMA 200 must cross zero on this completed candle.",
        "CE requires previous completed daily close above daily SMA 200; PE requires below.",
        "Daily 20-return volatility must be ≤ its 252-day median; at least 272 completed daily candles, 200 five-minute candles and three consecutive intervals.",
    ],
    "box15": [
        "Build the opening range from all 15 one-minute candles closing 09:16–09:30 IST. Range must span at least 20 index points.",
        "Only the first close outside this range between 09:31 and 09:45 can qualify; all intervening minutes must exist.",
        "Breakout body ≥50% of range, matching bullish/bearish direction, and three consecutive intervals. A weak first breakout consumes the opportunity for the day.",
    ],
    "sma_macd": [
        "On a completed 5-minute candle, the sign of SMA 5 minus SMA 34 must change to positive (CE) or negative (PE).",
        "Zero-difference candles do not enter; at least 35 completed candles. This is an SMA zero-cross, not the standard EMA MACD.",
    ],
    "bollinger": [
        "Completed 5-minute close below SMA 20 − 2 sample standard deviations gives CE; above SMA 20 + 2 sample standard deviations gives PE.",
        "Sample standard deviation uses ddof=1. A return inside the band is not required by this implemented research variant. At least 35 completed candles.",
    ],
}


def scalar(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (bool, str)):
        return value
    try:
        number = float(value)
        return round(number, 6) if isfinite(number) else None
    except (TypeError, ValueError):
        return str(value)


def explain(profile, inputs, result, expected):
    source = inputs["minute" if profile in {"ema5", "box15"} else "five"]
    ready = expected in source.index
    direction = (
        str(result.loc[expected, "direction"])
        if expected in result.index
        else ("" if ready else None)
    )
    out = {
        "profile": profile,
        "bar_at": expected.isoformat(),
        "data_ready": ready,
        "direction": direction,
        "rules": RULES.get(profile, []),
        "checks": [],
        "metrics": {},
    }
    if not ready:
        return out
    metrics = out["metrics"]

    def values(frame, columns, prefix=""):
        if expected in frame.index:
            for key in columns:
                if key in frame:
                    metrics[prefix + key] = scalar(frame.loc[expected, key])

    def check(side, label, condition):
        if isinstance(condition, pd.Series):
            value = condition.loc[expected] if expected in condition.index else None
        else:
            value = condition
        out["checks"].append(
            {
                "side": side,
                "label": label,
                "passed": None if value is None or pd.isna(value) else bool(value),
            }
        )

    values(source, ["open", "high", "low", "close"])
    if profile in {"ema915", "macd200"}:
        f = indicators(inputs["five"]) if profile == "ema915" else macd_features(inputs["five"])
        values(
            f,
            [
                "ema9",
                "ema15",
                "slope9",
                "slope15",
                "atr",
                "prior_atr",
                "macd",
                "macd_signal",
                "ema200",
                "support",
                "resistance",
            ],
        )
        check("Both", "Three consecutive 5-minute intervals and indicator warm-up", f.ready)
        if profile == "ema915":
            body = f.close - f.open
            touch = (f.low <= f[["ema9", "ema15"]].max(axis=1)) & (
                f.high >= f[["ema9", "ema15"]].min(axis=1)
            )
            for side in ["CE", "PE"]:
                up = side == "CE"
                trend = (
                    (f.ema9 > f.ema15) & (f.slope9 >= 0.1) & (f.slope15 >= 0.1)
                    if up
                    else (f.ema9 < f.ema15) & (f.slope9 <= -0.1) & (f.slope15 <= -0.1)
                )
                check(side, "EMA alignment and both slopes meet 0.10 ATR threshold", trend)
                check(
                    side,
                    "Touches EMA band, matching body and close beyond EMA 9",
                    touch
                    & ((body > 0) & (f.close > f.ema9) if up else (body < 0) & (f.close < f.ema9)),
                )
        else:
            support = (
                (
                    f.low.between(f.support - 0.25 * f.atr, f.support + 0.25 * f.atr)
                    & (f.close > f.support)
                    & (f.close > f.open)
                )
                .rolling(3)
                .max()
                .eq(1)
            )
            resistance = (
                (
                    f.high.between(f.resistance - 0.25 * f.atr, f.resistance + 0.25 * f.atr)
                    & (f.close < f.resistance)
                    & (f.close < f.open)
                )
                .rolling(3)
                .max()
                .eq(1)
            )
            for side in ["CE", "PE"]:
                up = side == "CE"
                check(
                    side,
                    "Fresh MACD/signal crossover",
                    (f.macd > f.macd_signal) & (f.macd.shift() <= f.macd_signal.shift())
                    if up
                    else (f.macd < f.macd_signal) & (f.macd.shift() >= f.macd_signal.shift()),
                )
                check(
                    side,
                    "Both MACD lines on required side of zero",
                    (f.macd < 0) & (f.macd_signal < 0)
                    if up
                    else (f.macd > 0) & (f.macd_signal > 0),
                )
                check(
                    side,
                    "Close on required side of EMA 200",
                    f.close > f.ema200 if up else f.close < f.ema200,
                )
                check(
                    side, "Confirmed pivot retest within three bars", support if up else resistance
                )
    elif profile == "regime50200":
        f = regime_features(inputs["five"], inputs["daily"])
        values(
            f,
            [
                "ema_diff",
                "daily_close",
                "daily_ma200",
                "daily_vol20",
                "daily_vol_median",
                "observations",
            ],
        )
        metrics["previous_ema_diff"] = scalar(f.ema_diff.shift().loc[expected])
        check("Both", "200 bars and three consecutive intervals", f.ready & f.observations.ge(200))
        check(
            "Both", "Daily volatility below or equal to median", f.daily_vol20 <= f.daily_vol_median
        )
        for side in ["CE", "PE"]:
            up = side == "CE"
            check(
                side,
                "Fresh EMA 50/200 crossover",
                (f.ema_diff > 0) & (f.ema_diff.shift() <= 0)
                if up
                else (f.ema_diff < 0) & (f.ema_diff.shift() >= 0),
            )
            check(
                side,
                "Previous daily close confirms regime",
                f.daily_close > f.daily_ma200 if up else f.daily_close < f.daily_ma200,
            )
    elif profile in {"sma_macd", "bollinger"}:
        close = inputs["five"].close
        if profile == "sma_macd":
            gap = close.rolling(5).mean() - close.rolling(34).mean()
            for key, series in [
                ("sma5", close.rolling(5).mean()),
                ("sma34", close.rolling(34).mean()),
                ("sma_gap", gap),
                ("previous_sma_gap", gap.shift()),
            ]:
                metrics[key] = scalar(series.loc[expected])
        else:
            mean, std = close.rolling(20).mean(), close.rolling(20).std(ddof=1)
            for key, series in [
                ("sma20", mean),
                ("standard_deviation", std),
                ("lower_band", mean - 2 * std),
                ("upper_band", mean + 2 * std),
            ]:
                metrics[key] = scalar(series.loc[expected])
    elif profile == "ema5":
        for frame, side in [(inputs["five"], "PE"), (aggregate_fifteen(inputs["five"]), "CE")]:
            past = frame.loc[frame.index <= expected]
            if len(past):
                ema = past.close.ewm(span=5, adjust=False, min_periods=25).mean().iloc[-1]
                row = past.iloc[-1]
                metrics[side + "_latest_alert_bar_at"] = past.index[-1].isoformat()
                metrics[side + "_ema5"] = scalar(ema)
                metrics[side + "_latest_high"] = scalar(row.high)
                metrics[side + "_latest_low"] = scalar(row.low)
                check(
                    side,
                    "Latest completed alert bar qualifies (older active alerts may still trigger)",
                    None if pd.isna(ema) else row.low > ema if side == "PE" else row.high < ema,
                )
    else:
        day = source.loc[(source.index.date == expected.date()) & (source.index <= expected)]
        opening = pd.date_range(f"{expected.date()} 09:16", periods=15, freq="min", tz=expected.tz)
        complete = opening.isin(day.index).all()
        check("Both", "All 15 opening-range minutes present", complete)
        if complete:
            box = day.loc[opening]
            high, low = float(box.high.max()), float(box.low.min())
            metrics.update(box_high=high, box_low=low, box_width=high - low)
            window = day.loc[
                (day.index > opening[-1]) & (day.index <= opening[-1] + pd.Timedelta(minutes=15))
            ]
            broken = window[(window.close > high) | (window.close < low)]
            metrics["first_break_at"] = broken.index[0].isoformat() if len(broken) else None
            check("Both", "Opening range at least 20 points", high - low >= 20)
            check(
                "Both",
                "Current candle is first breakout within 09:31–09:45",
                len(broken) > 0 and broken.index[0] == expected,
            )
    for side in ["CE", "PE"]:
        check(side, "Complete entry pattern from actual strategy evaluator", direction == side)
    return out
