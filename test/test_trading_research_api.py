"""Authenticated bounded research requests persist jobs without executing them."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from flask import Flask
from test_trading_research import current_payload as payload
from test_trading_research import fees

from blueprints import trading_research
from database.trading_research_db import ResearchStore
from limiter import limiter


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = ResearchStore(f"sqlite:///{tmp_path / 'api.db'}")
    store.init_db()
    monkeypatch.setattr(trading_research, "get_store", lambda: store)
    monkeypatch.setattr(limiter, "enabled", False)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="research-test")
    app.register_blueprint(trading_research.trading_research_bp)
    yield app.test_client(), store
    store.engine.dispose()


def login(client, user="alice"):
    with client.session_transaction() as session:
        session.update(
            logged_in=True, user=user, login_time=datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
        )


def test_unauthenticated_api_returns_json_without_disclosing_datasets(api):
    client, store = api
    response = client.get("/strategy/api/research")
    assert response.status_code == 401
    assert response.json["status"] == "error"


def test_api_queue_returns_offline_state_then_owner_scoped_run(api):
    client, store = api
    login(client)
    response = client.post("/strategy/api/research/datasets", json=payload(80))
    assert response.status_code == 201
    dataset_id = response.json["data"]["id"]
    response = client.post(
        "/strategy/api/research/runs",
        json={"dataset_id": dataset_id, "candidate": "trend_breakout", "costs": fees()},
    )
    assert response.status_code == 202
    run_id = response.json["data"]["id"]
    assert response.json["data"]["status"] == "queued"
    assert client.get("/strategy/api/research").json["data"]["worker"]["online"] is False
    assert (
        client.get(f"/strategy/api/research/runs/{run_id}/release").json["data"][
            "eligible_for_live"
        ]
        is False
    )
    login(client, "bob")
    assert client.get(f"/strategy/api/research/runs/{run_id}").status_code == 404
    assert client.post(f"/strategy/api/research/runs/{run_id}/cancel").status_code == 404


def test_api_optimization_creation_result_and_owner_scoped_promotion(api):
    from services.research import jobs

    client, store = api
    login(client)
    dataset_id = client.post("/strategy/api/research/datasets", json=payload(80)).json["data"]["id"]
    response = client.post(
        "/strategy/api/research/runs",
        json={
            "dataset_id": dataset_id,
            "candidate": "trend_breakout",
            "costs": fees(),
            "run_kind": "optimization",
            "parameter_grid": {"lookback": [2, 3]},
        },
    )
    assert response.status_code == 202
    run = response.json["data"]
    assert run["kind"] == "optimization"
    store.acquire_worker("worker")
    jobs.process_job(store, "worker", store.claim_job("worker"))
    result = client.get(f"/strategy/api/research/runs/{run['id']}").json["data"]
    assert result["report"]["candidate_count"] == 2
    assert client.post(f"/strategy/api/research/runs/{run['id']}/freeze").status_code == 400
    login(client, "bob")
    assert client.post(f"/strategy/api/research/runs/{run['id']}/promote").status_code == 404
    login(client)
    promoted = client.post(f"/strategy/api/research/runs/{run['id']}/promote")
    assert promoted.status_code == 202
    assert promoted.json["data"]["parent_run_id"] == run["id"]
    assert promoted.json["data"]["kind"] == "development"


def test_api_ml_capabilities_and_unavailable_dependency(api, monkeypatch):
    client, store = api
    login(client)
    monkeypatch.setattr(
        trading_research.jobs,
        "ml_dependencies",
        lambda: {"available": False, "reason": "Install research dependencies"},
    )
    result = client.get("/strategy/api/research").json["data"]
    assert result["capabilities"]["ml"]["available"] is False
    assert result["capabilities"]["ml_live"] is True  # JSON inference does not require training dependencies.
    assert result["capabilities"]["optimization_max_candidates"] == 256


def test_bad_json_and_excess_request_body_fail_before_work(api, monkeypatch):
    client, store = api
    login(client)
    assert client.post("/strategy/api/research/datasets", json=[]).status_code == 400
    monkeypatch.setattr(trading_research, "MAX_BODY_BYTES", 100)
    assert (
        client.post("/strategy/api/research/datasets", json={"padding": "x" * 200}).status_code
        == 413
    )
