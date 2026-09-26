"""Durable shadow outcomes survive a strategy worker restart."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from database import profit_comparison_db as comparisons
from database.engine_factory import create_db_engine
from services.strategy_module.profit_comparison import start_comparison

START = datetime(2026, 9, 25, 4, 0, tzinfo=UTC)
RUN_ID = 987654321


@pytest.fixture(autouse=True)
def isolated_comparison(tmp_path, monkeypatch):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'comparisons.db'}")
    monkeypatch.setattr(comparisons, "engine", engine)
    monkeypatch.setattr(comparisons, "Session", sessionmaker(bind=engine, expire_on_commit=False))
    comparisons.init_db()
    yield
    engine.dispose()


def _entry(risk=100.0):
    return start_comparison(
        run_id=RUN_ID,
        position_ref="entry-test",
        mode="sandbox",
        side="BUY",
        broker_connection_id="pinned-kotak",
        symbol="NIFTY29SEP2623500CE",
        exchange="NFO",
        run_open_positions=1,
        entry_price=100,
        quantity=10,
        planned_stop_risk=risk,
        overall_stop_remaining=150,
        daily_allowance_remaining=100,
        baseline_risk={"combined_stoploss": 150, "combined_target": 300},
        baseline_leg_state={
            "leg_id": 1,
            "position": "B",
            "entry_avg": 100,
            "qty": 10,
            "sl_pts": 15,
            "target_pts": 30,
        },
        entry_at=START,
        cutoff_at=START + timedelta(hours=5),
    )


def test_persisted_floor_and_budget_survive_reload_and_duplicate_start():
    assert comparisons.create_if_absent(_entry())["risk_budget"] == 100.0
    comparisons.observe(
        RUN_ID,
        "entry-test",
        observed_at=START + timedelta(seconds=10),
        received_at=START + timedelta(seconds=10),
        ltp=106,
        source="prospective",
        broker_connection_id="pinned-kotak",
        symbol="NIFTY29SEP2623500CE",
        exchange="NFO",
    )
    saved = comparisons.load_comparison(RUN_ID, "entry-test")
    assert saved["profiles"]["early"]["lock_floor"] == pytest.approx(10.0)
    assert comparisons.create_if_absent(_entry(risk=500))["risk_budget"] == 100.0
    assert comparisons.load_comparison(RUN_ID, "entry-test")["risk_budget"] == 100.0


def test_duplicate_observation_cannot_replay_a_fill():
    comparisons.create_if_absent(_entry())
    moment = START + timedelta(seconds=10)
    comparisons.observe(
        RUN_ID,
        "entry-test",
        observed_at=moment,
        ltp=106,
        source="prospective",
        received_at=moment,
        broker_connection_id="pinned-kotak",
        symbol="NIFTY29SEP2623500CE",
        exchange="NFO",
    )
    with pytest.raises(ValueError, match="ordered"):
        comparisons.observe(
            RUN_ID,
            "entry-test",
            observed_at=moment,
            ltp=102,
            source="prospective",
            received_at=moment,
            broker_connection_id="pinned-kotak",
            symbol="NIFTY29SEP2623500CE",
            exchange="NFO",
        )
    assert (
        comparisons.load_comparison(RUN_ID, "entry-test")["profiles"]["early"]["peak_profit"]
        == 60.0
    )


def test_duplicate_position_reference_cannot_change_its_instrument():
    comparisons.create_if_absent(_entry())
    altered = _entry()
    altered["symbol"] = "BANKNIFTY29SEP2650000CE"
    with pytest.raises(ValueError, match="identity"):
        comparisons.create_if_absent(altered)


def test_session_cutoff_marks_unfilled_shadow_without_inventing_pnl():
    comparisons.create_if_absent(_entry())
    now = START + timedelta(hours=5, seconds=1)
    # Prospective polling needs a real current session; move the created_at
    # into that session rather than relying on today's wall clock.
    with comparisons.Session.begin() as session:
        row = session.query(comparisons.Comparison).filter_by(run_id=RUN_ID).one()
        row.created_at = START.replace(tzinfo=None)
    assert comparisons.list_pending(START + timedelta(minutes=1))
    assert comparisons.finalize_due(now) == 1
    snapshot = comparisons.load_comparison(RUN_ID, "entry-test")
    assert {p["status"] for p in snapshot["profiles"].values()} == {"cutoff"}
    assert all(p["simulated_realized_pnl"] is None for p in snapshot["profiles"].values())
    assert comparisons.list_pending(now) == []
