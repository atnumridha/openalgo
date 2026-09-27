"""Bounded, validated JSON RandomForest inference without executable deserialization."""

import math
import re

import numpy as np

MAX_TREES = 500
MAX_TREE_NODES = 8191
MAX_TOTAL_NODES = 500_000
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _number(value, name, *, minimum=None, maximum=1e15):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"ML artifact {name} must be numeric")
    result = float(value)
    if (
        not math.isfinite(result)
        or abs(result) > maximum
        or (minimum is not None and result < minimum)
    ):
        raise ValueError(f"ML artifact {name} is outside finite bounds")
    return result


def _integer(value, name):
    if type(value) is not int:
        raise ValueError(f"ML artifact {name} must be an integer")
    return value


def validate_artifact(artifact, expected_features=None):
    """Reject malformed/unreachable trees before any scoring or selection."""
    from services.research.ml import ML_FEATURES

    if not isinstance(artifact, dict) or artifact.get("schema_version") != 2:
        raise ValueError("Unsupported ML artifact schema")
    features = artifact.get("features")
    expected = list(expected_features or ML_FEATURES)
    if features != expected or len(features) != len(set(features)):
        raise ValueError("ML artifact feature recipe differs from the frozen model")
    if artifact.get("feature_recipe") != "causal-two-session-v1":
        raise ValueError("ML artifact feature recipe is unavailable")
    if not isinstance(artifact.get("training_hash"), str) or not _HASH.fullmatch(
        artifact["training_hash"]
    ):
        raise ValueError("ML artifact training identity is missing")
    if artifact.get("weighting") != "session_balanced_average_uniqueness":
        raise ValueError("ML artifact weighting recipe is invalid")
    weight_hash = artifact.get("sample_weight_hash")
    if not isinstance(weight_hash, str) or not _HASH.fullmatch(weight_hash):
        raise ValueError("ML artifact sample-weight identity is missing")
    importance = artifact.get("feature_importance")
    if not isinstance(importance, dict) or set(importance) != set(features):
        raise ValueError("ML artifact feature importance is malformed")
    for feature, value in importance.items():
        _number(value, f"importance {feature}", minimum=0, maximum=1)
    dependencies = artifact.get("dependencies")
    if (
        not isinstance(dependencies, dict)
        or dependencies.get("available") is not True
        or not all(
            isinstance(dependencies.get(key), str) and dependencies[key]
            for key in ("sklearn_version", "numpy_version", "pandas_version")
        )
    ):
        raise ValueError("ML artifact dependency provenance is malformed")
    trees = artifact.get("trees")
    if not isinstance(trees, list) or len(trees) > MAX_TREES:
        raise ValueError("ML artifact exceeds the tree bound")
    if "constant" in artifact:
        if trees or _number(artifact["constant"], "constant", minimum=0, maximum=1) not in (0, 1):
            raise ValueError("ML artifact constant classifier is malformed")
        return artifact
    if not trees or artifact.get("classes") != [0, 1]:
        raise ValueError("ML artifact must contain two ordered classes and trees")
    total = 0
    for tree in trees:
        if not isinstance(tree, dict):
            raise ValueError("ML artifact tree is malformed")
        keys = ("children_left", "children_right", "feature", "threshold", "value")
        columns = [tree.get(key) for key in keys]
        if not all(isinstance(column, list) for column in columns):
            raise ValueError("ML artifact tree arrays are required")
        count = len(columns[0])
        total += count
        if (
            not 1 <= count <= MAX_TREE_NODES
            or total > MAX_TOTAL_NODES
            or any(len(column) != count for column in columns)
        ):
            raise ValueError("ML artifact tree node count is invalid")
        left, right, feature, threshold, value = columns
        for node in range(count):
            lo = _integer(left[node], "left child")
            hi = _integer(right[node], "right child")
            split = _integer(feature[node], "feature index")
            _number(threshold[node], "threshold")
            classes = value[node]
            if (
                not isinstance(classes, list)
                or len(classes) != 1
                or not isinstance(classes[0], list)
                or len(classes[0]) != 2
            ):
                raise ValueError("ML artifact class values are malformed")
            counts = [_number(item, "class value", minimum=0) for item in classes[0]]
            if counts[0] + counts[1] <= 0:
                raise ValueError("ML artifact node has no class mass")
            if lo == hi == -1:
                if split != -2:
                    raise ValueError("ML artifact leaf feature is invalid")
            elif not (
                0 <= lo < count and 0 <= hi < count and lo != hi and 0 <= split < len(features)
            ):
                raise ValueError("ML artifact split is invalid")
        seen = set()
        pending = [0]
        while pending:
            node = pending.pop()
            if node in seen:
                raise ValueError("ML artifact tree has a cycle or duplicate parent")
            seen.add(node)
            if left[node] != -1:
                pending.extend((left[node], right[node]))
        if len(seen) != count:
            raise ValueError("ML artifact tree contains unreachable nodes")
    return artifact


def predict_probabilities(artifact, values):
    """Match sklearn's float32 feature conversion and <= threshold traversal."""
    validate_artifact(artifact)
    matrix = np.asarray(values, dtype=np.float64)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != len(artifact["features"])
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("ML inference requires a finite feature matrix")
    with np.errstate(over="ignore"):
        matrix = matrix.astype(np.float32)
    if not np.isfinite(matrix).all():
        raise ValueError("ML inference features exceed float32 bounds")
    if "constant" in artifact:
        return np.full(matrix.shape[0], artifact["constant"], dtype=float)
    result = np.zeros(matrix.shape[0], dtype=float)
    for tree in artifact["trees"]:
        left, feature, threshold, value = (
            tree["children_left"],
            tree["feature"],
            tree["threshold"],
            tree["value"],
        )
        right = tree["children_right"]
        for row_index, row in enumerate(matrix):
            node = 0
            while left[node] != -1:
                node = left[node] if row[feature[node]] <= threshold[node] else right[node]
            counts = value[node][0]
            result[row_index] += counts[1] / (counts[0] + counts[1])
    return result / len(artifact["trees"])
