"""Matched timeframe/session experiment; offline transformations only."""

import numpy as np
import pandas as pd

from services.research.ema_scalp import _validate
from services.research.ig_scalping import bars_from_minutes
from services.research.tradetron_scalping import tradetron_signals

WINDOWS = {"all": (555, 930), "opening": (555, 615), "closing": (870, 930)}


def timeframe_signals(minutes, timeframe):
    _validate(minutes)
    if timeframe not in (1, 3, 5):
        raise ValueError("Only the registered 1/3/5-minute intervals are supported")
    f = minutes.copy() if timeframe == 1 else bars_from_minutes(minutes, timeframe)
    for p in (5, 10):
        f[f"ema{p}"] = f.close.ewm(span=p, adjust=False).mean()
    f["ema_ready"] = np.arange(len(f)) >= 49
    consecutive = f.index.to_series().diff().eq(pd.Timedelta(minutes=timeframe))
    f["ready"] = consecutive.rolling(3).sum().eq(3)
    return tradetron_signals(f, "ema")


def entry_window(signals, window):
    if window not in WINDOWS:
        raise ValueError("Unknown entry window")
    out = signals.copy()
    at = out.index.tz_convert("Asia/Kolkata")
    clock = at.hour * 60 + at.minute
    start, end = WINDOWS[window]
    out.loc[(clock < start) | (clock >= end), "direction"] = ""
    return out
