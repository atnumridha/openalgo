"""The optional model must predict causally and report reproducible evidence."""

import numpy as np
import pandas as pd
import pytest
from test_research_ml import candles
from test_trading_research import fees, payload
from test_trading_research_jobs import store as research_store_fixture

store = research_store_fixture

from services.research import jobs, ml
from services.research.dataset import validate_dataset


def test_scalping_horizon_is_validated_and_weights_are_recorded():
    assert jobs.validate_ml_settings({})["max_hold_minutes"] == 15
    for value in (0, 4, 20, True, 5.0):
        with pytest.raises(ValueError, match="holding"):
            jobs.validate_ml_settings({"max_hold_minutes": value})
    frame = opportunities()
    days = list(frame.timestamp.str[:10].unique())
    result = ml.random_forest_signals(frame, days[:10], days[10:], estimators=50)
    assert result["artifact"]["weighting"] == "session_balanced_average_uniqueness"
    assert sum(result["artifact"]["feature_importance"].values()) == pytest.approx(1)
    assert result["diagnostics"]["brier_score"] >= 0
    assert result["diagnostics"]["reliability"]


def opportunities(days=20):
    rows = []
    for day in pd.date_range("2026-01-01", periods=days):
        for i in range(8):
            at = f"{day.date()}T10:{i:02}:00+05:30"
            rows.append(
                {
                    **{name: float(i % 2) for name in ml.ML_FEATURES},
                    "timestamp": at,
                    "direction": "CE",
                    "symbol": "CALL",
                    "net_r": 1.0 if i % 2 else -1.0,
                    "label_exit_at": f"{day.date()}T10:30:00+05:30",
                }
            )
    return pd.DataFrame(rows)


def test_index_features_do_not_require_invented_underlying_volume():
    source = candles().reset_index(names="timestamp")
    source["timestamp"] = source.timestamp.map(lambda value: value.isoformat())
    source["volume"] = None
    source["symbol"] = "NIFTY"
    result = ml.build_underlying_features(
        {"metadata": {"underlying_symbol": "NIFTY"}, "rows": source.to_dict("records")}
    )
    assert "relative_volume" not in result
    assert result.iloc[-1]["return_1"] > 0
    # A single session correctly has no previous-session prices.
    assert pd.isna(result.iloc[-1]["prior_close_distance"])


def test_folds_keep_unlabelled_validation_and_purge_training_label_overlap():
    frame = opportunities()
    frame.loc[0, "label_exit_at"] = "2026-01-12T10:30:00+05:30"
    frame.loc[frame.timestamp.str.startswith("2026-01-11"), ["net_r", "label_exit_at"]] = [
        np.nan,
        None,
    ]
    folds = ml.chronological_folds(frame, folds=2, min_train_sessions=10)
    assert folds[0]["validation"].timestamp.str.startswith("2026-01-11").sum() == 8
    assert len(folds[0]["training"]) == 79
    assert folds[0]["purged_observations"] == 1


def test_cv_reports_predictions_for_missing_outcomes_and_accuracy_separately():
    frame = opportunities()
    frame.loc[frame.timestamp.str.startswith("2026-01-11"), ["net_r", "label_exit_at"]] = [
        np.nan,
        None,
    ]
    result = ml.random_forest_cross_validate(frame, folds=2, estimators=50)
    first = result["model_metadata"]["folds_report"][0]
    assert first["validation_observations"] == 40
    assert first["accuracy"]["labelled_observations"] == 32
    assert first["accuracy"]["accuracy_pct"] == 100
    assert len(result["predictions"]) == 80


def test_model_hash_binds_fitted_state_and_predictions_are_reproducible():
    frame = opportunities()
    days = list(frame.timestamp.str[:10].unique())
    before = ml.random_forest_signals(frame, days[:10], days[10:], estimators=50)
    again = ml.random_forest_signals(frame, days[:10], days[10:], estimators=50)
    assert before == again
    changed = frame.copy()
    changed.loc[changed.timestamp.str[:10].isin(days[:10]), "net_r"] *= -1
    after = ml.random_forest_signals(changed, days[:10], days[10:], estimators=50)
    assert before["model_hash"] != after["model_hash"]
    assert before["prediction_hash"] != after["prediction_hash"]
    assert before["model_metadata"]["sklearn_version"]
    assert before["artifact"]["trees"]
    # Outcomes in the target period do not enter fitting or signal selection.
    changed = frame.copy()
    changed.loc[changed.timestamp.str[:10].isin(days[10:]), "net_r"] = np.nan
    unlabelled = ml.random_forest_signals(changed, days[:10], days[10:], estimators=50)
    assert before["model_hash"] == unlabelled["model_hash"]
    assert before["prediction_hash"] == unlabelled["prediction_hash"]


