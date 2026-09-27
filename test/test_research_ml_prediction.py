"""Prediction-specific safeguards, with independently calculated expectations."""

import numpy as np
import pandas as pd
import pytest


def test_direction_alignment_handles_opposite_call_put_trends_and_breakouts():
    from services.research.ml_prediction import align_direction

    data = pd.DataFrame(
        {
            "direction_ce": [1.0, 0.0],
            "u_return_3": [0.02, -0.02],
            "u_rsi": [0.7, 0.3],
            "u_close_location": [0.8, 0.2],
            "u_high_break_distance": [0.01, -0.04],
            "u_low_break_distance": [0.04, -0.01],
            "u_atr_fraction": [0.003, 0.003],
            "moneyness": [0.01, -0.01],
            "o_return_3": [0.03, 0.03],
        }
    )
    got = align_direction(data)
    np.testing.assert_allclose(got.u_return_3, [0.02, 0.02])
    np.testing.assert_allclose(got.u_rsi, [0.2, 0.2])
    np.testing.assert_allclose(got.u_close_location, [0.3, 0.3])
    np.testing.assert_allclose(got.u_high_break_distance, [0.01, 0.01])
    np.testing.assert_allclose(got.u_low_break_distance, [0.04, 0.04])
    np.testing.assert_allclose(got.moneyness, [0.01, 0.01])
    np.testing.assert_allclose(got.o_return_3, [0.03, 0.03])
    np.testing.assert_allclose(got.u_atr_fraction, [0.003, 0.003])
    assert data.u_return_3.tolist() == [0.02, -0.02]
    pd.testing.assert_frame_equal(align_direction(data.iloc[:1]), got.iloc[:1])
    with pytest.raises(ValueError, match="direction"):
        align_direction(data.assign(direction_ce=2))


def test_session_weights_prevent_a_busy_day_dominating_prediction_error():
    from services.research.ml_prediction import prediction_metrics

    dates = ["2025-01-01T10:00:00+05:30", "2025-01-02T10:00:00+05:30", "2025-01-02T10:05:00+05:30"]
    result = prediction_metrics(np.array([2.0, 0.0, 0.0]), np.zeros(3), dates)
    assert result["mse"] == pytest.approx(2)
    assert result["mae"] == pytest.approx(1)
    assert result["bias"] == pytest.approx(-1)
    assert result["sessions"] == 2
    assert result["rank_correlation"] is None
    with pytest.raises(ValueError, match="finite"):
        prediction_metrics(np.array([float("nan")]), np.zeros(1), dates[:1])


def test_overlapping_labels_have_lower_weight_than_isolated_labels():
    from services.research.ml_prediction import training_weights

    frame = pd.DataFrame(
        {
            "timestamp": [f"2025-01-01T{t}:00+05:30" for t in ("09:20", "09:20", "10:00")],
            "label_exit_at": [f"2025-01-01T{t}:00+05:30" for t in ("09:30", "09:30", "10:10")],
        }
    )
    weights = training_weights(frame, uniqueness=True)
    np.testing.assert_allclose(weights, [0.75, 0.75, 1.5])
    np.testing.assert_allclose(training_weights(frame), [1, 1, 1])


def test_calibration_cannot_invert_or_amplify_a_noisy_forecast():
    from services.research.ml_prediction import fit_calibration

    dates = ["2025-01-01", "2025-01-02"]
    inverse = fit_calibration(np.array([0.0, 1.0]), np.array([1.0, 0.0]), dates)
    assert inverse["slope"] == 0
    assert inverse["intercept"] == pytest.approx(0.5)
    positive = fit_calibration(np.array([0.0, 1.0]), np.array([0.0, 10.0]), dates)
    assert positive["slope"] == 1
    assert positive["intercept"] == pytest.approx(4.5)


def test_recent_training_uses_session_boundaries_not_row_counts():
    from services.research.ml_prediction import recent_sessions

    frame = pd.DataFrame(
        {
            "timestamp": [
                "2025-01-01T10:00",
                "2025-01-02T10:00",
                "2025-01-02T10:05",
                "2025-01-03T10:00",
            ]
        }
    )
    assert recent_sessions(frame, 2).timestamp.tolist() == [
        "2025-01-02T10:00",
        "2025-01-02T10:05",
        "2025-01-03T10:00",
    ]


def test_daily_bootstrap_pairs_same_days_and_rejects_misalignment():
    from services.research.ml_prediction import paired_daily_interval

    a = pd.Series([1.0] * 10, index=pd.date_range("2025-01-01", periods=10).strftime("%Y-%m-%d"))
    result = paired_daily_interval(a, a + 1)
    assert result["mean_difference"] == -1
    assert result["lower_95"] == -1 and result["upper_95"] == -1
    with pytest.raises(ValueError, match="same"):
        paired_daily_interval(a, (a + 1).iloc[::-1])
