import numpy as np
import pandas as pd
import pytest

from services.research.tradetron_scalping import (
    FAMILIES,
    confirmed_divergence,
    features,
    regular_sessions,
    tradetron_signals,
)


def frame(values, frequency="5min", start="2025-01-02 09:20"):
    close = np.asarray(values, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close},
        index=pd.date_range(start, periods=len(close), freq=frequency, tz="Asia/Kolkata"),
    )


def test_divergence_waits_two_bars_and_does_not_backdate_signal():
    f = frame([105, 103, 100, 103, 105, 104, 102, 99, 101, 102])
    f["rsi"] = [50, 40, 20, 40, 50, 50, 40, 30, 45, 50]
    f["segment"] = 0
    result = confirmed_divergence(f)
    assert list(np.flatnonzero(result.bull)) == [9]
    assert not result.bear.any()
    assert not confirmed_divergence(f.iloc[:9]).bull.any()
    # Same pattern on another session/gap must not reuse the earlier pivot.
    f.loc[f.index[5] :, "segment"] = 1
    assert not confirmed_divergence(f).bull.any()


def test_divergence_bearish_mirror_and_equal_pivots_do_not_count():
    f = frame([95, 97, 100, 97, 95, 96, 98, 101, 99, 98])
    f["rsi"] = [50, 60, 80, 60, 50, 50, 60, 70, 55, 50]
    f["segment"] = 0
    assert list(np.flatnonzero(confirmed_divergence(f).bear)) == [9]
    f.loc[f.index[8], "high"] = f.iloc[7].high
    assert not confirmed_divergence(f).bear.any()


def fixture():
    f = frame([100.0] * 8)
    f["ready"], f["recent_five"], f["level_ready"] = True, True, True
    f["ema5"], f["ema10"] = 99.0, 100.0
    f["ema_ready"] = True
    f["bull"], f["bear"] = False, False
    f["upper"], f["lower"] = 103.0, 97.0
    f["recent_squeeze"] = False
    f["support"], f["resistance"], f["atr_prev"] = 95.0, 105.0, 3.0
    return f


def test_ema_only_crosses_completed_bar_in_either_direction():
    f = fixture()
    f["ema5"] = [99, 101, 102, 101, 99, 98, 101, 102]
    f.loc[f.index[6], "ready"] = False
    result = tradetron_signals(f, "ema")
    assert result.direction.tolist() == ["", "CE", "", "", "PE", "", "", ""]
    assert result.iloc[1].stop_price == 85
    assert result.iloc[4].stop_price == 115


def test_squeeze_uses_previous_band_and_prior_squeeze():
    f = fixture()
    f.loc[f.index[3], ["close", "high", "recent_squeeze"]] = [104, 105, True]
    f.loc[f.index[6], ["close", "low", "recent_squeeze"]] = [96, 95, True]
    result = tradetron_signals(f, "squeeze")
    assert result.direction.tolist() == ["", "", "", "CE", "", "", "PE", ""]
    f.loc[f.index[6], "recent_five"] = False
    assert tradetron_signals(f, "squeeze").iloc[6].direction == ""


def test_pin_bar_requires_level_rejection_and_wick_shape():
    f = fixture()
    f.loc[f.index[3], ["open", "high", "low", "close"]] = [99, 101, 94, 100]
    f.loc[f.index[5], ["open", "high", "low", "close"]] = [101, 106, 99, 100]
    r = tradetron_signals(f, "pinbar")
    assert r.iloc[3].direction == "CE" and r.iloc[5].direction == "PE"
    f.loc[f.index[3], "low"] = 96  # no touch of support
    f.loc[f.index[5], "close"] = 95  # ordinary large body
    assert not tradetron_signals(f, "pinbar").direction.ne("").any()


def test_range_requires_compact_prior_range_and_close_in_correct_half():
    f = fixture()
    f.loc[f.index[3], ["open", "low", "close"]] = [96, 94, 97]
    f.loc[f.index[5], ["open", "high", "close"]] = [104, 106, 103]
    r = tradetron_signals(f, "range")
    assert r.iloc[3].direction == "CE" and r.iloc[5].direction == "PE"
    f.loc[f.index[3], "atr_prev"] = 1
    f.loc[f.index[5], "level_ready"] = False
    assert not tradetron_signals(f, "range").direction.ne("").any()


def test_features_are_prefix_invariant_and_reset_levels_at_gap():
    f = frame(1000 + np.random.default_rng(12).normal(size=300).cumsum(), "min")
    full, prefix = features(f, 1), features(f.iloc[:250], 1)
    pd.testing.assert_frame_equal(full.iloc[:250], prefix)
    for family in FAMILIES:
        pd.testing.assert_frame_equal(
            tradetron_signals(full, family).iloc[:250], tradetron_signals(prefix, family)
        )
    g = features(f.drop(f.index[210]), 1)
    assert not g.loc[f.index[211:214], "ready"].any()
    assert not g.loc[f.index[211:231], "level_ready"].any()
    assert g.loc[f.index[231], "level_ready"]
    expected = f.iloc[230:250].low.min()
    assert full.iloc[250].support == expected
    with pytest.raises(ValueError):
        tradetron_signals(full, "unknown")


def test_squeeze_percentile_excludes_current_and_ema_warms_up():
    f = frame(1000 + np.sin(np.arange(220) / 4), "min")
    result = features(f, 1)
    assert not result.iloc[:49].ema_ready.any()
    assert result.iloc[49].ema_ready
    assert result.iloc[200].squeeze_threshold == pytest.approx(
        result.iloc[80:200].bandwidth.quantile(0.1)
    )
    assert result.iloc[200].recent_squeeze == result.iloc[195:200].squeezed.any()


def test_simultaneous_divergence_is_skipped():
    f = fixture()
    f["bull"] = True
    f["bear"] = True
    assert not tradetron_signals(f, "divergence").direction.ne("").any()


def test_ema_roundoff_is_not_a_crossover():
    f = fixture()
    f["ema5"] = [100 - 2e-12, 100 + 3e-12] * 4
    assert not tradetron_signals(f, "ema").direction.ne("").any()


def test_regular_sessions_excludes_documented_muhurat_day_only():
    f = pd.concat(
        [frame([100], start=d + " 09:20") for d in ("2025-10-20", "2025-10-21", "2025-10-23")]
    )
    r = regular_sessions(f)
    assert r.index.strftime("%Y-%m-%d").tolist() == ["2025-10-20", "2025-10-23"]
