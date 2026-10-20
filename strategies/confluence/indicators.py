"""Pure indicator calculations. Prices/volume are inputs; no broker access."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def smooth(values, period, alpha):
    """Seed with an SMA, then recurse (Wilder uses 1/n, EMA uses 2/(n+1))."""
    a = np.asarray(values, dtype=float)
    out = np.full(len(a), np.nan)
    for i in range(period - 1, len(a)):
        if i > 0 and np.isfinite(out[i - 1]):
            out[i] = out[i - 1] + alpha * (a[i] - out[i - 1])
        elif np.isfinite(a[i - period + 1 : i + 1]).all():
            out[i] = a[i - period + 1 : i + 1].mean()
    return out


def indicators(b: pd.DataFrame):
    if len(b) < 100:
        raise ValueError("At least 100 completed candles required")
    c, h, low, v = (b[x].to_numpy(float) for x in ("close", "high", "low", "volume"))
    delta = np.r_[np.nan, np.diff(c)]
    gain = smooth(np.maximum(delta, 0), 14, 1 / 14)
    loss = smooth(np.maximum(-delta, 0), 14, 1 / 14)
    total = gain + loss
    rsi = np.divide(100 * gain, total, out=np.full(len(c), 50.0), where=total > 0)
    prev = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - low, np.abs(h - prev), np.abs(low - prev)])
    atr = smooth(tr, 14, 1 / 14)
    up = np.r_[np.nan, np.diff(h)]
    down = np.r_[np.nan, -np.diff(low)]
    plus = np.where((up > down) & (up > 0), up, 0.0)
    minus = np.where((down > up) & (down > 0), down, 0.0)
    plus[0] = minus[0] = np.nan
    pdi = np.divide(100 * smooth(plus, 14, 1 / 14), atr, out=np.zeros(len(c)), where=atr > 0)
    mdi = np.divide(100 * smooth(minus, 14, 1 / 14), atr, out=np.zeros(len(c)), where=atr > 0)
    dx = np.divide(100 * np.abs(pdi - mdi), pdi + mdi, out=np.zeros(len(c)), where=pdi + mdi > 0)
    dx[:14] = np.nan
    adx = smooth(dx, 14, 1 / 14)
    macd = smooth(c, 12, 2 / 13) - smooth(c, 26, 2 / 27)
    signal = smooth(macd, 9, 2 / 10)
    hist = macd - signal
    vol = pd.Series(v).rolling(20).sum()
    vwma = (pd.Series(c * v).rolling(20).sum() / vol.replace(0, np.nan)).to_numpy()
    result = {
        "rsi": rsi[-1],
        "adx": adx[-1],
        "plus_di": pdi[-1],
        "minus_di": mdi[-1],
        "macd": macd[-1],
        "macd_signal": signal[-1],
        "macd_hist": hist[-1],
        "macd_hist_previous": hist[-2],
        "vwma": vwma[-1],
        "vwma_slope": vwma[-1] - vwma[-4],
        "atr": atr[-1],
        "close": c[-1],
    }
    if not all(math.isfinite(float(x)) for x in result.values()) or result["atr"] <= 0:
        raise ValueError("Indicator warmup, volatility or volume unavailable")
    return {k: float(x) for k, x in result.items()}


def pivots(high, low, close):
    if not 0 < low <= close <= high or high == low:
        raise ValueError("Invalid prior session OHLC")
    p = (high + low + close) / 3
    bc = (high + low) / 2
    tc = 2 * p - bc
    r = 1.1 * (high - low)
    out = {"pivot": p, "bc": min(bc, tc), "tc": max(bc, tc)}
    for n, divisor in [(1, 12), (2, 6), (3, 4), (4, 2)]:
        out[f"r{n}"] = close + r / divisor
        out[f"s{n}"] = close - r / divisor
    return out


def volume_profile(b, bins=64, fraction=0.7):
    """Estimate volume-at-price by uniform distribution across each candle range.

    Not tick volume-at-price. Expand contiguously from the POC, taking the
    larger adjacent bin; ties select the lower bin deterministically.
    """
    if not 2 <= bins <= 256 or not 0 < fraction <= 1:
        raise ValueError("Invalid profile settings")
    lo = float(b.low.min())
    hi = float(b.high.max())
    if hi <= lo:
        raise ValueError("Prior session price range unavailable")
    edges = np.linspace(lo, hi, bins + 1)
    volume = np.zeros(bins)
    for row in b.itertuples():
        if row.volume < 0:
            raise ValueError("Negative volume")
        if row.high == row.low:
            index = min(bins - 1, max(0, int(np.searchsorted(edges, row.close, side="right") - 1)))
            volume[index] += row.volume
        else:
            overlap = np.maximum(
                0, np.minimum(edges[1:], row.high) - np.maximum(edges[:-1], row.low)
            )
            volume += row.volume * overlap / (row.high - row.low)
    total = float(volume.sum())
    if total <= 0:
        raise ValueError("Prior session volume unavailable")
    poc = int(np.argmax(volume))
    left = right = poc
    covered = volume[poc]
    while covered < total * fraction and (left > 0 or right < bins - 1):
        a = volume[left - 1] if left > 0 else -1
        bvol = volume[right + 1] if right < bins - 1 else -1
        if a >= bvol:
            left -= 1
            covered += volume[left]
        else:
            right += 1
            covered += volume[right]
    return {
        "val": float(edges[left]),
        "vah": float(edges[right + 1]),
        "poc": float((edges[poc] + edges[poc + 1]) / 2),
        "coverage": float(covered / total),
        "bins": bins,
        "volumes": volume.tolist(),
        "method": "uniform_1m_candle_range_estimate",
    }


def option_analysis(rows, spot, now):
    """One expiry, paired liquid strikes. OI is contracts, not signed positioning."""
    valid = []
    for r in rows:
        try:
            v = {
                k: float(r[k])
                for k in (
                    "strike",
                    "expiry",
                    "timestamp",
                    "bid",
                    "ask",
                    "iv",
                    "oi_contracts",
                    "delta",
                )
            }
            if not all(math.isfinite(x) for x in v.values()):
                continue
            if not 0 <= now - v["timestamp"] <= 60 or v["expiry"] <= now + 1800:
                continue
            if (
                not 0 < v["bid"] <= v["ask"]
                or (v["ask"] - v["bid"]) / ((v["ask"] + v["bid"]) / 2) > 0.3
            ):
                continue
            if not 0 < v["iv"] <= 5 or v["oi_contracts"] <= 0 or abs(v["strike"] / spot - 1) > 0.05:
                continue
            if r["side"] not in ("CALL", "PUT") or not 0 < abs(v["delta"]) < 1:
                continue
            if (r["side"] == "CALL") != (v["delta"] > 0):
                continue
            valid.append({**v, "side": r["side"]})
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            continue
    if not valid:
        raise ValueError("Fresh liquid option-chain data unavailable")
    expiry = min(r["expiry"] for r in valid)
    pairs = {}
    for r in valid:
        if r["expiry"] == expiry:
            pairs.setdefault(r["strike"], {})[r["side"]] = r
    pairs = {k: v for k, v in pairs.items() if len(v) == 2}
    if len(pairs) < 3:
        raise ValueError("Option chain needs three paired liquid strikes in one expiry")
    calls = [p["CALL"] for p in pairs.values()]
    puts = [p["PUT"] for p in pairs.values()]
    coi = sum(r["oi_contracts"] for r in calls)
    poi = sum(r["oi_contracts"] for r in puts)
    call25 = min(calls, key=lambda r: abs(r["delta"] - 0.25))
    put25 = min(puts, key=lambda r: abs(r["delta"] + 0.25))
    if abs(call25["delta"] - 0.25) > 0.2 or abs(put25["delta"] + 0.25) > 0.2:
        raise ValueError("25-delta option IV coverage unavailable")
    skew = put25["iv"] - call25["iv"]

    def pain(price):
        return sum(
            max(price - k, 0) * p["CALL"]["oi_contracts"]
            + max(k - price, 0) * p["PUT"]["oi_contracts"]
            for k, p in pairs.items()
        )

    return {
        "expiry": expiry,
        "paired_strikes": len(pairs),
        "put_call_ratio": poi / coi,
        "call_oi": coi,
        "put_oi": poi,
        "call_wall": max(calls, key=lambda r: r["oi_contracts"])["strike"],
        "put_wall": max(puts, key=lambda r: r["oi_contracts"])["strike"],
        "max_pain": min(sorted(pairs), key=pain),
        "skew_25d": skew,
        "vote": 1 if skew < -0.01 else -1 if skew > 0.01 else 0,
        "scope": "Paired liquid strikes within 5% of spot; max pain and OI walls are local estimates",
        "interpretation": "IV-skew heuristic; OI does not identify buyers versus writers",
    }
