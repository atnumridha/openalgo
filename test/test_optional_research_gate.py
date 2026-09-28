"""Optional research checks do not grant live permission or bypass risk checks."""

from datetime import datetime
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from blueprints import trading_risk as routes
from database import strategy_module_db as strategies, trading_risk_db as ledger
from database.engine_factory import create_db_engine
from limiter import limiter
from services.research import qualification, qualification_execution
from services.risk.budget import current_policy
from services.strategy_module import trading_budget

COSTS = {"schedule_id": "fixture", "source": "test-only", "effective_from": "2026-01-01",
         "effective_to": "2026-12-31", "brokerage_per_order": 20, "exchange_rate": 0,
         "sebi_rate": 0, "gst_rate": 0, "stamp_buy_rate": 0, "stt_sell_rate": 0,
         "slippage_bps": 0}
LEG = {"position_ref": "p1", "leg_id": 1, "position": "B", "option_type": "CE",
       "exchange": "NFO", "symbol": "NIFTYTESTCE", "lot_size": 50, "quantity": 50}


def test_required_default_is_portable_to_postgresql():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(ledger.RiskLiveEntryPolicy.__table__).compile(dialect=postgresql.dialect()))
    assert "research_required BOOLEAN DEFAULT true NOT NULL" in ddl


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    engine = create_db_engine(f"sqlite:///{tmp_path}/optional-research.db")
    monkeypatch.setattr(ledger, "engine", engine)
    monkeypatch.setattr(ledger, "POLICY", current_policy())
    monkeypatch.setattr(strategies, "engine", engine)
    sessions = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(strategies, "db_session", sessions)
    ledger.init_db()
    strategies.Base.metadata.create_all(engine)
    from database.strategy_qualification_db import QualificationStore
    research = QualificationStore(engine=engine)
    research.init_db()
    monkeypatch.setattr(qualification, "get_store", lambda: research)
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test", TESTING=True, RATELIMIT_ENABLED=False)
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(routes, "is_session_valid", lambda: True)
    app.register_blueprint(routes.trading_risk_bp)
    with app.test_client() as client:
        yield client, engine
    sessions.remove()
    engine.dispose()


def sign_in(client, user="owner"):
    with client.session_transaction() as session:
        session["user"] = user


def request_payload(**overrides):
    return {"research_required": False, "expected_revision": 0,
            "reason": "Operator reviewed optional research", "confirm": True, **overrides}


def test_default_still_requires_campaign_and_post_requires_authentication(isolated):
    client, _ = isolated
    assert client.post("/strategy/api/risk/live-entry-policy", json=request_payload()).status_code == 401
    sign_in(client)
    policy = client.get("/strategy/api/risk").json["data"]["live_entry_policy"]
    assert policy["research_required"] is True
    assert policy["revision"] == 0
    assert qualification.live_release_reason("owner", 1, {}, "fixed-300-v3", COSTS)


def test_optional_choice_is_durable_audited_and_owner_scoped_without_live_activation(isolated):
    client, engine = isolated
    sign_in(client)
    response = client.post("/strategy/api/risk/live-entry-policy", json=request_payload())
    assert response.status_code == 200
    assert response.json["data"]["research_required"] is False
    assert response.json["data"]["revision"] == 1
    ledger.init_db()
    assert client.get("/strategy/api/risk").json["data"]["live_entry_policy"]["research_required"] is False
    assert qualification.live_release_reason("owner", 1, {}, "fixed-300-v3", COSTS) is None
    assert qualification.live_release_reason("other", 1, {}, "fixed-300-v3", COSTS)
    from services.strategy_module.live_authorization import peek_status
    assert not peek_status("owner").active
    with Session(engine) as db:
        assert not db.scalars(select(strategies.SmStrategyRun)).all()
        audit = db.scalars(select(ledger.RiskReview)).one()
        assert audit.details["action"] == "live_entry_policy"
        assert audit.details["research_required"] is False


@pytest.mark.parametrize("overrides", [
    {"confirm": False}, {"confirm": "true"}, {"research_required": 0},
    {"research_required": "false"}, {"expected_revision": True},
    {"expected_revision": -1}, {"reason": ""}, {"unexpected": True},
])
def test_optional_choice_needs_explicit_well_formed_review(isolated, overrides):
    client, _ = isolated
    sign_in(client)
    assert client.post("/strategy/api/risk/live-entry-policy", json=request_payload(**overrides)).status_code == 400
    assert client.get("/strategy/api/risk").json["data"]["live_entry_policy"]["research_required"] is True


def test_stale_review_cannot_overwrite_new_policy_and_required_can_be_restored(isolated):
    client, _ = isolated
    sign_in(client)
    assert client.post("/strategy/api/risk/live-entry-policy", json=request_payload()).status_code == 200
    assert client.post("/strategy/api/risk/live-entry-policy", json=request_payload(research_required=True)).status_code == 400
    result = client.post("/strategy/api/risk/live-entry-policy", json=request_payload(research_required=True, expected_revision=1))
    assert result.status_code == 200
    assert qualification.live_release_reason("owner", 1, {}, "fixed-300-v3", COSTS)


def test_cannot_change_requirement_while_any_strategy_is_live_enabled(isolated):
    client, engine = isolated
    sign_in(client)
    with Session(engine) as db, db.begin():
        db.add(strategies.SmStrategy(user_id="owner", name="Live test", universe_tab="nse",
            underlying="NIFTY", underlying_exchange="NSE_INDEX", live_enabled=True, legs=[],
            webhook_token_hash="test-only"))
    response = client.post("/strategy/api/risk/live-entry-policy", json=request_payload())
    assert response.status_code == 400
    assert "live" in response.json["message"].lower()
    assert client.get("/strategy/api/risk").json["data"]["live_entry_policy"]["research_required"] is True