def test_ml_cancellation_is_checked_during_model_training():
    def cancel():
        raise jobs.Cancelled()

    with pytest.raises(jobs.Cancelled):
        ml.random_forest_cross_validate(
            opportunities(), folds=2, estimators=50, check_cancel=cancel
        )


def test_ml_preparation_never_reads_sealed_sessions(monkeypatch):
    data = validate_dataset(payload(80))
    config = {"costs": fees(), "seed": 42}

    class PreparedOnly(Exception):
        pass

    def inspect(prepared):
        assert prepared["sessions"] == data["sessions"][:-60]
        assert max(row["timestamp"][:10] for row in prepared["rows"]) == prepared["sessions"][-1]
        raise PreparedOnly()

    monkeypatch.setattr(jobs, "build_underlying_features", inspect)
    with pytest.raises(PreparedOnly):
        jobs.run_ml_experiment(data, config)


def test_ml_empty_opportunities_has_actionable_error(monkeypatch):
    monkeypatch.setattr(jobs, "build_underlying_features", lambda _: pd.DataFrame())
    monkeypatch.setattr(jobs, "build_opportunities", lambda *a, **kw: (pd.DataFrame(), {}))
    with pytest.raises(ValueError, match="no usable opportunities"):
        jobs.run_ml_experiment(validate_dataset(payload(80)), {"costs": fees(), "seed": 42})


def test_frozen_final_all_ineligible_options_reports_rejections(monkeypatch):
    from services.risk.cash_exit import CASH_RISK_RECIPE as ML_RISK_RECIPE

    artifact = {
        "test": "frozen",
        "risk_recipe": ML_RISK_RECIPE,
        "risk_policy_version": "shared-300-3r-v1",
    }
    configuration = {
        "risk_recipe": ML_RISK_RECIPE,
        "risk_policy_version": "shared-300-3r-v1",
        "pacing": {"cooldown_minutes": 5, "daily_trade_cap": None},
        "max_hold_minutes": 5,
        "parameters": {"stop_pct": 0.1, "target_pct": 0.3},
        "costs": fees(),
        "capital": 25000,
        "ml_settings": {"max_hold_minutes": 5},
    }
    parent = {
        "kind": "ml",
        "status": "completed",
        "frozen_at": "2026-01-01T00:00:00Z",
        "configuration_hash": jobs.digest(configuration),
        "report": {"ml": {"artifact": artifact, "model_hash": jobs.digest(artifact)}},
    }
    monkeypatch.setattr(jobs, "validate_artifact", lambda _: None)
    monkeypatch.setattr(jobs, "build_underlying_features", lambda _: pd.DataFrame())
    monkeypatch.setattr(
        jobs, "build_opportunities", lambda *a, **kw: (pd.DataFrame(), {"liquidity_filter": 17})
    )
    days = pd.date_range("2026-01-01", periods=61).strftime("%Y-%m-%d").tolist()
    with pytest.raises(ValueError, match="no eligible final opportunities.*liquidity_filter"):
        jobs.run_ml_final_experiment({"sessions": days, "rows": []}, configuration, parent)


def test_nonadjacent_final_seed_is_rejected_before_holdout_consumption(monkeypatch):
    from services.research.ml import require_recent_seed
    from services.risk.cash_exit import CASH_RISK_RECIPE as ML_RISK_RECIPE

    require_recent_seed("2026-04-23", "2026-04-24")
    require_recent_seed("2026-04-24", "2026-04-28")  # weekend and a short holiday
    with pytest.raises(ValueError, match="not recent"):
        require_recent_seed("2025-03-27", "2026-04-24")
    configuration = {
        "engine_version": jobs.ENGINE_VERSION,
        "implementation_hash": jobs.implementation_hash(),
        "risk_recipe": ML_RISK_RECIPE,
        "risk_policy_version": "shared-300-3r-v1",
        "pacing": {"cooldown_minutes": 5, "daily_trade_cap": None},
        "max_hold_minutes": 5,
        "parameters": {"stop_pct": 0.1, "target_pct": 0.3},
    }
    run = {"id": 9, "kind": "ml", "dataset_id": 7, "configuration": configuration}
    sessions = ["2025-03-27"] + pd.date_range("2026-04-24", periods=60).strftime(
        "%Y-%m-%d"
    ).tolist()

    class Store:
        def get_run(self, owner, run_id):
            assert (owner, run_id) == ("alice", 9)
            return run

        def get_dataset(self, owner, dataset_id):
            assert (owner, dataset_id) == ("alice", 7)
            return {"sessions": sessions}

        def queue_final(self, *_):
            pytest.fail("A stale seed must not consume the sealed final sessions")

    with pytest.raises(ValueError, match="not recent.*2025-03-27.*2026-04-24"):
        jobs.queue_final(Store(), "alice", 9)

    artifact = {
        "test": "frozen",
        "risk_recipe": ML_RISK_RECIPE,
        "risk_policy_version": "shared-300-3r-v1",
    }
    parent = {
        "kind": "ml",
        "status": "completed",
        "frozen_at": "2026-01-01T00:00:00Z",
        "configuration_hash": jobs.digest(configuration),
        "report": {"ml": {"artifact": artifact, "model_hash": jobs.digest(artifact)}},
    }
    monkeypatch.setattr(jobs, "validate_artifact", lambda _: None)
    with pytest.raises(ValueError, match="not recent"):
        jobs.run_ml_final_experiment({"sessions": sessions, "rows": []}, configuration, parent)


