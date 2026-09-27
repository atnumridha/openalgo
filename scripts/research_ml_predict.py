"""Registered offline prediction-quality experiment; no order access."""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts.research_ml_search import COMPACT_FEATURES, FOLDS
from scripts.research_ml_train import file_hash, load_development, read_json, write_json
from services.research.jobs import implementation_hash
from services.research.ml import assert_chronology, build_opportunities, technical_features
from services.research.ml_prediction import (
    align_direction,
    daily_mse,
    fit_calibration,
    paired_daily_interval,
    prediction_metrics,
    recent_sessions,
    reliability_bins,
    session_weights,
    training_weights,
)
from utils.logging import get_logger

logger = get_logger(__name__)
SPECS = (
    {"id": "original-ridge10", "aligned": False, "alpha": 10},
    {"id": "aligned-ridge10", "aligned": True, "alpha": 10},
    {"id": "aligned-ridge1000", "aligned": True, "alpha": 1000},
    {"id": "aligned-ridge10000", "aligned": True, "alpha": 10000},
    {"id": "recent-ridge1000", "aligned": True, "alpha": 1000, "recent": 60},
    {"id": "recent-ridge10000", "aligned": True, "alpha": 10000, "recent": 60},
    {"id": "aligned-boosted", "aligned": True, "boosted": True},
    {"id": "unique-ridge1000", "aligned": True, "alpha": 1000, "uniqueness": True},
)


def make_model(spec):
    if spec.get("boosted"):
        return HistGradientBoostingRegressor(
            max_iter=100,
            max_leaf_nodes=3,
            min_samples_leaf=200,
            learning_rate=0.03,
            l2_regularization=30,
            early_stopping=False,
            random_state=42,
        )
    return make_pipeline(StandardScaler(), Ridge(alpha=spec["alpha"]))


