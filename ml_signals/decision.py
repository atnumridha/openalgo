"""How a model's probabilities become a trade: levels, expected value, side.

Pure arithmetic, no I/O. Training tunes these numbers, the live snapshot and
the suggestion API apply them, and both import them from here so a backtest
and a live suggestion are decided by the same rule.

* Stop and target are scaled to volatility. A bar's ATR, as a percent of
  price, is stretched to the hold by the square root of the number of bars
  in it, so 1m and 15m bars give comparable distances. The stop is a
  multiple of that, kept between a floor and the operator's cap, and the
  target is a reward-to-risk multiple of the stop, kept under its own cap.
* Expected value per side, in percent of notional after fees:
  ``p_win x average net win - (1 - p_win) x average net loss``, with the
  averages measured on rows the model was not fitted on.
* A side is taken only when its expected value clears the minimum edge tuned
  on validation; otherwise the answer is WAIT.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}


@dataclass(frozen=True)
class Payoff:
    """One side's average outcome, in percent of notional after fees."""

    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    win_rate: float = 0.0


@dataclass(frozen=True)
class DecisionParams:
    """Everything one interval's model needs to turn probabilities into a trade."""

    interval: str
    hold_minutes: int = 28
    stop_atr_mult: float = 0.8
    reward_risk: float = 2.0
    stop_floor_pct: float = 0.05
    stop_cap_pct: float = 0.2
    target_cap_pct: float = 2.0
    min_edge_pct: float = 0.05
    long: Payoff = field(default_factory=Payoff)
    short: Payoff = field(default_factory=Payoff)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DecisionParams:
        values = dict(raw)
        values["long"] = Payoff(**(values.get("long") or {}))
        values["short"] = Payoff(**(values.get("short") or {}))
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})


def horizon_vol_pct(atr_pct: float | np.ndarray, interval: str, hold_minutes: int) -> Any:
    """A bar's ATR stretched to the hold: ATR x sqrt(bars held)."""
    bars = max(1.0, hold_minutes / INTERVAL_MINUTES[interval])
    return np.asarray(atr_pct, dtype=float) * math.sqrt(bars)


def levels_pct(params: DecisionParams, atr_pct: float | np.ndarray) -> tuple[Any, Any]:
    """Stop and target distances in percent of entry, for one bar or many.

    A missing ATR (warm-up) takes the floor, so a level is always defined.
    """
    vol = horizon_vol_pct(atr_pct, params.interval, params.hold_minutes)
    vol = np.where(np.isfinite(vol), vol, 0.0)
    stop = np.clip(params.stop_atr_mult * vol, params.stop_floor_pct, params.stop_cap_pct)
    target = np.minimum(params.reward_risk * stop, params.target_cap_pct)
    if np.ndim(stop) == 0:
        return float(stop), float(target)
    return stop, target


def expected_values(p_long: Any, p_short: Any, params: DecisionParams) -> tuple[Any, Any]:
    """Expected net percent of a long and of a short, after fees."""
    p_long = np.asarray(p_long, dtype=float)
    p_short = np.asarray(p_short, dtype=float)
    ev_long = p_long * params.long.avg_win_pct - (1 - p_long) * params.long.avg_loss_pct
    ev_short = p_short * params.short.avg_win_pct - (1 - p_short) * params.short.avg_loss_pct
    if np.ndim(ev_long) == 0:
        return float(ev_long), float(ev_short)
    return ev_long, ev_short


def choose(ev_long: Any, ev_short: Any, min_edge_pct: float) -> Any:
    """+1 for long, -1 for short, 0 for WAIT, for one bar or many."""
    ev_long = np.asarray(ev_long, dtype=float)
    ev_short = np.asarray(ev_short, dtype=float)
    side = np.where(ev_long >= ev_short, 1, -1)
    best = np.maximum(ev_long, ev_short)
    out = np.where(np.isfinite(best) & (best > min_edge_pct), side, 0)
    return int(out) if np.ndim(out) == 0 else out


def decide(p_long: float, p_short: float, atr_pct: float, params: DecisionParams) -> dict[str, Any]:
    """One bar's decision with everything a suggestion shows about it."""
    ev_long, ev_short = expected_values(p_long, p_short, params)
    side = choose(ev_long, ev_short, params.min_edge_pct)
    stop, target = levels_pct(params, atr_pct)
    return {
        "action": "LONG" if side > 0 else "SHORT" if side < 0 else "WAIT",
        "ev_long_pct": ev_long,
        "ev_short_pct": ev_short,
        "ev_pct": ev_long if side > 0 else ev_short if side < 0 else max(ev_long, ev_short),
        "min_edge_pct": params.min_edge_pct,
        "stop_pct": stop,
        "target_pct": target,
        "hold_minutes": params.hold_minutes,
    }


def take_non_overlapping(
    candidates: np.ndarray, exit_index: dict[int, np.ndarray], sides: np.ndarray
) -> list[int]:
    """Signal bars actually traded when only one position is held at a time.

    ``candidates`` are signal-bar indices in time order and ``sides`` their
    side. A trade enters on the next bar's open and holds until its exit bar,
    so the next signal is taken only once that exit has happened.
    """
    taken: list[int] = []
    free_from = -1
    for index, side in zip(candidates.tolist(), sides.tolist(), strict=True):
        if index < free_from:
            continue
        exit_at = int(exit_index[int(side)][index])
        if exit_at < 0:
            continue
        taken.append(index)
        free_from = exit_at
    return taken