def ml_payload():
    from copy import deepcopy
    from datetime import datetime, timedelta

    from test_research_minute_execution import filtered_payload

    base = filtered_payload()
    body = deepcopy(base)
    body["rows"], body["metadata"]["contracts"] = [], []
    for day in range(80):
        symbol = f"CALL_{day}"
        contract = deepcopy(base["metadata"]["contracts"][0])
        contract.update(
            symbol=symbol, expiry=(datetime(2026, 1, 6) + timedelta(days=day)).date().isoformat()
        )
        body["metadata"]["contracts"].append(contract)
        for source in base["rows"]:
            row = dict(source)
            row["timestamp"] = (
                datetime.fromisoformat(row["timestamp"]) + timedelta(days=day)
            ).isoformat()
            if row["symbol"] != "NIFTY":
                row["symbol"] = symbol
            body["rows"].append(row)
    return body


def test_ml_queue_worker_frozen_final_reuses_exact_json_model(store, monkeypatch):
    imported = jobs.import_dataset(store, "alice", ml_payload())
    run = jobs.queue_run(
        store,
        "alice",
        {
            "dataset_id": imported["id"],
            "candidate": "trend_breakout_filtered",
            "costs": fees(),
            "run_kind": "ml",
            "ml_settings": {"estimators": 50, "folds": 2},
        },
    )
    assert run["kind"] == "ml"
    assert store.acquire_worker("worker")
    report = jobs.process_job(store, "worker", store.claim_job("worker"))
    assert report["split"]["holdout_consumed"] is False
    assert report["split"]["oos_sessions"] == 6
    assert report["ml"]["accuracy"]["labelled_observations"] > 0
    assert report["ml"]["deployment_supported"] is True
    assert report["ml"]["artifact"]["risk_recipe"] == "one-lot-cash300-profit-trail-v2"
    assert report["ml"]["artifact"]["risk_policy_version"] == "shared-300-3r-v1"
    assert report["configuration_hash"] == run["configuration_hash"]
    assert store.get_run("alice", run["id"])["status"] == "completed"
    frozen = store.freeze_run("alice", run["id"])
    assert frozen["frozen_at"]
    final = jobs.queue_final(store, "alice", run["id"])
    assert final["kind"] == "final"
    monkeypatch.setattr(
        jobs, "random_forest_signals", lambda *args, **kwargs: pytest.fail("final refit")
    )
    final_report = jobs.process_job(store, "worker", store.claim_job("worker"))
    assert final_report["split"]["kind"] == "final"
    assert final_report["ml"]["model_hash"] == report["ml"]["model_hash"]
    assert final_report["ml"]["training_hash"] == report["ml"]["artifact"]["training_hash"]
    assert final_report["ml"]["artifact_hash"] == report["ml"]["model_hash"]
    with pytest.raises(ValueError, match="optimization"):
        jobs.queue_optimized_best(store, "alice", run["id"])
    assert jobs.release_status(store, "alice", run["id"])["eligible_for_live"] is False


def test_missing_ml_dependency_is_reported_before_queueing(store, monkeypatch):
    imported = jobs.import_dataset(store, "alice", ml_payload())
    monkeypatch.setattr(
        jobs,
        "ml_dependencies",
        lambda: {"available": False, "reason": "Install research dependencies"},
    )
    with pytest.raises(ValueError, match="Install research dependencies"):
        jobs.queue_run(
            store,
            "alice",
            {
                "dataset_id": imported["id"],
                "candidate": "trend_breakout_filtered",
                "costs": fees(),
                "run_kind": "ml",
            },
        )
    assert store.overview("alice")["runs"] == []


def test_opportunity_preparation_cancels_before_expensive_feature_groups(monkeypatch):
    from test_research_minute_execution import filtered_payload

    data = validate_dataset(filtered_payload())

    def unexpected(*args, **kwargs):
        raise AssertionError("Feature groups must check cancellation before computing")

    def cancel():
        raise jobs.Cancelled()

    monkeypatch.setattr(ml, "technical_features", unexpected)
    with pytest.raises(jobs.Cancelled):
        ml.build_opportunities(data, pd.DataFrame(), fees(), check_cancel=cancel)
