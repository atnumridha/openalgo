from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from database import trading_risk_db as ledger
from database.engine_factory import create_db_engine
from services.risk import budget

DAY = "2026-09-26"
NEXT_DAY = "2026-09-27"


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", budget.current_policy())
    engine = create_db_engine(f"sqlite:///{tmp_path}/equity.db")
    monkeypatch.setattr(ledger, "engine", engine)
    ledger.init_db()
    yield
    engine.dispose()


def reserve(ref, risk="100", day=DAY, segment="index", mode="sandbox", strategy=1):
    return ledger.reserve("equity", mode, ref, day, D(risk), D("1000"), segment,
                          f"broker-{strategy}", strategy, {}, gross_risk=D("80"))


def close(ref, pnl, day=DAY):
    return ledger.update_trade("equity", "sandbox", ref, status="closed", net_pnl=D(pnl),
                                filled=True, evidence={},
                                completed_at=datetime.fromisoformat(f"{day}T10:00:00+05:30"))


def test_new_account_rejects_all_in_risk_above_equity_cap():
    assert reserve("too-much", "250.01").code == "per_trade_risk_exceeded"
    assert reserve("fits", "250").allowed
    snapshot = ledger.status("equity", "sandbox", DAY)
    assert snapshot["daily_limit"] == D("750")
    assert snapshot["daily_remaining"] == D("500")


def test_concurrent_different_brokers_and_segments_share_one_position():
    ledger.status("equity", "sandbox", DAY)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: reserve(f"race-{i}", segment=("index", "mcx")[i],
                                                 strategy=i + 1), range(2)))
    assert sum(result.allowed for result in results) == 1
    assert {result.code for result in results} == {"entry_allowed", "position_limit"}
    assert reserve("independent-mode", mode="live").allowed


def test_day_baseline_survives_profit_restart_funding_change_and_review(monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", budget.current_policy(D("10000")))
    assert reserve("loss").allowed
    close("loss", "-90")
    assert reserve("win", "90").allowed
    close("win", "400")
    before = ledger.status("equity", "sandbox", DAY)
    assert before["day_start_equity"] == D("10000")
    assert before["daily_remaining"] == D("210")
    after = ledger.review_allocation("equity", "sandbox", "25000", "Additional funding", DAY)
    assert after["equity"] == D("25310")
    assert after["day_start_equity"] == D("10000")
    assert after["daily_limit"] == D("300")
    assert after["daily_remaining"] == D("210")
    ledger.init_db()
    ledger.resume("equity", "sandbox", DAY, "Reviewed equity", reconciled=True)
    assert ledger.status("equity", "sandbox", DAY)["daily_remaining"] == D("210")
    next_day = ledger.status("equity", "sandbox", NEXT_DAY)
    assert next_day["day_start_equity"] == D("25310")
    assert next_day["daily_limit"] == D("759.30")
    assert ledger.status("equity", "sandbox", DAY)["daily_limit"] == D("300")


def test_funding_change_without_prior_status_preserves_original_day_allowance(monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", budget.current_policy(D("10000")))
    changed = ledger.review_allocation("equity", "sandbox", "25000", "Funding review", DAY)
    assert changed["day_start_equity"] == D("10000")
    assert changed["daily_limit"] == D("300")


def test_first_update_on_new_session_records_opening_equity_before_new_mark():
    assert reserve("overnight").allowed
    ledger.update_trade("equity", "sandbox", "overnight", status="open", net_pnl=D("100"),
                        filled=True, evidence={})
    close("overnight", "-150", NEXT_DAY)
    snapshot = ledger.status("equity", "sandbox", NEXT_DAY)
    assert snapshot["day_start_equity"] == D("25100")
    assert snapshot["daily_limit"] == D("753")
    assert snapshot["daily_loss"] == D("150")
    assert snapshot["daily_remaining"] == D("603")


def test_idle_migration_preserves_history_and_capital(monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", budget.policy_for_version("shared-300-3r-v1", D("10000")))
    assert reserve("old", "300").allowed
    close("old", "-150")
    before = ledger.list_trades("equity", "sandbox")
    monkeypatch.setattr(ledger, "POLICY", budget.current_policy())
    ledger.ensure_current_policy("equity", "sandbox", DAY)
    after = ledger.status("equity", "sandbox", DAY)
    assert after["policy_version"] == "equity-1pct-v2"
    assert after["capital"] == D("10000")
    assert after["peak_equity"] == D("10000")
    assert after["daily_limit"] == D("300")
    assert after["daily_remaining"] == D("150")
    assert ledger.list_trades("equity", "sandbox") == before


def test_migration_with_legacy_exposure_fails_without_rewriting_it(monkeypatch):
    monkeypatch.setattr(ledger, "POLICY", budget.policy_for_version("shared-300-3r-v1", D("25000")))
    assert reserve("old", "300").allowed
    before = ledger.list_trades("equity", "sandbox")
    monkeypatch.setattr(ledger, "POLICY", budget.current_policy())
    with pytest.raises(ValueError, match="exposure"):
        ledger.ensure_current_policy("equity", "sandbox", DAY)
    assert ledger.list_trades("equity", "sandbox") == before
    with Session(ledger.engine) as db:
        assert db.get(ledger.RiskAccount, "equity|sandbox").policy_version == "shared-300-3r-v1"


def test_eight_percent_drawdown_pause_survives_restart_and_new_session():
    assert reserve("gap").allowed
    close("gap", "-2000")
    ledger.init_db()
    snapshot = ledger.status("equity", "sandbox", NEXT_DAY)
    assert snapshot["paused"]
    assert "8%" in snapshot["pause_reason"]
    assert reserve("blocked", "100", NEXT_DAY).code == "portfolio_paused"


def test_payload_exposes_equity_risk_and_position_scope():
    payload = ledger.policy_payload()
    assert payload["version"] == "equity-1pct-v2"
    assert payload["per_trade_equity_pct"] == 0.01
    assert payload["daily_equity_pct"] == 0.03
    assert payload["max_positions"] == 1


def test_exhausted_equity_remains_observable_and_closed_on_next_session():
    assert reserve("catastrophic-gap").allowed
    close("catastrophic-gap", "-30000")
    snapshot = ledger.status("equity", "sandbox", NEXT_DAY)
    assert snapshot["equity"] == D("-5000")
    assert snapshot["paused"]
    assert snapshot["daily_limit"] == D("0")
    assert snapshot["per_trade_limit"] == D("0")
    assert not reserve("blocked", day=NEXT_DAY).allowed
