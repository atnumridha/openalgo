from copy import deepcopy
from types import SimpleNamespace

import pytest


def workflow(mode="sandbox"):
    return SimpleNamespace(
        id=8,
        broker_connection_id="account",
        is_active=False,
        nodes=[
            {
                "id": "run",
                "type": "strategyModuleRun",
                "position": {"x": 10, "y": 20},
                "data": {"strategyId": 1, "brokerOwner": "alice", "mode": mode},
            },
            {"id": "condition", "type": "condition", "data": {"operator": "gt", "value": 42}},
        ],
        edges=[{"id": "e", "source": "condition", "target": "run"}],
    )


def test_binding_preserves_rules_but_allows_operational_live_transition():
    from services.research.qualification_context import strategy_digest, workflow_digest

    strategy = {
        "id": 1,
        "name": "test",
        "legs": [{"sl_pts": 10}],
        "live_enabled": False,
        "status": "stopped",
        "current_run_id": None,
    }
    live = {
        **strategy,
        "live_enabled": True,
        "status": "running",
        "current_run_id": 12,
        "updated_at": "later",
    }
    assert strategy_digest(strategy) == strategy_digest(live)
    assert workflow_digest([workflow()]) == workflow_digest([workflow("live")])
    changed = deepcopy(live)
    changed["legs"][0]["sl_pts"] = 20
    assert strategy_digest(changed) != strategy_digest(strategy)
    changed_flow = workflow()
    changed_flow.nodes[1]["data"]["value"] = 43
    assert workflow_digest([changed_flow]) != workflow_digest([workflow()])


def test_binding_excludes_graph_secrets_from_returned_context(monkeypatch):
    from services.research import qualification_context as context

    monkeypatch.setattr(context, "_source_hash", lambda: "source-v1")
    s = {
        "id": 1,
        "broker_connection_id": "account",
        "legs": [{"sl_pts": 10}],
        "underlying": "NIFTY",
        "strategy_kind": "batch",
    }
    monkeypatch.setattr(context, "_read_strategy", lambda *args: s)
    monkeypatch.setattr(context, "_read_workflows", lambda *args: [workflow()])
    monkeypatch.setattr(
        context,
        "_broker_identity",
        lambda *args: {
            "broker": "kotak",
            "broker_connection_id": "account",
            "broker_epoch": "hashed-token",
        },
    )
    monkeypatch.setattr(
        context, "_risk_context", lambda *args: {"costs": {"schedule_id": "v1"}, "paused": False}
    )
    data = context.current_binding("alice", 1)
    assert data["broker_epoch"] == "hashed-token"
    assert data["binding_hash"]
    assert "nodes" not in data and "strategy" not in data
    monkeypatch.setattr(
        context,
        "_broker_identity",
        lambda *args: {
            "broker": "kotak",
            "broker_connection_id": "account",
            "broker_epoch": "new-token-hash",
        },
    )
    assert context.current_binding("alice", 1)["binding_hash"] == data["binding_hash"]
    with pytest.raises(ValueError, match="changed after admission"):
        context.current_binding("alice", 1, strategy_config={"legs": [{"sl_pts": 99}]})
    from services.research import qualification_execution

    monkeypatch.setattr(
        qualification_execution,
        "current_flow_origin",
        lambda: {"workflow_id": 8, "execution_id": 1, "workflow_hash": "old-graph"},
    )
    with pytest.raises(ValueError, match="running Flow graph differs"):
        context.current_binding("alice", 1)


def test_entry_release_check_cannot_be_skipped_but_exit_is_unblocked(monkeypatch):
    from services.research import qualification_execution as execution

    monkeypatch.setattr(execution, "entry_release_reason", lambda *args: "Release revoked")
    assert (
        execution.before_dispatch({"owner": "alice", "strategy_id": 1}, "live", "entry", "key", {})
        == "Release revoked"
    )
    assert (
        execution.before_dispatch({"owner": "alice", "strategy_id": 1}, "live", "exit", "key", {})
        is None
    )


