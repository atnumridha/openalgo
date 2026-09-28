from decimal import Decimal as D

import pytest

from services.risk import budget

DAY = "2026-09-26"


def closed(ref, pnl, sequence, day=DAY):
    return budget.BudgetTrade(ref, day, "shared", "closed", D("100"), D(pnl), True, sequence, day)


def decide(*, equity="25000", peak="25000", risk="200", gross="180", trades=(), **kwargs):
    return budget.evaluate_budget(budget.policy_for_version(budget.EQUITY_POLICY_VERSION), trades, DAY, D(equity), D(peak),
                                  D(risk), proposed_gross_risk=D(gross), **kwargs)


@pytest.mark.parametrize(("equity", "risk", "allowed"), [
    ("10000", "100", True), ("10000", "100.01", False),
    ("25000", "250", True), ("25000", "250.01", False),
    ("40000", "300", True), ("40000", "300.01", False),
])
def test_caps_total_planned_loss_including_costs(equity, risk, allowed):
    result = decide(equity=equity, peak=equity, risk=risk, gross="90")
    assert result.allowed is allowed
    if not allowed:
        assert result.code == "per_trade_risk_exceeded"


@pytest.mark.parametrize(("equity", "limit", "reduced", "paused"), [
    ("23750.01", "237.5001", False, False),
    ("23750", "118.75", True, False),
    ("23000.01", "115.00005", True, False),
    ("23000", "115", True, True),
])
def test_drawdown_thresholds_use_peak_equity(equity, limit, reduced, paused):
    snapshot = budget.budget_snapshot(budget.policy_for_version(budget.EQUITY_POLICY_VERSION), [], DAY, D(equity), D("25000"))
    assert snapshot["per_trade_limit"] == D(limit)
    assert snapshot["risk_reduced"] is reduced
    assert snapshot["paused"] is paused
    assert snapshot["drawdown_pct"] == (D("25000") - D(equity)) / D("25000")


def test_explicit_day_opening_equity_and_wins_do_not_refill_loss_allowance():
    trades = [closed("loss", "-200", 1), closed("win", "900", 2)]
    result = decide(equity="25700", peak="25700", trades=trades,
                    day_start_equity=D("25000"))
    assert result.metrics["day_start_equity"] == D("25000")
    assert result.metrics["daily_limit"] == D("750")
    assert result.metrics["daily_remaining"] == D("550")
    assert result.allowed


def test_pure_reconstruction_removes_current_day_net_but_keeps_previous_days():
    trades = [closed("prior", "1000", 1, "2026-09-25"), closed("loss", "-100", 2),
              closed("win", "600", 3)]
    snapshot = budget.budget_snapshot(budget.policy_for_version(budget.EQUITY_POLICY_VERSION), trades, DAY, D("26500"), D("26500"))
    assert snapshot["day_start_equity"] == D("26000")
    assert snapshot["daily_limit"] == D("780")
    assert snapshot["daily_remaining"] == D("680")


def test_daily_cap_is_capped_at_2000_for_larger_accounts():
    snapshot = budget.budget_snapshot(budget.policy_for_version(budget.EQUITY_POLICY_VERSION, D("100000")), [], DAY,
                                      D("100000"), D("100000"))
    assert snapshot["daily_limit"] == D("2000")


def test_pending_or_open_exposure_blocks_second_position_across_segments():
    for state in ("pending", "open"):
        existing = budget.BudgetTrade("held", DAY, "shared", state, D("100"), D("0"))
        assert decide(trades=[existing], risk="100", gross="80").code == "position_limit"


def test_old_policy_versions_keep_their_original_allowances():
    old = budget.policy_for_version("shared-300-3r-v1", D("25000"))
    result = budget.evaluate_budget(old, [], DAY, D("25000"), D("25000"), D("340"),
                                    proposed_gross_risk=D("300"))
    assert result.allowed
    assert result.metrics["daily_remaining"] == D("2000")
    two_bucket = budget.policy_for_version("two-bucket-v1", D("10000"))
    assert budget.evaluate_budget(two_bucket, [], DAY, D("10000"), D("10000"), D("1000")).allowed
    with pytest.raises(ValueError, match="policy"):
        budget.policy_for_version("future", D("25000"))


def test_invalid_opening_equity_fails_closed():
    for value in (D("NaN"), D("Infinity")):
        assert decide(day_start_equity=value).code == "risk_evidence_missing"
