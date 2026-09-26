"""Kotak quote fields required by portfolio admission."""

from broker.kotak.api.data import BrokerData


def test_kotak_quote_preserves_broker_time_and_best_level_depth(monkeypatch):
    data = BrokerData.__new__(BrokerData)
    monkeypatch.setattr(data, "_get_kotak_exchange", lambda _exchange: "nse_cm")
    monkeypatch.setattr(data, "_get_index_symbol_candidates", lambda _symbol: ["NIFTY 50"])
    monkeypatch.setattr(
        data,
        "_query_index_with_candidates",
        lambda *_args: (
            [
                {
                    "display_symbol": "NIFTY 50",
                    "ltp": 24000,
                    "lstup_time": "25/09/2026 10:00:00",
                    "depth": {
                        "buy": [{"price": 23999, "quantity": 110}],
                        "sell": [{"price": 24001, "quantity": 90}],
                    },
                }
            ],
            "nse_cm|NIFTY 50",
        ),
    )

    quote = data.get_quotes("NIFTY", "NSE_INDEX")

    assert quote["timestamp"] == "25/09/2026 10:00:00"
    assert quote["bid_qty"] == 110
    assert quote["ask_qty"] == 90


def test_kotak_multiquote_preserves_native_broker_market_time(monkeypatch):
    data = BrokerData.__new__(BrokerData)
    monkeypatch.setattr(data, "_get_kotak_exchange", lambda _exchange: "nse_cm")
    monkeypatch.setattr(data, "_get_index_symbol_candidates", lambda _symbol: ["NIFTY 50"])
    monkeypatch.setattr(
        data,
        "_make_quotes_request",
        lambda *_args: [
            {
                "exchange": "nse_cm",
                "exchange_token": "NIFTY 50",
                "display_symbol": "NIFTY 50",
                "ltp": 24000,
                "lstup_time": "25/09/2026 10:00:00",
                "ohlc": {"open": 23900, "high": 24100, "low": 23800, "close": 23950},
                "depth": {"buy": [{"price": 23999}], "sell": [{"price": 24001}]},
            }
        ],
    )

    rows = data.get_multiquotes([{"symbol": "NIFTY", "exchange": "NSE_INDEX"}])

    assert rows[0]["data"]["timestamp"] == "25/09/2026 10:00:00"
    assert rows[0]["data"]["ltp"] == 24000