def inputs(table, spec):
    values = table[list(COMPACT_FEATURES)]
    return align_direction(values) if spec["aligned"] else values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    previous = ROOT / "data/research/ml-walkforward-2026-09-26-verified"
    old = read_json(previous / "registered-search.json")
    if implementation_hash() != old["implementation_hash"]:
        raise ValueError("Shared risk/cost implementation changed; rebuild labels")
    for path, expected in old["source_hashes"].items():
        if file_hash(ROOT / path) != expected:
            raise ValueError(f"Cached feature implementation changed: {path}")
    plan = ROOT / "docs/plans/2026-09-26-ml-prediction-improvement.md"
    manifest = {
        "plan_hash": file_hash(plan),
        "implementation_hash": implementation_hash(),
        "source_hashes": {
            p: file_hash(ROOT / p)
            for p in (
                "scripts/research_ml_predict.py",
                "services/research/ml_prediction.py",
                "services/research/ml.py",
                "scripts/research_ml_train.py",
                "scripts/research_ml_search.py",
            )
        },
        "input_hashes": {
            k: file_hash(previous / f"opportunities-{k}.parquet")
            for k in ("q1", "q2", "q3", "q4", "2026")
        },
        "versions": {
            "sklearn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "specs": SPECS,
        "features": list(COMPACT_FEATURES),
        "folds": FOLDS,
        "calibration": {"penalty": 0.05, "slope_bounds": [0, 1], "first_selection_sessions": 30},
        "evidence_role": "Reused development periods; no final confirmation",
        "reserved_sessions_used": 0,
        "costs": old["costs"],
    }
    write_json(out / "registered-prediction-experiment.json", manifest)
    manifest_hash = file_hash(out / "registered-prediction-experiment.json")
    tables = {
        k: pd.read_parquet(previous / f"opportunities-{k}.parquet")
        for k in manifest["input_hashes"]
    }
    if any(t.timestamp.max()[:10] >= "2026-04-24" for t in tables.values()):
        raise ValueError("Reserved dates in prediction development data")
    data_root = ROOT / "data/research/robustness-2026-09-26"
    paths = {f"q{q}": data_root / f"nifty-2025-q{q}-robustness.json" for q in range(1, 5)}
    paths["2026"] = (
        ROOT / "data/research/filtered-minute-2026-09-26/nifty-2026-mixed-resolution.json"
    )
    expected = read_json(previous / "datasets.json")
    parts = {}
    for key, path in paths.items():
        if file_hash(path) != expected[key]["source_file_hash"]:
            raise ValueError("Historical source changed")
        parts[key] = load_development(path, "2025-01-01", "2026-04-23")
        if parts[key]["content_hash"] != expected[key]["development_content_hash"]:
            raise ValueError("Normalized data changed")
    write_json(out / "datasets.json", expected)
    results = []
    for fold in FOLDS:
        folder = out / fold["id"]
        folder.mkdir()
        all_training = pd.concat([tables[k] for k in fold["train"]], ignore_index=True)
        fit = all_training.dropna(subset=["net_r", "label_exit_at"]).sort_values("timestamp")
        split_day = sorted(parts[fold["calibration"]]["sessions"])[30]
        middle = tables[fold["calibration"]]
        calibration = middle[middle.timestamp.str[:10] < split_day].dropna(
            subset=["net_r", "label_exit_at"]
        )
        validation = middle[middle.timestamp.str[:10] >= split_day].dropna(
            subset=["net_r", "label_exit_at"]
        )
        later = tables[fold["later"]]
        assert_chronology(fit, calibration)
        assert_chronology(calibration, validation)
        assert_chronology(validation, later)
        candidates, models = [], {}
        training_mean = float(np.average(fit.net_r.clip(-3, 3), weights=training_weights(fit)))
        calibration_mean = float(
            np.average(calibration.net_r, weights=session_weights(calibration.timestamp))
        )
        for spec in SPECS:
            train = recent_sessions(fit, spec["recent"]) if spec.get("recent") else fit
            weight = training_weights(train, uniqueness=spec.get("uniqueness", False))
            model = make_model(spec)
            kwargs = (
                {"sample_weight": weight}
                if spec.get("boosted")
                else {"ridge__sample_weight": weight}
            )
            model.fit(inputs(train, spec), train.net_r.clip(-3, 3), **kwargs)
            models[spec["id"]] = model
            with (folder / f"{spec['id']}.joblib").open("wb") as stream:
                joblib.dump(model, stream)
            model_hash = file_hash(folder / f"{spec['id']}.joblib")
            cal_score = model.predict(inputs(calibration, spec))
            val_score = model.predict(inputs(validation, spec))
            parameters = fit_calibration(cal_score, calibration.net_r, calibration.timestamp)
            calibration[["timestamp", "symbol", "net_r"]].assign(prediction=cal_score).to_parquet(
                folder / f"{spec['id']}-calibration.parquet", index=False
            )
            validation[["timestamp", "symbol", "net_r"]].assign(prediction=val_score).to_parquet(
                folder / f"{spec['id']}-validation.parquet", index=False
            )
            for mode, transform in (
                ("raw", {"slope": 1.0, "intercept": 0.0}),
                ("calibrated", parameters),
            ):
                predicted = val_score * transform["slope"] + transform["intercept"]
                candidates.append(
                    {
                        "id": f"{spec['id']}-{mode}",
                        "spec": spec,
                        "mode": mode,
                        "transform": transform,
                        "model_hash": model_hash,
                        "metrics": prediction_metrics(
                            validation.net_r, predicted, validation.timestamp
                        ),
                        "training_rows": len(train),
                        "training_sessions": int(train.timestamp.str[:10].nunique()),
                    }
                )
        chosen = min(candidates, key=lambda c: (c["metrics"]["mse"], c["metrics"]["mae"], c["id"]))
        frozen = {
            "fold": fold,
            "selected": chosen,
            "all_candidates": candidates,
            "training_mean": training_mean,
            "calibration_mean": calibration_mean,
            "training_last_label": fit.label_exit_at.max(),
            "calibration_first": calibration.timestamp.min(),
            "calibration_last_label": calibration.label_exit_at.max(),
            "validation_first": validation.timestamp.min(),
            "validation_last_label": validation.label_exit_at.max(),
            "later_first": later.timestamp.min(),
            "split_day": split_day,
        }
        write_json(folder / "frozen-selection.json", frozen)
        frozen_hash = file_hash(folder / "frozen-selection.json")
        # Labels for the last period are first constructed after its choice is frozen.
        if "net_r" not in later:
            spot_path = ROOT / "data/research/five-minute-2026-09-26/NIFTY-spot-5m.parquet"
            old_spot = read_json(
                ROOT / "data/research/technical-ml-2026-09-26-corrected/feature-source.json"
            )
            if file_hash(spot_path) != old_spot["file_hash"]:
                raise ValueError("Underlying source changed")
            spot = pd.read_parquet(spot_path)
            spot = spot[spot.bar_close.dt.strftime("%Y-%m-%d") < "2026-04-24"].set_index(
                "bar_close"
            )
            underlying = technical_features(spot[["open", "high", "low", "close", "volume"]])
            labelled, audit = build_opportunities(
                parts[fold["later"]], underlying, old["costs"], labels=True
            )
            compare = [c for c in later.columns if c != "predicted_net_r"]
            pd.testing.assert_frame_equal(labelled[compare], later[compare])
            later = labelled
            later.to_parquet(out / "opportunities-2026-labelled.parquet", index=False)
            write_json(out / "label-audit.json", audit)
            del spot, underlying, labelled
        selected_model = models[chosen["spec"]["id"]]
        raw = selected_model.predict(inputs(later, chosen["spec"]))
        predicted = raw * chosen["transform"]["slope"] + chosen["transform"]["intercept"]
        original = models["original-ridge10"].predict(inputs(later, SPECS[0]))
        available = later.net_r.notna() & later.label_exit_at.notna()
        observed = later.loc[available]
        forecasts = {
            "selected": predicted[available],
            "original_ridge": original[available],
            "training_mean": np.repeat(training_mean, int(available.sum())),
            "calibration_mean": np.repeat(calibration_mean, int(available.sum())),
        }
        metrics = {
            k: prediction_metrics(observed.net_r, v, observed.timestamp)
            for k, v in forecasts.items()
        }
        daily = {k: daily_mse(observed.net_r, v, observed.timestamp) for k, v in forecasts.items()}
        comparisons = {
            k: paired_daily_interval(daily["selected"], v)
            for k, v in daily.items()
            if k != "selected"
        }
        for k, v in comparisons.items():
            v["mse_improvement_pct"] = 100 * (1 - metrics["selected"]["mse"] / metrics[k]["mse"])
        daily_frame = pd.DataFrame(daily)
        daily_frame.to_csv(folder / "daily-errors.csv", index_label="session")
        saved = later[["timestamp", "direction", "symbol", "net_r", "label_exit_at"]].copy()
        saved["prediction"] = predicted
        saved["original_prediction"] = original
        saved.to_parquet(folder / "later-predictions.parquet", index=False)
        evaluation = {
            "fold": fold,
            "selected": chosen["id"],
            "metrics": metrics,
            "comparisons": comparisons,
            "reliability": reliability_bins(
                observed.net_r, forecasts["selected"], observed.timestamp
            ),
            "selection_hash": frozen_hash,
            "unavailable_labels": int((~available).sum()),
        }
        assert file_hash(folder / "frozen-selection.json") == frozen_hash
        write_json(folder / "evaluation.json", evaluation)
        results.append(evaluation)
        logger.info(
            "%s selected=%s MSE=%.6f vs original=%.6f; mean=%.6f; recent mean=%.6f",
            fold["id"],
            chosen["id"],
            metrics["selected"]["mse"],
            metrics["original_ridge"]["mse"],
            metrics["training_mean"]["mse"],
            metrics["calibration_mean"]["mse"],
        )
    checks = {
        "all_periods_beat_every_control_by_one_percent": all(
            c["mse_improvement_pct"] >= 1 for r in results for c in r["comparisons"].values()
        ),
        "all_periods_lower_mae_than_original": all(
            r["metrics"]["selected"]["mae"] < r["metrics"]["original_ridge"]["mae"] for r in results
        ),
        "all_paired_upper_bounds_below_zero": all(
            c["upper_95"] < 0 for r in results for c in r["comparisons"].values()
        ),
        "at_least_forty_labeled_sessions_each": all(
            r["metrics"]["selected"]["sessions"] >= 40 for r in results
        ),
    }
    assert file_hash(plan) == manifest["plan_hash"]
    assert file_hash(out / "registered-prediction-experiment.json") == manifest_hash
    write_json(
        out / "results.json",
        {
            "fits": 24,
            "validation_variants": 48,
            "folds": results,
            "checks": checks,
            "passes_prediction_screen": all(checks.values()),
            "eligible_for_live": False,
            "reserved_sessions_used": 0,
            "manifest_hash": manifest_hash,
        },
    )
    logger.info("Prediction experiment complete: %s", checks)


if __name__ == "__main__":
    main()
