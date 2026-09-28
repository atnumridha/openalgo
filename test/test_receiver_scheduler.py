"""A migrated receiver graph must replace its stale persisted interval at boot."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


def custom_callback(workflow_id, api_key=None):
    raise AssertionError("Paused test scheduler must never execute")


@pytest.mark.parametrize("invalid_interval", [None, 10**20])
def test_restart_repairs_receiver_interval_without_replacing_custom_job_settings(
    tmp_path, monkeypatch, invalid_interval
):
    from database import flow_db
    from services import flow_readiness_service
    from services import flow_scheduler_service as scheduling

    url = f"sqlite:///{tmp_path / 'receiver-scheduler.db'}"

    def scheduler():
        result = BackgroundScheduler(jobstores={"default": SQLAlchemyJobStore(url=url)})
        result.start(paused=True)
        return result

    profiles = {
        1: "receiver_momentum",
        2: "ema915",
        3: "receiver_trend",
        4: "receiver_retest",
        5: "receiver_momentum",
    }
    if invalid_interval is not None:
        # Process the invalid graph first: it must not abort the later repairs.
        profiles = {6: "receiver_trend", **profiles}
    flows = {
        wid: SimpleNamespace(
            id=wid,
            is_active=True,
            nodes=[
                {
                    "type": "start",
                    "data": {
                        "scheduleType": "interval",
                        "intervalValue": 1,
                        "intervalUnit": "minutes",
                        "marketHoursOnly": True,
                        "marketHoursExchange": "MCX",
                    },
                },
                {
                    "type": "strategyModuleRun",
                    "data": {
                        "strategyId": wid,
                        "mode": "live",
                        "barEvidence": {"scalpProfile": profile},
                    },
                },
            ],
        )
        for wid, profile in profiles.items()
    }
    if invalid_interval is not None:
        flows[6].nodes[0]["data"]["intervalValue"] = invalid_interval
    before = deepcopy(flows)
    first = scheduler()
    start = datetime(2026, 9, 28, 14, 35, 6, tzinfo=ZoneInfo("Asia/Kolkata"))
    try:
        for wid in profiles:
            kwargs = {"market_hours_only": True} if wid != 3 else {}
            first.add_job(
                custom_callback if wid == 3 else scheduling.execute_workflow_scheduled,
                id=f"flow_workflow_{wid}",
                args=[wid, None],
                kwargs=kwargs,
                trigger=IntervalTrigger(minutes=1 if wid == 4 else 5, start_date=start, jitter=2),
                coalesce=False,
                misfire_grace_time=17,
                max_instances=3,
                name=f"Saved receiver {wid}",
            )
        first.pause_job("flow_workflow_5")
    finally:
        first.shutdown()

    restored = scheduler()
    wrapper = object.__new__(scheduling.FlowScheduler)
    wrapper._scheduler = restored
    updates = []
    monkeypatch.setattr(scheduling, "get_flow_scheduler", lambda: wrapper)
    monkeypatch.setattr(flow_db, "get_workflow", lambda wid: flows.get(wid))
    monkeypatch.setattr(flow_db, "get_active_workflows", lambda: list(flows.values()))
    monkeypatch.setattr(flow_db, "get_workflow_api_key", lambda _: "fixture")
    monkeypatch.setattr(flow_db, "set_schedule_job_id", lambda *args: updates.append(args))
    monkeypatch.setattr(flow_readiness_service, "strategy_link_issues", lambda *args, **kwargs: [])
    try:
        old = {wid: restored.get_job(f"flow_workflow_{wid}").__getstate__() for wid in profiles}
        assert old[1]["trigger"].interval == timedelta(minutes=5)
        assert scheduling.reconcile_scheduler_jobs() == {"removed": 0, "restored": 2}
        for wid in (1, 5):
            job = restored.get_job(f"flow_workflow_{wid}")
            assert job.trigger.interval == timedelta(minutes=1)
            assert job.trigger.start_date.second == scheduling.interval_alignment_offset(True)
            assert job.trigger.jitter == 2
            for key in (
                "func",
                "args",
                "kwargs",
                "coalesce",
                "misfire_grace_time",
                "max_instances",
                "name",
            ):
                assert job.__getstate__()[key] == old[wid][key]
        assert restored.get_job("flow_workflow_5").next_run_time is None
        for wid in (2, 3, 4, 6) if invalid_interval is not None else (2, 3, 4):
            current = restored.get_job(f"flow_workflow_{wid}").__getstate__()
            original = old[wid].copy()
            assert current.pop("trigger").__getstate__() == original.pop("trigger").__getstate__()
            assert current == original
        assert scheduling.reconcile_scheduler_jobs() == {"removed": 0, "restored": 0}
        assert flows == before
        assert updates == []
    finally:
        restored.shutdown()
