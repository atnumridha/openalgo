"""A frozen forest is safe to load and predicts exactly as its fitted source."""

from copy import deepcopy

import numpy as np
import pytest
from test_research_random_forest import opportunities

from services.research import ml
from services.research.ml_artifact import predict_probabilities, validate_artifact


def fitted():
    frame = opportunities()
    days = list(frame.timestamp.str[:10].unique())
    training = frame[frame.timestamp.str[:10].isin(days[:10])]
    model, artifact = ml._fit_forest(training, seed=42, estimators=50)
    return model, artifact, frame


def test_json_forest_matches_sklearn_at_threshold_boundaries():
    model, artifact, frame = fitted()
    x = frame.loc[:, ml.ML_FEATURES].to_numpy(dtype=float)
    tree = model.estimators_[0].tree_
    features = [int(i) for i in tree.feature if i >= 0]
    thresholds = [float(t) for t, i in zip(tree.threshold, tree.feature, strict=True) if i >= 0]
    for feature, threshold in zip(features[:5], thresholds[:5], strict=True):
        for value in (
            np.nextafter(np.float32(threshold), -np.inf),
            threshold,
            np.nextafter(np.float32(threshold), np.inf),
        ):
            row = x[0].copy()
            row[feature] = value
            x = np.vstack((x, row))
    assert predict_probabilities(artifact, x) == pytest.approx(
        model.predict_proba(x)[:, 1], abs=1e-12
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a["trees"][0]["children_left"].__setitem__(0, 0),
        lambda a: a["trees"][0]["feature"].__setitem__(0, 999),
        lambda a: a["trees"][0]["threshold"].__setitem__(0, float("nan")),
        lambda a: a["trees"][0]["value"].__setitem__(0, [[-1, 2]]),
        lambda a: a.__setitem__("features", ["wrong"]),
    ],
)
def test_malformed_forest_is_refused(mutate):
    _, source, _ = fitted()
    artifact = deepcopy(source)
    mutate(artifact)
    with pytest.raises(ValueError):
        validate_artifact(artifact)
