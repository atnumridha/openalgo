from decimal import Decimal as D

import pytest

from services.risk import budget

DAY = "2026-09-28"


@pytest.mark.parametrize("capital", ["10000", "25000", "50000", "100000"])
def test_fixed_limits_ignore_capital_and_account_for_charges_separately(capital):
    policy = budget.current_policy(D(capital))
    result = budget.evaluate_budget(policy, [], DAY, D(capital), D(capital), D("345"),
                                    proposed_gross_risk=D("300"))
    assert result.allowed
    assert result.metrics["per_trade_limit"] == D("300")
    assert result.metrics["daily_limit"] == D("2000")
    assert not result.metrics["risk_reduced"]
    assert budget.evaluate_budget(policy, [], DAY, D(capital), D(capital), D("345"),
                                   proposed_gross_risk=D("300.01")).code == "per_trade_risk_exceeded"


def test_fixed_policy_retains_streak_stop_and_one_open_position():
    policy = budget.current_policy(D("50000"))
    losses = [budget.BudgetTrade(str(i), DAY, "shared", "closed", D("345"), D("-345"),
                                 True, i, DAY) for i in range(1, 4)]
    result = budget.evaluate_budget(policy, losses, DAY, D("48965"), D("50000"), D("345"),
                                    proposed_gross_risk=D("300"))
    assert result.code == "consecutive_losses_stop"
    assert result.metrics["daily_remaining"] == D("965")
    pending = budget.BudgetTrade("pending", DAY, "shared", "pending", D("345"))
    assert budget.evaluate_budget(policy, [pending], DAY, D("50000"), D("50000"), D("345"),
                                  proposed_gross_risk=D("300")).code == "position_limit"


def test_drawdown_pause_remains_but_never_halves_fixed_trade_limit():
    policy = budget.current_policy(D("50000"))
    result = budget.budget_snapshot(policy, [], DAY, D("47500"), D("50000"))
    assert result["per_trade_limit"] == D("300") and not result["risk_reduced"]
    assert budget.budget_snapshot(policy, [], DAY, D("46000"), D("50000"))["paused"]
