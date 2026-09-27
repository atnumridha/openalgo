from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal as D

import pytest

from database import trading_risk_db as ledger
from database.engine_factory import create_db_engine
from services.risk.budget import legacy_policy

DAY = "2026-09-26"


def completion(day=DAY):
    return datetime.fromisoformat(f"{day}T10:00:00+05:30")


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", legacy_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/risk.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    yield
    engine.dispose()


def reserve(ref, risk="1000", day=DAY, **kwargs):
    return ledger.reserve(
        "user", "sandbox", ref, day, D(risk), D("2000"), "index", "sandbox", 1, {}, **kwargs
    )


def value(ref, pnl, status="closed", filled=True, *, completed_at=None):
    ledger.update_trade(
        "user", "sandbox", ref, status=status, net_pnl=D(pnl), filled=filled, evidence={},
        completed_at=completed_at,
    )


def test_account_survives_reinitialization_and_keeps_loss_buckets():
    assert reserve("first").allowed
    value("first", "-1000")
    assert reserve("second", "400").allowed
    value("second", "-400")
    ledger.init_db()
    assert reserve("too-much", "601").allowed is False
    assert reserve("last", "600").allowed
    snapshot = ledger.status("user", "sandbox", DAY)
    assert snapshot["later_remaining"] == D("0")
    assert snapshot["reserved_risk"] == D("600")


def test_concurrent_first_reservations_cannot_spend_twice():
    ledger.status("user", "sandbox", DAY)
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(reserve, ["a", "b"]))
    assert sum(item.allowed for item in decisions) == 1


def test_rejected_no_fill_releases_first_slot_but_unknown_keeps_it():
    assert reserve("attempt").allowed
    assert reserve("unknown-retry").code == "first_trade_pending"
    value("attempt", "0", "void", False)
    assert reserve("real-first").bucket == "first"


def test_drawdown_pause_persists_across_day_and_requires_review():
    assert reserve("first").allowed
    value("first", "-1000")
    assert reserve("second").allowed
    value("second", "-1000")
    assert ledger.status("user", "sandbox", "2026-09-27")["paused"]
    assert not reserve("new-day", day="2026-09-27").allowed
    ledger.resume("user", "sandbox", "2026-09-27", "Reviewed executions", reconciled=True)
    snapshot = ledger.status("user", "sandbox", "2026-09-27")
    assert snapshot["equity"] == D("8000")
    assert snapshot["peak_equity"] == D("8000")
    assert reserve("reviewed", day="2026-09-27").allowed


def test_review_cannot_reset_daily_loss_budget_or_unresolved_exposure():
    assert reserve("pending").allowed
    with pytest.raises(ValueError, match="exposure"):
        ledger.resume("user", "sandbox", DAY, "Review", reconciled=True)
    value("pending", "-1000")
    assert reserve("second").allowed
    value("second", "-1000")
    ledger.resume("user", "sandbox", DAY, "Review", reconciled=True)
    assert not reserve("third", "1").allowed


def test_brokers_share_one_allocation_and_cannot_duplicate_index_positions():
    assert ledger.reserve(
        "user", "live", "a", DAY, D("500"), D("2000"), "index", "broker-a", 1, {}
    ).allowed
    value_live = {"status": "open", "net_pnl": D("0"), "filled": True, "evidence": {}}
    ledger.update_trade("user", "live", "a", **value_live)
    other = ledger.reserve(
        "user", "live", "b", DAY, D("500"), D("2000"), "index", "broker-b", 2, {}
    )
    assert other.code == "position_limit"


def test_same_reference_cannot_be_used_to_dispatch_twice():
    assert reserve("same").allowed
    assert reserve("same").code == "duplicate_trade"


def test_cash_buffer_and_scope_are_enforced():
    decision = ledger.reserve(
        "user", "sandbox", "a", DAY, D("500"), D("8001"), "index", "sandbox", 1, {}
    )
    assert decision.code == "cash_buffer"
    assert reserve("ok").allowed
    assert ledger.status("user", "live", DAY)["reserved_risk"] == 0


def test_profile_activation_is_separate_from_cost_evidence():
    assert not ledger.policy_enabled("new-user")
    ledger.activate_policy("new-user")
    assert ledger.policy_enabled("new-user")
    assert ledger.get_costs("new-user") is None


