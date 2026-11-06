from datetime import date
from decimal import Decimal as D

from services.neo_desk.fees import FeePlan, PromotionWindow, estimate_charges


def row(id="a", qty=65, day="2026-10-09"):
    return {
        "fill_id": id,
        "order_id": "order",
        "side": "BUY",
        "quantity": qty,
        "price": "50",
        "trade_date": day,
        "exchange": "NFO",
    }


def test_literal_plan_and_promotion_fees():
    promotion = PromotionWindow(date(2026, 10, 1), date(2026, 10, 30), True)
    assert D(estimate_charges([row()], promotion, FeePlan())["total"]) == D("1.46")
    assert D(estimate_charges([row(day="2026-10-31")], promotion, FeePlan())["total"]) == D("13.26")


def test_unverified_promotion_is_not_assumed():
    result = estimate_charges([row()], None, FeePlan())
    assert D(result["total"]) == D("13.26") and not result["promotion_verified"]


def test_brokerage_once_for_split_fills_and_no_charge_for_zero_fill():
    result = estimate_charges([row("a", 20), row("b", 45), row("cancelled", 0)], None, FeePlan())
    assert D(result["breakdown"]["brokerage"]) == 10


def test_runtime_estimate_uses_plan_rate_without_a_dated_promotion():
    from services.neo_desk.fees import estimate

    assert estimate("BUY", D(50), 65) == D("13.26")


def test_mixed_nse_bse_options_keep_both_estimates():
    nse = row("nse")
    bse = {
        **row("bse"),
        "exchange": "bse_fo",
        "order_id": "bse-order",
        "symbol": "SENSEX22OCT2674000CE",
    }
    result = estimate_charges([nse, bse])
    assert result["complete"] and result["fill_count"] == 2
    assert D(result["total"]) > D(estimate_charges([nse])["total"])
    assert D(result["breakdown"]["brokerage"]) == 20
    assert D(result["breakdown"]["exchange"]) == D("2.21")
    assert len(result["per_fill"]) == 2


def test_unknown_instrument_cannot_hide_supported_charges():
    result = estimate_charges([row(), {**row("future"), "symbol": "NIFTY29OCT26FUT"}])
    assert not result["complete"] and result["estimated_fill_count"] == 1
    assert result["unsupported_fill_count"] == 1
    assert result["total"] == estimate_charges([row()])["total"]


def test_account_plan_uses_dated_order_brokerage_and_split_fills_once():
    plan = FeePlan(brokerage=None)
    earlier = row("before", day="2026-10-21")
    split = [row("part1", 20, "2026-10-22"), row("part2", 45, "2026-10-22")]
    result = estimate_charges([earlier, *split], plan=plan)
    assert D(result["breakdown"]["brokerage"]) == 10
    assert result["executed_order_count"] == 2


def test_split_prices_keep_turnover_taxes_with_each_fill_and_conserve_total():
    from services.neo_desk.fees import fill_key

    a = {**row("low", 20), "price": "10"}
    b = {**row("high", 45), "price": "100"}
    result = estimate_charges([a, b])
    assert result["per_fill_breakdown"][fill_key(a)]["exchange"] == "0.07"
    assert result["per_fill_breakdown"][fill_key(b)]["exchange"] == "1.60"
    assert sum(D(x) for x in result["per_fill"].values()) == D(result["total"])
    assert sum(D(x["brokerage"]) for x in result["per_fill_breakdown"].values()) == 10
