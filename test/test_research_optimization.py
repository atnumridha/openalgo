"""Search must preserve the submitted rules and the sealed lifecycle."""

import copy

import pytest
from test_trading_research import current_payload as payload
from test_trading_research import fees
from test_trading_research_jobs import store as research_store_fixture

store = research_store_fixture

from services.research import jobs
from services.research.dataset import validate_dataset


def queued_search(store):
    imported = jobs.import_dataset(store, "alice", payload(80))
    return jobs.queue_run(
        store,
        "alice",
        {
            "dataset_id": imported["id"],
            "candidate": "trend_breakout",
            "parameters": {"stop_pct": 0.15, "target_pct": 0.45},
            "parameter_grid": {"lookback": [2, 3]},
            "run_kind": "optimization",
            "costs": fees(),
        },
    )


def test_optimizer_keeps_fixed_parameters_and_selects_deterministically():
    data = validate_dataset(payload(80))
    args = (data, "trend_breakout", {"lookback": [3, 2]}, fees())
    result = jobs.optimize_experiment(*args, parameters={"stop_pct": 0.15, "target_pct": 0.45})
    assert all(c["parameters"]["stop_pct"] == 0.15 for c in result["candidates"])
    assert all(c["parameters"]["target_pct"] == 0.45 for c in result["candidates"])
    again = jobs.optimize_experiment(
        data,
        "trend_breakout",
        {"lookback": [2, 3]},
        fees(),
        parameters={"stop_pct": 0.15, "target_pct": 0.45},
    )
    assert result == again
    assert result["holdout_consumed"] is False
    assert result["best_report"]["split"]["development_sessions"] == 20


@pytest.mark.parametrize(
    "grid",
    [
        {"lookback": [2, "2"]},
        {"lookback": [True]},
        {"stop_pct": [float("nan")]},
        {"volume_ratio": [1, 2]},
        {"lookback": []},
        {"lookback": list(range(2, 20)), "stop_pct": [i / 100 for i in range(1, 20)]},
    ],
)
def test_grid_rejects_alias_duplicates_inactive_parameters_and_unbounded_search(grid):
    with pytest.raises(ValueError):
        jobs.validate_parameter_grid(validate_dataset(payload(80)), "trend_breakout", grid, fees())


def test_optimization_promotes_as_new_development_then_consumes_final_once(store):
    source = queued_search(store)
    assert source["kind"] == "optimization"
    assert store.acquire_worker("worker")
    report = jobs.process_job(store, "worker", store.claim_job("worker"))
    assert report["best_configuration"]["parameters"]["stop_pct"] == 0.15
    with pytest.raises(ValueError, match="development"):
        store.freeze_run("alice", source["id"])
    with pytest.raises(LookupError):
        jobs.queue_optimized_best(store, "bob", source["id"])
    promoted = jobs.queue_optimized_best(store, "alice", source["id"])
    assert promoted["kind"] == "development"
    assert promoted["parent_run_id"] == source["id"]
    assert promoted["configuration"] == report["best_configuration"]
    jobs.process_job(store, "worker", store.claim_job("worker"))
    store.freeze_run("alice", promoted["id"])
    final = jobs.queue_final(store, "alice", promoted["id"])
    assert final["kind"] == "final"
    result = jobs.process_job(store, "worker", store.claim_job("worker"))
    assert result["split"]["evaluated_sessions"] == 60
    with pytest.raises(ValueError, match="consumed"):
        jobs.queue_final(store, "alice", promoted["id"])


def test_promotion_refuses_incomplete_best_and_modified_report(store, monkeypatch):
    source = queued_search(store)
    store.acquire_worker("worker")
    jobs.process_job(store, "worker", store.claim_job("worker"))
    original = store.get_run("alice", source["id"])
    for mutate in ("incomplete", "tampered"):
        run = copy.deepcopy(original)
        if mutate == "incomplete":
            run["report"]["best_report"]["oos"]["incomplete_outcomes"] = [{"reason": "gap"}]
        else:
            run["report"]["best_configuration"]["parameters"]["lookback"] = 99
        monkeypatch.setattr(store, "get_run", lambda *_, result=run: result)
        with pytest.raises(ValueError):
            jobs.queue_optimized_best(store, "alice", source["id"])


def test_cancel_search_before_first_candidate():
    def cancel():
        raise jobs.Cancelled()

    with pytest.raises(jobs.Cancelled):
        jobs.optimize_experiment(
            validate_dataset(payload(80)),
            "trend_breakout",
            {"lookback": [2]},
            fees(),
            check_cancel=cancel,
        )


def test_oversized_grid_is_rejected_before_per_value_dataset_validation(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Oversized grids must be rejected before expensive validation")

    monkeypatch.setattr(jobs, "validate_configuration", unexpected)
    with pytest.raises(ValueError, match="256"):
        jobs.validate_parameter_grid({}, "trend_breakout", {"lookback": list(range(300))}, fees())


@pytest.mark.parametrize("cooldown", [0, 15])
def test_queued_search_preserves_bound_pacing_in_evaluations_and_promotion(
    store, monkeypatch, cooldown
):
    imported = jobs.import_dataset(store, "alice", payload(80))
    run = jobs.queue_run(
        store,
        "alice",
        {
            "dataset_id": imported["id"],
            "candidate": "trend_breakout",
            "costs": fees(),
            "run_kind": "optimization",
            "parameter_grid": {"lookback": [2, 3]},
            "cooldown_minutes": cooldown,
        },
    )
    observed = []
    original = jobs.evaluate_experiment

    def evaluate(data, configuration, *args, **kwargs):
        observed.append(copy.deepcopy(configuration))
        return original(data, configuration, *args, **kwargs)

    monkeypatch.setattr(jobs, "evaluate_experiment", evaluate)
    assert store.acquire_worker("worker")
    report = jobs.process_job(store, "worker", store.claim_job("worker"))
    assert len(observed) == 2
    assert all(
        c["pacing"] == {"cooldown_minutes": cooldown, "daily_trade_cap": None} for c in observed
    )
    assert report["configuration_hash"] == run["configuration_hash"]
    assert [c["configuration_hash"] for c in report["candidates"]] == [
        jobs.digest(c) for c in observed
    ]
    assert report["best_report"]["configuration_hash"] == jobs.digest(report["best_configuration"])
    promoted = jobs.queue_optimized_best(store, "alice", run["id"])
    assert promoted["configuration"]["pacing"]["cooldown_minutes"] == cooldown
    assert promoted["configuration_hash"] == jobs.digest(promoted["configuration"])
