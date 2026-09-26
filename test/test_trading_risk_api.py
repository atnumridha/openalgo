import pytest
from flask import Flask

from blueprints import trading_risk as routes
from database import trading_risk_db as ledger
from database.engine_factory import create_db_engine
from limiter import limiter


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_db_engine(f"sqlite:///{tmp_path}/risk.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test", TESTING=True, RATELIMIT_ENABLED=False)
    monkeypatch.setattr(limiter, "enabled", False)
    app.register_blueprint(routes.trading_risk_bp)
    monkeypatch.setattr(routes, "is_session_valid", lambda: True)
    with app.test_client() as client:
        yield client
    engine.dispose()


def test_risk_settings_require_session_and_show_distinct_budgets(client):
    assert client.get("/strategy/api/risk").status_code == 401
    with client.session_transaction() as session:
        session["user"] = "owner"
    response = client.get("/strategy/api/risk")
    assert response.status_code == 200
    data = response.json["data"]
    assert data["costs"] is None
    assert data["accounts"]["sandbox"]["later_remaining"] == 1000
    assert data["policy"]["daily_limit"] == 2000


def test_missing_cost_fields_and_unreviewed_resume_are_rejected(client):
    with client.session_transaction() as session:
        session["user"] = "owner"
    assert (
        client.put("/strategy/api/risk/costs", json={"brokerage_per_order": 0}).status_code == 400
    )
    assert (
        client.post(
            "/strategy/api/risk/resume", json={"mode": "live", "reason": "review"}
        ).status_code
        == 400
    )


def test_activation_refuses_existing_untracked_strategy_runs(client, monkeypatch):
    from database import strategy_module_db as store

    costs = {
        "schedule_id": "fixture",
        "source": "test-only",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "brokerage_per_order": 20,
        "exchange_rate": 0,
        "sebi_rate": 0,
        "gst_rate": 0,
        "stamp_buy_rate": 0,
        "stt_sell_rate": 0,
        "slippage_bps": 0,
    }
    with client.session_transaction() as session:
        session["user"] = "owner"
    monkeypatch.setattr(store, "list_strategies", lambda _: [{"current_run_id": 12}])
    response = client.put("/strategy/api/risk/costs", json=costs)
    assert response.status_code == 400
    assert not ledger.policy_enabled("owner")
    monkeypatch.setattr(store, "list_strategies", lambda _: [])
    assert client.put("/strategy/api/risk/costs", json=costs).status_code == 200
    assert ledger.policy_enabled("owner")
