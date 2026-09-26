"""Session summaries never choose a winner or turn triggers into fills."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from services.strategy_module import comparison_reporting


def _snapshot(status="closed", realized=50):
    profile = {
        "status": status, "simulated_realized_pnl": realized,
        "peak_profit": 80, "max_drawdown": 30,
        "missed_fill": status != "closed", "trigger_at": None,
    }
    return {
        "run_id": 42,
        "profiles": {name: dict(profile) for name in ("baseline", "early", "room")},
    }


def test_incomplete_profile_has_no_realized_total_or_winner():
    row = _snapshot(status="trigger_only", realized=None)
    payload = comparison_reporting._session_payload([row])
    assert payload["all_profiles_complete"] is False
    assert payload["profiles"]["baseline"]["realized_estimate"] is None
    assert payload["rule_selected"] is None
    assert payload["fees"] == "unavailable"


def test_completed_session_report_is_idempotent_through_store(monkeypatch):
    now = datetime(2026, 9, 26, 4, 0, tzinfo=UTC)
    previous_day = (now.astimezone(comparison_reporting.IST) - timedelta(days=1)).date()
    seen = []
    monkeypatch.setattr(comparison_reporting.comparisons, "finalize_due", lambda _: 0)
    monkeypatch.setattr(
        comparison_reporting.comparisons, "list_created_between",
        lambda start, end: [_snapshot()] if start.astimezone(comparison_reporting.IST).date() == previous_day else [],
    )
    monkeypatch.setattr(comparison_reporting.store, "get_run", lambda _: SimpleNamespace(mode="sandbox", strategy_id=7))
    monkeypatch.setattr(comparison_reporting.store, "get_strategy_unscoped", lambda _: SimpleNamespace(user_id="owner"))

    def record(strategy_id, user_id, day, message, payload):
        key = (strategy_id, day)
        if key in seen:
            return False
        seen.append(key)
        assert "no rule selected" in message
        assert payload["all_profiles_complete"] is True
        return True

    monkeypatch.setattr(comparison_reporting.store, "record_comparison_session_summary", record)
    assert comparison_reporting.report_completed_sessions(now) == 1
    assert comparison_reporting.report_completed_sessions(now) == 0
