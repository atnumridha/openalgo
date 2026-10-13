from services.neo_desk.chart_views import risk_overlay


def trade():
    return {
        "run_id": 5,
        "symbol": "NIFTY13OCT2622500PE",
        "exchange": "NFO",
        "entry_price": "50",
        "quantity": 20,
        "option_stop": "45",
        "option_target": "80",
        "direction": "PE",
        "index_reference": "22500",
        "index_stop": "22510",
        "target": "22440",
    }


def test_overlay_matches_option_scale():
    p = trade()
    levels = risk_overlay("NFO:NIFTY13OCT2622500PE", p)
    assert [x["price"] for x in levels] == ["50", "45", "80"]
    assert risk_overlay("NFO:NIFTY13OCT2622500CE", p) == []
    assert [x["price"] for x in risk_overlay("NSE_INDEX:NIFTY", p)] == ["22500", "22510", "22440"]


def test_unfilled_trade_has_no_executed_entry_overlay():
    assert risk_overlay("NFO:NIFTY13OCT2622500PE", trade() | {"quantity": 0}) == []


def test_manual_close_identity(monkeypatch):
    from test_native_entries import OWNER
    from test_ownership import owned

    from services.neo_desk.lifecycle import request_owned_exit

    rid, orders = owned(monkeypatch, qty=20)
    assert not request_owned_exit(OWNER, str(rid + 100), "manual", "stale")["ok"]
    assert len(orders) == 1
    assert request_owned_exit(OWNER, str(rid), "manual", "current")["ok"]
    assert len(orders) == 2 and orders[-1]["quantity"] == "20" and orders[-1]["action"] == "SELL"


from test_native_entries import isolated