def test_detached_open_live_run_still_blocks_requirement_changes(isolated):
    client, engine = isolated
    sign_in(client)
    with Session(engine) as db, db.begin():
        strategy = strategies.SmStrategy(user_id="owner", name="Detached live run",
            universe_tab="nse", underlying="NIFTY", underlying_exchange="NSE_INDEX",
            live_enabled=False, legs=[], webhook_token_hash="test-only")
        db.add(strategy)
        db.flush()
        db.add(strategies.SmStrategyRun(strategy_id=strategy.id, mode="live"))
    response = client.post("/strategy/api/risk/live-entry-policy", json=request_payload())
    assert response.status_code == 400
    assert "close its positions" in response.json["message"]
    assert ledger.get_live_entry_policy("owner")["research_required"] is True


@pytest.mark.parametrize("trade_status", ["pending", "open"])
def test_outstanding_live_risk_reservations_block_setting_changes(isolated, trade_status):
    client, engine = isolated
    sign_in(client)
    with Session(engine) as db, db.begin():
        db.add(ledger.RiskTrade(scope=ledger._scope("owner", "live"), ref="unresolved",
            session_day="2026-09-28", bucket="first", status=trade_status,
            planned_risk=200, premium=2000, segment="index", broker="kotak", strategy_id=1))
    response = client.post("/strategy/api/risk/live-entry-policy", json=request_payload())
    assert response.status_code == 400
    assert "reconcile live positions" in response.json["message"]
    assert ledger.get_live_entry_policy("owner")["research_required"] is True


def test_optional_research_does_not_waive_broker_identity_checks(isolated, monkeypatch):
    client, _ = isolated
    sign_in(client)
    ledger.set_costs("owner", COSTS)
    assert client.post("/strategy/api/risk/live-entry-policy", json=request_payload()).status_code == 200
    from services.research import qualification_context
    def identity_unavailable(*_args):
        raise ValueError("Test account identity unavailable")
    monkeypatch.setattr(qualification_context, "_broker_identity", identity_unavailable)
    reason = qualification_execution.live_session_reason({"owner": "owner"}, "test-token", "kotak", None)
    assert reason and "unavailable" in reason


@pytest.mark.parametrize(("gross_risk", "cash", "allowed", "code"), [
    ("200", "10000", True, None),
    ("301", "10000", False, "per_trade_risk_exceeded"),
    ("200", "1000", False, "cash_buffer"),
])
def test_optional_research_still_enforces_stop_and_real_cash_limits(isolated, gross_risk, cash, allowed, code):
    client, _ = isolated
    sign_in(client)
    assert client.post("/strategy/api/risk/live-entry-policy", json=request_payload()).status_code == 200
    ledger.set_costs("owner", COSTS)
    facts = SimpleNamespace(entry_risk=D(gross_risk), estimated_debit=D("2000"),
                            available_cash=D(cash), open_derivative_positions=0)
    strategy = SimpleNamespace(id=1, strategy_type="intraday")
    decision, ref = trading_budget.reserve_entry("owner", strategy, [dict(LEG)], "live", "kotak", facts,
        datetime(2026, 9, 28, 10, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert decision.allowed is allowed
    if code:
        assert decision.code == code and ref is None
    else:
        assert ref == "p1"
        assert ledger.list_trades("owner", "live")[0]["planned_risk"] == D("240")


def test_dispatch_rechecks_the_same_saved_research_choice_and_failures_block_entries(isolated, monkeypatch):
    client, _ = isolated
    sign_in(client)
    ledger.set_costs("owner", COSTS)
    metadata = {"owner": "owner", "strategy_id": 1}
    assert qualification_execution.before_dispatch(metadata, "live", "entry", "unused", {"exchange": "NFO"})
    assert client.post("/strategy/api/risk/live-entry-policy", json=request_payload()).status_code == 200
    assert qualification_execution.before_dispatch(metadata, "live", "entry", "unused", {"exchange": "NFO"}) is None
    client.post("/strategy/api/risk/live-entry-policy", json=request_payload(research_required=True, expected_revision=1))
    assert qualification_execution.before_dispatch(metadata, "live", "entry", "unused", {"exchange": "NFO"})
    def unavailable(_user):
        raise RuntimeError("test storage unavailable")
    monkeypatch.setattr(ledger, "get_live_entry_policy", unavailable)
    assert qualification_execution.before_dispatch(metadata, "live", "entry", "unused", {"exchange": "NFO"})
    assert qualification_execution.before_dispatch(metadata, "live", "exit", "unused", {}) is None


def test_migration_adds_policy_table_without_changing_existing_capital_or_costs(isolated):
    _, engine = isolated
    ledger.set_costs("owner", COSTS)
    ledger.review_allocation("owner", "sandbox", 50000, "Existing test allocation", "2026-09-28")
    ledger.RiskLiveEntryPolicy.__table__.drop(engine)
    from upgrade.migrate_trading_research import apply, status
    assert not status(engine)
    assert apply(engine) and apply(engine)
    assert ledger.get_live_entry_policy("owner")["research_required"] is True
    assert ledger.status("owner", "sandbox", "2026-09-28")["capital"] == D("50000")
    assert ledger.get_costs("owner") == COSTS
    ledger.review_live_entry_policy("owner", False, 0, "Existing optional choice")
    assert apply(engine)
    assert ledger.get_live_entry_policy("owner")["research_required"] is False
