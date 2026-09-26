"""A completed Flow signal bar is durably claimed before order ownership runs."""

from datetime import datetime
from multiprocessing import get_context
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from database import flow_db


def _claim_in_worker(db_path, execution_id, workflow_id, stamp, barrier, queue):
    """Use a distinct process and DB connection, as separate workers do."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker

    from database import flow_db as worker_db

    worker_engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 10})
    worker_session = scoped_session(sessionmaker(bind=worker_engine))
    worker_db.db_session = worker_session
    try:
        barrier.wait(timeout=10)
        queue.put(worker_db.claim_execution_bar(execution_id, workflow_id, datetime.fromisoformat(stamp)))
    finally:
        worker_session.remove()
        worker_engine.dispose()


def test_simultaneous_workers_can_claim_a_bar_only_once(tmp_path):
    db_path = tmp_path / "concurrent-claims.db"
    engine = create_engine(f"sqlite:///{db_path}")
    flow_db.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    try:
        workflow = flow_db.FlowWorkflow(name="concurrent", nodes=[], edges=[])
        session.add(workflow)
        session.flush()
        executions = [flow_db.FlowWorkflowExecution(workflow_id=workflow.id, status="running") for _ in range(2)]
        session.add_all(executions)
        session.commit()
        workflow_id = workflow.id
        execution_ids = [row.id for row in executions]
    finally:
        session.remove()
        engine.dispose()

    context = get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    stamp = datetime(2026, 9, 25, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata")).isoformat()
    workers = [context.Process(target=_claim_in_worker, args=(str(db_path), eid, workflow_id, stamp, barrier, queue)) for eid in execution_ids]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0
    assert sorted(queue.get(timeout=2) for _ in workers) == ["claimed", "duplicate"]


def test_migration_backfills_existing_log_claims(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from sqlalchemy import inspect, text

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "upgrade"))
    from upgrade.migrate_flow import create_flow_bar_claims_table

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-claims.db'}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE flow_workflows (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            conn.execute(text("CREATE TABLE flow_workflow_executions (id INTEGER PRIMARY KEY, workflow_id INTEGER, logs JSON)"))
            conn.execute(text("INSERT INTO flow_workflows VALUES (1, 'Legacy')"))
            conn.execute(text("INSERT INTO flow_workflow_executions VALUES (10, 1, :logs)"),
                         {"logs": json.dumps([{"bar_claim": "2026-09-25T09:40:00+05:30"}])})
        assert create_flow_bar_claims_table(engine)
        assert create_flow_bar_claims_table(engine)
        assert "flow_workflow_bar_claims" in inspect(engine).get_table_names()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT workflow_id, bar_start FROM flow_workflow_bar_claims")).all() == [
                (1, "2026-09-25T04:10:00+00:00")
            ]
    finally:
        engine.dispose()


def test_completed_bar_claim_survives_session_restart(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'flow-claims.db'}")
    flow_db.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(flow_db, "db_session", session)
    try:
        workflow = flow_db.FlowWorkflow(name="starter", nodes=[], edges=[])
        session.add(workflow)
        session.commit()
        workflow_id = workflow.id
        first = flow_db.FlowWorkflowExecution(
            workflow_id=workflow_id, status="running", started_at=datetime(2026, 9, 25, 4, 15)
        )
        session.add(first)
        session.commit()
        bar = datetime(2026, 9, 25, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata"))

        assert flow_db.claim_execution_bar(first.id, workflow_id, bar) == "claimed"
        session.remove()
        second = flow_db.FlowWorkflowExecution(
            workflow_id=workflow_id, status="running", started_at=datetime(2026, 9, 25, 4, 16)
        )
        session.add(second)
        session.commit()
        assert flow_db.claim_execution_bar(second.id, workflow_id, bar) == "duplicate"
        assert session.query(flow_db.FlowWorkflowExecution).get(second.id).logs in (None, [])
    finally:
        session.remove()
        engine.dispose()


def test_claim_is_independent_of_execution_log_retention(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'flow-claims-pruned.db'}")
    flow_db.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(flow_db, "db_session", session)
    monkeypatch.setattr(flow_db, "EXECUTION_RETENTION_COUNT", 2)
    try:
        workflow = flow_db.FlowWorkflow(name="starter", nodes=[], edges=[])
        session.add(workflow)
        session.commit()
        for _ in range(2):
            session.add(
                flow_db.FlowWorkflowExecution(
                    workflow_id=workflow.id, status="running", started_at=datetime(2026, 9, 25, 4, 15)
                )
            )
        session.commit()
        current = session.query(flow_db.FlowWorkflowExecution).order_by(flow_db.FlowWorkflowExecution.id.desc()).first()
        bar = datetime(2026, 9, 25, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata"))

        assert flow_db.claim_execution_bar(current.id, workflow.id, bar) == "claimed"
    finally:
        session.remove()
        engine.dispose()


def test_same_execution_cannot_claim_the_same_bar_twice(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'flow-claims-same-execution.db'}")
    flow_db.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(flow_db, "db_session", session)
    try:
        workflow = flow_db.FlowWorkflow(name="two run nodes", nodes=[], edges=[])
        session.add(workflow)
        session.commit()
        execution = flow_db.FlowWorkflowExecution(
            workflow_id=workflow.id, status="running", started_at=datetime(2026, 9, 25, 4, 15)
        )
        session.add(execution)
        session.commit()
        bar = datetime(2026, 9, 25, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata"))

        assert flow_db.claim_execution_bar(execution.id, workflow.id, bar) == "claimed"
        assert flow_db.claim_execution_bar(execution.id, workflow.id, bar) == "duplicate"
    finally:
        session.remove()
        engine.dispose()


def test_claim_finds_prior_execution_started_before_the_claimed_bar(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'flow-claims-early-start.db'}")
    flow_db.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(flow_db, "db_session", session)
    try:
        workflow = flow_db.FlowWorkflow(name="long running signal", nodes=[], edges=[])
        session.add(workflow)
        session.commit()
        first = flow_db.FlowWorkflowExecution(
            workflow_id=workflow.id, status="running", started_at=datetime(2026, 9, 25, 4, 4, 59)
        )
        session.add(first)
        session.commit()
        bar = datetime(2026, 9, 25, 9, 35, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert flow_db.claim_execution_bar(first.id, workflow.id, bar) == "claimed"

        second = flow_db.FlowWorkflowExecution(
            workflow_id=workflow.id, status="running", started_at=datetime(2026, 9, 25, 4, 10, 20)
        )
        session.add(second)
        session.commit()
        assert flow_db.claim_execution_bar(second.id, workflow.id, bar) == "duplicate"
    finally:
        session.remove()
        engine.dispose()


def test_old_retained_executions_do_not_permanently_exhaust_claim_window(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'flow-claims-old-history.db'}")
    flow_db.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(flow_db, "db_session", session)
    try:
        workflow = flow_db.FlowWorkflow(name="long lived workflow", nodes=[], edges=[])
        session.add(workflow)
        session.commit()
        session.add_all(
            flow_db.FlowWorkflowExecution(
                workflow_id=workflow.id,
                status="completed",
                started_at=datetime(2026, 9, 24, 4, 0),
                completed_at=datetime(2026, 9, 24, 4, 1),
            )
            for _ in range(500)
        )
        current = flow_db.FlowWorkflowExecution(
            workflow_id=workflow.id, status="running", started_at=datetime(2026, 9, 25, 4, 10)
        )
        session.add(current)
        session.commit()
        bar = datetime(2026, 9, 25, 9, 35, tzinfo=ZoneInfo("Asia/Kolkata"))

        assert flow_db.claim_execution_bar(current.id, workflow.id, bar) == "claimed"
    finally:
        session.remove()
        engine.dispose()
