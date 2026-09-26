"""WhatsApp status changes are durable, sparse, and broker-pinned."""

from services.strategy_module import connection_alerts
from datetime import date


def test_broker_transition_and_whatsapp_outbox_commit_together(tmp_path, monkeypatch):
    from sqlalchemy.orm import scoped_session, sessionmaker

    from database import strategy_module_db as store
    from database.engine_factory import create_db_engine

    engine = create_db_engine(f"sqlite:///{tmp_path / 'connection-status.db'}")
    store.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine, autoflush=False))
    monkeypatch.setattr(store, "db_session", session)
    try:
        assert store.record_broker_data_transition(
            "owner", "kotak-connection", healthy=False, broker_status="expired"
        )
        assert not store.record_broker_data_transition(
            "owner", "kotak-connection", healthy=False, broker_status="expired"
        )
        assert store.record_broker_data_transition(
            "owner", "kotak-connection", healthy=True, broker_status="connected"
        )
        assert session.query(store.SmAutomationEvent).count() == 2
        assert session.query(store.SmCriticalAlert).count() == 2
        assert session.query(store.SmBrokerDataStatus).one().state == "healthy"
    finally:
        session.remove()
        engine.dispose()


def test_comparison_summary_is_once_per_strategy_session_with_outbox(tmp_path, monkeypatch):
    from sqlalchemy.orm import scoped_session, sessionmaker

    from database import strategy_module_db as store
    from database.engine_factory import create_db_engine

    engine = create_db_engine(f"sqlite:///{tmp_path / 'summary.db'}")
    store.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine, autoflush=False))
    monkeypatch.setattr(store, "db_session", session)
    try:
        created, error = store.create_strategy("owner", {
            "name": "Sandbox summary", "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX", "universe_tab": "weekly_monthly",
            "legs": [],
        })
        assert error is None
        day = date(2026, 9, 25)
        args = (created["id"], "owner", day, "Incomplete sandbox comparison", {"fees": "unavailable"})
        assert store.record_comparison_session_summary(*args)
        assert not store.record_comparison_session_summary(*args)
        assert session.query(store.SmComparisonSessionSummary).count() == 1
        assert session.query(store.SmStrategyEvent).filter_by(kind="sandbox_comparison_summary").count() == 1
        assert session.query(store.SmCriticalAlert).count() == 1
    finally:
        session.remove()
        engine.dispose()


def test_expired_connection_alerts_once_and_recovery_needs_prior_failure(monkeypatch):
    row = {
        "id": "kotak-connection", "user_id": "owner", "broker": "kotak",
        "status": "expired", "is_revoked": False,
    }
    seen = []
    monkeypatch.setattr(connection_alerts, "_active_connections", lambda: [row])
    def transition(_user, _connection, *, healthy, broker_status):
        kind = "broker_data_recovered" if healthy else "broker_data_unavailable"
        if seen and seen[-1] == kind:
            return False
        seen.append(kind)
        return True

    monkeypatch.setattr(connection_alerts.store, "record_broker_data_transition", transition)

    assert connection_alerts.check_active_connections() == 1
    assert connection_alerts.check_active_connections() == 0
    row["status"] = "connected"
    assert connection_alerts.check_active_connections() == 1
    assert connection_alerts.check_active_connections() == 0
    assert seen == ["broker_data_unavailable", "broker_data_recovered"]
