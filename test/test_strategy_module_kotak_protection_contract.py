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
