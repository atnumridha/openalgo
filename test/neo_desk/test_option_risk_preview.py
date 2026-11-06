from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from services.neo_desk.option_risk_preview import option_risk_preview
from services.neo_desk.fees import FeePlan, estimate_charges


def contract(side="CE", exchange="NFO", lot=65, tick="0.05"):
    return SimpleNamespace(symbol=f"NIFTY03NOV2623050{side}", exchange=exchange,
                           lotsize=lot, tick_size=tick)


def preview(c=None, **changes):
    c = c or contract()
    body = dict(symbol=c.symbol, exchange=c.exchange, entry="100", stop="90", lots=2,
                slippage="0.05") | changes
    return option_risk_preview(body, c, date(2026, 10, 30))


@pytest.mark.parametrize("side", ["CE", "PE"])
@pytest.mark.parametrize("exchange,lot", [("NFO",65),("BFO",20)])
def test_long_premium_target_and_cash_estimates_use_exact_contract(side, exchange, lot):
    c = contract(side, exchange, lot)
    p = preview(c)
    qty = lot * 2
    assert p["symbol"] == c.symbol and p["exchange"] == exchange
    assert p["quantity"] == qty and p["target"] == "120.00"
    assert p["gross_reward_risk"] == "2.00"
    def charges(exit):
        return D(estimate_charges([
            dict(fill_id="buy", order_id="entry", symbol=c.symbol, exchange=exchange,
                 side="BUY", quantity=qty, price="100", trade_date="2026-10-30"),
            dict(fill_id="sell", order_id="exit", symbol=c.symbol, exchange=exchange,
                 side="SELL", quantity=qty, price=exit, trade_date="2026-10-30"),
        ], plan=FeePlan(brokerage=None))["total"])
    assert D(p["profit_fees"]) == charges("119.95")
    assert D(p["loss_fees"]) == charges("89.95")
    assert D(p["net_profit"]) == D("19.95")*qty - charges("119.95")
    assert D(p["net_loss"]) == D("10.05")*qty + charges("89.95")
    assert D(p["net_reward_risk"]) < 2


def test_brokerage_is_per_order_not_per_lot_and_uses_account_date():
    a, b = preview(lots=1), preview(lots=3)
    assert a["brokerage_per_order"] == b["brokerage_per_order"] == "10.00"
    c = contract()
    before = option_risk_preview(dict(symbol=c.symbol,exchange=c.exchange,entry="100",
        stop="90",lots=1,slippage="0"), c, date(2026,10,21))
    assert before["brokerage_per_order"] == "0.00"


@pytest.mark.parametrize("changes", [dict(entry="NaN"),dict(stop="Infinity"),dict(stop="100"),
    dict(stop="0"),dict(stop="100.05"),dict(lots=0),dict(lots=1.5),dict(lots=True),
    dict(entry="100.01"),dict(slippage="-0.05"),dict(slippage="90"),
    dict(symbol="OTHERPE"),dict(exchange="BFO"),dict(quantity=100),dict(lots=10001)])
def test_invalid_or_mismatched_inputs_do_not_return_a_cash_estimate(changes):
    with pytest.raises(ValueError):
        preview(**changes)


@pytest.mark.parametrize("c", [None, contract(lot=0),contract(tick="0"),contract(exchange="NSE")])
def test_missing_contract_metadata_is_not_a_zero_fee_or_default_lot_estimate(c):
    with pytest.raises(ValueError):
        option_risk_preview(dict(symbol="NIFTY03NOV2623050CE",exchange="NFO",entry="100",
                                stop="90",lots=1,slippage="0"), c, date(2026,10,30))


def test_a_small_target_can_still_be_a_net_loss():
    p = preview(entry="1",stop="0.95",slippage="0",lots=1)
    assert D(p["net_profit"]) < 0
    assert D(p["net_loss"]) > 0


@pytest.mark.parametrize("side", ["CE", "PE"])
@pytest.mark.parametrize("exchange,expected", [("NFO", "103.01"), ("BFO", "100.00")])
def test_flattrade_guide_matches_published_zero_brokerage_round_trip(side, exchange, expected):
    c = contract(side, exchange, lot=100)
    p = preview(c, broker="flattrade", entry="100", stop="90", target="110", lots=4, slippage="0")
    assert p["broker"] == "flattrade"
    assert p["brokerage_per_order"] == "0.00"
    assert p["profit_fees"] == expected
    assert D(p["net_profit"]) == D("4000") - D(expected)
    assert p["gross_reward_risk"] == "1.00"
    assert p["target"] == "110.00"
    assert "flattrade.in/brokerage-calculator" in p["fee_source"]


@pytest.mark.parametrize("changes", [dict(broker="other"), dict(broker=None), dict(target="99"),
    dict(target="NaN"), dict(target="110.01"), dict(target="1000001")])
def test_guidance_rejects_unknown_fee_profile_and_invalid_target(changes):
    with pytest.raises(ValueError):
        preview(**changes)


def test_explicit_kotak_profile_preserves_default_estimate():
    assert preview(broker="kotak")["profit_fees"] == preview()["profit_fees"]


def test_position_valuation_reports_profit_at_a_trailing_stop_above_entry():
    p = preview(broker="flattrade", position=True, stop="105", target="110", slippage="0")
    assert D(p["net_at_stop"]) > 0
    assert p["net_reward_risk"] is None


def test_new_entry_cannot_use_a_profitable_position_stop_override():
    with pytest.raises(ValueError):
        preview(broker="flattrade", stop="105", target="110")


def test_preview_route_requires_a_kotak_session_and_uses_master_contract_metadata(monkeypatch):
    from flask import Flask
    from blueprints.neo_desk import neo_desk_bp
    from database import token_db

    monkeypatch.setenv("NEO_SAVED_LOGIN", "TRUE")
    calls = []
    monkeypatch.setattr(token_db, "get_symbol_info", lambda symbol, exchange: calls.append((symbol, exchange)) or contract())
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(neo_desk_bp)
    client = app.test_client()
    body = dict(symbol=contract().symbol, exchange="NFO", entry="100", stop="90", lots=1,slippage="0")
    assert client.post("/neodesk/api/chart/risk-preview", json=body).status_code == 401
    assert not calls
    with client.session_transaction() as session:
        session.update(user="fixture", logged_in=True, broker="kotak")
    response = client.post("/neodesk/api/chart/risk-preview", json=body)
    assert response.status_code == 200
    assert response.json["quantity"] == 65
    assert calls == [(contract().symbol, "NFO")]
    get_response = client.get("/neodesk/api/chart/risk-preview", query_string=body)
    assert get_response.status_code == 200
    assert get_response.json["net_profit"] == response.json["net_profit"]
    assert get_response.json["target"] == "120.00"
    assert client.post("/neodesk/api/chart/risk-preview", json=body | {"quantity": 1}).status_code == 400
