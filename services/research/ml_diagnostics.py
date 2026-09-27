"""Offline training-reference drift checks; no automatic retraining or trading."""

import numpy as np


def feature_drift(reference, observed):
    """Compare later distributions with bins and bounds learned only on training.

    PSI is descriptive, not a p-value or probability of model failure. Missing
    values are reported separately, and a constant feature has explicit bounds.
    """
    if list(reference.columns) != list(observed.columns):
        raise ValueError("Feature columns must match in the recorded order")
    if reference.empty or observed.empty:
        raise ValueError("Drift comparison requires both periods")
    result = {}
    for column in reference:
        raw_train = reference[column].to_numpy(dtype=float)
        raw_later = observed[column].to_numpy(dtype=float)
        train = raw_train[np.isfinite(raw_train)]
        later = raw_later[np.isfinite(raw_later)]
        if not len(train) or not len(later):
            raise ValueError("Drift comparison requires finite observations")
        low, high = float(train.min()), float(train.max())
        if low == high:
            epsilon = max(abs(low) * 1e-9, 1e-9)
            interior = [low - epsilon, high + epsilon]
        else:
            interior = np.unique(np.quantile(train, np.arange(0.1, 1, 0.1)))
        bins = np.r_[-np.inf, interior, np.inf]
        # Fixed pseudocount makes empty bins finite without fitting test bins.
        a = np.histogram(train, bins=bins)[0] + 0.5
        b = np.histogram(later, bins=bins)[0] + 0.5
        a, b = a / a.sum(), b / b.sum()
        std = float(train.std())
        result[column] = {
            "psi": float(np.sum((b - a) * np.log(b / a))),
            "reference_min": low,
            "reference_max": high,
            "outside_training_range_fraction": float(np.mean((later < low) | (later > high))),
            "mean_shift_training_std": float((later.mean() - train.mean()) / std) if std else None,
            "reference_missing_fraction": float(1 - len(train) / len(raw_train)),
            "observed_missing_fraction": float(1 - len(later) / len(raw_later)),
        }
    return result
