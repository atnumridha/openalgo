import pandas as pd
import pytest

from broker.kotak.api import data as module


@pytest.mark.parametrize(
    "clock,end",
    [
        ("2026-10-14T07:50:00+05:30", "2026-10-13"),
        ("2026-10-14T09:15:00+05:30", "2026-10-14"),
        ("2026-10-19T08:30:00+05:30", "2026-10-16"),
    ],
)
def test_cash_history_never_requests_a_session_that_has_not_opened(monkeypatch, clock, end):
    monkeypatch.setattr(module, "_history_clock", lambda: pd.Timestamp(clock), raising=False)
    broker = module.BrokerData(
        "fixture-trade:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-api"
    )
    monkeypatch.setattr(broker, "_history_segment", lambda *a: "nse_fo")
    monkeypatch.setattr(broker, "_history_neosymbols", lambda *a: ["nse_fo|fixture"])
    calls = []

    def fetch(symbol, interval, start, through):
        calls.append(through.strftime("%Y-%m-%d"))
        return [[through.strftime("%Y-%m-%d") + "T15:25:00+05:30", 50, 52, 49, 51, 100, 0]]

    monkeypatch.setattr(broker, "_fetch_history_chunk", fetch)
    frame = broker.get_history("NIFTY19OCT2622750CE", "NFO", "5m", "2026-09-14", clock[:10])
    assert calls[-1] == end
    assert not frame.empty


def test_today_only_history_before_open_is_empty_without_a_broker_request(monkeypatch):
    monkeypatch.setattr(
        module, "_history_clock", lambda: pd.Timestamp("2026-10-14T07:50:00+05:30"), raising=False
    )
    broker = module.BrokerData(
        "fixture-trade:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-api"
    )
    monkeypatch.setattr(broker, "_history_segment", lambda *a: "nse_fo")
    monkeypatch.setattr(broker, "_history_neosymbols", lambda *a: ["nse_fo|fixture"])
    monkeypatch.setattr(
        broker, "_fetch_history_chunk", lambda *a: pytest.fail("Unopened session sent to broker")
    )
    assert broker.get_history("NIFTY19OCT2622750CE", "NFO", "5m", "2026-10-14", "2026-10-14").empty
