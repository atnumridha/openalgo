from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D

import pytest

from database import trading_risk_db as ledger
from database.engine_factory import create_db_engine

DAY = "2026-09-26"


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    engine = create_db_engine(f"sqlite:///{tmp_path}/risk.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    yield
    engine.dispose()


def reserve(ref, risk="1000", day=DAY, **kwargs):
    return ledger.reserve(
        "user", "sandbox", ref, day, D(risk), D("2000"), "index", "sandbox", 1, {}, **kwargs
    )


def value(ref, pnl, status="closed", filled=True):
    ledger.update_trade(
        "user", "sandbox", ref, status=status, net_pnl=D(pnl), filled=filled, evidence={}
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
