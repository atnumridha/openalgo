"""Research orchestration; imports only offline research and its own store."""

import hashlib
import itertools
import json
import math
from pathlib import Path

from services.research.dataset import digest, validate_dataset
from services.research.ml import (
    ML_FEATURES,
    _require_frame_columns,
    build_opportunities,
    build_underlying_features,
    ml_dependencies,
    prediction_accuracy,
    random_forest_cross_validate,
    random_forest_signals,
    require_recent_seed,
    signal_schedule,
    validation_qualifies,
)
from services.research.ml_artifact import predict_probabilities, validate_artifact
from services.research.replay import (
    DEFAULTS,
    ENGINE_VERSION,
    Cancelled,
    evaluate_experiment,
    research_capital,
    run_replay,
    validate_configuration,
)
from services.risk.admission import ML_RISK_RECIPE
from services.risk.budget import current_policy
from services.risk.cash_exit import CASH_RISK_RECIPE, current_configuration


def implementation_hash():
    """Bind jobs to actual rules, fees and risk source, including uncommitted changes."""
    root = Path(__file__).resolve().parents[2]
    sources = (
        "services/research/dataset.py",
        "services/research/replay.py",
        "services/research/costs.py",
        "services/research/ml.py",
        "services/research/ml_artifact.py",
        "services/research/ml_live.py",
        "services/research/ml_install.py",
        "services/research/qualification_context.py",
        "services/research/ml_prediction.py",
        "services/research/analytics.py",
        "portfolio/analytics.py",
        "services/research/jobs.py",
        "services/research/low_risk_study.py",
        "services/risk/budget.py",
        "services/risk/admission.py",
        "services/risk/cash_exit.py",
        "services/risk/position.py",
        "services/risk/models.py",
        "services/strategy_module/ml_forest.py",
        "services/strategy_module/engine.py",
        "services/strategy_module/recovery.py",
        "services/strategy_module/trading_budget.py",
        "services/strategy_module/scalping.py",
        "database/strategy_module_db.py",
        "database/trading_risk_db.py",
    )
    hasher = hashlib.sha256()
    for relative in sources:
        hasher.update(relative.encode())
        with (root / relative).open("rb") as source:
            hasher.update(source.read())
    return hasher.hexdigest()


MAX_OPTIMIZATION_CANDIDATES = 256


def import_dataset(store, owner, payload):
    return store.import_dataset(owner, validate_dataset(payload))


def _canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def optimize_experiment(
    data,
    candidate,
    parameter_grid,
    costs,
    seed=42,
    *,
    parameters=None,
    check_cancel=None,
    capital=25000,
    cooldown_minutes=5,
):
    """Evaluate a bounded deterministic parameter grid on development sessions only."""
    if len(data["sessions"]) < 80:
        raise ValueError(
            "At least 80 sessions are required: 20 development and 60 sealed final sessions"
        )
    ordered, candidate_count = validate_parameter_grid(data, candidate, parameter_grid, costs, seed)

    base = validate_configuration(
        data,
        candidate,
        parameters or {},
        costs,
        seed,
        capital=capital,
        cooldown_minutes=cooldown_minutes,
    )
    base["risk_policy_version"] = current_policy().version
    base["implementation_hash"] = implementation_hash()
    results = []
    scored = []
    for index, values in enumerate(
        itertools.product(*(ordered[key] for key in sorted(ordered))), start=1
    ):
        if check_cancel:
            check_cancel()
        varied = base["parameters"] | dict(zip(sorted(ordered), values, strict=True))
        configuration = {
            **base,
            "parameters": validate_configuration(data, candidate, varied, costs, seed)[
                "parameters"
            ],
        }
        report = evaluate_experiment(data, configuration, "development", check_cancel)
        metrics = report["oos"]["metrics"]
        net_pnl = metrics.get("net_pnl")
        max_drawdown = metrics.get("max_drawdown_pct")
        trade_count = metrics.get("trade_count", 0)
        complete = (
            all(not report[part]["incomplete_outcomes"] for part in ("oos", "stress"))
            and not report["incomplete_outcomes"]
            and all(
                value is not None and math.isfinite(float(value))
                for value in (net_pnl, max_drawdown)
            )
        )
        valid_net = float(net_pnl) if complete and math.isfinite(float(net_pnl)) else float("-inf")
        valid_dd = float(max_drawdown) if complete and max_drawdown is not None else float("inf")
        valid_trades = int(trade_count) if complete else 0
        rank = (
            0 if complete else 1,
            -valid_net,
            valid_dd,
            -valid_trades,
            report["configuration_hash"],
        )
        scored.append((rank, index - 1, configuration, report))
        results.append(
            {
                "index": index,
                "parameters": configuration["parameters"],
                "configuration_hash": report["configuration_hash"],
                "metrics": metrics,
                "oos_metrics": metrics,
                "complete": complete,
            }
        )

    scored.sort(key=lambda item: item[0])
    _, best_index, best_configuration, best_report = scored[0]
    return {
        "candidate_count": candidate_count,
        "max_candidates": MAX_OPTIMIZATION_CANDIDATES,
        "development_sessions": len(data["sessions"][:-60]),
        "holdout_sessions": 60,
        "holdout_consumed": False,
        "best_index": best_index + 1,
        "best_configuration": best_configuration,
        "best_report": best_report,
        "candidates": results,
    }


