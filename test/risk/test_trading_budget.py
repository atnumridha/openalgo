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
