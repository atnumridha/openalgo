"""Feature generation tests for ML scalp labels and causal data alignment."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml_signals.features import build_features, make_training_matrix


def bars(n=800):
    rng = np.random.default_rng(21)
    returns = rng.normal(0, 0.0004, n)
    close = 85000 * np.exp(np.cumsum(returns))
    spread = close * rng.uniform(0.0001, 0.001, n)
    return pd.DataFrame(
        {
            "time": 1_700_000_000 + np.arange(n) * 60,
            "open": close - returns * close / 2,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.lognormal(5, 0.5, n),
        }
    )


def test_features_use_only_past_bars():
    b = bars()
    original = build_features(b, interval="1m", include_sentiment=False)
    changed = b.copy()
    cut = 500
    changed.loc[cut + 1 :, ["open", "high", "low", "close", "volume"]] *= 1.3
    after = build_features(changed, interval="1m", include_sentiment=False)
    np.testing.assert_allclose(original.iloc[: cut + 1], after.iloc[: cut + 1], equal_nan=True)


@pytest.mark.parametrize("interval", ["1m", "3m", "5m", "15m"])
def test_supported_timeframes_add_timeframe_code(interval):
    features = build_features(bars(), interval=interval, include_sentiment=False)
    assert features["timeframe_code"].eq({"1m": 1, "3m": 3, "5m": 5, "15m": 15}[interval]).all()
    assert "supertrend_direction" in features
    assert "efficiency_20" in features


def test_unknown_timeframe_is_rejected():
    with pytest.raises(ValueError, match="unsupported scalp timeframe"):
        build_features(bars(), interval="1h", include_sentiment=False)


def test_feature_matrix_drops_unlabelled_and_featureless_rows():
    f = pd.DataFrame({"a": [np.nan, 1, 2, np.nan], "b": [np.nan, 1, np.nan, np.nan]})
    X, y, indices = make_training_matrix(f, np.array([0, 1, np.nan, 2]))
    assert indices.tolist() == [1]
    assert y.tolist() == [1]
    assert X.shape == (1, 2)