def validate_parameter_grid(data, candidate, parameter_grid, costs, seed=42):
    if not isinstance(parameter_grid, dict) or not parameter_grid:
        raise ValueError("Parameter grid must be a non-empty object")
    if any(not isinstance(key, str) or not key for key in parameter_grid):
        raise ValueError("Parameter grid keys must be non-empty names")
    if set(parameter_grid) & {"stop_pct", "target_pct"}:
        raise ValueError("Cash-stop and 3R exit settings are fixed during parameter search")
    unknown = set(parameter_grid) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown rule parameters: {sorted(unknown)}")
    if candidate != "vwap_pullback" and set(parameter_grid) & {
        "volume_ratio",
        "pullback_tolerance",
    }:
        raise ValueError("The selected rules do not use volume_ratio or pullback_tolerance")
    raw_count = 1
    for values in parameter_grid.values():
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError("Each parameter grid dimension must be a non-empty array")
        raw_count *= len(values)
        if raw_count > MAX_OPTIMIZATION_CANDIDATES:
            raise ValueError(
                f"Parameter grid exceeds the hard limit of {MAX_OPTIMIZATION_CANDIDATES} candidates"
            )
    normalized = {}
    candidate_count = 1
    for key in sorted(parameter_grid):
        values = parameter_grid[key]
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError(f"Parameter grid for {key} must be a non-empty array")
        encoded_values = []
        seen = set()
        for value in values:
            value = validate_configuration(data, candidate, {key: value}, costs, seed)[
                "parameters"
            ][key]
            try:
                encoded = _canonical_json(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Parameter grid value for {key} must be JSON-serializable"
                ) from exc
            if encoded in seen:
                raise ValueError(f"Parameter grid for {key} contains duplicate values")
            seen.add(encoded)
            encoded_values.append((encoded, value))
        encoded_values.sort(key=lambda item: item[0])
        normalized[key] = [value for _, value in encoded_values]
        candidate_count *= len(normalized[key])
        if candidate_count > MAX_OPTIMIZATION_CANDIDATES:
            raise ValueError(
                f"Parameter grid exceeds the hard limit of {MAX_OPTIMIZATION_CANDIDATES} candidates"
            )
    return normalized, candidate_count


def validate_ml_settings(value):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("ML settings must be an object")
    unknown = set(value) - {
        "folds",
        "min_train_sessions",
        "estimators",
        "threshold",
        "max_hold_minutes",
    }
    if unknown:
        raise ValueError(f"Unknown ML settings: {sorted(unknown)}")
    settings = {
        "folds": value.get("folds", 3),
        "min_train_sessions": value.get("min_train_sessions", 10),
        "estimators": value.get("estimators", 200),
        "threshold": value.get("threshold", 0.5),
        "max_hold_minutes": value.get("max_hold_minutes", 15),
    }
    if type(settings["max_hold_minutes"]) is not int or settings["max_hold_minutes"] not in (
        5,
        10,
        15,
    ):
        raise ValueError("ML holding time must be 5, 10 or 15 minutes")
    if (
        isinstance(settings["folds"], bool)
        or not isinstance(settings["folds"], int)
        or not 2 <= settings["folds"] <= 10
    ):
        raise ValueError("ML folds must be a whole number between 2 and 10")
    if (
        isinstance(settings["min_train_sessions"], bool)
        or not isinstance(settings["min_train_sessions"], int)
        or settings["min_train_sessions"] < 10
    ):
        raise ValueError("ML minimum training sessions must be at least 10")
    if (
        isinstance(settings["estimators"], bool)
        or not isinstance(settings["estimators"], int)
        or not 50 <= settings["estimators"] <= 500
    ):
        raise ValueError("ML estimators must be a whole number between 50 and 500")
    threshold = settings["threshold"]
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
        or not 0 <= threshold <= 1
    ):
        raise ValueError("ML prediction threshold must be between 0 and 1")
    settings["threshold"] = float(threshold)
    return settings


