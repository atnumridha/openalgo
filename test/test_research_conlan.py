"""Independent mathematical and causality checks for the repository adaptations."""

import numpy as np
import pandas as pd
import pytest

from services.research import conlan


def candles():
    index = pd.date_range("2025-01-01 09:20", periods=180, freq="5min", tz="Asia/Kolkata")
    close = 100 + np.sin(np.arange(len(index)) / 5) * 5
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close}, index=index
    )


@pytest.mark.parametrize("family", ["sma_macd", "bollinger"])
def test_signals_match_math_and_are_unchanged_by_future(family):
    frame = candles()
    actual = conlan.rule_signals(frame, family)
    if family == "sma_macd":
        sign = np.sign(frame.close.rolling(5).mean() - frame.close.rolling(34).mean())
        expected = sign.where(sign.ne(sign.shift()), 0).fillna(0)
    else:
        mean, std = frame.close.rolling(20).mean(), frame.close.rolling(20).std(ddof=1)
        expected = pd.Series(
            np.where(
                frame.close < mean - 2 * std, 1, np.where(frame.close > mean + 2 * std, -1, 0)
            ),
            index=frame.index,
        )
    np.testing.assert_array_equal(actual.signal, expected)
    changed = frame.copy()
    changed.iloc[100:] *= 2
    pd.testing.assert_frame_equal(
        actual.iloc[:100], conlan.rule_signals(changed, family).iloc[:100]
    )
    assert actual.direction.isin(["CE", "PE", ""]).all()


def test_calendar_lag_uses_past_asof_and_cusum_resets():
    s = pd.Series(
        [10.0, 20.0, 30.0],
        index=pd.to_datetime(["2025-01-01", "2025-01-04", "2025-01-10"], utc=True),
    )
    assert conlan.calendar_change(s, 5).iloc[-1] == 10  # Jan 4, not future Jan 10
    assert conlan.calendar_change(s, 5).iloc[:2].isna().all()
    changes = pd.Series(
        [0.6, 0.6, -0.7, -0.7], index=pd.date_range("2025-01-01", periods=4, tz="UTC")
    )
    assert list(conlan.cusum_events(changes, 1)) == list(changes.index[[1, 3]])
    with pytest.raises(ValueError):
        conlan.cusum_events(changes, 0)


def test_barriers_do_not_invent_unobserved_vertical_exits():
    idx = pd.date_range("2025-01-01 10:00", periods=5, freq="min", tz="UTC")
    prices = pd.Series([100.0, 101.0, 103.0, 102.0, 100.0], index=idx)
    labels = conlan.triple_barriers(
        prices, idx[[0, 3]], horizon=pd.Timedelta(minutes=3), upper=0.02, lower=-0.02
    )
    assert labels.iloc[0].label == 1 and labels.iloc[0].exit_at == idx[2]
    assert pd.isna(labels.iloc[1].label) and pd.isna(labels.iloc[1].exit_at)
    neutral = conlan.triple_barriers(
        prices, idx[:1], horizon=pd.Timedelta(minutes=3), upper=0.2, lower=-0.2
    )
    assert neutral.iloc[0].label == 0 and neutral.iloc[0].exit_at == idx[3]
    missing = pd.Series([100.0, 103.0], index=idx[[0, 2]])
    gap = conlan.triple_barriers(missing, idx[:1], horizon="1min", bar_interval="1min")
    assert pd.isna(gap.iloc[0].label)


def test_sma_macd_emits_first_observable_sign_after_warmup():
    frame = candles().iloc[:40].copy()
    for key in ("open", "high", "low", "close"):
        frame[key] = np.arange(40) + 100.0
    result = conlan.rule_signals(frame, "sma_macd")
    assert result.signal.iloc[:33].eq(0).all()
    assert result.signal.iloc[33] == 1


def test_event_weights_penalize_concurrent_events():
    idx = pd.date_range("2025-01-01", periods=5, tz="UTC")
    events = pd.Series([idx[1], idx[1], idx[4]], index=idx[[0, 0, 3]])
    np.testing.assert_allclose(conlan.event_uniqueness(events, idx), [0.5, 0.5, 1.0])