def test_dispatch_token_must_match_current_approved_session(monkeypatch):
    from database import trading_risk_db as ledger
    from services.research import qualification_context, qualification_execution
    from services.research.dataset import digest

    monkeypatch.setattr(ledger, "policy_enabled", lambda owner: True)
    identity = {
        "broker": "kotak",
        "broker_account_hash": "account",
        "broker_epoch": digest({"account": "account", "token": "current-token"}),
    }
    monkeypatch.setattr(qualification_context, "_broker_identity", lambda *args: identity)
    metadata = {"owner": "alice", "strategy_id": 1}
    assert (
        qualification_execution.live_session_reason(metadata, "current-token", "kotak", "pin")
        is None
    )
    assert qualification_execution.live_session_reason(metadata, "old-token", "kotak", "pin")


def test_kotak_identity_uses_authenticated_account_not_retagged_config(tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from database import auth_db
    from database.engine_factory import create_db_engine
    from services.research.qualification_context import _broker_identity
    from utils import config

    engine = create_db_engine(f"sqlite:///{tmp_path / 'account.db'}")
    monkeypatch.setattr(auth_db, "engine", engine)
    auth_db.Base.metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE broker_connections (id TEXT,user_id TEXT,broker TEXT,status TEXT,is_revoked INTEGER)"
            )
        )
        db.execute(text("ALTER TABLE api_keys ADD COLUMN broker_connection_id TEXT"))
        db.execute(
            text("INSERT INTO broker_connections VALUES ('pin','alice','kotak','connected',0)")
        )
        db.execute(
            text(
                "INSERT INTO api_keys(user_id,api_key_hash,api_key_encrypted,broker_connection_id) VALUES ('alice','test','test','pin')"
            )
        )
    with Session(engine) as db:
        db.add(
            auth_db.Auth(
                name="alice", broker="kotak", auth=auth_db.encrypt_token("token"), user_id=None
            )
        )
        db.commit()
    try:
        monkeypatch.setattr(config, "get_broker_api_key", lambda: "test-ucc-one")
        with pytest.raises(ValueError, match="account identity"):
            _broker_identity("alice", "pin")
        with Session(engine) as db:
            db.query(auth_db.Auth).first().user_id = "test-ucc-one"
            db.commit()
        first = _broker_identity("alice", "pin")
        # Fernet re-encryption of the same token must not reset the epoch.
        with Session(engine) as db:
            db.query(auth_db.Auth).first().auth = auth_db.encrypt_token("token")
            db.commit()
        assert _broker_identity("alice", "pin") == first
        monkeypatch.setattr(config, "get_broker_api_key", lambda: "test-ucc-two")
        with pytest.raises(ValueError, match="account changed"):
            _broker_identity("alice", "pin")
        with Session(engine) as db:
            row = db.query(auth_db.Auth).first()
            row.user_id = "test-ucc-two"
            row.auth = auth_db.encrypt_token("new-authenticated-token")
            db.commit()
        assert (
            _broker_identity("alice", "pin")["broker_account_hash"] != first["broker_account_hash"]
        )
        monkeypatch.setattr(config, "get_broker_api_key", lambda: None)
        with pytest.raises(ValueError, match="account changed"):
            _broker_identity("alice", "pin")
    finally:
        engine.dispose()


def test_execution_origin_is_scoped_to_a_durable_running_flow(tmp_path, monkeypatch):
    from datetime import datetime

    from sqlalchemy.orm import Session

    from database import flow_db
    from database.engine_factory import create_db_engine
    from services.research.qualification_execution import current_flow_origin, flow_origin

    engine = create_db_engine(f"sqlite:///{tmp_path / 'flow.db'}")
    monkeypatch.setattr(flow_db, "engine", engine)
    flow_db.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            flow_db.FlowWorkflowExecution(
                id=10, workflow_id=8, status="running", started_at=datetime.now()
            )
        )
        db.commit()
    try:
        assert current_flow_origin() is None
        with flow_origin(8, 10, "current-graph"):
            assert current_flow_origin()["workflow_hash"] == "current-graph"
            with Session(engine) as db:
                db.get(flow_db.FlowWorkflowExecution, 10).status = "completed"
                db.commit()
            assert current_flow_origin() is None
        assert current_flow_origin() is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("revoked_during_quote", [False, True])
