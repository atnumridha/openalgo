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


def test_allocation_review_preserves_peak_gap_and_history(client):
    from decimal import Decimal

    from sqlalchemy.orm import Session

    ledger.status("owner", "sandbox", "2026-01-02")
    with Session(ledger.engine) as db:
        account = db.get(ledger.RiskAccount, "owner|sandbox")
        account.peak = Decimal("11000")
        db.add(ledger.RiskTrade(scope="owner|sandbox", ref="closed-1",
                                session_day="2026-01-02", bucket="first", status="closed",
                                planned_risk=Decimal("700"), premium=Decimal("7500"),
                                net_pnl=Decimal("-500"), filled=True, segment="index",
                                broker="test", strategy_id=1, details={}, evidence={}))
        db.commit()
    before = ledger.status("owner", "sandbox", "2026-01-02")
    assert before["allocation_revision"] == 0
    after = ledger.review_allocation("owner", "sandbox", 25000,
                                     "Reviewed additional funded allocation", "2026-01-02")
    assert after["capital"] == 25000
    assert after["allocation_revision"] == 1
    assert after["peak_equity"] - after["equity"] == before["peak_equity"] - before["equity"]
    assert after["first_loss"] == before["first_loss"] == 500
    with Session(ledger.engine) as db:
        assert db.get(ledger.RiskAccount, "owner|sandbox").peak == 26000
        assert db.query(ledger.RiskReview).filter_by(scope="owner|sandbox").count() == 1
        db.add(ledger.RiskTrade(scope="owner|sandbox", ref="open-1",
                                session_day="2026-01-02", bucket="later", status="open",
                                planned_risk=Decimal("500"), premium=Decimal("7500"),
                                net_pnl=Decimal("0"), filled=True, segment="index",
                                broker="test", strategy_id=1, details={}, evidence={}))
        db.commit()
    with pytest.raises(ValueError, match="open or pending"):
        ledger.review_allocation("owner", "sandbox", 10000, "try to reset", "2026-01-02")


def test_allocation_revision_survives_round_trip_and_restart(client):
    first = ledger.status("owner", "sandbox", "2026-01-02")
    assert first["capital"] == 10000 and first["allocation_revision"] == 0
    ledger.review_allocation("owner", "sandbox", 25000, "Reviewed additional funding", "2026-01-02")
    ledger.review_allocation("owner", "sandbox", 10000, "Reviewed return of funding", "2026-01-02")
    restored = ledger.status("owner", "sandbox", "2026-01-02")
    assert restored["capital"] == 10000 and restored["allocation_revision"] == 2
    ledger.init_db()  # additive schema migration is idempotent across application startup
    assert ledger.status("owner", "sandbox", "2026-01-02")["allocation_revision"] == 2


def test_existing_risk_account_schema_adds_allocation_revision(tmp_path, monkeypatch):
    from sqlalchemy import inspect, text

    engine = create_db_engine(f"sqlite:///{tmp_path}/prior-risk.db")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE trading_risk_account (scope VARCHAR(180) PRIMARY KEY, "
                        "capital NUMERIC(20,4) NOT NULL, peak NUMERIC(20,4) NOT NULL, "
                        "paused BOOLEAN NOT NULL, pause_reason TEXT)"))
        db.execute(text("INSERT INTO trading_risk_account(scope,capital,peak,paused) "
                        "VALUES ('alice|sandbox',10000,10000,0)"))
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    assert "allocation_revision" in {column["name"] for column in inspect(engine).get_columns("trading_risk_account")}
    assert ledger.status("alice", "sandbox", "2026-01-02")["allocation_revision"] == 0
    ledger.init_db()
    engine.dispose()