def run_ml_experiment(data, configuration, *, check_cancel=None, include_schedule=False):
    current_configuration(configuration)
    settings = validate_ml_settings(configuration.get("ml_settings"))
    risk_recipe = configuration.get("risk_recipe")
    if risk_recipe not in (None, ML_RISK_RECIPE, CASH_RISK_RECIPE):
        raise ValueError("Unsupported ML admission risk recipe")
    if len(data["sessions"]) < 80:
        raise ValueError(
            "At least 80 sessions are required: 20 development and 60 sealed final sessions"
        )
    if check_cancel:
        check_cancel()
    selected = data["sessions"][:-60]
    development = dict(
        data,
        sessions=selected,
        rows=[row for row in data["rows"] if row["timestamp"][:10] in set(selected)],
    )
    underlying_features = build_underlying_features(development)
    opportunities, rejected = build_opportunities(
        development,
        underlying_features,
        configuration["costs"],
        labels=True,
        max_hold_minutes=settings["max_hold_minutes"],
        capital=research_capital(configuration),
        risk_recipe=risk_recipe,
        check_cancel=check_cancel,
    )
    split = max(1, int(len(selected) * 0.7))
    training_sessions = selected[:split]
    oos_sessions = selected[split:]
    if opportunities.empty:
        raise ValueError("RandomForest research produced no usable opportunities")
    if check_cancel:
        check_cancel()
    cross_validation = random_forest_cross_validate(
        opportunities[opportunities.timestamp.str[:10].isin(training_sessions)],
        seed=configuration["seed"],
        folds=settings["folds"],
        min_train_sessions=settings["min_train_sessions"],
        estimators=settings["estimators"],
        threshold=settings["threshold"],
        check_cancel=check_cancel,
    )
    if check_cancel:
        check_cancel()
    model = random_forest_signals(
        opportunities,
        training_sessions,
        oos_sessions,
        seed=configuration["seed"],
        estimators=settings["estimators"],
        threshold=settings["threshold"],
        check_cancel=check_cancel,
    )
    if current_configuration(configuration):
        model["artifact"].update(
            risk_recipe=CASH_RISK_RECIPE, risk_policy_version=current_policy().version
        )
        model["model_hash"] = digest(model["artifact"])
    replay_configuration = dict(configuration)
    replay_configuration["max_hold_minutes"] = settings["max_hold_minutes"]
    replay_configuration["research_signal_hash"] = digest(model["schedule"])
    replay_configuration["research_model_hash"] = model["model_hash"]
    oos_report = run_replay(
        data,
        replay_configuration,
        oos_sessions,
        check_cancel,
        research_signals=model["schedule"],
    )
    if check_cancel:
        check_cancel()
    stress_report = run_replay(
        data,
        replay_configuration,
        oos_sessions,
        check_cancel,
        stress=True,
        research_signals=model["schedule"],
    )
    return {
        **oos_report,
        **(
            {
                "research_signals": model["schedule"],
                "replay_configuration": replay_configuration,
                "evaluated_sessions": oos_sessions,
            }
            if include_schedule
            else {}
        ),
        "oos": oos_report,
        "stress": stress_report,
        "rejections": {**rejected, **oos_report["rejections"]},
        "split": {
            "kind": "development",
            "development_sessions": len(selected),
            "training_sessions": len(training_sessions),
            "oos_sessions": len(oos_sessions),
            "holdout_sessions": 60,
            "last_development_date": selected[-1],
            "holdout_consumed": False,
        },
        "ml": {
            "model_metadata": model["model_metadata"],
            "artifact": model["artifact"],
            "accuracy": model["accuracy"],
            "diagnostics": model["diagnostics"],
            "model_hash": model["model_hash"],
            "prediction_hash": model["prediction_hash"],
            "research_signal_hash": replay_configuration["research_signal_hash"],
            "signal_count": len(model["schedule"]),
            "cross_validation": cross_validation,
            "deployment_supported": True,
            "deployment_reason": "Frozen JSON inference is available; historical gates, exact strategy installation and forward qualification are still required.",
        },
        "configuration_hash": digest(configuration),
        "replay_configuration_hash": oos_report["configuration_hash"],
        "dataset_hash": configuration["dataset_hash"],
        "risk_policy_version": configuration["risk_policy_version"],
        "implementation_hash": configuration["implementation_hash"],
    }


