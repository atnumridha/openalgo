from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
import pytest
from conftest import bars, when, contract
from services.neo_desk.types import Candle
from services.neo_desk.datasets import HistoricalDataset
from services.neo_desk.replay import ReplayRequest, run_replay, whole_lots


def fixture(missing=False, future=False):
    index = bars() + [Candle(when("09:45"), D(104), D(105), D(103), D(104))]
    c = contract("CE")
    minute = Candle(when("09:45"), D(100 if future else 50), D(100 if future else 51), D(49), D(50))
    option = {minute.time: minute}
    if not missing:
        option[when("09:46")] = Candle(when("09:46"), D(40), D(80), D(39), D(50))
    return HistoricalDataset(
        "fixture",
        index,
        {c.symbol: c},
        {c.symbol: option},
        [date(2026, 10, 13)],
        {"synthetic": True},
        [],
    )


def request():
    return ReplayRequest(
        "fixture", "orb_trail", "NIFTY", date(2026, 10, 13), date(2026, 10, 13), date(2026, 10, 13)
    )


def test_compounding_whole_lots():
    assert whole_lots(D(10000), D(50), 65, D(0)) == 3
    assert whole_lots(D(7000), D(50), 65, D(0)) == 2
    assert 10000 - 3 * 50 * 65 == 250


def test_missing_option_exit_is_unresolved():
    report = run_replay(fixture(missing=True), request())
    assert report["trades"][0]["status"] == "unresolved_option_gap"
    assert report["net_complete"] is None


def test_no_future_price_selection():
    report = run_replay(fixture(future=True), request())
    assert not report["trades"] and report["skipped"]


def test_conservative_stop_and_fee_algebra_without_live_execution(monkeypatch):
    monkeypatch.setattr(
        "services.strategy_module.order_dispatch.dispatch_order",
        lambda **kw: (_ for _ in ()).throw(AssertionError("Replay cannot submit an order")),
    )
    report = run_replay(fixture(), request())
    trade = report["trades"][0]
    assert trade["entry_price"] == "50.50" and D(trade["exit_price"]) <= D("39.50")
    assert D(trade["gross"]) == (D(trade["exit_price"]) - D(trade["entry_price"])) * 65
    assert D(trade["net"]) == D(trade["gross"]) - D(trade["fees"])
    assert "OHLC" in report["assumptions"][0]


def test_one_year_request_validation():
    with pytest.raises(ValueError):
        run_replay(fixture(), replace(request(), start=date(2024, 1, 1)))


def test_unresolved_entry_still_has_estimated_entry_charges():
    report = run_replay(fixture(missing=True), request())
    assert D(report["fees_estimate"]) > 0
