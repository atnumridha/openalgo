"""Read-only Kotak payload contract for a bounded entry and separate stop."""

from types import SimpleNamespace
from unittest.mock import patch

from broker.kotak.mapping import transform_data as kotak_mapping
from services.strategy_module.order_dispatch import build_order


def test_kotak_maps_limit_entry_and_separate_stop_limit_with_positive_prices():
    entry = build_order(
        symbol="NIFTY28MAY2624000CE", exchange="NFO", action="BUY",
        quantity=25, product="NRML", strategy_name="contract",
        pricetype="LIMIT", price=100.50,
    )
    stop = build_order(
        symbol="NIFTY28MAY2624000CE", exchange="NFO", action="SELL",
        quantity=25, product="NRML", strategy_name="contract",
        pricetype="SL-M", trigger_price=90,
    )
    with (
        patch.object(kotak_mapping, "get_br_symbol", return_value="NIFTY-OPT"),
        patch.object(
            kotak_mapping, "get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)
        ),
    ):
        mapped_entry = kotak_mapping.transform_data(entry, "token")
        mapped_stop = kotak_mapping.transform_data(stop, "token")

    assert mapped_entry["pt"] == "L"
    assert mapped_entry["pr"] == "100.5"
    assert mapped_entry["qt"] == "25"
    assert mapped_stop["pt"] == "SL"
    assert mapped_stop["tp"] == "90"
    assert float(mapped_stop["pr"]) < 90
    assert float(mapped_stop["pr"]) > 0


def test_recovery_verifies_broker_fallback_without_dropping_earned_app_stop(monkeypatch):
    from services.strategy_module import live_protection as protection
    from services.risk.profit_exit import profit_config
    costs = dict(brokerage_per_order=0, exchange_rate=0, sebi_rate=0, gst_rate=0,
                 stamp_buy_rate=0, stt_sell_rate=0, slippage_bps=0)
    leg = dict(leg_id=1,position='B',entry_avg=100,qty=75,status='open',
               symbol='NIFTY_CE',exchange='NFO',position_ref='p1',sl_pts=4,
               effective_sl=108,highest_price=112,
               profit_protection=profit_config({'tick_size':.05}, costs))
    stop = dict(kind='protective_stop',position_ref='p1',status='open',broker_order_id='broker-stop',trigger_price=96,product='NRML')
    monkeypatch.setattr(protection.state,'get_run_state',lambda _: {'legs':{'1':leg}})
    monkeypatch.setattr(protection.store,'get_run',lambda _: SimpleNamespace(broker_connection_id='kotak-1'))
    monkeypatch.setattr(protection,'_active_kotak_pin',lambda *a: True)
    monkeypatch.setattr(protection.store,'list_orders',lambda _: [stop])
    def broker_evidence(key, broker_id, expected):
        return {'orderid':broker_id} if expected['trigger_price']==96 else None
    monkeypatch.setattr(protection,'_verify_working_stop',broker_evidence)
    assert protection.verify_recovered_run(1,'test-key') == []
    assert leg['effective_sl'] == 108
    # Neither weakening the durable fallback nor a broker mismatch is accepted.
    stop['trigger_price']=95
    assert protection.verify_recovered_run(1,'test-key') == ['NIFTY_CE']
    stop['trigger_price']=97
    assert protection.verify_recovered_run(1,'test-key') == ['NIFTY_CE']
