import numpy as np
import pandas as pd
import pytest

from services.research.stockgro_timeframes import entry_window, timeframe_signals
from services.research.tradetron_scalping import features, tradetron_signals


def minutes(n=350):
    close = 25000 + np.random.default_rng(9).normal(size=n).cumsum()
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close},
        index=pd.date_range("2025-01-02 09:16", periods=n, freq="min", tz="Asia/Kolkata"),
    )


def test_one_minute_signals_equal_existing_corrected_ema_baseline():
    f = minutes()
    pd.testing.assert_frame_equal(timeframe_signals(f, 1), tradetron_signals(features(f, 1), "ema"))


@pytest.mark.parametrize("tf", [1, 3, 5])
def test_signal_prefix_invariance_and_fifty_bar_warmup(tf):
    f = minutes()
    full, prefix = timeframe_signals(f, tf), timeframe_signals(f.iloc[:300], tf)
    pd.testing.assert_frame_equal(full.loc[prefix.index], prefix)
    assert not full.iloc[:49].direction.ne("").any()


def test_aggregation_rejects_partial_buckets_and_ready_resets_after_gap():
    f = minutes()
    original = timeframe_signals(f, 3)
    g = timeframe_signals(f.drop(f.index[181]), 3)
    missing_close = pd.Timestamp("2025-01-02 12:18", tz="Asia/Kolkata")
    assert missing_close in original.index and missing_close not in g.index
    assert not g.loc["2025-01-02 12:21":"2025-01-02 12:27"].direction.ne("").any()
    expected = f.loc["2025-01-02 09:16":"2025-01-02 09:18"]
    assert original.iloc[0].open == expected.iloc[0].open
    assert original.iloc[0].close == expected.iloc[-1].close


@pytest.mark.parametrize("zone", ["Asia/Kolkata", "UTC"])
def test_entry_window_boundaries_are_ist_and_do_not_change_history(zone):
    times = ["09:14", "09:15", "10:14", "10:15", "14:29", "14:30", "15:10", "15:30"]
    ix = pd.DatetimeIndex([f"2025-01-02 {t}:00+05:30" for t in times]).tz_convert(zone)
    f = pd.DataFrame({"direction": "CE", "close": 100.0}, index=ix)
    opening = entry_window(f, "opening")
    closing = entry_window(f, "closing")
    assert opening.direction.ne("").to_list() == [
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ]
    assert closing.direction.ne("").to_list() == [
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        False,
    ]
    assert f.direction.eq("CE").all()
    pd.testing.assert_series_equal(opening.close, f.close)


def test_invalid_timeframe_or_window_fails():
    with pytest.raises(ValueError):
        timeframe_signals(minutes(), 2)
    with pytest.raises(ValueError):
        entry_window(timeframe_signals(minutes(), 1), "afternoon")


def test_baseline_option_sources_must_match_before_reuse(tmp_path):
    import hashlib
    import json

    from scripts.verify_stockgro_timeframes import check_baseline_option_sources

    baseline = tmp_path / "baseline"
    audit = baseline / "ema-1m/option-audit"
    audit.mkdir(parents=True)
    registration = baseline / "registered-experiment.json"
    registration.write_text("{}")
    prices = tmp_path / "options.parquet"
    prices.write_bytes(b"original-price-evidence")
    (audit / "option-inputs.json").write_text(
        json.dumps(
            {
                "manifest_sha256": hashlib.sha256(registration.read_bytes()).hexdigest(),
                "inputs": {"options.parquet": hashlib.sha256(prices.read_bytes()).hexdigest()},
            }
        )
    )
    assert check_baseline_option_sources(baseline, tmp_path) == 1
    prices.write_bytes(b"changed-price-evidence")
    with pytest.raises(AssertionError, match="options.parquet"):
        check_baseline_option_sources(baseline, tmp_path)
