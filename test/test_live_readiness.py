"""Setup diagnostics are read-only and must expose simultaneous blockers."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

NOW = datetime(2026, 9, 28, 10, tzinfo=UTC)


@pytest.fixture
def evidence(monkeypatch):
    from services.strategy_module import live_readiness as ready

    monkeypatch.setattr(ready, "broker_problem", lambda *a: None)
    monkeypatch.setattr(ready, "cost_problem", lambda *a: None)
    monkeypatch.setattr(ready, "campaign_approval", lambda *a: None)
    return ready


def snapshot(ready, *, live=True, approved=False, research=True, risk=None):
    row = SimpleNamespace(id=19, live_enabled=live, broker_connection_id="pin",
                          underlying_exchange="NSE_INDEX", automation_state="armed")
    return ready.inspect_setup(
        "alice", row, {"mode": "live" if live else "sandbox", "link_error": None,
                       "workflow_active": True, "schedule_status": "scheduled"},
        SimpleNamespace(active=approved),
        risk or {"available": True, "ledger": {"daily_remaining": 2000}},
        {"status": "running"}, {"research_required": research}, now=NOW,
    )


def test_missing_approval_and_research_are_both_visible(evidence):
    result = snapshot(evidence)
    assert {c["code"] for c in result["checks"] if c["status"] == "blocked"} == {
        "session_approval", "research_release"
    }
    assert result["blocked"] is True
    assert result["blocker_count"] == 2


def test_optional_research_does_not_query_or_claim_order_ready(evidence, monkeypatch):
    monkeypatch.setattr(evidence, "campaign_approval", lambda *a: pytest.fail("optional research queried"))
    result = snapshot(evidence, approved=True, research=False)
    assert result["blocked"] is False
    assert any(c["code"] == "entry_checks" and c["status"] == "pending" for c in result["checks"])


def test_missing_evidence_is_a_blocker_not_a_pass(evidence, monkeypatch):
    monkeypatch.setattr(evidence, "broker_problem", lambda *a: "Broker evidence is unavailable")
    result = snapshot(evidence, approved=True, research=False, risk={"available": False})
    codes = {c["code"] for c in result["checks"] if c["status"] == "blocked"}
    assert codes == {"broker_session", "risk_budget"}


def test_expired_release_is_blocked(evidence, monkeypatch):
    monkeypatch.setattr(evidence, "campaign_approval", lambda *a: {
        "status": "approved", "expires_at": "2026-09-27T10:00:00+00:00"})
    result = snapshot(evidence, approved=True)
    check = next(c for c in result["checks"] if c["code"] == "research_release")
    assert check["status"] == "blocked" and "expired" in check["message"]


def test_saved_release_requires_fresh_entry_validation(evidence, monkeypatch):
    monkeypatch.setattr(evidence, "campaign_approval", lambda *a: {
        "status": "approved", "expires_at": "2026-09-29T10:00:00+00:00"})
    result = snapshot(evidence, approved=True)
    check = next(c for c in result["checks"] if c["code"] == "research_release")
    assert check["status"] == "pending"
    assert "binding" in check["message"]


@pytest.mark.parametrize("ledger", [
    {"paused": True}, {"daily_remaining": 0}, {"daily_stopped": True},
    {"daily_remaining": 2000, "drawdown_headroom": 0},
    {"daily_remaining": 2000, "first_pending": True},
    {"daily_remaining": 2000, "prior_session_exposure": True},
])
def test_risk_pause_blocks_new_entry(evidence, ledger):
    result = snapshot(evidence, approved=True, research=False, risk={"available": True, "ledger": ledger})
    assert next(c for c in result["checks"] if c["code"] == "risk_budget")["status"] == "blocked"


def test_concurrent_position_limit_is_visible(evidence):
    result = snapshot(evidence, approved=True, research=False,
                      risk={"available": True, "max_positions": 1,
                            "ledger": {"daily_remaining": 2000, "position_count": 1}})
    check = next(c for c in result["checks"] if c["code"] == "risk_budget")
    assert check["status"] == "blocked" and "concurrent" in check["message"]
