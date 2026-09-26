"""Research orchestration; imports only offline research and its own store."""

import hashlib
from pathlib import Path

from services.research.dataset import digest, validate_dataset
from services.research.replay import (
    ENGINE_VERSION,
    Cancelled,
    evaluate_experiment,
    validate_configuration,
)
from services.risk.budget import BudgetPolicy


def implementation_hash():
    """Bind jobs to actual rules, fees and risk source, including uncommitted changes."""
    root = Path(__file__).resolve().parents[2]
    sources = (
        "services/research/dataset.py",
        "services/research/replay.py",
        "services/research/costs.py",
        "services/research/jobs.py",
        "services/risk/budget.py",
        "services/risk/position.py",
        "services/risk/models.py",
    )
    hasher = hashlib.sha256()
    for relative in sources:
        hasher.update(relative.encode())
        with (root / relative).open("rb") as source:
            hasher.update(source.read())
    return hasher.hexdigest()


def import_dataset(store, owner, payload):
    return store.import_dataset(owner, validate_dataset(payload))


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
    configuration = validate_configuration(
        data,
        payload.get("candidate"),
        payload.get("parameters", {}),
        payload.get("costs"),
        payload.get("seed", 42),
    )
    configuration["risk_policy_version"] = BudgetPolicy().version
    configuration["implementation_hash"] = implementation_hash()
    return store.queue_run(
        owner,
        dataset_id,
        configuration,
        digest(configuration),
        data["sessions"][:-60],
        data["metadata"]["underlying_symbol"],
    )


def queue_final(store, owner, run_id):
    run = store.get_run(owner, run_id)
    if run is None:
        raise LookupError("Research run not found")
    if (
        run["configuration"]["engine_version"] != ENGINE_VERSION
        or run["configuration"].get("risk_policy_version") != BudgetPolicy().version
        or run["configuration"].get("implementation_hash") != implementation_hash()
    ):
        raise ValueError("The frozen version differs from the current rules or risk policy")
    data = store.get_dataset(owner, run["dataset_id"])
    if data is None:
        raise ValueError("The frozen dataset is unavailable")
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
            or run["configuration"].get("risk_policy_version") != BudgetPolicy().version
            or run["configuration"].get("implementation_hash") != implementation_hash()
        ):
            raise ValueError("Rules or risk policy changed after this job was queued")
        report = evaluate_experiment(data, run["configuration"], run["kind"], check_cancel)
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
    except Exception:
        store.finish_job(
            token,
            run["id"],
            "failed",
            error="The research run could not complete. Check the worker log and dataset assumptions.",
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
