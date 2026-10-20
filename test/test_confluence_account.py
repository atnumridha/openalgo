"""The UI startup must fund paper once, never reset it or expose credentials."""

import hashlib
import hmac
import json
import subprocess
import time
from argparse import Namespace

import httpx
import pytest

from strategies.confluence import cli
from strategies.confluence.paper import Ledger, PaperBook
from strategies.confluence.strategy import Config


def args(**overrides):
    return Namespace(wallet_snapshot=None, capital_usd=None, account_balance=True, **overrides)


def snapshot(amount="12.34567890"):
    return {
        "environment": "india_prod",
        "captured_at": time.time(),
        "result": [{"asset_symbol": "USD", "available_balance": amount}],
    }


def test_host_start_selects_readonly_account_bootstrap(monkeypatch):
    monkeypatch.setenv("STRATEGY_ID", "delta_confluence_strategy_registered")
    assert cli.parser().parse_args([]).account_balance is True


def test_first_initialization_uses_available_balance_and_records_provenance(tmp_path, monkeypatch):
    data = snapshot()
    monkeypatch.setattr(cli, "read_connected_snapshot", lambda: data, raising=False)
    with Ledger(tmp_path / "paper.sqlite") as db:
        p = cli.prepare_paper(db, args(), Config())
        assert p.state["initial_cash"] == 12.34567890 and p.state["cash"] == 12.34567890
        assert p.state["seed_snapshot"] == {
            "environment": "india_prod",
            "captured_at": data["captured_at"],
            "available_usd": "12.34567890",
        }
        assert p.state["position"] is None and p.state["pending"] is None
        assert db.load(Config()).state["cash"] == p.state["cash"]
        assert (db.path.stat().st_mode & 0o077) == 0


def test_existing_losses_and_halt_never_refetch_or_reseed(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("Existing ledger must not fetch the wallet again")

    monkeypatch.setattr(cli, "read_connected_snapshot", forbidden, raising=False)
    with Ledger(tmp_path / "paper.sqlite") as db:
        p = PaperBook.fresh(20, time.time(), Config())
        p.state.update(cash=17, day_net=-3, halt_day=1, paused=True)
        db.save(p)
        loaded = cli.prepare_paper(db, args(), Config())
        assert loaded.state["cash"] == 17 and loaded.state["day_net"] == -3
        assert loaded.state["halt_day"] == 1 and loaded.state["paused"] is True


def test_allowlist_failure_does_not_create_zero_or_hypothetical_balance(tmp_path, monkeypatch):
    def blocked():
        raise ValueError("Delta API IP allowlist blocks the wallet read")

    monkeypatch.setattr(cli, "read_connected_snapshot", blocked, raising=False)
    with Ledger(tmp_path / "paper.sqlite") as db:
        with pytest.raises(ValueError, match="allowlist"):
            cli.prepare_paper(db, args(), Config())
        assert db.load(Config()) is None and db.report()["trade_count"] == 0


@pytest.fixture
def connection_file(tmp_path):
    p = tmp_path / "config.env"
    p.write_text("DELTA_API_KEY=test-key\nDELTA_API_SECRET=test-secret\nDELTA_MCP_ENV=india_prod\n")
    p.chmod(0o600)
    return p


class Transport(httpx.MockTransport):
    closed = False

    def close(self):
        self.closed = True
        super().close()


def test_host_with_no_subprocess_permission_can_read_only_wallet(connection_file, monkeypatch):
    from strategies.confluence.account import read_connected_snapshot

    def forbidden(*a, **k):
        raise BlockingIOError(35, "host process limit")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setenv("OPENALGO_API_KEY", "unused-host-key")

    def handler(req):
        assert (
            req.method == "GET"
            and str(req.url) == "https://api.india.delta.exchange/v2/wallet/balances"
        )
        expected = hmac.new(
            b"test-secret",
            ("GET" + req.headers["timestamp"] + "/v2/wallet/balances").encode(),
            hashlib.sha256,
        ).hexdigest()
        assert req.headers["signature"] == expected and req.headers["api-key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [
                    {
                        "asset_symbol": "USD",
                        "available_balance": "12.30",
                        "balance": "999",
                        "account_id": 123,
                        "secret": "must not escape",
                    },
                    {"asset_symbol": "INR", "available_balance": "500"},
                ],
            },
        )

    transport = Transport(handler)
    r = read_connected_snapshot(config_path=connection_file, transport=transport)
    assert (
        r["result"] == [{"asset_symbol": "USD", "available_balance": "12.30"}] and transport.closed
    )
    assert "secret" not in json.dumps(r) and "account_id" not in json.dumps(r)


@pytest.mark.parametrize(
    "error", ["ip_not_whitelisted_for_api_key", "invalid_api_key", "unknown_error"]
)
def test_read_error_is_actionable_and_does_not_expose_context(connection_file, error):
    from strategies.confluence.account import read_connected_snapshot

    transport = Transport(
        lambda req: httpx.Response(
            401,
            json={
                "success": False,
                "error": {"code": error, "context": "private transport context"},
            },
        )
    )
    with pytest.raises(ValueError) as e:
        read_connected_snapshot(config_path=connection_file, transport=transport)
    assert transport.closed and "private transport" not in str(e.value)
    if error.startswith("ip_"):
        assert "allowlist" in str(e.value).lower()


def test_wallet_timeout_is_bounded_and_client_closes(connection_file):
    from strategies.confluence.account import read_connected_snapshot

    def timeout(req):
        assert req.extensions["timeout"]["read"] == 5
        raise httpx.ReadTimeout("private output")

    transport = Transport(timeout)
    with pytest.raises(ValueError, match="timed out") as e:
        read_connected_snapshot(config_path=connection_file, transport=transport)
    assert transport.closed and "private output" not in str(e.value)


@pytest.mark.parametrize("problem", ["permissions", "environment", "symlink"])
def test_connection_must_be_private_regular_and_india_prod(connection_file, problem):
    from strategies.confluence.account import read_connected_snapshot

    if problem == "permissions":
        connection_file.chmod(0o644)
    if problem == "environment":
        connection_file.write_text(
            connection_file.read_text().replace("india_prod", "india_testnet")
        )
    if problem == "symlink":
        link = connection_file.with_name("link")
        link.symlink_to(connection_file)
        connection_file = link

    def forbidden(req):
        raise AssertionError("No network request permitted")

    with pytest.raises(ValueError):
        read_connected_snapshot(config_path=connection_file, transport=Transport(forbidden))