def test_revenue_features_use_release_time_not_period_end():
    idx = pd.date_range("2023-01-01", periods=800, tz="UTC")
    prices = pd.Series(100 + np.arange(800) * 0.1, index=idx)
    releases = pd.DataFrame(
        {
            "period_end": ["2022-12-31", "2023-12-31"],
            "available_at": [idx[40], idx[420]],
            "revenue": [100.0, 130.0],
        }
    )
    before = conlan.alternative_features(prices, releases)
    changed = releases.copy()
    changed.loc[1, "revenue"] = 1000
    after = conlan.alternative_features(prices, changed)
    pd.testing.assert_frame_equal(before.iloc[:420], after.iloc[:420])
    assert before.revenue.iloc[:40].isna().all()
    assert before.revenue.iloc[419] == 100 and before.revenue.iloc[420] == 130
    with pytest.raises(ValueError, match="available_at"):
        conlan.alternative_features(prices, releases.drop(columns="available_at"))
    revised = pd.concat(
        [
            releases,
            pd.DataFrame(
                {"period_end": ["2022-12-31"], "available_at": [idx[450]], "revenue": [105.0]}
            ),
        ],
        ignore_index=True,
    )
    assert conlan.alternative_features(prices, revised).revenue.iloc[450] == 130


def test_preference_execution_is_lagged_and_controls_are_seeded():
    idx = pd.date_range("2025-01-01", periods=110, tz="UTC")
    closes = pd.DataFrame({"A": np.arange(110) + 100.0, "B": 200 - np.arange(110) * 0.2}, index=idx)
    sig = pd.DataFrame(1, index=idx, columns=closes.columns)
    pref = pd.DataFrame({"A": np.ones(110), "B": np.zeros(110)}, index=idx)
    result = conlan.preference_portfolio(closes, sig, pref, max_positions=1)
    assert result["trades"][0]["signal_at"] == idx[0].isoformat()
    assert result["trades"][0]["entry_at"] == idx[1].isoformat()
    assert result["trades"][0]["symbol"] == "A"
    a = conlan.preference_controls(closes, sig, repeats=3, window=10)
    assert a == conlan.preference_controls(closes, sig, repeats=3, window=10)
    assert a["white_noise"]["repeats"] == 3
    with pytest.raises(ValueError, match="two"):
        conlan.preference_controls(closes[["A"]], sig[["A"]], repeats=3)


def test_extended_metrics_include_initial_loss_and_require_benchmark_alignment():
    idx = pd.date_range("2025-01-01", periods=4, tz="UTC")
    result = conlan.equity_metrics(pd.Series([100.0, 90.0, 95.0, 110.0], index=idx))
    assert result["max_drawdown_cash"] == 10
    assert result["max_drawdown_pct"] == pytest.approx(10)
    assert result["drawdown_peak_at"] == idx[0].isoformat()
    assert result["jensen_alpha_per_period"] is None
    assert result["log_return_minus_max_log_drawdown"] == pytest.approx(
        np.log(1.1) - np.log(100 / 90)
    )


def test_money_flow_requires_actual_volume_and_handles_flat_bars():
    frame = candles()
    with pytest.raises(ValueError, match="volume"):
        conlan.money_flow(frame)
    frame["volume"] = 100
    frame["close"] = frame.high
    flow = conlan.money_flow(frame)
    assert flow.chaikin_money_flow.iloc[-1] == pytest.approx(1.0)
    frame.iloc[-1, frame.columns.get_indexer(["open", "high", "low", "close"])] = 100
    assert pd.isna(conlan.money_flow(frame).chaikin_money_flow.iloc[-1])


def test_event_classifier_keeps_unlabelled_target_opportunities():
    idx = pd.date_range("2025-01-01", periods=100, tz="UTC")
    price = pd.Series(100 + np.sin(np.arange(100) / 3) * 5, index=idx)
    feature = pd.DataFrame({"lag_return": price.pct_change(fill_method=None).shift()}, index=idx)
    result = conlan.event_model_study(price, feature, idx, horizon="3D", estimators=50)
    changed = price.copy()
    changed.iloc[75:] = 100
    other = conlan.event_model_study(changed, feature, idx, horizon="3D", estimators=50)
    assert result["feature_importance"] == other["feature_importance"]
    assert [r["label"] for r in result["predictions"]] == [r["label"] for r in other["predictions"]]
    assert result["evaluation_events"] == other["evaluation_events"]
    assert other["labelled_evaluation_events"] < other["evaluation_events"]
    assert not result["deployment_supported"]


def test_revenue_pipeline_builds_only_post_training_portfolio():
    index = pd.date_range("2020-01-01", periods=1000, tz="UTC")
    prices = pd.Series(100 + 5 * np.sin(np.arange(1000) / 15), index=index)
    releases = pd.DataFrame(
        {
            "period_end": index[::90],
            "available_at": index[::90] + pd.Timedelta(days=5),
            "revenue": 100 + 20 * np.arange(len(index[::90])),
        }
    )
    result = conlan.alternative_data_study(prices, releases, threshold=0.05, horizon="5D")
    assert result["training_events"] >= 20
    assert not result["deployment_supported"]
    first = result["predictions"][0]["timestamp"]
    assert all(t["entry_at"] > first for t in result["portfolio"]["trades"])
    assert result["portfolio"]["abstract_asset_simulation"] is True