def test_live_dispatch_rechecks_release_after_quote_and_never_blocks_exit(
    monkeypatch, revoked_during_quote
):
    import restx_api  # noqa: F401
    from services import place_order_service
    from services.research import qualification_execution as execution
    from services.strategy_module import live_protection
    from services.strategy_module import order_dispatch as dispatch

    revoked = False
    calls = []
    monkeypatch.setattr(
        execution, "entry_release_reason", lambda metadata: "Release revoked" if revoked else None
    )
    monkeypatch.setattr(dispatch, "resolve_live_auth", lambda key: ("token", "kotak", None))
    monkeypatch.setattr(
        live_protection, "_connection_for_api_key", lambda key: ("account", "kotak")
    )

    def quote(order, *args):
        nonlocal revoked
        revoked = revoked_during_quote
        return order, None

    monkeypatch.setattr(dispatch, "bounded_live_entry_order", quote)

    def broker(order, *args, **kwargs):
        assert not any(key.startswith("_strategy_") for key in order)
        calls.append(order)
        return True, {"status": "success", "orderid": "test-order"}, 200

    monkeypatch.setattr(place_order_service, "place_order_with_auth", broker)
    order = dispatch.build_order(
        symbol="NIFTYTESTCE",
        exchange="NFO",
        action="BUY",
        quantity=10,
        product="MIS",
        strategy_name="Qualification",
        pricetype="LIMIT",
        price=100,
    )
    order.update(
        _strategy_broker="kotak",
        _strategy_connection_id="account",
        protective_stop_required=True,
        protective_stop_loss_points=10,
        _strategy_qualification={"owner": "alice", "strategy_id": 1},
    )
    result = dispatch.dispatch_order(mode="live", api_key="key", order=order, intent="entry")
    assert result.ok is not revoked_during_quote
    assert len(calls) == (0 if revoked_during_quote else 1)
    revoked = True
    assert dispatch.dispatch_order(
        mode="live", api_key="key", order={**order, "action": "SELL"}, intent="exit"
    ).ok