def run_ml_final_experiment(data, configuration, parent, *, check_cancel=None):
    """Score sealed sessions with the frozen parent forest; never fit or relabel it."""
    if not current_configuration(configuration):
        raise ValueError("Frozen ML admission risk recipe is missing or changed")
    ml_report = (parent.get("report") or {}).get("ml") or {}
    artifact = ml_report.get("artifact")
    validate_artifact(artifact)
    if (
        artifact.get("risk_recipe") != CASH_RISK_RECIPE
        or artifact.get("risk_policy_version") != current_policy().version
    ):
        raise ValueError("Frozen ML artifact belongs to an earlier exit or risk recipe")
    model_hash = digest(artifact)
    if (
        parent.get("kind") != "ml"
        or parent.get("status") != "completed"
        or not parent.get("frozen_at")
        or parent.get("configuration_hash") != digest(configuration)
        or model_hash != ml_report.get("model_hash")
    ):
        raise ValueError("Frozen ML model identity or development evidence changed")
    final_days = data["sessions"][-60:]
    previous_day = data["sessions"][-61]
    require_recent_seed(previous_day, final_days[0])
    selected = {previous_day, *final_days}
    prepared = dict(
        data,
        sessions=[previous_day, *final_days],
        rows=[row for row in data["rows"] if row["timestamp"][:10] in selected],
    )
    if check_cancel:
        check_cancel()
    underlying = build_underlying_features(prepared)
    opportunities, rejected = build_opportunities(
        prepared,
        underlying,
        configuration["costs"],
        labels=True,
        max_hold_minutes=configuration["ml_settings"]["max_hold_minutes"],
        capital=research_capital(configuration),
        risk_recipe=configuration["risk_recipe"],
        check_cancel=check_cancel,
    )
    if opportunities.empty:
        raise ValueError(
            f"Frozen ML model has no eligible final opportunities; filters: {rejected}"
        )
    target = opportunities[opportunities.timestamp.str[:10].isin(final_days)].copy()
    if target.empty:
        raise ValueError(
            f"Frozen ML model has no eligible final opportunities; filters: {rejected}"
        )
    features = _require_frame_columns(target, ML_FEATURES).to_numpy(dtype=float)
    scores = predict_probabilities(artifact, features)
    schedule = signal_schedule(target, scores, configuration["ml_settings"]["threshold"])
    replay_config = dict(configuration)
    replay_config.update(
        max_hold_minutes=configuration["ml_settings"]["max_hold_minutes"],
        research_signal_hash=digest(schedule),
        research_model_hash=model_hash,
    )
    report = run_replay(data, replay_config, final_days, check_cancel, research_signals=schedule)
    stress = run_replay(
        data, replay_config, final_days, check_cancel, stress=True, research_signals=schedule
    )
    report.update(
        stress=stress,
        rejections={**rejected, **report["rejections"]},
        split={
            "kind": "final",
            "evaluated_sessions": 60,
            "holdout_sessions": 60,
            "frozen_parent_run_id": parent["id"],
            "refitted": False,
        },
        ml={
            "model_hash": model_hash,
            "artifact_hash": model_hash,
            "training_hash": artifact["training_hash"],
            "prediction_hash": digest(
                [
                    {
                        "timestamp": row.timestamp,
                        "direction": row.direction,
                        "symbol": row.symbol,
                        "probability": float(score),
                    }
                    for row, score in zip(target.itertuples(index=False), scores, strict=True)
                ]
            ),
            "accuracy": prediction_accuracy(
                target, scores, configuration["ml_settings"]["threshold"]
            ),
            "signal_count": len(schedule),
            "deployment_supported": True,
            "deployment_reason": "Frozen final was scored without refitting. Installation requires historical gates and explicit operator action.",
            "cross_validation": ml_report["cross_validation"],
        },
        configuration_hash=digest(configuration),
        dataset_hash=configuration["dataset_hash"],
        risk_policy_version=configuration["risk_policy_version"],
        implementation_hash=configuration["implementation_hash"],
    )
    return report


