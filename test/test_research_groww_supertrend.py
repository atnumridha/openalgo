import numpy as np
import pandas as pd
import pytest

from services.research.ema_scalp import chart_outcome
from services.research.groww_supertrend import pullback_signals, supertrend_features


def bars(n=150):
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        index=pd.date_range("2025-01-02 09:16", periods=n, freq="min", tz="Asia/Kolkata"),
    )


def test_wilder_seed_initial_downtrend_and_strict_flip():
    f = bars()
    f.iloc[110] = [100, 108, 99, 107]
    out = supertrend_features(f)
    assert out.atr.iloc[:9].isna().all()
    assert out.atr.iloc[9] == 2 and out.supertrend.iloc[9] == 106
    assert out.trend.iloc[109] == -1 and out.trend.iloc[110] == 1
    assert out.atr.iloc[110] == pytest.approx(2.7)
    assert out.lower.iloc[110] == pytest.approx(95.4)


@pytest.mark.parametrize("direction", ["CE", "PE"])
def test_touch_waits_for_next_closed_break_and_keeps_original_stop(direction):
    f = supertrend_features(bars())
    f.loc[:, "trend"] = 1 if direction == "CE" else -1
    f.loc[:, "supertrend"] = 99 if direction == "CE" else 101
    if direction == "CE":
        f.loc[f.index[120], ["open", "high", "low", "close"]] = [100, 102, 98, 101]
        f.loc[f.index[121], ["open", "high", "low", "close"]] = [101, 104, 99, 103]
        stop = 98
    else:
        f.loc[f.index[120], ["open", "high", "low", "close"]] = [100, 102, 98, 99]
        f.loc[f.index[121], ["open", "high", "low", "close"]] = [99, 101, 96, 97]
        stop = 102
    out = pullback_signals(f)
    assert out.iloc[120].direction == ""
    assert out.iloc[121].direction == direction
    assert out.iloc[121].stop_price == stop
    assert out.iloc[121].setup_at == f.index[120].isoformat()
    f.loc[f.index[121], "trend"] *= -1
    assert pullback_signals(f).iloc[121].direction == ""


def test_break_is_strict_immediate_and_invalidated_by_opposite_extreme():
    f = supertrend_features(bars())
    f.loc[:, "trend"] = -1
    f.loc[:, "supertrend"] = 101
    f.loc[f.index[120], ["open", "high", "low", "close"]] = [100, 102, 98, 99]
    f.loc[f.index[121], ["open", "high", "low", "close"]] = [99, 100, 98, 98]
    f.loc[f.index[122], ["open", "high", "low", "close"]] = [98, 100, 96, 97]
    assert pullback_signals(f).iloc[121:123].direction.eq("").all()
    f.loc[f.index[121], ["open", "high", "low", "close"]] = [99, 102, 96, 97]
    assert pullback_signals(f).iloc[121].direction == ""


def test_gap_warmup_and_future_changes_cannot_create_past_signals():
    rng = np.random.default_rng(7)
    f = bars(350)
    close = 100 + rng.normal(size=350).cumsum()
    f.loc[:, ["open", "close"]] = np.column_stack([close, close])
    f.loc[:, "high"] = close + 2
    f.loc[:, "low"] = close - 2
    full = pullback_signals(supertrend_features(f))
    prefix = pullback_signals(supertrend_features(f.iloc[:250]))
    pd.testing.assert_frame_equal(full.iloc[:250], prefix)
    assert full.iloc[:100].direction.eq("").all()
    gap = pullback_signals(supertrend_features(f.drop(f.index[200])))
    assert gap.loc[f.index[201] : f.index[203]].direction.eq("").all()


def test_shared_replay_uses_setup_stop_actual_entry_r_and_stop_first():
    f = bars(10)
    at = f.index[0]
    signal = {
        "timestamp": at.isoformat(),
        "direction": "CE",
        "low": 99,
        "high": 102,
        "stop_price": 98,
        "reward_multiple": 3,
    }
    f.iloc[1] = [101, 111, 97, 104]
    r = chart_outcome(signal, f, 5)
    assert r["stop"] == 98 and r["target"] == 110 and r["ambiguous"] and r["r"] == -1


def test_invalid_candles_rejected_before_indicator():
    f = bars()
    f.iloc[50, 0] = 200
    with pytest.raises(ValueError):
        supertrend_features(f)
