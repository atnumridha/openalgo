import pytest

from services.kotak_assistant.analysis import (
    completed,
    fees,
    journal,
    plan,
    validate_settings,
    zones,
)

SETTINGS = {
    "risk": 1500,
    "daily_loss": 5000,
    "giveback": 2000,
    "premium": 50000,
    "spread": 2,
    "slippage": 0.1,
    "brokerage": 0,
    "cooldown": 300,
    "cutoff": "15:15",
}


def test_exchange_fees_differ_and_zero_brokerage_has_charges():
    assert fees(10000, 11000, "NFO")["total"] > fees(10000, 11000, "BFO")["total"] > 0
    assert fees(10000, 11000, "NFO")["stt"] == 16.5
    with pytest.raises(ValueError):
        fees(1, 1, "NSE")


def test_quantity_uses_cap_risk_and_whole_lots():
    p = plan(100, 90, 122, 65, "NFO", SETTINGS, 0.05, 65)
    assert p["risk"] > 650 and p["costs"] > 0 and p["fits"]
    assert not plan(100, 90, 122, 195, "NFO", SETTINGS, 0.05, 65)["fits"]
    with pytest.raises(ValueError):
        plan(100, 90, 122, 66, "NFO", SETTINGS, 0.05, 65)


def test_manual_plan_does_not_require_optional_rupee_budgets():
    p = plan(100, 90, 122, 65, "NFO", {}, 0.05, 65)
    assert p["fits"] and p["reason"] == ""
    assert p["max_lots"] is None
    assert p["risk"] > 650 and p["costs"] > 0


@pytest.mark.parametrize(
    "settings, fits, max_lots",
    [
        ({"risk": 600}, False, 0),
        ({"risk": 1500}, True, 2),
        ({"premium": 6000}, False, 0),
        ({"premium": 13000}, True, 2),
        ({"daily_loss": 5000, "giveback": 2000}, True, None),
    ],
)
def test_each_configured_budget_is_honoured_independently(settings, fits, max_lots):
    p = plan(100, 90, 122, 65, "NFO", settings, 0.05, 65)
    assert p["fits"] is fits
    assert p["max_lots"] == max_lots


@pytest.mark.parametrize("sl,target", [(101, 120), (0, 120), (90, 99), (float("nan"), 120)])
def test_invalid_long_option_plan(sl, target):
    with pytest.raises(ValueError):
        plan(100, sl, target, 65, "NFO", SETTINGS, 0.05, 65)


def test_forming_candle_and_malformed_candle_excluded():
    bars = [
        {"time": 60, "open": 10, "high": 11, "low": 9, "close": 10},
        {"time": 120, "open": 10, "high": 11, "low": 9, "close": 10},
    ]
    assert len(completed(bars, 179, 60)) == 1
    assert len(completed(bars, 180, 60)) == 2


def test_pivot_cannot_be_used_before_two_right_bars():
    bars = [
        {"time": i * 300, "open": 10, "high": h, "low": 5, "close": 10}
        for i, h in enumerate([11, 12, 20, 13, 12])
    ]
    assert not any(z["price"] == 20 for z in zones(bars[:4]))
    assert any(z["price"] == 20 and z["known_at"] == 1500 for z in zones(bars))


def test_settings_reject_nonfinite_limits():
    with pytest.raises(ValueError):
        validate_settings({**SETTINGS, "risk": float("inf")})
    with pytest.raises(ValueError):
        validate_settings({**SETTINGS, "cutoff": "16:00"})


def test_journal_deduplicates_fills_and_reconciles_quantity():
    b = {
        "tradeid": "1",
        "orderid": "a",
        "symbol": "NIFTYCE",
        "exchange": "NFO",
        "product": "MIS",
        "action": "BUY",
        "quantity": 65,
        "average_price": 100,
        "timestamp": "14-Oct-2026 10:00:00",
    }
    s = {
        **b,
        "tradeid": "2",
        "orderid": "b",
        "action": "SELL",
        "average_price": 110,
        "timestamp": "14-Oct-2026 10:01:00",
    }
    j = journal([b, b, s], [], "2026-10-14")
    assert j["complete"] and j["gross_realised"] == 650 and len(j["cycles"]) == 1
    assert j["charges"] > 0 and j["cycles"][0]["net"] < 650
    assert not journal([b], [], "2026-10-14")["complete"]


def test_journal_missing_fill_identity_never_invents_total():
    assert not journal([{"symbol": "X"}], [], "2026-10-14")["complete"]


def test_partial_loss_counts_before_flat():
    b = {
        "tradeid": "1",
        "orderid": "a",
        "symbol": "NIFTYCE",
        "exchange": "NFO",
        "product": "MIS",
        "action": "BUY",
        "quantity": 130,
        "average_price": 100,
        "timestamp": "14-Oct-2026 10:00:00",
    }
    s = {**b, "tradeid": "2", "orderid": "b", "action": "SELL", "quantity": 65, "average_price": 50}
    j = journal(
        [b, s],
        [{"symbol": "NIFTYCE", "exchange": "NFO", "product": "MIS", "quantity": 65}],
        "2026-10-14",
    )
    assert j["complete"] and j["gross_realised"] == -3250 and not j["cycles"]


def test_completed_five_minute_bar_remains_usable_until_next_bar_is_due():
    from services.kotak_assistant.analysis import analyse

    now = 1791955800
    one = [dict(time=now - (60-i)*60, open=100, high=102, low=98, close=100) for i in range(60)]
    five = [dict(time=now - 540 - (59-i)*300, open=100, high=102, low=98, close=100) for i in range(60)]
    assert analyse(one, five, now)['reason'] != 'History is stale'
    assert analyse(one, five, now+126)['reason'] == 'History is stale'
