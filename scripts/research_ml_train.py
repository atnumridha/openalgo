"""Train the registered technical ML experiment. Offline; never places orders.

UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync --with scikit-learn==1.7.2 \
    python scripts/research_ml_train.py --output data/research/technical-ml-2026-09-26
"""

import argparse
import hashlib
import json
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
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from services.research.dataset import digest, validate_dataset
from services.research.jobs import implementation_hash
from services.research.ml import (
    assert_chronology,
    build_opportunities,
    signal_schedule,
    technical_features,
    validation_qualifies,
)
from services.research.replay import run_replay, validate_configuration
from utils.logging import get_logger

logger = get_logger(__name__)
THRESHOLDS = (0.10, 0.20, 0.30)
SCENARIOS = {
    "base": {"slippage_bps": 10, "brokerage_per_order": 0},
    "stress": {"slippage_bps": 30, "brokerage_per_order": 20},
}


def read_json(path):
    with path.open() as stream:
        return json.load(stream)


def write_json(path, value):
    with path.open("w") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def file_hash(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def load_development(path, first, last):
    body = read_json(path)
    body["rows"] = [r for r in body["rows"] if first <= r["timestamp"][:10] <= last]
    symbols = {r["symbol"] for r in body["rows"]}
    body["metadata"]["contracts"] = [
        c for c in body["metadata"]["contracts"] if c["symbol"] in symbols
    ]
    return validate_dataset(body)


def merge_data(parts):
    contracts = {}
    for part in parts:
        for contract in part["metadata"]["contracts"]:
            if contract["symbol"] in contracts and contracts[contract["symbol"]] != contract:
                raise ValueError("Contract definitions changed between periods")
            contracts[contract["symbol"]] = contract
    body = {
        "name": "Continuous ML evaluation",
        "provider": "Existing local research sources",
        "metadata": parts[0]["metadata"] | {"contracts": list(contracts.values())},
        "rows": sorted(
            [r for p in parts for r in p["rows"]], key=lambda r: (r["timestamp"], r["symbol"])
        ),
    }
    return validate_dataset(body)


def evaluate(data, costs, schedule=None, model_hash=None):
    results = {}
    for name, changes in SCENARIOS.items():
        config = validate_configuration(data, "trend_breakout_filtered", {}, costs | changes)
        config["implementation_hash"] = implementation_hash()
        if schedule is not None:
            config.update(research_signal_hash=digest(schedule), research_model_hash=model_hash)
        results[name] = {
            "configuration": config,
            "report": run_replay(data, config, research_signals=schedule),
        }
    return results


def summary(results):
    return {name: result["report"]["metrics"] for name, result in results.items()}


def selection_key(item):
    base, stress = item["metrics"]["base"], item["metrics"]["stress"]
    complete = base["net_pnl"] is not None and stress["net_pnl"] is not None
    enough = complete and min(base["trade_count"], stress["trade_count"]) >= 20
    return (
        enough,
        stress["net_pnl"] if complete else -float("inf"),
        base["net_pnl"] if complete else -float("inf"),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Train and evaluate technical ML locally; no order access."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    plan = ROOT / "docs/plans/2026-09-26-technical-ml-experiment.md"
    source_hashes = {
        name: file_hash(ROOT / name)
        for name in (
            "services/research/ml.py",
            "scripts/research_ml_train.py",
            "services/research/replay.py",
        )
    }
    original = read_json(ROOT / "data/research/robustness-2026-09-26/frozen-spec.json")
    costs = original["configuration"]["costs"] | {
        "effective_from": "2025-01-01",
        "effective_to": "2026-04-23",
        "schedule_id": "Hypothetical current Kotak NFO fees for offline ML research",
        "source": "Current configured Kotak rates applied hypothetically to historical prices; not a verified historical fee table. Same numerical assumptions as earlier research; no change to saved live costs.",
    }
    write_json(
        out / "registered-inputs.json",
        {
            "plan_sha256": file_hash(plan),
            "source_hashes": source_hashes,
            "implementation_hash": implementation_hash(),
            "sklearn_version": sklearn.__version__,
            "costs": costs,
            "thresholds": THRESHOLDS,
            "scenarios": SCENARIOS,
            "purpose": "Offline research only. No live qualification or order activation.",
        },
    )
    root = ROOT / "data/research/robustness-2026-09-26"
    paths = {f"q{q}": root / f"nifty-2025-q{q}-robustness.json" for q in range(1, 5)}
    paths["2026"] = (
        ROOT / "data/research/filtered-minute-2026-09-26/nifty-2026-mixed-resolution.json"
    )
    # Reserved rows and definitions are removed before any feature/label work.
    parts = {key: load_development(path, "2025-01-01", "2026-04-23") for key, path in paths.items()}
    assert all(max(p["sessions"]) < "2026-04-24" for p in parts.values())
    write_json(
        out / "datasets.json",
        {
            key: {
                "source_file_hash": file_hash(paths[key]),
                "development_content_hash": part["content_hash"],
                "dates": [min(part["sessions"]), max(part["sessions"])],
                "session_count": len(part["sessions"]),
                "row_count": part["row_count"],
            }
            for key, part in parts.items()
        },
    )
    spot_path = ROOT / "data/research/five-minute-2026-09-26/NIFTY-spot-5m.parquet"
    spot = pd.read_parquet(spot_path)
    spot = spot[spot.bar_close.dt.strftime("%Y-%m-%d") < "2026-04-24"].set_index("bar_close")
    underlying = technical_features(spot[["open", "high", "low", "close", "volume"]])
    write_json(
        out / "feature-source.json",
        {
            "file_hash": file_hash(spot_path),
            "rows_used": len(spot),
            "first_bar": spot.index.min().isoformat(),
            "last_bar": spot.index.max().isoformat(),
            "reserved_rows_used": 0,
        },
    )
    tables, audits = {}, {}
    for key in ("q1", "q2", "q3"):
        logger.info("Building technical features and option payoff labels for %s", key)
        tables[key], audits[key] = build_opportunities(parts[key], underlying, costs, labels=True)
        tables[key].to_parquet(out / f"opportunities-{key}.parquet", index=False)
        logger.info(
            "%s: %d observable opportunities, %d available payoff labels",
            key,
            len(tables[key]),
            tables[key].net_r.notna().sum(),
        )
    training = pd.concat([tables["q1"], tables["q2"]], ignore_index=True).sort_values("timestamp")
    validation = tables["q3"]
    fit = training.dropna(subset=["net_r", "label_exit_at"])
    assert_chronology(fit, validation)
    excluded = {"timestamp", "direction", "symbol", "net_r", "label_exit_at", "label_ambiguous"}
    features = [c for c in training.columns if c not in excluded]
    assert np.isfinite(training[features]).all().all()
    assert np.isfinite(validation[features]).all().all()
    if len(fit) < 1000 or fit.timestamp.str[:10].nunique() < 60:
        raise ValueError("Insufficient dated training observations")
    counts = fit.groupby(fit.timestamp.str[:10]).timestamp.transform("size")
    weight = len(fit) / fit.timestamp.str[:10].nunique() / counts
    target = fit.net_r.clip(-3, 3)
    models = {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=10)),
        "boosted_trees": HistGradientBoostingRegressor(
            max_iter=120,
            max_leaf_nodes=7,
            min_samples_leaf=100,
            learning_rate=0.05,
            l2_regularization=10,
            early_stopping=False,
            random_state=42,
        ),
    }
    candidates, hashes, predictions = [], {}, {}
    fit_metrics = {}
    for name, model in models.items():
        logger.info(
            "Fitting %s on %d observations and %d technical features", name, len(fit), len(features)
        )
        kwargs = {"ridge__sample_weight": weight} if name == "ridge" else {"sample_weight": weight}
        model.fit(fit[features], target, **kwargs)
        with (out / f"{name}.joblib").open("wb") as stream:
            joblib.dump(model, stream)
        hashes[name] = file_hash(out / f"{name}.joblib")
        predictions[name] = model.predict(validation[features])
        available = validation.net_r.notna()
        fit_metrics[name] = {
            "training_mse_clipped_target": mean_squared_error(
                target, model.predict(fit[features]), sample_weight=weight
            ),
            "validation_mse_raw_target": mean_squared_error(
                validation.loc[available, "net_r"], predictions[name][available]
            ),
            "validation_constant_mean_mse": mean_squared_error(
                validation.loc[available, "net_r"],
                np.repeat(np.average(target, weights=weight), available.sum()),
            ),
        }
        for threshold in THRESHOLDS:
            schedule = signal_schedule(validation, predictions[name], threshold)
            results = evaluate(parts["q3"], costs, schedule, hashes[name])
            item = {
                "model": name,
                "threshold": threshold,
                "metrics": summary(results),
                "signal_count": len(schedule),
            }
            candidates.append(item)
            write_json(
                out / f"validation-{name}-{threshold:.2f}.json",
                {"candidate": item, "signals": schedule, "results": results},
            )
            logger.info(
                "Validation %s threshold %.2f: %s", name, threshold, json.dumps(item["metrics"])
            )
    selected = max(candidates, key=selection_key)
    name, threshold = selected["model"], selected["threshold"]
    model = models[name]
    frozen = {
        "selected": selected,
        "model_hash": hashes[name],
        "features": features,
        "training_observations": len(fit),
        "training_sessions": int(fit.timestamp.str[:10].nunique()),
        "training_first": fit.timestamp.min(),
        "training_last_label": fit.label_exit_at.max(),
        "validation_sessions": len(parts["q3"]["sessions"]),
        "selection_candidates": candidates,
        "fit_metrics": fit_metrics,
        "selection_passes": validation_qualifies(selected["metrics"]),
        "note": "Frozen before later-period opportunities or outcomes are evaluated. Earlier rule research saw these dates.",
    }
    write_json(out / "frozen-selection.json", frozen)
    frozen_hash = file_hash(out / "frozen-selection.json")
    logger.info(
        "Selection frozen: %s at %.2f R. Beginning held-out ML evaluation.", name, threshold
    )
    evaluations, schedules = {}, {}
    for key in ("q4", "2026"):
        table, audits[key] = build_opportunities(parts[key], underlying, costs, labels=False)
        assert_chronology(training.dropna(subset=["label_exit_at"]), table)
        assert validation.timestamp.max() < table.timestamp.min()
        table["predicted_net_r"] = model.predict(table[features])
        table.to_parquet(out / f"opportunities-{key}.parquet", index=False)
        schedules[key] = signal_schedule(table, table.predicted_net_r, threshold)
        evaluations[key] = {
            "ml": evaluate(parts[key], costs, schedules[key], hashes[name]),
            "rule_baseline": evaluate(parts[key], costs),
            "dates": [min(parts[key]["sessions"]), max(parts[key]["sessions"])],
        }
        write_json(out / f"evaluation-{key}.json", evaluations[key] | {"signals": schedules[key]})
        logger.info("Evaluation %s: %s", key, json.dumps(summary(evaluations[key]["ml"])))
    combined = merge_data([parts["q4"], parts["2026"]])
    evaluations["continuous"] = {
        "ml": evaluate(combined, costs, schedules["q4"] | schedules["2026"], hashes[name]),
        "rule_baseline": evaluate(combined, costs),
    }
    write_json(out / "evaluation-continuous.json", evaluations["continuous"])
    assert file_hash(out / "frozen-selection.json") == frozen_hash
    # Interpret on validation only; never refit or choose features from test results.
    available = validation.dropna(subset=["net_r"])
    importance = permutation_importance(
        model,
        available[features],
        available.net_r,
        scoring="neg_mean_squared_error",
        n_repeats=3,
        random_state=42,
        n_jobs=1,
    )
    pd.DataFrame(
        {
            "feature": features,
            "validation_mse_increase": importance.importances_mean,
            "std": importance.importances_std,
        }
    ).sort_values("validation_mse_increase", ascending=False).to_csv(
        out / "feature-importance.csv", index=False
    )
    reports = [
        value["report"] for period in evaluations.values() for value in period["ml"].values()
    ]
    checks = {
        "validation_passes": frozen["selection_passes"],
        "both_test_periods_positive_base_and_stress": all(
            evaluations[k]["ml"][s]["report"]["metrics"]["net_pnl"] is not None
            and evaluations[k]["ml"][s]["report"]["metrics"]["net_pnl"] > 0
            for k in ("q4", "2026")
            for s in SCENARIOS
        ),
        "at_least_40_test_trades": sum(
            evaluations[k]["ml"]["base"]["report"]["metrics"]["trade_count"] for k in ("q4", "2026")
        )
        >= 40,
        "complete_outcomes": all(not r["incomplete_outcomes"] for r in reports),
        "no_ambiguous_exits": (
            all(r["metrics"]["ambiguous_exit_count"] == 0 for r in reports)
            and all(m["ambiguous_exit_count"] == 0 for m in selected["metrics"].values())
        ),
        "improves_on_rule_baseline": all(
            evaluations[k]["ml"][s]["report"]["metrics"]["net_pnl"] is not None
            and evaluations[k]["rule_baseline"][s]["report"]["metrics"]["net_pnl"] is not None
            and evaluations[k]["ml"][s]["report"]["metrics"]["net_pnl"]
            > evaluations[k]["rule_baseline"][s]["report"]["metrics"]["net_pnl"]
            for k in ("q4", "2026")
            for s in SCENARIOS
        ),
    }
    result = {
        "selected": frozen,
        "selection_file_hash": frozen_hash,
        "audit": audits,
        "checks": checks,
        "passes_research_screen": all(checks.values()),
        "eligible_for_live": False,
        "reserved_sessions_used": 0,
        "evaluations": {
            key: {kind: summary(value[kind]) for kind in ("ml", "rule_baseline")}
            for key, value in evaluations.items()
        },
    }
    write_json(out / "results.json", result)
    logger.info(
        "Experiment complete; screen=%s; evidence=%s", result["passes_research_screen"], out
    )


if __name__ == "__main__":
    main()