def historical_ml_reason(final, parent):
    """Explain why this exact frozen model cannot enter forward qualification."""
    from services.risk.qualification import final_screen_passes

    if not final_screen_passes(final):
        return "Frozen ML final screen needs 20 resolved trades and positive net P&L"
    if parent.get("kind") != "ml" or not parent.get("frozen_at"):
        return "Frozen ML development parent is unavailable"
    config = parent.get("configuration") or {}
    if (
        not isinstance(config, dict)
        or config.get("engine_version") != ENGINE_VERSION
        or config.get("risk_policy_version") != current_policy().version
        or config.get("risk_recipe") != CASH_RISK_RECIPE
        or config.get("implementation_hash") != implementation_hash()
        or digest(config) != parent.get("configuration_hash")
        or digest(final.get("configuration")) != final.get("configuration_hash")
    ):
        return "Frozen ML source, rules, risk policy or configuration changed after evaluation"
    artifact = (parent.get("report") or {}).get("ml", {}).get("artifact")
    try:
        validate_artifact(artifact)
    except ValueError as exc:
        return str(exc)
    if (
        artifact.get("risk_recipe") != CASH_RISK_RECIPE
        or artifact.get("risk_policy_version") != current_policy().version
    ):
        return "Frozen ML artifact belongs to an earlier exit or risk recipe"
    try:
        current_configuration(config)
    except ValueError as exc:
        return str(exc)
    hash_value = digest(artifact)
    if (
        hash_value != parent["report"]["ml"].get("model_hash")
        or hash_value != (final.get("report") or {}).get("ml", {}).get("model_hash")
        or parent.get("configuration_hash") != final.get("configuration_hash")
    ):
        return "Frozen ML model or configuration differs between development and final"
    for period, report in (("development", parent["report"]), ("final", final["report"])):
        base = report.get("oos", report)
        stress = report.get("stress") or {}
        if base.get("incomplete_outcomes") or stress.get("incomplete_outcomes"):
            return f"{period.title()} option outcomes are incomplete"
        metrics = {"base": base.get("metrics") or {}, "stress": stress.get("metrics") or {}}
        try:
            if not validation_qualifies(metrics):
                return f"{period.title()} base and stress each need 20 trades, positive net P&L and no ambiguous exits"
        except (KeyError, TypeError, ValueError):
            return f"{period.title()} base or stress metrics are incomplete"
    return None


def queue_run(store, owner, payload):
    if not isinstance(payload, dict):
        raise ValueError("Run configuration must be an object")
    dataset_id = payload.get("dataset_id")
    if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
        raise ValueError("dataset_id must be a whole number")
    data = store.get_dataset(owner, dataset_id)
    if data is None:
        raise LookupError("Dataset not found")
    if len(data["sessions"]) < 80:
        raise ValueError(
            "At least 80 sessions are required: 20 development and 60 sealed final sessions"
        )
    run_kind = payload.get("run_kind", "development")
    if run_kind not in {"development", "optimization", "ml"}:
        raise ValueError("Unsupported research run kind")
    seed = payload.get("seed", 42)
    configuration = validate_configuration(
        data,
        payload.get("candidate"),
        payload.get("parameters", {}),
        payload.get("costs"),
        seed,
        capital=payload.get("capital", 25000),
        cooldown_minutes=payload.get("cooldown_minutes", 5),
    )
    if run_kind == "optimization":
        parameter_grid, candidate_count = validate_parameter_grid(
            data,
            payload.get("candidate"),
            payload.get("parameter_grid"),
            payload.get("costs"),
            seed,
        )
        configuration["parameter_grid"] = parameter_grid
        configuration["candidate_count"] = candidate_count
        configuration["run_kind"] = run_kind
    elif run_kind == "ml":
        dependency = ml_dependencies()
        if not dependency["available"]:
            raise ValueError(dependency["reason"])
        if (
            configuration["candidate"] != "trend_breakout_filtered"
            or configuration["parameters"] != DEFAULTS
        ):
            raise ValueError(
                "ML uses filtered minute execution with one-lot cash stops up to ₹300 and gross 3R targets; use the default rule parameters"
            )
        configuration["ml_settings"] = validate_ml_settings(payload.get("ml_settings"))
        configuration["max_hold_minutes"] = configuration["ml_settings"]["max_hold_minutes"]
        settings = configuration["ml_settings"]
        if (
            int(len(data["sessions"][:-60]) * 0.7)
            < settings["min_train_sessions"] + settings["folds"]
        ):
            raise ValueError(
                "More development sessions are needed for training folds before the out-of-sample period"
            )
        configuration["ml_dependencies"] = dependency
        configuration["risk_recipe"] = CASH_RISK_RECIPE
        configuration["run_kind"] = run_kind
    configuration["risk_policy_version"] = current_policy().version
    configuration["implementation_hash"] = implementation_hash()
    return store.queue_run(
        owner,
        dataset_id,
        configuration,
        digest(configuration),
        data["sessions"][:-60],
        data["metadata"]["underlying_symbol"],
    )


