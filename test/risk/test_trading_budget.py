from decimal import Decimal as D

from services.risk import budget


def trade(name, bucket, pnl, status="closed", day="2026-09-26", risk="1000"):
    return budget.BudgetTrade(name, day, bucket, status, D(risk), D(pnl), status != "pending")


def decision(trades, risk="1000", equity="10000", peak="10000", day="2026-09-26", paused=False):
    return budget.evaluate_budget(
        budget.BudgetPolicy(), trades, day, D(equity), D(peak), D(risk), paused
    )


def test_first_loss_and_all_later_losses_use_two_separate_buckets():
    trades = [trade("1", "first", "-1000"), trade("2", "later", "-400")]
    assert decision(trades, "600", "8600").allowed
    assert not decision(trades, "601", "8600").allowed
    assert decision(trades, "600", "8600").bucket == "later"


def test_unused_first_budget_and_wins_cannot_fund_later_trades():
    trades = [trade("1", "first", "-500"), trade("2", "later", "-400"), trade("3", "later", "700")]
    assert decision(trades, "600", "9800").available == D("600")
    assert not decision(trades, "601", "9800").allowed


def test_pending_first_order_blocks_later_and_unfilled_void_does_not_count():
    pending = trade("1", "first", "0", status="pending")
    assert decision([pending], "1").code == "first_trade_pending"
    assert decision([trade("1", "first", "0", status="void")]).bucket == "first"


def test_open_positions_reserve_budgets_without_replenishing_on_profit():
    trades = [
        trade("1", "first", "200", status="open"),
        trade("2", "later", "200", status="open", risk="600"),
    ]
    assert decision(trades, "400", "10400", "10400").available == D("400")
    assert not decision(trades, "401", "10400", "10400").allowed


def test_drawdown_reduces_new_day_budget_and_pause_never_resets_with_date():
    assert decision([], "801", "8800").code == "drawdown_headroom"
    assert decision([], "800", "8800").allowed
    assert decision([], "1", "8000").code == "portfolio_drawdown"
    assert decision([], "1", "10000", paused=True).code == "portfolio_paused"
    assert (
        decision([trade("1", "first", "-1000", day="2026-09-25")], "1000", "9000").bucket == "first"
    )


def test_previous_session_exposure_blocks_reset_and_overruns_count():
    assert (
        decision([trade("1", "first", "0", status="open", day="2026-09-25")]).code
        == "prior_session_exposure"
    )
    trades = [trade("1", "first", "-1300"), trade("2", "later", "-400")]
    assert decision(trades, "301", "8300").allowed is False
    assert decision(trades, "300", "8300").available == D("300")


def test_nonfinite_and_nonpositive_risk_is_rejected():
    for value in ["NaN", "Infinity", "0", "-1"]:
        assert not decision([], value).allowed


def test_current_policy_uses_one_shared_loss_pool_and_a_separate_gross_cap():
    policy = budget.current_policy()
    trades = [
        budget.BudgetTrade("winner", "2026-09-26", "shared", "closed", D("280"), D("700"), True, 1, "2026-09-26"),
        budget.BudgetTrade("loser", "2026-09-26", "shared", "closed", D("280"), D("-1700"), True, 2, "2026-09-26"),
    ]
    allowed = budget.evaluate_budget(policy, trades, "2026-09-26", D("24000"), D("25000"), D("300"), proposed_gross_risk=D("290"))
    assert allowed.allowed and allowed.available == D("300")
    assert allowed.metrics["daily_remaining"] == D("300")
    assert allowed.metrics["per_trade_limit"] == D("300")
    assert budget.evaluate_budget(policy, trades, "2026-09-26", D("24000"), D("25000"), D("301"), proposed_gross_risk=D("290")).code == "daily_budget_exhausted"
    assert budget.evaluate_budget(policy, [], "2026-09-26", D("25000"), D("25000"), D("340"), proposed_gross_risk=D("301")).code == "per_trade_risk_exceeded"


def test_current_policy_latches_three_completed_losses_and_needs_order():
    policy = budget.current_policy()
    trades = [budget.BudgetTrade(str(i), "2026-09-26", "shared", "closed", D("100"), D(pnl), True, i, "2026-09-26") for i, pnl in enumerate(["-100", "0", "-100", "-100", "-100"], 1)]
    result = budget.evaluate_budget(policy, trades, "2026-09-26", D("24600"), D("25000"), D("100"), proposed_gross_risk=D("100"))
    assert result.code == "consecutive_losses_stop"
    assert result.metrics["consecutive_losses"] == 3
    assert result.metrics["daily_stopped"]
    assert budget.evaluate_budget(policy, trades[:-1], "2026-09-26", D("24700"), D("25000"), D("100"), proposed_gross_risk=D("100")).allowed
    incomplete = [budget.BudgetTrade("old", "2026-09-26", "first", "closed", D("100"), D("-100"), True)]
    assert budget.evaluate_budget(policy, incomplete, "2026-09-26", D("24900"), D("25000"), D("100"), proposed_gross_risk=D("100")).code == "risk_evidence_missing"


def test_current_daily_actual_loss_keeps_managed_exit_protection():
    policy = budget.current_policy()
    open_trade = budget.BudgetTrade("open", "2026-09-26", "shared", "open", D("300"), D("-2000"), True)
    snapshot = budget.budget_snapshot(policy, [open_trade], "2026-09-26", D("23000"), D("25000"))
    assert snapshot["daily_remaining"] == 0
    assert "shared" in snapshot["exit_buckets"]
    assert not snapshot["daily_stopped"]


def test_current_unfilled_closed_row_does_not_reset_completed_loss_streak():
    policy = budget.current_policy()
    trades = [
        budget.BudgetTrade("loss-1", "2026-09-26", "shared", "closed", D("100"), D("-100"), True, 1, "2026-09-26"),
        budget.BudgetTrade("unfilled", "2026-09-26", "shared", "closed", D("100"), D("0"), False, 2, "2026-09-26"),
        budget.BudgetTrade("loss-2", "2026-09-26", "shared", "closed", D("100"), D("-100"), True, 3, "2026-09-26"),
        budget.BudgetTrade("loss-3", "2026-09-26", "shared", "closed", D("100"), D("-100"), True, 4, "2026-09-26"),
    ]
    result = budget.evaluate_budget(policy, trades, "2026-09-26", D("24700"), D("25000"), D("100"), proposed_gross_risk=D("80"))
    assert result.code == "consecutive_losses_stop"
    assert result.metrics["consecutive_losses"] == 3
    assert result.metrics["daily_loss"] == D("300")


def test_current_overnight_completion_spends_close_day_allowance_and_streak():
    policy = budget.current_policy()
    trades = [
        budget.BudgetTrade("overnight", "2026-09-25", "shared", "closed", D("300"), D("-700"), True, 1, "2026-09-26"),
        budget.BudgetTrade("today-1", "2026-09-26", "shared", "closed", D("300"), D("-600"), True, 2, "2026-09-26"),
        budget.BudgetTrade("today-2", "2026-09-26", "shared", "closed", D("300"), D("-500"), True, 3, "2026-09-26"),
    ]
    result = budget.evaluate_budget(policy, trades, "2026-09-26", D("23200"), D("25000"), D("100"), proposed_gross_risk=D("80"))
    assert result.metrics["daily_loss"] == D("1800")
    assert result.metrics["daily_remaining"] == D("200")
    assert result.metrics["consecutive_losses"] == 3
    assert result.code == "consecutive_losses_stop"
    yesterday = budget.budget_snapshot(policy, trades, "2026-09-25", D("23200"), D("25000"))
    assert yesterday["daily_loss"] == 0