def test_unrealized_profit_is_not_available_cash_for_another_entry():
    assert ledger.reserve(
        "user", "sandbox", "first", DAY, D("500"), D("4000"), "index", "a", 1, {}
    ).allowed
    value("first", "2000", status="open")
    result = ledger.reserve(
        "user", "sandbox", "second", DAY, D("500"), D("5000"), "mcx", "b", 2, {}
    )
    assert result.code == "cash_buffer"


def test_current_policy_day_stop_is_durable_and_a_late_win_cannot_clear_it(tmp_path, monkeypatch):
    from sqlalchemy.orm import Session

    from services.risk.budget import current_policy

    monkeypatch.setattr(ledger, "POLICY", current_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/current.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    for index in range(3):
        ref = f"loss-{index}"
        assert ledger.reserve("new", "sandbox", ref, DAY, D("140"), D("2000"), "index", "sandbox", index, {}, gross_risk=D("100")).allowed
        ledger.update_trade("new", "sandbox", ref, status="closed", net_pnl=D("-140"), filled=True, evidence={}, completed_at=completion())
    snapshot = ledger.status("new", "sandbox", DAY)
    assert snapshot["consecutive_losses"] == 3
    assert snapshot["daily_stopped"]
    before_duplicate = ledger.list_trades("new", "sandbox", ref="loss-2")[0]
    ledger.update_trade("new", "sandbox", "loss-2", status="closed", net_pnl=D("-140"), filled=True, evidence={})
    after_duplicate = ledger.list_trades("new", "sandbox", ref="loss-2")[0]
    assert after_duplicate["close_sequence"] == before_duplicate["close_sequence"]
    assert after_duplicate["closed_at"] == before_duplicate["closed_at"]
    assert after_duplicate["ledger_revision"] == before_duplicate["ledger_revision"]
    assert ledger.reserve("new", "sandbox", "blocked", DAY, D("100"), D("2000"), "index", "sandbox", 4, {}, gross_risk=D("80")).code == "consecutive_losses_stop"
    ledger.update_trade("new", "sandbox", "loss-2", status="closed", net_pnl=D("500"), filled=True, evidence={"late": True})
    assert ledger.status("new", "sandbox", DAY)["daily_stopped"]
    ledger.init_db()
    with Session(engine) as db:
        assert db.get(ledger.RiskAccount, "new|sandbox").daily_stop_day == DAY
    ledger.resume("new", "sandbox", DAY, "Reviewed drawdown", reconciled=True)
    assert ledger.status("new", "sandbox", DAY)["daily_stopped"]
    assert not ledger.status("new", "sandbox", "2026-09-27")["daily_stopped"]
    next_day = "2026-09-27"
    for index in range(3):
        ref = f"next-loss-{index}"
        assert ledger.reserve("new", "sandbox", ref, next_day, D("140"), D("2000"), "index", "sandbox", index, {}, gross_risk=D("100")).allowed
        ledger.update_trade("new", "sandbox", ref, status="closed", net_pnl=D("-140"), filled=True, evidence={}, completed_at=completion(next_day))
    assert ledger.status("new", "sandbox", next_day)["daily_stopped"]
    ledger.update_trade("new", "sandbox", "loss-1", status="closed", net_pnl=D("500"), filled=True, evidence={"late": True})
    assert ledger.status("new", "sandbox", next_day)["daily_stopped"]
    assert ledger.status("new", "sandbox", DAY)["daily_stopped"]
    engine.dispose()


def test_current_policy_new_day_still_blocks_prior_exposure(tmp_path, monkeypatch):
    from services.risk.budget import current_policy

    monkeypatch.setattr(ledger, "POLICY", current_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/current-exposure.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    assert ledger.reserve("new", "sandbox", "old", DAY, D("150"), D("2000"), "index", "sandbox", 1, {}, gross_risk=D("100")).allowed
    result = ledger.reserve("new", "sandbox", "next", "2026-09-27", D("150"), D("2000"), "index", "sandbox", 2, {}, gross_risk=D("100"))
    assert result.code == "prior_session_exposure"
    engine.dispose()


def test_current_policy_concurrent_reservations_share_remaining_headroom(tmp_path, monkeypatch):
    from services.risk.budget import current_policy

    monkeypatch.setattr(ledger, "POLICY", current_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/current-concurrency.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    for index in range(2):
        ref = f"prior-{index}"
        assert ledger.reserve("new", "sandbox", ref, DAY, D("200"), D("2000"), "index", "sandbox", index, {}, gross_risk=D("160")).allowed
        ledger.update_trade("new", "sandbox", ref, status="closed", net_pnl=D("-800"), filled=True, evidence={}, completed_at=completion())

    def attempt(index):
        return ledger.reserve("new", "sandbox", f"candidate-{index}", DAY, D("300"), D("2000"), "index", "sandbox", index, {}, gross_risk=D("260"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(attempt, [3, 4]))
    assert sum(result.allowed for result in decisions) == 1
    assert ledger.status("new", "sandbox", DAY)["daily_remaining"] == D("100")
    engine.dispose()


def test_legacy_upgrade_keeps_unknown_close_order_unknown(tmp_path, monkeypatch):
    from sqlalchemy import inspect, text
    from sqlalchemy.orm import Session

    from services.risk.budget import current_policy

    engine = create_db_engine(f"sqlite:///{tmp_path}/prior.db")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE trading_risk_account (scope VARCHAR(180) PRIMARY KEY, capital NUMERIC(20,4) NOT NULL, peak NUMERIC(20,4) NOT NULL, paused BOOLEAN NOT NULL, pause_reason TEXT)"))
        db.execute(text("INSERT INTO trading_risk_account(scope,capital,peak,paused) VALUES ('prior|sandbox',25000,25000,0)"))
        db.execute(text("CREATE TABLE trading_risk_trade (scope VARCHAR(180), ref VARCHAR(64), session_day VARCHAR(10), bucket VARCHAR(10), status VARCHAR(12), planned_risk NUMERIC(20,4), premium NUMERIC(20,4), net_pnl NUMERIC(20,4), filled BOOLEAN, segment VARCHAR(12), broker VARCHAR(50), strategy_id INTEGER, run_id INTEGER, details JSON, evidence JSON, PRIMARY KEY(scope,ref))"))
        db.execute(text("INSERT INTO trading_risk_trade(scope,ref,session_day,bucket,status,planned_risk,premium,net_pnl,filled,segment,broker,strategy_id,details,evidence) VALUES ('prior|sandbox','old','2026-09-26','first','closed',100,1000,-100,1,'index','sandbox',1,'{}','{}')"))
    monkeypatch.setattr(ledger, "engine", engine)
    monkeypatch.setattr(ledger, "POLICY", current_policy())
    ledger.init_db()
    ledger.init_db()
    assert {"closed_at", "close_sequence", "completion_day"} <= {c["name"] for c in inspect(engine).get_columns("trading_risk_trade")}
    with Session(engine) as db:
        account = db.get(ledger.RiskAccount, "prior|sandbox")
        row = db.get(ledger.RiskTrade, ("prior|sandbox", "old"))
        assert account.policy_version == "two-bucket-v1"
        assert row.closed_at is None and row.close_sequence is None and row.completion_day is None
    with pytest.raises(ValueError, match="close order"):
        ledger.ensure_current_policy("prior", "sandbox", DAY)
    with pytest.raises(ValueError, match="completion day"):
        ledger.ensure_current_policy("prior", "sandbox", "2026-09-27")
    assert ledger.status("prior", "sandbox", DAY)["first_loss"] == D("100")
    engine.dispose()


def test_idle_legacy_upgrade_preserves_current_day_loss_and_peak(monkeypatch):
    from services.risk.budget import current_policy

    assert reserve("old").allowed
    value("old", "-500", completed_at=completion())
    before = ledger.status("user", "sandbox", DAY)
    monkeypatch.setattr(ledger, "POLICY", current_policy())
    ledger.ensure_current_policy("user", "sandbox", DAY)
    after = ledger.status("user", "sandbox", DAY)
    assert after["policy_version"] == "shared-300-3r-v1"
    assert after["daily_loss"] == D("500")
    assert after["daily_remaining"] == D("1500")
    assert after["peak_equity"] == before["peak_equity"]
    assert after["capital"] == before["capital"]
    assert after["allocation_revision"] == before["allocation_revision"]


def test_current_ledger_rejects_unfilled_closed_row_without_changing_streak(tmp_path, monkeypatch):
    from services.risk.budget import current_policy

    monkeypatch.setattr(ledger, "POLICY", current_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/unfilled.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    assert ledger.reserve("new", "sandbox", "loss", DAY, D("100"), D("2000"), "index", "sandbox", 1, {}, gross_risk=D("80")).allowed
    ledger.update_trade("new", "sandbox", "loss", status="closed", net_pnl=D("-100"), filled=True, evidence={}, completed_at=completion())
    assert ledger.reserve("new", "sandbox", "unfilled", DAY, D("100"), D("2000"), "index", "sandbox", 2, {}, gross_risk=D("80")).allowed
    with pytest.raises(ValueError, match="unfilled"):
        ledger.update_trade("new", "sandbox", "unfilled", status="closed", net_pnl=D("0"), filled=False, evidence={}, completed_at=completion())
    assert ledger.status("new", "sandbox", DAY)["consecutive_losses"] == 1
    assert ledger.list_trades("new", "sandbox", ref="unfilled")[0]["status"] == "pending"
    engine.dispose()


def test_current_ledger_charges_overnight_close_to_completion_day(tmp_path, monkeypatch):
    from services.risk.budget import current_policy

    monkeypatch.setattr(ledger, "POLICY", current_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/overnight.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    assert ledger.reserve("new", "sandbox", "overnight", DAY, D("300"), D("2000"), "index", "sandbox", 1, {}, gross_risk=D("250")).allowed
    ledger.update_trade("new", "sandbox", "overnight", status="open", net_pnl=D("0"), filled=True, evidence={})
    next_day = "2026-09-27"
    assert ledger.reserve("new", "sandbox", "blocked", next_day, D("100"), D("2000"), "index", "sandbox", 2, {}, gross_risk=D("80")).code == "prior_session_exposure"
    ledger.update_trade("new", "sandbox", "overnight", status="closed", net_pnl=D("-700"), filled=True, evidence={}, completed_at=completion(next_day))
    assert ledger.status("new", "sandbox", DAY)["daily_loss"] == 0
    assert ledger.status("new", "sandbox", next_day)["daily_loss"] == D("700")
    for index in range(2):
        ref = f"today-{index}"
        assert ledger.reserve("new", "sandbox", ref, next_day, D("300"), D("2000"), "index", "sandbox", index + 3, {}, gross_risk=D("250")).allowed
        ledger.update_trade("new", "sandbox", ref, status="closed", net_pnl=D("-400"), filled=True, evidence={}, completed_at=completion(next_day))
    today = ledger.status("new", "sandbox", next_day)
    assert today["daily_loss"] == D("1500")
    assert today["consecutive_losses"] == 3
    assert today["daily_stopped"]
    assert ledger.reserve("new", "sandbox", "fourth", next_day, D("100"), D("2000"), "index", "sandbox", 5, {}, gross_risk=D("80")).code == "consecutive_losses_stop"
    engine.dispose()


@pytest.mark.parametrize(
    ("reset", "observed", "expected_day"),
    [
        ("03:00", "2026-09-27T02:59:59+05:30", DAY),
        ("03:00", "2026-09-26T21:29:59+00:00", DAY),
        ("03:00", "2026-09-26T21:30:00+00:00", "2026-09-27"),
        ("03:00", "2026-09-27T03:00:01+05:30", "2026-09-27"),
        ("05:30", "2026-09-27T05:29:59+05:30", DAY),
        ("05:30", "2026-09-27T05:30:00+05:30", "2026-09-27"),
    ],
)
def test_current_completion_uses_configured_session_reset(
    tmp_path, monkeypatch, reset, observed, expected_day
):
    from services.risk.budget import current_policy

    monkeypatch.setenv("SESSION_EXPIRY_TIME", reset)
    monkeypatch.setattr(ledger, "POLICY", current_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/reset.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    assert ledger.reserve("new", "sandbox", "overnight", DAY, D("150"), D("2000"), "index", "sandbox", 1, {}, gross_risk=D("100")).allowed
    ledger.update_trade("new", "sandbox", "overnight", status="closed", net_pnl=D("-150"), filled=True, evidence={}, completed_at=datetime.fromisoformat(observed))
    row = ledger.list_trades("new", "sandbox", ref="overnight")[0]
    assert row["completion_day"] == expected_day
    assert ledger.status("new", "sandbox", expected_day)["daily_loss"] == D("150")
    other = "2026-09-27" if expected_day == DAY else DAY
    assert ledger.status("new", "sandbox", other)["daily_loss"] == 0
    ledger.update_trade("new", "sandbox", "overnight", status="closed", net_pnl=D("-200"), filled=True, evidence={"correction": True}, completed_at=datetime.fromisoformat("2026-09-28T10:00:00+05:30"))
    assert ledger.list_trades("new", "sandbox", ref="overnight")[0]["completion_day"] == expected_day
    assert ledger.status("new", "sandbox", expected_day)["daily_loss"] == D("200")
    engine.dispose()