def queue_optimized_best(store, owner, run_id):
    run = store.get_run(owner, run_id)
    if run is None:
        raise LookupError("Research run not found")
    if run["kind"] != "optimization" or run["status"] != "completed":
        raise ValueError("A completed optimization run is required")
    report = run.get("report") or {}
    configuration = report.get("best_configuration")
    if not isinstance(configuration, dict):
        raise ValueError("The optimization run has no reusable best configuration")
    best = report.get("best_report") or {}
    if best.get("configuration_hash") != digest(configuration):
        raise ValueError("The selected configuration does not match its evidence")
    if any(
        part.get("incomplete_outcomes")
        for part in (best, best.get("oos", {}), best.get("stress", {}))
    ):
        raise ValueError("Resolve incomplete outcomes before promoting a candidate")
    if (
        report.get("configuration_hash") != run["configuration_hash"]
        or digest(run["configuration"]) != run["configuration_hash"]
    ):
        raise ValueError("The search configuration does not match its evidence")
    if (
        configuration.get("engine_version") != ENGINE_VERSION
        or configuration.get("risk_policy_version") != current_policy().version
        or configuration.get("implementation_hash") != implementation_hash()
    ):
        raise ValueError("The optimized version differs from the current rules or risk policy")
    data = store.get_dataset(owner, run["dataset_id"])
    if data is None or configuration.get("dataset_hash") != digest(
        {"metadata": data["metadata"], "rows": data["rows"]}
    ):
        raise ValueError("The optimized dataset is unavailable or has changed")
    configuration = dict(configuration)
    configuration.pop("run_kind", None)
    configuration.pop("parameter_grid", None)
    configuration.pop("candidate_count", None)
    return store.queue_run(
        owner,
        run["dataset_id"],
        configuration,
        digest(configuration),
        data["sessions"][:-60],
        data["metadata"]["underlying_symbol"],
        parent_run_id=run_id,
    )


def queue_final(store, owner, run_id):
    run = store.get_run(owner, run_id)
    if run is None:
        raise LookupError("Research run not found")
    if (
        run["configuration"]["engine_version"] != ENGINE_VERSION
        or run["configuration"].get("risk_policy_version") != current_policy().version
        or run["configuration"].get("implementation_hash") != implementation_hash()
    ):
        raise ValueError("The frozen version differs from the current rules or risk policy")
    data = store.get_dataset(owner, run["dataset_id"])
    if data is None:
        raise ValueError("The frozen dataset is unavailable")
    if run["kind"] == "ml":
        for previous_day, session_day in zip(
            data["sessions"][-61:-1], data["sessions"][-60:], strict=True
        ):
            require_recent_seed(previous_day, session_day)
        ml_report = (run.get("report") or {}).get("ml") or {}
        validate_artifact(ml_report.get("artifact"))
        if digest(ml_report["artifact"]) != ml_report.get("model_hash"):
            raise ValueError("Frozen ML artifact differs from its development evidence")
    return store.queue_final(
        owner, run_id, data["sessions"][-60:], data["metadata"]["underlying_symbol"]
    )


class WorkerStopping(Cancelled):
    """An operator stopped the worker; preserve an interrupted outcome."""


