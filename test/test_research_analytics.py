"""Session analytics reuse portfolio formulas and never annualize trade counts."""

import math

import pytest
from test_trading_research import fees, payload

from services.research import replay
from services.research.dataset import validate_dataset


def test_replay_includes_no_trade_sessions_in_return_analytics():
    data = validate_dataset(payload(80))
    config = replay.validate_configuration(data, "trend_breakout", {"lookback": 2}, fees())
    report = replay.evaluate_experiment(data, config)
    result = report["session_analytics"]
    assert result["session_count"] == 14
    assert result["annualization_sessions"] == 252
    assert result["benchmark"] is None
    assert report["oos"]["session_analytics"]["session_count"] == 6
    assert all(value is None or math.isfinite(value) for value in result["metrics"].values())


def test_session_returns_use_prior_equity_and_zero_for_empty_sessions():
    from services.research.analytics import session_returns

    returns = session_returns(
        [
            {"exit_at": "2026-01-01T10:00:00+05:30", "net_pnl": 100},
            {"exit_at": "2026-01-03T10:00:00+05:30", "net_pnl": -101},
        ],
        ["2026-01-01", "2026-01-02", "2026-01-03"],
        initial=10000,
    )
    assert list(returns) == pytest.approx([0.01, 0, -0.01])


def test_session_returns_scale_with_selected_research_capital():
    from services.research.analytics import session_returns

    trades = [{"exit_at": "2026-01-01T10:00:00+05:30", "net_pnl": 100}]
    dates = ["2026-01-01", "2026-01-02"]
    assert list(session_returns(trades, dates, initial=25000)) == pytest.approx([0.004, 0])


def test_incomplete_replay_does_not_publish_annualized_metrics():
    from services.research.analytics import session_analytics

    report = {"trades": [], "incomplete_outcomes": [{"reason": "missing_exposure_bar"}]}
    assert session_analytics(report, ["2026-01-01"])["metrics"] == {}
