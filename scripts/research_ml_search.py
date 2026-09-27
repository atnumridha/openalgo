"""Run the registered 12-configuration offline search; never places orders."""

import argparse
import json
import os
import sys
import time
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
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts.research_ml_train import (
    SCENARIOS,
    THRESHOLDS,
    evaluate,
    file_hash,
    load_development,
    read_json,
    summary,
    write_json,
)
from services.research.dataset import digest
from services.research.jobs import implementation_hash
from services.research.ml import (
    build_opportunities,
    signal_schedule,
    technical_features,
    validation_qualifies,
)
from services.research.ml_search import (
    choose_threshold,
    chronological_fold,
    rank_candidates,
    summarize_candidate,
)
from utils.logging import get_logger

logger = get_logger(__name__)
FOLDS = (
    {"id": "fold-1", "train": ["q1"], "calibration": "q2", "later": "q3"},
    {"id": "fold-2", "train": ["q1", "q2"], "calibration": "q3", "later": "q4"},
    {"id": "fold-3", "train": ["q1", "q2", "q3"], "calibration": "q4", "later": "2026"},
)
COMPACT_FEATURES = (
    "u_return_3",
    "u_return_12",
    "u_ema_21_distance",
    "u_trend_spread",
    "u_trend_slope",
    "u_rsi",
    "u_atr_fraction",
    "u_adx",
    "u_bollinger_position",
    "u_body",
    "u_close_location",
    "u_high_break_distance",
    "u_low_break_distance",
    "u_efficiency",
    "u_realized_volatility",
    "o_return_3",
    "o_relative_volume",
    "o_vwap_distance",
    "direction_ce",
    "moneyness",
)


def feature_sets(all_features):
    return {
        "all": list(all_features),
        "portable": [
            f
            for f in all_features
            if f not in {"premium", "lot_size", "days_to_expiry", "o_volume_log"}
        ],
        "compact": list(COMPACT_FEATURES),
    }


def make_model(name):
    if name in ("ridge10", "ridge100"):
        return make_pipeline(StandardScaler(), Ridge(alpha=int(name[5:])))
    if name == "boosted":
        return HistGradientBoostingRegressor(
            max_iter=120,
            max_leaf_nodes=7,
            min_samples_leaf=100,
            learning_rate=0.05,
            l2_regularization=10,
            early_stopping=False,
            random_state=42,
        )
    if name == "extra_trees":
        return ExtraTreesRegressor(
            n_estimators=120,
            max_depth=4,
            min_samples_leaf=100,
            max_features=0.7,
            n_jobs=1,
            random_state=42,
        )
    raise ValueError("Unknown registered model")


