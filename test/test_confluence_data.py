import httpx
import pytest

from strategies.confluence import cli
from strategies.confluence.data import DeltaPublic, normalize_options
from strategies.confluence.paper import Ledger, PaperBook
from strategies.confluence.strategy import Config


def test_option_quote_timestamp_contract_units_and_verified_expiry():
    row = {
        "symbol": "C-BTC-85000-071026",
        "underlying_asset_symbol": "BTC",
        "product_trading_status": "operational",
        "contract_type": "call_options",
        "strike_price": "85000",
        "timestamp": 1791288000000000,
        "time": "2020-01-01T00:00:00Z",
        "oi": ".123",
        "oi_contracts": "123",
        "quotes": {"best_bid": "10", "best_ask": "11", "mark_iv": ".25"},
        "greeks": {"delta": ".3"},
    }
    r = normalize_options([row], 1791374400, "071026")[0]
    assert r["timestamp"] == 1791288000 and r["oi_contracts"] == 123 and r["iv"] == 0.25
    assert r["expiry"] == 1791374400 and r["side"] == "CALL"
    assert normalize_options([row], 1791374400, "081026") == []


def test_public_client_get_only_normalizes_tape_and_closes():
    calls = []

    def handler(req):
        calls.append(req)
        assert req.method == "GET" and "api-key" not in req.headers
        result = (
            {
                "buy": [{"price": "100", "size": 5}],
                "sell": [{"price": "101", "size": 6}],
                "last_updated_at": 1791288000000000,
            }
            if "orderbook" in req.url.path
            else [{"timestamp": 1791288000000000, "price": "100", "size": 2, "buyer_role": "maker"}]
        )
        return httpx.Response(200, json={"success": True, "result": result})

    with DeltaPublic(httpx.MockTransport(handler)) as feed:
        q = feed.market()
        assert q["bid"] == 100 and q["ask"] == 101
        assert q["trades"][0]["side"] == "sell" and q["trades"][0]["timestamp"] == 1791288000
    assert feed.client.is_closed and len(calls) == 2


def test_tape_outage_does_not_hide_book_from_stop_manager():
    def handler(req):
        if "trades" in req.url.path:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "buy": [{"price": 100, "size": 1}],
                    "sell": [{"price": 101, "size": 1}],
                    "last_updated_at": 1791288000000000,
                },
            },
        )

    with DeltaPublic(httpx.MockTransport(handler)) as feed:
        q = feed.market()
        assert q["bid"] == 100 and not q["trades"]


def test_report_is_readable_while_controller_owns_ledger(tmp_path):
    path = tmp_path / "p.sqlite"
    with Ledger(path) as writer:
        writer.save(PaperBook.fresh(20, 1791288000, Config()))
        with Ledger(path, readonly=True) as reader:
            r = reader.report()
            assert r["trade_count"] == 0 and r["win_rate"] is None


def test_cli_live_selection_does_not_arm_execution():
    args = cli.parser().parse_args(["--mode", "live"])
    assert args.mode == "live" and args.arm_live is False


def test_first_run_needs_balance_and_closes_resources(tmp_path, monkeypatch):
    instances = []

    class Feed:
        def __enter__(self):
            instances.append(self)
            self.closed = False
            return self

        def __exit__(self, *args):
            self.closed = True

    monkeypatch.setattr(cli, "DeltaPublic", Feed)
    path = tmp_path / "p.sqlite"
    with pytest.raises(ValueError, match="wallet-snapshot"):
        cli.main(["--db", str(path)])
    assert instances[0].closed
    with Ledger(path):
        pass  # failed startup released the controller lock