def process_job(store, token, run, *, should_stop=None):
    def check_cancel():
        if should_stop is not None and should_stop():
            raise WorkerStopping("Research worker is stopping")
        if not store.check_job(token, run["owner"], run["id"]):
            raise Cancelled("Research run was cancelled")

    try:
        check_cancel()
        data = store.get_dataset(run["owner"], run["dataset_id"])
        if (
            data is None
            or digest({"metadata": data["metadata"], "rows": data["rows"]})
            != run["configuration"]["dataset_hash"]
        ):
            raise ValueError("Dataset integrity check failed")
        if (
            run["configuration_hash"] != digest(run["configuration"])
            or run["configuration"]["engine_version"] != ENGINE_VERSION
            or run["configuration"].get("risk_policy_version") != current_policy().version
            or run["configuration"].get("implementation_hash") != implementation_hash()
        ):
            raise ValueError("Rules or risk policy changed after this job was queued")
        run_kind = (
            run["kind"]
            if run["kind"] == "final"
            else run["configuration"].get("run_kind", run["kind"])
        )
        if run_kind == "optimization":
            report = optimize_experiment(
                data,
                run["configuration"]["candidate"],
                run["configuration"]["parameter_grid"],
                run["configuration"]["costs"],
                run["configuration"]["seed"],
                parameters=run["configuration"]["parameters"],
                capital=research_capital(run["configuration"]),
                cooldown_minutes=run["configuration"]["pacing"]["cooldown_minutes"],
                check_cancel=check_cancel,
            )
            report["configuration_hash"] = run["configuration_hash"]
            report["dataset_hash"] = run["configuration"]["dataset_hash"]
            report["risk_policy_version"] = run["configuration"]["risk_policy_version"]
            report["implementation_hash"] = run["configuration"]["implementation_hash"]
        elif run_kind == "final" and run["configuration"].get("run_kind") == "ml":
            parent = store.get_run(run["owner"], run["parent_run_id"])
            if parent is None:
                raise ValueError("Frozen ML parent run is unavailable")
            report = run_ml_final_experiment(
                data, run["configuration"], parent, check_cancel=check_cancel
            )
        elif run_kind == "ml":
            if run["configuration"].get("ml_dependencies") != ml_dependencies():
                raise ValueError(
                    "ML dependencies changed after this job was queued; create a new run"
                )
            report = run_ml_experiment(data, run["configuration"], check_cancel=check_cancel)
            report["configuration_hash"] = run["configuration_hash"]
            report["dataset_hash"] = run["configuration"]["dataset_hash"]
            report["risk_policy_version"] = run["configuration"]["risk_policy_version"]
            report["implementation_hash"] = run["configuration"]["implementation_hash"]
        else:
            report = evaluate_experiment(data, run["configuration"], run_kind, check_cancel)
        check_cancel()
        store.finish_job(token, run["id"], "completed", report=report)
        return report
    except WorkerStopping:
        store.finish_job(
            token,
            run["id"],
            "interrupted",
            error="The research worker was stopped before this run completed.",
        )
        raise
    except Cancelled:
        store.finish_job(token, run["id"], "cancelled")
        raise
    except Exception as exc:
        store.finish_job(
            token,
            run["id"],
            "failed",
            error=str(exc)[:500]
            if isinstance(exc, ValueError)
            else "The research run could not complete. Check the worker log and dataset assumptions.",
        )
        raise


def release_status(store, owner, run_id):
    if store.get_run(owner, run_id) is None:
        raise LookupError("Research run not found")
    from database.strategy_qualification_db import get_store
    from services.research import qualification

    campaigns = [
        qualification.detail(owner, item["id"])
        for item in get_store().list_campaigns(owner)
        if item["final_run_id"] == run_id
    ]
    approved = any((item.get("approval") or {}).get("status") == "approved" for item in campaigns)
    return {
        "eligible_for_live": approved,
        "paper_evidence": "collecting" if campaigns else "not_enrolled",
        "approval": "approved" if approved else "not_granted",
        "campaigns": [
            {
                "id": item["id"],
                "strategy_id": item["strategy_id"],
                "qualification": item["qualification"],
                "approval": item.get("approval"),
            }
            for item in campaigns
        ],
        "reasons": []
        if approved
        else [
            "Enroll and qualify the exact strategy and Flow, reconcile its forward evidence, then explicitly approve a release."
        ],
    }


def live_release_reason(user_id, strategy_id, strategy_config, risk_policy_version, costs):
    from services.research.qualification import live_release_reason as evaluate_release

    return evaluate_release(user_id, strategy_id, strategy_config, risk_policy_version, costs)
