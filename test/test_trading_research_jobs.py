"""Research persistence, sealed data and worker ownership must fail closed."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from test_trading_research import fees, payload

from database.trading_research_db import ResearchStore
from services.research import jobs


@pytest.fixture
def store(tmp_path):
    instance = ResearchStore(f"sqlite:///{tmp_path / 'research.db'}")
    instance.init_db()
    yield instance
    instance.engine.dispose()


def create_run(store, days=80):
    imported = jobs.import_dataset(store, "alice", payload(days))
    run = jobs.queue_run(
        store,
        "alice",
        {
            "dataset_id": imported["id"],
            "candidate": "trend_breakout",
            "parameters": {"lookback": 2},
            "costs": fees(),
        },
    )
    return imported, run


def test_store_reimports_identical_dataset_and_hides_other_owners(store):
    data = jobs.import_dataset(store, "alice", payload())
    assert jobs.import_dataset(store, "alice", payload())["id"] == data["id"]
    assert store.get_dataset("bob", data["id"]) is None
    assert store.overview("bob")["datasets"] == []


def test_development_requires_enough_sessions_to_seal_last_sixty(store):
    with pytest.raises(ValueError, match="80"):
        create_run(store, 60)


def test_worker_cannot_run_same_job_twice_and_cancel_is_durable(store):
    _, run = create_run(store)
    assert store.acquire_worker("first") is True
    assert store.acquire_worker("second") is False
    claim = store.claim_job("first")
    assert claim["id"] == run["id"]
    assert store.claim_job("first") is None
    assert store.cancel_run("alice", run["id"])["cancel_requested"] is True
    with pytest.raises(jobs.Cancelled):
        jobs.process_job(store, "first", claim)
    assert store.get_run("alice", run["id"])["status"] == "cancelled"


def test_worker_completion_holdout_freeze_and_once_only_across_renamed_data(store):
    data, run = create_run(store)
    with pytest.raises(ValueError, match="frozen"):
        jobs.queue_final(store, "alice", run["id"])
    assert store.acquire_worker("worker")
    jobs.process_job(store, "worker", store.claim_job("worker"))
    complete = store.get_run("alice", run["id"])
    assert complete["status"] == "completed"
    assert complete["report"]["split"]["development_sessions"] == 20
    assert complete["report"]["split"]["holdout_consumed"] is False
    frozen = store.freeze_run("alice", run["id"])
    assert frozen["frozen_at"]
    final = jobs.queue_final(store, "alice", run["id"])
    assert final["kind"] == "final"
    with pytest.raises(ValueError, match="consumed"):
        jobs.queue_final(store, "alice", run["id"])
    store.cancel_run("alice", final["id"])
    with pytest.raises(ValueError, match="consumed"):
        jobs.queue_final(store, "alice", run["id"])
    assert jobs.release_status(store, "alice", run["id"])["eligible_for_live"] is False


def test_stale_worker_recovery_marks_running_interrupted_without_replaying_holdout(store):
    _, run = create_run(store)
    now = datetime.now(UTC).replace(tzinfo=None)
    assert store.acquire_worker("old", now=now)
    store.claim_job("old", now=now)
    assert store.acquire_worker("new", now=now + timedelta(seconds=121))
    assert store.get_run("alice", run["id"])["status"] == "interrupted"
    assert store.claim_job("new", now=now + timedelta(seconds=121)) is None


def test_graceful_worker_stop_marks_job_interrupted_and_does_not_requeue(store):
    _, run = create_run(store)
    assert store.acquire_worker("worker")
    claim = store.claim_job("worker")
    with pytest.raises(jobs.Cancelled):
        jobs.process_job(store, "worker", claim, should_stop=lambda: True)
    assert store.get_run("alice", run["id"])["status"] == "interrupted"
    assert store.claim_job("worker") is None


def test_worker_readiness_is_only_published_after_lease_and_removed_at_shutdown(store, tmp_path):
    import json
    import os
    import signal
    import subprocess
    import sys
    import time
    from pathlib import Path

    ready = tmp_path / "worker.ready"
    output = tmp_path / "worker.log"
    environment = os.environ | {"DATABASE_URL": str(store.engine.url), "LOG_FORMAT": "%(message)s"}
    with output.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "services.research.worker", "--ready-file", str(ready)],
            cwd=Path(__file__).parents[1],
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            assert ready.exists(), output.read_text()
            assert json.loads(ready.read_text())["pid"] == process.pid
            assert store.overview("alice")["worker"]["online"]
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=5) == 0
            assert not ready.exists()
            assert not store.overview("alice")["worker"]["online"]
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_consumed_holdout_cannot_become_development_data_in_extended_import(store):
    _, run = create_run(store, 80)
    assert store.acquire_worker("worker")
    jobs.process_job(store, "worker", store.claim_job("worker"))
    store.freeze_run("alice", run["id"])
    jobs.queue_final(store, "alice", run["id"])
    with pytest.raises(ValueError, match="holdout"):
        create_run(store, 100)


def test_previously_exposed_development_sessions_cannot_be_sealed_by_shorter_import(store):
    create_run(store, 100)
    _, shorter = create_run(store, 80)
    assert store.acquire_worker("worker")
    jobs.process_job(store, "worker", store.claim_job("worker"))
    jobs.process_job(store, "worker", store.claim_job("worker"))
    store.freeze_run("alice", shorter["id"])
    with pytest.raises(ValueError, match="exposed"):
        jobs.queue_final(store, "alice", shorter["id"])


def test_overview_does_not_load_dataset_bars_or_full_reports(store):
    from sqlalchemy import event

    create_run(store)
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store.engine, "before_cursor_execute", record)
    try:
        assert store.overview("alice")["datasets"]
    finally:
        event.remove(store.engine, "before_cursor_execute", record)
    assert all(
        "tr_dataset.content," not in sql and "tr_run.report," not in sql for sql in statements
    )


def test_queued_jobs_refuse_changed_implementation_and_preserve_failure(store, monkeypatch):
    _, run = create_run(store)
    assert store.acquire_worker("worker")
    monkeypatch.setattr(jobs, "implementation_hash", lambda: "different-code")
    with pytest.raises(ValueError, match="changed"):
        jobs.process_job(store, "worker", store.claim_job("worker"))
    assert store.get_run("alice", run["id"])["status"] == "failed"


def test_worker_cli_runs_offline_job_in_separate_process(store):
    import os
    import subprocess
    import sys
    from pathlib import Path

    _, run = create_run(store)
    environment = os.environ | {"DATABASE_URL": str(store.engine.url), "LOG_FORMAT": "%(message)s"}
    result = subprocess.run(
        [sys.executable, "-m", "services.research.worker", "--once"],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert store.get_run("alice", run["id"])["status"] == "completed"
    assert store.overview("alice")["worker"]["online"] is False


def test_cancellation_committed_before_finish_update_wins_race(store):
    from threading import Event, Thread, current_thread

    from sqlalchemy import event

    _, run = create_run(store)
    assert store.acquire_worker("worker")
    store.claim_job("worker")
    ready, release = Event(), Event()
    failures = []

    def before_write(connection, cursor, statement, parameters, context, executemany):
        if current_thread().name == "research-finisher" and statement.startswith("UPDATE tr_run"):
            ready.set()
            assert release.wait(5)

    def finish():
        try:
            store.finish_job("worker", run["id"], "completed", report={"visible": True})
        except Exception as error:
            failures.append(error)

    event.listen(store.engine, "before_cursor_execute", before_write)
    thread = Thread(target=finish, name="research-finisher")
    try:
        thread.start()
        assert ready.wait(5)
        assert store.cancel_run("alice", run["id"])["cancel_requested"] is True
    finally:
        release.set()
        thread.join(10)
        event.remove(store.engine, "before_cursor_execute", before_write)
    assert not thread.is_alive()
    assert not failures
    result = store.get_run("alice", run["id"])
    assert result["status"] == "cancelled"
    assert result["report"] is None


def test_expired_worker_cannot_commit_final_results(store):
    _, run = create_run(store)
    assert store.acquire_worker("worker")
    store.claim_job("worker")
    store.release_worker("worker")
    assert store.finish_job("worker", run["id"], "completed", report={"visible": True}) is False
    assert store.get_run("alice", run["id"])["status"] == "running"