def test_prospective_dispatch_collects_actual_order_shapes_and_retries_delivery(
    tmp_path, monkeypatch
):
    """Real intent rows + ledger + receipt store, with only the broker mocked."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy.orm import Session, scoped_session, sessionmaker
    from test_strategy_qualification import binding, costs, final_run

    import restx_api  # noqa: F401
    from database import auth_db
    from database import strategy_module_db as orders
    from database import trading_risk_db as ledger
    from database.engine_factory import create_db_engine
    from database.strategy_qualification_db import QualificationStore, QualificationTrade
    from services import quotes_service, sandbox_service
    from services.research import qualification, qualification_context
    from services.strategy_module import live_protection, state, trading_budget
    from services.strategy_module import order_dispatch as dispatch

    engine = create_db_engine(f"sqlite:///{tmp_path / 'integrated.db'}")
    sessions = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(ledger, "engine", engine)
    monkeypatch.setattr(orders, "db_session", sessions)
    ledger.init_db()
    orders.Base.metadata.create_all(engine)
    collector = QualificationStore(engine=engine)
    collector.init_db()
    monkeypatch.setattr(qualification, "get_store", lambda: collector)
    bound = {
        **binding(),
        "broker": "kotak",
        "broker_connection_id": "account",
        "broker_account_hash": "identity",
    }
    monkeypatch.setattr(qualification, "current_binding", lambda *args, **kwargs: bound)
    monkeypatch.setattr(qualification_context, "_broker_identity", lambda *args: bound)
    monkeypatch.setattr(auth_db, "verify_api_key", lambda key: "alice")
    monkeypatch.setattr(auth_db, "get_auth_token_fresh", lambda owner: "test-token")
    monkeypatch.setattr(
        live_protection, "_connection_for_api_key", lambda key: ("account", "kotak")
    )
    now = datetime.now(UTC)
    campaign = collector.create_campaign(
        "alice", 1, 4, bound, final_run(), now - timedelta(seconds=1)
    )
    ledger.set_costs("alice", costs())
    leg = {
        "position_ref": "prospective",
        "leg_id": 1,
        "position": "B",
        "exchange": "NFO",
        "symbol": "NIFTYTESTCE",
        "lot_size": 10,
        "quantity": 10,
    }
    facts = SimpleNamespace(
        entry_risk=Decimal("100"),
        estimated_debit=Decimal("1000"),
        available_cash=Decimal("10000"),
        open_derivative_positions=0,
    )
    accepted, ref = trading_budget.reserve_entry(
        "alice", {"id": 1, "strategy_type": "intraday"}, [leg], "sandbox", "sandbox", facts, now
    )
    assert accepted.allowed
    trading_budget.dispatch_started("alice", "sandbox", ref, 12)
    monkeypatch.setattr(
        state, "get_run_state", lambda run_id: {"legs": {"1": {"position_ref": ref, "ltp": 101}}}
    )
    side = "BUY"
    monkeypatch.setattr(
        quotes_service,
        "get_quotes",
        lambda *args, **kwargs: (
            True,
            {
                "data": {
                    "bid": 100 if side == "BUY" else 120,
                    "ask": 101 if side == "BUY" else 121,
                    "bid_qty": 100,
                    "ask_qty": 100,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
            200,
        ),
    )

    def fill(order, key, original):
        assert "_strategy_qualification" not in order and "_strategy_qualification" not in original
        with Session(engine) as db:
            row = db.get(QualificationTrade, ("alice", ref))
            assert str(order_id) in row.quotes  # committed before sandbox placement
        assert orders.update_order(
            order_id,
            status="complete",
            broker_order_id=f"sandbox-{order_id}",
            avg_fill_price=100 if side == "BUY" else 121,
            filled_qty=10,
        )
        return True, {"status": "success", "orderid": f"sandbox-{order_id}"}, 200

    monkeypatch.setattr(sandbox_service, "sandbox_place_order", fill)
    try:
        for side in ("BUY", "SELL"):
            with Session(engine) as db:
                intent = orders.SmStrategyOrder(
                    run_id=12,
                    leg_id=1,
                    kind="entry" if side == "BUY" else "exit",
                    position_ref=ref,
                    symbol=leg["symbol"],
                    exchange="NFO",
                    action=side,
                    qty=10,
                    product="MIS",
                    status="pending",
                )
                db.add(intent)
                db.commit()
                order_id = intent.id
            outgoing = dispatch.build_order(
                symbol=leg["symbol"],
                exchange="NFO",
                action=side,
                quantity=10,
                product="MIS",
                strategy_name="Qualified test",
            )
            outgoing["_strategy_qualification"] = {
                "owner": "alice",
                "strategy_id": 1,
                "trade_ref": ref,
                "order_id": order_id,
            }
            assert dispatch.dispatch_order(
                mode="sandbox",
                api_key="test-key",
                order=outgoing,
                intent="entry" if side == "BUY" else "exit",
            ).ok
            trading_budget.sync_run(12)
        collected = collector.get_campaign("alice", campaign["id"])
        trade = collected["trades"][0]
        assert trade["valid"], trade["issues"]
        assert trade["net_pnl"] == pytest.approx(185.79)
        revision = collected["revision"]
        trading_budget.sync_run(12)
        assert collector.get_campaign("alice", campaign["id"])["revision"] == revision
        # A post-commit sink failure is recovered even with no new fill delta.
        with Session(engine) as db:
            db.get(orders.SmStrategyOrder, order_id).avg_fill_price = 119
            db.commit()
        sessions.remove()
        original_record = qualification.record_trade
        monkeypatch.setattr(
            qualification,
            "record_trade",
            lambda *args: (_ for _ in ()).throw(RuntimeError("write interrupted")),
        )
        trading_budget.sync_run(12)
        assert ledger.status("alice", "sandbox", now.date().isoformat())["paused"]
        monkeypatch.setattr(qualification, "record_trade", original_record)
        trading_budget.sync_run(12)
        updated = collector.get_campaign("alice", campaign["id"])
        assert updated["revision"] > revision
        assert updated["trades"][0]["net_pnl"] == pytest.approx(175.80)
    finally:
        sessions.remove()
        engine.dispose()
