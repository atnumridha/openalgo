from datetime import date
from decimal import Decimal as D
from services.neo_desk.fees import estimate_charges, PromotionWindow, FeePlan


def row(id="a", qty=65, day="2026-10-09"):
    return dict(
        fill_id=id,
        order_id="order",
        side="BUY",
        quantity=qty,
        price="50",
        trade_date=day,
        exchange="NFO",
    )


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
