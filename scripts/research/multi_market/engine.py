"""Causal chart-rule combinations and conservative offline fill simulation.

Signal definitions are research choices, not a claim about any source's returns.
Only the shared pure risk evaluator decides a touched stop/target. This module
translates minute OHLC into a conservative sequence and estimates fill costs.
"""

from dataclasses import dataclass
import itertools
import math

import numpy as np
import pandas as pd

from services.risk.models import PositionRisk, Side
from services.risk.position import evaluate_position


@dataclass(frozen=True)
class Candidate:
    family: str
    timeframe: int
    selective: bool
    stop_atr: float
    reward: float
    hold_minutes: int

    @property
    def id(self):
        return f"{self.family}/{self.timeframe}m/{'selective' if self.selective else 'base'}/SL{self.stop_atr:g}ATR/TP{self.reward:g}R/{self.hold_minutes}min"


def candidates():
    return [
        Candidate(*v)
        for v in itertools.product(
            ["pullback", "retest", "range", "sweep", "regime"],
            [5, 15],
            [False, True],
            [1.0, 1.5, 2.5],
            [0.5, 1.0, 1.5, 2.0, 3.0],
            [30, 120],
        )
    ]


def wilder(x, n):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    finite = np.flatnonzero(np.isfinite(x))
    if len(finite) < n:
        return out
    start = finite[0] + n - 1
    if start >= len(x) or not np.isfinite(x[start - n + 1 : start + 1]).all():
        return out
    out[start] = x[start - n + 1 : start + 1].mean()
    for i in range(start + 1, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def _features(b):
    f = b.copy()
    c = f.close
    h = f.high
    l = f.low
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    f["atr"] = wilder(tr, 14)
    up = h.diff()
    down = -l.diff()
    plus = wilder(up.where((up > down) & (up > 0), 0), 14)
    minus = wilder(down.where((down > up) & (down > 0), 0), 14)
    den = plus + minus
    dx = np.divide(100 * np.abs(plus - minus), den, out=np.zeros(len(f)), where=den > 0)
    dx[~np.isfinite(plus)] = np.nan
    f["adx"] = wilder(dx, 14)
    change = c.diff()
    gain = wilder(change.clip(lower=0), 14)
    loss = wilder((-change).clip(lower=0), 14)
    f["rsi"] = np.divide(
        100 * gain, gain + loss, out=np.full(len(f), 50.0), where=(gain + loss) > 0
    )
    for n in [20, 50]:
        f[f"ema{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    f["slope"] = f.ema20 - f.ema20.shift(3)
    f["prior_high"] = h.rolling(20, min_periods=20).max().shift(1)
    f["prior_low"] = l.rolling(20, min_periods=20).min().shift(1)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    f["upper"] = mid + 2 * sd
    f["lower"] = mid - 2 * sd
    f["median_atr"] = f.atr.rolling(50, min_periods=30).median().shift(1)
    f["median_volume"] = f.volume.rolling(20, min_periods=20).median().shift(1)
    f["warm"] = np.arange(len(f)) >= 60
    return f


def features(b, indian):
    # Normal exchange overnight closures retain indicators; unexpected missing
    # bars reset them so discontinuities cannot silently create signals.
    d = b.copy().reset_index(drop=True)
    if d.empty:
        return _features(d)
    day = (
        pd.to_datetime(d.time, unit="s", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.strftime("%Y-%m-%d")
    )
    gap = d.time.diff().ne(d.end - d.time)
    if indian:
        local_start = pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
        local_end = pd.to_datetime(d.end.shift(1), unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
        normal_close = (local_end.dt.hour * 60 + local_end.dt.minute).eq(930)
        normal_open = (local_start.dt.hour * 60 + local_start.dt.minute).eq(555)
        gap &= ~(day.ne(day.shift(1)) & normal_close & normal_open)
    groups = gap.cumsum()
    return pd.concat([_features(g) for _, g in d.groupby(groups)], ignore_index=True)


def signal_series(f, family, selective, indian):
    c = f.close
    o = f.open
    a = f.atr
    up = (c > f.ema20) & (f.ema20 > f.ema50) & (f.slope > 0)
    dn = (c < f.ema20) & (f.ema20 < f.ema50) & (f.slope < 0)
    strength = 25 if selective else 20
    pull_l = up & (f.low <= f.ema20) & (c > o) & (f.adx >= strength)
    pull_s = dn & (f.high >= f.ema20) & (c < o) & (f.adx >= strength)
    sweep_l = (f.low < f.prior_low) & (c > f.prior_low) & (c > o)
    sweep_s = (f.high > f.prior_high) & (c < f.prior_high) & (c < o)
    range_l = (c.shift(1) < f.lower.shift(1)) & (c > f.lower) & (c > o) & (f.adx < 20)
    range_s = (c.shift(1) > f.upper.shift(1)) & (c < f.upper) & (c < o) & (f.adx < 20)
    if selective:
        pull_l &= (f.rsi >= 50) & (f.rsi <= 65)
        pull_s &= (f.rsi <= 50) & (f.rsi >= 35)
        sweep_l &= f.rsi < 45
        sweep_s &= f.rsi > 55
        range_l &= f.rsi.shift(1) < 35
        range_s &= f.rsi.shift(1) > 65
    # Freeze a breakout's level; first successful retest in the next 3 bars.
    ret_l = np.zeros(len(f), bool)
    ret_s = np.zeros(len(f), bool)
    pending = None
    for i in range(len(f)):
        if i and f.time.iloc[i] != f.end.iloc[i - 1]:
            pending = None
        if pending:
            side, level, idx = pending
            if (
                i - idx > 3
                or (side == 1 and c.iloc[i] < level - 0.3 * a.iloc[i])
                or (side == -1 and c.iloc[i] > level + 0.3 * a.iloc[i])
            ):
                pending = None
            elif (
                side == 1
                and f.low.iloc[i] <= level + 0.15 * a.iloc[i]
                and c.iloc[i] > level
                and up.iloc[i]
            ):
                ret_l[i] = True
                pending = None
            elif (
                side == -1
                and f.high.iloc[i] >= level - 0.15 * a.iloc[i]
                and c.iloc[i] < level
                and dn.iloc[i]
            ):
                ret_s[i] = True
                pending = None
        if pending is None and not (ret_l[i] or ret_s[i]):
            if (
                c.iloc[i] > f.prior_high.iloc[i] + 0.1 * a.iloc[i]
                and up.iloc[i]
                and f.adx.iloc[i] >= strength
            ):
                pending = (1, f.prior_high.iloc[i], i)
            elif (
                c.iloc[i] < f.prior_low.iloc[i] - 0.1 * a.iloc[i]
                and dn.iloc[i]
                and f.adx.iloc[i] >= strength
            ):
                pending = (-1, f.prior_low.iloc[i], i)
    choices = {
        "pullback": (pull_l, pull_s),
        "retest": (ret_l, ret_s),
        "range": (range_l, range_s),
        "sweep": (sweep_l, sweep_s),
        "regime": (
            (pull_l | ret_l) | ((f.adx < 20) & (range_l | sweep_l)),
            (pull_s | ret_s) | ((f.adx < 20) & (range_s | sweep_s)),
        ),
    }
    long, short = choices[family]
    valid = f.warm & np.isfinite(a) & (a > 0)
    if selective:
        valid &= (a >= 0.6 * f.median_atr) & (a <= 2 * f.median_atr) & ((f.high - f.low) <= 2 * a)
        if not indian:
            valid &= f.volume >= f.median_volume
    # Avoid a signal spanning the overnight boundary or a missing base candle.
    valid &= f.time.eq(f.end.shift(1))
    if indian:
        t = pd.to_datetime(f.end, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
        minute = t.dt.hour * 60 + t.dt.minute
        valid &= (minute >= 575) & (minute < 900)
    return np.where(valid & long & ~short, 1, np.where(valid & short & ~long, -1, 0))


def simulate(d, signals, c, indian, *, slippage=None, fee_rate=None, units=None, max_per_day=3):
    """One position, next-minute open, deterministic worst-case OHLC ordering."""
    if slippage is None:
        slippage = 1.0 if indian else 0.0001
    if fee_rate is None:
        fee_rate = 0 if indian else 0.00059
    if units is None:
        units = 1 if indian else 0.001
    ts = d.time.to_numpy(dtype=np.int64)
    op = d.open.to_numpy()
    hi = d.high.to_numpy()
    lo = d.low.to_numpy()
    cl = d.close.to_numpy()
    day = (
        d.day.to_numpy()
        if "day" in d
        else pd.to_datetime(ts, unit="s", utc=True)
        .tz_convert("Asia/Kolkata")
        .strftime("%Y-%m-%d")
        .to_numpy()
    )
    if not len(ts):
        return []
    period_end = int((pd.Timestamp(day[-1], tz="Asia/Kolkata") + pd.Timedelta(days=1)).timestamp())
    rows = []
    busy = -1
    counts = {}
    for sig in signals.itertuples(index=False):
        i = int(np.searchsorted(ts, int(sig.end)))
        if i >= len(ts) or ts[i] != sig.end or ts[i] < busy or counts.get(day[i], 0) >= max_per_day:
            continue
        side = int(sig.side)
        if side not in [-1, 1] or not np.isfinite(sig.atr) or sig.atr <= 0:
            continue
        counts[day[i]] = counts.get(day[i], 0) + 1
        slip = slippage if indian else op[i] * slippage
        entry = float(op[i] + side * slip)
        distance = float(sig.atr * c.stop_atr)
        tick = 0.05 if indian else 0.5
        # Round initial stop outward (planned risk increases slightly), target
        # outward. Report the resulting risk, never pretend a fractional tick fills.
        stop = (
            math.floor((entry - distance) / tick) * tick
            if side > 0
            else math.ceil((entry + distance) / tick) * tick
        )
        risk = abs(entry - stop)
        target = (
            math.ceil((entry + risk * c.reward) / tick) * tick
            if side > 0
            else math.floor((entry - risk * c.reward) / tick) * tick
        )
        if stop <= 0 or target <= 0:
            continue
        end_time = min(ts[i] + c.hold_minutes * 60, period_end)
        if indian:
            close_time = int(pd.Timestamp(day[i] + " 15:15", tz="Asia/Kolkata").timestamp())
            end_time = min(end_time, close_time)
        j = min(int(np.searchsorted(ts, end_time, side="left")) - 1, len(ts) - 1)
        j = max(j, i)
        # First missing minute makes an unclosed trade unresolved. Earlier stop
        # or target remains usable; never skip the gap to seek a favourable exit.
        differences = np.flatnonzero(np.diff(ts[i : j + 1]) != 60)
        gap = bool(len(differences))
        if gap:
            j = i + int(differences[0])
        s_hit = (lo[i : j + 1] <= stop) if side > 0 else (hi[i : j + 1] >= stop)
        t_hit = (hi[i : j + 1] >= target) if side > 0 else (lo[i : j + 1] <= target)
        touched = np.flatnonzero(s_hit | t_hit)
        reason = "time"
        exit_price = None
        if len(touched):
            j = i + int(touched[0])
            r = PositionRisk(
                side=Side.BUY if side > 0 else Side.SELL,
                entry_price=entry,
                quantity=units,
                stop_price=stop,
                target_price=target,
            )
            # Open first for gaps. Otherwise adverse extreme before favourable.
            at_open = evaluate_position(r, float(op[j]))
            if at_open.reason:
                reason = str(at_open.reason)
                exit_price = float(op[j]) if reason == "sl" else target
            else:
                adverse = evaluate_position(r, float(lo[j] if side > 0 else hi[j]))
                if adverse.reason:
                    reason = "sl"
                    exit_price = stop
                else:
                    favourable = evaluate_position(r, float(hi[j] if side > 0 else lo[j]))
                    if favourable.reason:
                        reason = "target"
                        exit_price = target
        elif gap:
            reason = "missing_data"
        elif ts[j] + 60 < end_time:
            reason = "missing_data"
        else:
            exit_price = float(cl[j])
        busy = int(ts[j] + 60) if reason != "missing_data" else int(end_time)
        row = dict(
            signal_time=int(sig.time),
            entry_time=int(ts[i]),
            exit_time=int(ts[j] + 60),
            side=side,
            entry=entry,
            stop=stop,
            target=target,
            risk=risk,
            reason=reason,
            exit=None,
            gross=None,
            fees=None,
            funding_reserve=None,
            net=None,
            net_r=None,
        )
        if exit_price is not None:
            exit_price -= side * (slippage if indian else exit_price * slippage)
            gross = side * (exit_price - entry) * units
            fees = (entry + exit_price) * units * fee_rate
            # Explicit reserve, not a claim of historical booked funding.
            settlements = (int(ts[j] + 60) // 28800 - int(ts[i]) // 28800) if not indian else 0
            funding = settlements * entry * units * 0.0001
            net = gross - fees - funding
            row.update(
                exit=exit_price,
                gross=gross,
                fees=fees,
                funding_reserve=funding,
                net=net,
                net_r=net / (risk * units),
            )
        rows.append(row)
    return rows


def summarize(trades):
    settled = [t for t in trades if t["net"] is not None]
    vals = np.array([t["net"] for t in settled], dtype=float)
    n = len(vals)
    wins = int((vals > 0).sum())
    gain = float(vals[vals > 0].sum())
    loss = float(-vals[vals < 0].sum())
    equity = np.r_[0, np.cumsum(vals)]
    dd = float(np.max(np.maximum.accumulate(equity) - equity))
    p = wins / n if n else 0.0
    z = 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n) if n else 0
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / (1 + z * z / n) if n else 0
    return dict(
        trades=n,
        unresolved=len(trades) - n,
        wins=wins,
        win_rate=p,
        win_interval=[centre - half, centre + half],
        net=float(vals.sum()),
        fees=sum(t["fees"] for t in settled),
        funding_reserve=sum(t["funding_reserve"] for t in settled),
        expectancy=float(vals.mean()) if n else 0,
        expectancy_r=float(np.mean([t["net_r"] for t in settled])) if n else 0,
        profit_factor=gain / loss if loss else None,
        drawdown=dd,
        average_win=gain / wins if wins else 0,
        average_loss=loss / (n - wins) if n > wins else 0,
    )


def choose_development(rows):
    eligible = [
        r
        for r in rows
        if r["trades"] >= 30
        and r["expectancy"] > 0
        and factor_at_least(r, 1.1)
        and r.get("unresolved", 0) == 0
    ]
    return sorted(eligible, key=lambda r: (r["win_rate"], r["expectancy"]), reverse=True)[:10]


def factor_at_least(metrics, minimum):
    # Null with positive winners and no losing trades represents an unbounded
    # observed ratio, not zero. Sample-count gates still apply independently.
    pf = metrics["profit_factor"]
    return (
        pf >= minimum
        if pf is not None
        else metrics["trades"] > 0 and metrics["wins"] > 0 and metrics["net"] > 0
    )
