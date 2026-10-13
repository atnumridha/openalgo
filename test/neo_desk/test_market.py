from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

from services.neo_desk.presets import get_preset
from services.neo_desk.selection import select_contract
from test.neo_desk.conftest import contract, quote, when


def test_server_observed_depth_snapshot_does_not_invent_exchange_time():
    c = contract()
    q = replace(quote(c), exchange_time=None, verified_depth_snapshot=True)
    assert q.exchange_time is None and q.fresh(when())
    assert select_contract(
        [c], {c.symbol: q}, get_preset("orb_trail"), D(10000), when(), direction="CE"
    ).ok
    assert not replace(q, received_at=when() - timedelta(seconds=6)).fresh(when())
    assert not replace(q, verified_depth_snapshot=False).fresh(when())


def test_kotak_reported_trading_limit_is_separate_from_cash(monkeypatch):
    import json

    from broker.kotak.api.funds import get_margin_data

    payload = {
        "stat": "Ok",
        "CollateralValue": "14959.63",
        "Collateral": "0",
        "MarginUsed": "-14254.45",
        "Net": "29214.08",
    }
    monkeypatch.setattr(
        "broker.kotak.api.funds.get_httpx_client",
        lambda: SimpleNamespace(
            post=lambda *a, **k: SimpleNamespace(status_code=200, text=json.dumps(payload))
        ),
    )
    value = get_margin_data(
        "fixture-token:::fixture-sid:::https://fixture.kotaksecurities.com:::fixture-key"
    )
    assert value["availablecash"] == "14959.63"
    assert value["availabletradinglimit"] == "29214.08"


def test_missing_reported_limit_is_not_invented_from_collateral(monkeypatch):
    import json

    from broker.kotak.api.funds import get_margin_data

    payload = {"stat": "Ok", "CollateralValue": "14959.63", "Collateral": "5000", "MarginUsed": "0"}
    monkeypatch.setattr(
        "broker.kotak.api.funds.get_httpx_client",
        lambda: SimpleNamespace(
            post=lambda *a, **k: SimpleNamespace(status_code=200, text=json.dumps(payload))
        ),
    )
    value = get_margin_data(
        "fixture-token:::fixture-sid:::https://fixture.kotaksecurities.com:::fixture-key"
    )
    assert value.get("availabletradinglimit") is None


def test_runner_prewarms_once_and_close_fetches_only_current_day(monkeypatch):
    from services.neo_desk.market import NativeMarket

    calls = []
    monkeypatch.setattr("services.neo_desk.market.get_auth_token", lambda owner: "fixture-auth")
    monkeypatch.setattr(
        "services.neo_desk.market.get_api_key_for_tradingview", lambda owner: "fixture-key"
    )

    def history(symbol, exchange, interval, start, end, **kwargs):
        calls.append((start, end))
        return True, {"data": []}, 200

    monkeypatch.setattr("services.neo_desk.market.get_history", history)
    m = NativeMarket()
    p = get_preset("orb_trail")
    m.snapshot("owner", p, when("09:40"))
    m.snapshot("owner", p, when("09:41"))
    assert len(calls) == 1 and calls[0][0] != calls[0][1]
    m.snapshot("owner", p, when("09:45"))
    assert calls[-1] == ("2026-10-13", "2026-10-13")
