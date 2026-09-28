"""Flow status must survive scoped-session cleanup inside client/node calls."""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import scoped_session, sessionmaker

from database import flow_db
from database.engine_factory import create_db_engine
from services import flow_executor_service as executor_service


@pytest.mark.parametrize(
    "cleanup_at,outcome,expected_status",
    [
        ("client", "success", "completed"),
        ("node", "success", "completed"),
        ("node", "node_error", "failed"),
        ("node", "collecting_history", "collecting_history"),
        ("node", "exception", "failed"),
    ],
)
def test_execution_finishes_after_session_cleanup(
    tmp_path, monkeypatch, cleanup_at, outcome, expected_status
):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'executions.db'}")
    session = scoped_session(sessionmaker(bind=engine))
    try:
        flow_db.Base.metadata.create_all(engine)
        monkeypatch.setattr(flow_db, "db_session", session)
        monkeypatch.setattr(
            flow_db, "get_execution", lambda eid: session.get(flow_db.FlowWorkflowExecution, eid)
        )
        monkeypatch.setattr(flow_db, "prune_workflow_executions", lambda wid: 0)
        monkeypatch.setattr(
            executor_service, "get_workflow", lambda wid: session.get(flow_db.FlowWorkflow, wid)
        )
        workflow = flow_db.FlowWorkflow(
            name="Session cleanup regression",
            nodes=[
                {"id": "start", "type": "start", "position": {"x": 0, "y": 0}, "data": {}}
            ],
            edges=[],
        )
        session.add(workflow)
        session.commit()
        workflow_id = workflow.id

        def cleanup_session():
            # Synchronous downstream services may commit, then remove their
            # shared scoped session. This leaves existing ORM rows expired and
            # detached, including their primary keys.
            session.commit()
            session.remove()

        def client_factory(api_key):
            if cleanup_at == "client":
                cleanup_session()
            return SimpleNamespace()

        def node_chain(node_id, nodes, edges, incoming, executor, context, visited, depth=0):
            if cleanup_at == "node":
                cleanup_session()
            executor.log("Node reached after session cleanup")
            if outcome == "node_error":
                executor.errors.append({"type": "test", "message": "node rejected"})
            elif outcome == "collecting_history":
                executor.readiness_status = "collecting_history"
                executor.readiness_label = "Collecting history"
                executor.readiness_message = "Need more candles"
            elif outcome == "exception":
                raise RuntimeError("node crashed")

        monkeypatch.setattr(executor_service, "get_flow_client", client_factory)
        monkeypatch.setattr(executor_service, "execute_node_chain", node_chain)
        result = executor_service.execute_workflow(workflow_id, api_key="test-only")

        session.remove()
        saved = session.get(flow_db.FlowWorkflowExecution, result["execution_id"])
        assert saved.status == expected_status
        assert saved.logs == result["logs"]
        assert any("Node reached" in entry["message"] for entry in saved.logs)
        assert not executor_service.get_workflow_lock(workflow_id).locked()
        if expected_status in {"completed", "failed"}:
            assert saved.completed_at is not None
        if expected_status == "failed":
            assert result["status"] == "error"
            expected_error = "test: node rejected" if outcome == "node_error" else "node crashed"
            assert saved.error == expected_error
        else:
            assert result["status"] == ("success" if outcome == "success" else outcome)
    finally:
        session.remove()
        engine.dispose()
