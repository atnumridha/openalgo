"""Distribution checks must use training references, never test-fitted bounds."""

import pandas as pd
import pytest


def test_drift_detects_new_range_without_moving_training_reference():
    from services.research.ml_diagnostics import feature_drift

    reference = pd.DataFrame({"trend": range(100)})
    same = feature_drift(reference, reference)["trend"]
    shifted = feature_drift(reference, pd.DataFrame({"trend": range(200, 300)}))["trend"]
    assert same["psi"] == 0
    assert shifted["psi"] > 1
    assert shifted["outside_training_range_fraction"] == 1
    assert shifted["reference_min"] == same["reference_min"] == 0
    assert shifted["reference_max"] == same["reference_max"] == 99


def test_constant_training_feature_still_detects_change():
    from services.research.ml_diagnostics import feature_drift

    result = feature_drift(pd.DataFrame({"lots": [75] * 20}), pd.DataFrame({"lots": [65] * 20}))[
        "lots"
    ]
    assert result["outside_training_range_fraction"] == 1
    assert result["psi"] > 0
    assert result["mean_shift_training_std"] is None


def test_drift_refuses_missing_features_instead_of_silently_ignoring_them():
    from services.research.ml_diagnostics import feature_drift

    with pytest.raises(ValueError, match="columns"):
        feature_drift(pd.DataFrame({"x": [1, 2]}), pd.DataFrame({"y": [1, 2]}))