def model_spec(name):
    model = make_model(name)
    if name.startswith("ridge"):
        return {"standardize_using_training_only": True, **model[-1].get_params()}
    return model.get_params()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    previous = ROOT / "data/research/technical-ml-2026-09-26-corrected"
    old_manifest = read_json(previous / "registered-inputs.json")
    # Old labels are only reused with the exact implementation that produced them.
    if implementation_hash() != old_manifest["implementation_hash"]:
        raise ValueError(
            "Shared risk, costs or replay implementation changed; rebuild cached labels"
        )
    for name, expected in old_manifest["source_hashes"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError(f"Source changed since the verified feature run: {name}")
    all_features = read_json(previous / "frozen-selection.json")["features"]
    groups = feature_sets(all_features)
    specs = [
        {
            "id": f"{group}-{name}",
            "model": name,
            "feature_set": group,
            "features": features,
            "parameters": model_spec(name),
        }
        for group, features in groups.items()
        for name in ("ridge10", "ridge100", "boosted", "extra_trees")
    ]
    plan = ROOT / "docs/plans/2026-09-26-ml-walkforward-search.md"
    sources = (
        "scripts/research_ml_search.py",
        "services/research/ml_search.py",
        "scripts/research_ml_train.py",
        "services/research/ml.py",
        "services/research/replay.py",
        "services/research/costs.py",
        "services/research/dataset.py",
        "services/risk/budget.py",
    )
    manifest = {
        "plan_sha256": file_hash(plan),
        "implementation_hash": implementation_hash(),
        "source_hashes": {name: file_hash(ROOT / name) for name in sources},
        "previous_results_sha256": file_hash(previous / "results.json"),
        "reused_table_hashes": {
            key: file_hash(previous / f"opportunities-{key}.parquet")
            for key in ("q1", "q2", "q3", "q4", "2026")
        },
        "versions": {
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "candidates": specs,
        "folds": FOLDS,
        "thresholds": THRESHOLDS,
        "scenarios": SCENARIOS,
        "costs": old_manifest["costs"],
        "planned_model_fits": 36,
        "planned_ml_replays": 288,
        "reserved_sessions_used": 0,
        "evidence_role": "Known development dates; no independent final confirmation or live qualification.",
    }
    write_json(out / "registered-search.json", manifest)
    manifest_hash = file_hash(out / "registered-search.json")
    costs = manifest["costs"]
    data_root = ROOT / "data/research/robustness-2026-09-26"
    paths = {f"q{q}": data_root / f"nifty-2025-q{q}-robustness.json" for q in range(1, 5)}
    paths["2026"] = (
        ROOT / "data/research/filtered-minute-2026-09-26/nifty-2026-mixed-resolution.json"
    )
    expected = read_json(previous / "datasets.json")
    parts = {}
    for key, path in paths.items():
        if file_hash(path) != expected[key]["source_file_hash"]:
            raise ValueError(f"Historical source changed: {key}")
        parts[key] = load_development(path, "2025-01-01", "2026-04-23")
        if parts[key]["content_hash"] != expected[key]["development_content_hash"]:
            raise ValueError(f"Development content changed: {key}")
    write_json(out / "datasets.json", expected)
    tables = {
        key: pd.read_parquet(previous / f"opportunities-{key}.parquet").drop(
            columns=["predicted_net_r"], errors="ignore"
        )
        for key in paths
    }
    spot_path = ROOT / "data/research/five-minute-2026-09-26/NIFTY-spot-5m.parquet"
    if file_hash(spot_path) != read_json(previous / "feature-source.json")["file_hash"]:
        raise ValueError("Underlying source changed")
    spot = pd.read_parquet(spot_path)
    spot = spot[spot.bar_close.dt.strftime("%Y-%m-%d") < "2026-04-24"].set_index("bar_close")
    features = technical_features(spot[["open", "high", "low", "close", "volume"]])
    logger.info("Preparing Q4 payoff labels for chronological threshold calibration")
    q4, audit = build_opportunities(parts["q4"], features, costs, labels=True)
    pd.testing.assert_frame_equal(
        q4[["timestamp", "direction", "symbol", *all_features]],
        tables["q4"][["timestamp", "direction", "symbol", *all_features]],
    )
    tables["q4"] = q4
    for key, table in tables.items():
        if not np.isfinite(table[all_features]).all().all():
            raise ValueError(f"Non-finite features: {key}")
        table.to_parquet(out / f"opportunities-{key}.parquet", index=False)
    write_json(out / "label-audit.json", {"q4": audit, "reserved_sessions_used": 0})
    del spot, features, q4
    baselines = {}
    for key in ("q3", "q4", "2026"):
        baselines[key] = evaluate(parts[key], costs)
        write_json(out / f"baseline-{key}.json", baselines[key])
    completed = []
    fit_count = replay_count = 0
    for number, spec in enumerate(specs, 1):
        name, columns = spec["model"], spec["features"]
        candidate_dir = out / spec["id"]
        candidate_dir.mkdir()
        folds = []
        for fold in FOLDS:
            fold_dir = candidate_dir / fold["id"]
            fold_dir.mkdir()
            fit, calibration, later = chronological_fold(
                tables, fold["train"], fold["calibration"], fold["later"]
            )
            counts = fit.groupby(fit.timestamp.str[:10]).timestamp.transform("size")
            weight = len(fit) / fit.timestamp.str[:10].nunique() / counts
            target = fit.net_r.clip(-3, 3)
            model = make_model(name)
            kwargs = (
                {"ridge__sample_weight": weight}
                if name.startswith("ridge")
                else {"sample_weight": weight}
            )
            model.fit(fit[columns], target, **kwargs)
            fit_count += 1
            with (fold_dir / "model.joblib").open("wb") as stream:
                joblib.dump(model, stream)
            model_hash = file_hash(fold_dir / "model.joblib")
            scores = model.predict(calibration[columns])
            calibration[["timestamp", "direction", "symbol"]].assign(
                predicted_net_r=scores
            ).to_parquet(fold_dir / "calibration-predictions.parquet", index=False)
            candidates = []
            for threshold in THRESHOLDS:
                signals = signal_schedule(calibration, scores, threshold)
                results = evaluate(parts[fold["calibration"]], costs, signals, model_hash)
                replay_count += len(SCENARIOS)
                item = {
                    "threshold": threshold,
                    "metrics": summary(results),
                    "signal_count": len(signals),
                }
                candidates.append(item)
                write_json(
                    fold_dir / f"calibration-{threshold:.2f}.json",
                    {
                        "candidate": item,
                        "signals": signals,
                        "results": results,
                    },
                )
            chosen = choose_threshold(candidates)
            available = calibration.net_r.notna()
            frozen = {
                "fold": fold,
                "spec": spec,
                "selected": chosen,
                "calibration_passes": validation_qualifies(chosen["metrics"]),
                "model_hash": model_hash,
                "training_rows": len(fit),
                "training_sessions": int(fit.timestamp.str[:10].nunique()),
                "training_last_label": fit.label_exit_at.max(),
                "calibration_first": calibration.timestamp.min(),
                "calibration_last_label": calibration.label_exit_at.dropna().max(),
                "later_first": later.timestamp.min(),
                "calibration_mse": mean_squared_error(
                    calibration.loc[available, "net_r"], scores[available]
                ),
                "constant_mean_mse": mean_squared_error(
                    calibration.loc[available, "net_r"],
                    np.repeat(np.average(target, weights=weight), available.sum()),
                ),
            }
            # No later predictions or trading outcomes affect this selection.
            write_json(fold_dir / "frozen-selection.json", frozen)
            frozen_hash = file_hash(fold_dir / "frozen-selection.json")
            predicted = model.predict(later[columns])
            later[["timestamp", "direction", "symbol"]].assign(
                predicted_net_r=predicted
            ).to_parquet(fold_dir / "later-predictions.parquet", index=False)
            signals = signal_schedule(later, predicted, chosen["threshold"])
            result = evaluate(parts[fold["later"]], costs, signals, model_hash)
            replay_count += len(SCENARIOS)
            assert file_hash(fold_dir / "frozen-selection.json") == frozen_hash
            write_json(
                fold_dir / "evaluation.json",
                {
                    "results": result,
                    "signals": signals,
                    "signal_hash": digest(signals),
                    "selection_file_hash": frozen_hash,
                },
            )
            fold_summary = {
                "fold": fold["id"],
                "later_period": fold["later"],
                "threshold": chosen["threshold"],
                "calibration_passes": frozen["calibration_passes"],
                "metrics": summary(result),
                "baseline": summary(baselines[fold["later"]]),
                "training_rows": len(fit),
                "training_sessions": frozen["training_sessions"],
            }
            folds.append(fold_summary)
            logger.info(
                "%d/12 %s %s: base %.2f / stress %.2f; trades %d; calibration_pass=%s",
                number,
                spec["id"],
                fold["id"],
                fold_summary["metrics"]["base"]["net_pnl"],
                fold_summary["metrics"]["stress"]["net_pnl"],
                fold_summary["metrics"]["base"]["trade_count"],
                frozen["calibration_passes"],
            )
        row = summarize_candidate(spec["id"], folds)
        completed.append(row)
        write_json(candidate_dir / "summary.json", row)
        write_json(
            out / "progress.json",
            {
                "completed_candidates": number,
                "model_fits": fit_count,
                "ml_replays": replay_count,
                "elapsed_seconds": round(time.monotonic() - started, 1),
            },
        )
    ranked = rank_candidates(completed)
    result = {
        "candidate_count": len(ranked),
        "model_fit_count": fit_count,
        "ml_replay_count": replay_count,
        "baseline_replay_count": 6,
        "registered_search_hash": manifest_hash,
        "ranked_candidates": ranked,
        "best_development_candidate": ranked[0]["candidate"],
        "passing_candidate_count": sum(c["passes_development_screen"] for c in ranked),
        "eligible_for_live": False,
        "reserved_sessions_used": 0,
        "accounting_note": "Period sums compare three separately initialized accounts, not one continuous return.",
        "evidence_note": "These dates were seen in prior research and now used in model selection; no pristine final test or profit proof.",
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    assert file_hash(out / "registered-search.json") == manifest_hash
    assert file_hash(plan) == manifest["plan_sha256"]
    assert fit_count == 36 and replay_count == 288
    write_json(out / "results.json", result)
    pd.DataFrame(
        [
            {
                k: row[k]
                for k in (
                    "candidate",
                    "positive_periods",
                    "sum_base_net_pnl",
                    "sum_stress_net_pnl",
                    "worst_stress_net_pnl",
                    "base_trade_count",
                    "passes_development_screen",
                )
            }
            for row in ranked
        ]
    ).to_csv(out / "leaderboard.csv", index=False)
    logger.info(
        "Completed 12 candidates / 36 fits / 288 ML replays. Best=%s; passing=%d; output=%s",
        ranked[0]["candidate"],
        result["passing_candidate_count"],
        out,
    )


if __name__ == "__main__":
    main()
