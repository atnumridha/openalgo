"""Hosted Live activation uses the existing account and preserves execution limits."""

import json
from types import SimpleNamespace

import pytest

from strategies.confluence import cli, live
from strategies.confluence.strategy import Config


def hosted(monkeypatch):
    monkeypatch.setenv("STRATEGY_ID", "test-strategy")
    monkeypatch.setenv("OPENALGO_START_REASON", "manual")
    monkeypatch.setenv("OPENALGO_API_KEY", "test-host-key")
    monkeypatch.setenv("BROKER_API_SECRET", "test-delta-secret")


def test_host_start_is_activation_without_duplicate_arm_flag(monkeypatch):
    hosted(monkeypatch)
    assert cli.parser().parse_args([]).arm_live is True
    monkeypatch.delenv("STRATEGY_ID")
    assert cli.parser().parse_args([]).arm_live is False


def test_connected_credentials_can_be_ready_without_qualification_file(tmp_path, monkeypatch):
    hosted(monkeypatch)
    *_, Rest, _Risk, _Safety, _Store = live.backend()
    # Only account lookup is replaced; real readiness policy and secret-safe credential object run.
    monkeypatch.setattr(
        live,
        "execution_credentials",
        lambda root: Rest.Credentials("test-key", "test-secret"),
        raising=False,
    )
    result = live.readiness(tmp_path, Config(), armed=True)
    assert result["ready"] is True and result["blockers"] == []
    assert result["qualification_verified"] is False
    assert result["warnings"]
    assert "test-secret" not in json.dumps(result) and "test-key" not in json.dumps(result)


def test_standalone_still_requires_explicit_arming(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATEGY_ID", raising=False)
    *_, Rest, _Risk, _Safety, _Store = live.backend()
    monkeypatch.setattr(
        live, "execution_credentials", lambda root: Rest.Credentials("key", "secret"), raising=False
    )
    assert "Live execution is not armed" in live.readiness(tmp_path, Config())["blockers"]


def test_wrong_broker_or_revoked_account_is_not_accepted(monkeypatch):
    from strategies.confluence.connection import credentials_from_account

    for broker, revoked in [("fyers", False), ("deltaexchange", True)]:
        with pytest.raises(ValueError):
            credentials_from_account(
                SimpleNamespace(broker=broker, is_revoked=revoked, auth="encrypted"),
                SimpleNamespace(order_mode="auto"),
                lambda x: "test-key",
                {"BROKER_API_SECRET": "test-secret"},
            )


@pytest.mark.parametrize("mode", ["semi_auto", "unknown"])
def test_does_not_bypass_existing_order_approval_mode(mode):
    from strategies.confluence.connection import credentials_from_account

    with pytest.raises(ValueError, match="automatic"):
        credentials_from_account(
            SimpleNamespace(broker="deltaexchange", is_revoked=False, auth="encrypted"),
            SimpleNamespace(order_mode=mode),
            lambda x: "test-key",
            {"BROKER_API_SECRET": "test-secret"},
        )


def test_uses_openalgo_account_key_and_server_secret_without_copying(tmp_path):
    from strategies.confluence.connection import credentials_from_account

    c = credentials_from_account(
        SimpleNamespace(broker="deltaexchange", is_revoked=False, auth="encrypted"),
        SimpleNamespace(order_mode="auto"),
        lambda x: "stored-key",
        {"BROKER_API_SECRET": "stored-secret"},
    )
    assert c.key == "stored-key" and c.secret == "stored-secret"
    assert c.rotated is False  # Unknown is never relabeled as verified.
    assert "stored-secret" not in repr(c) and "stored-key" not in repr(c)
    assert list(tmp_path.iterdir()) == []


def test_missing_secret_or_wrong_environment_fails_closed():
    from strategies.confluence.connection import credentials_from_account

    for env in [
        {},
        {"BROKER_API_SECRET": "x", "DELTA_BASE_URL": "https://cdn-ind.testnet.deltaex.org"},
    ]:
        with pytest.raises(ValueError):
            credentials_from_account(
                SimpleNamespace(broker="deltaexchange", is_revoked=False, auth="encrypted"),
                SimpleNamespace(order_mode="auto"),
                lambda x: "key",
                env,
            )


def test_missing_connection_keeps_signal_monitoring_without_creating_orders(
    tmp_path, monkeypatch, capsys
):
    from strategies.confluence import observer

    class Feed:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def context(self, now):
            return {}

        def market(self):
            return {}

    class Host:
        def mode(self):
            return "live"

    gate = {"ready": False, "blockers": ["Connect Delta"], "warnings": []}
    monkeypatch.setattr(observer, "DeltaPublic", Feed)
    monkeypatch.setattr(
        observer, "decide", lambda *a: {"action": "HOLD", "reason": "test observation"}
    )
    monkeypatch.setattr(live, "readiness", lambda *a: gate)
    args = cli.parser().parse_args(["--iterations", "1", "--db", str(tmp_path / "paper.sqlite")])
    assert observer.run(args, Config(), Host(), cli.emit) == 0
    out = capsys.readouterr().out
    assert "monitoring" in out and '"execution_enabled": false' in out
    assert not (tmp_path / "paper.sqlite").exists() and not (tmp_path / "live.sqlite").exists()


def test_hosted_mode_reads_use_local_server_not_external_webhook_url(monkeypatch):
    import httpx

    from strategies.confluence.host import Host

    hosted(monkeypatch)
    monkeypatch.setenv("HOST_SERVER", "https://old-tunnel.example")
    monkeypatch.setenv("FLASK_PORT", "5050")
    monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5000")  # Legacy host default.

    def response(request):
        assert str(request.url) == "http://127.0.0.1:5050/api/v1/analyzer"
        return httpx.Response(
            200, json={"status": "success", "data": {"mode": "live", "analyze_mode": False}}
        )

    with Host(transport=httpx.MockTransport(response)) as client:
        assert client.mode() == "live"


def test_account_preflight_reports_real_settings_without_requesting_mutations(tmp_path):
    import asyncio

    from strategies.confluence.live import EntryNotReady, backend, live_types

    _, _, Market, _, Risk, _, _ = backend()
    Store, Broker = live_types(Config())

    class ReadOnly:
        async def get(self, path, params=None, auth=True):
            return {
                "/users/trading_preferences": {"user_id": 1, "default_auto_topup": True},
                "/sub_accounts": [],
            }[path]

    store = Store(tmp_path / "test.sqlite")
    try:
        with pytest.raises(EntryNotReady) as error:
            asyncio.run(Broker(ReadOnly(), Risk.Product(), Market.Book(), store).preflight())
        assert "Auto top-up is ON; the configured margin cap requires it OFF" in error.value.reasons
        assert "Isolated margin could not be confirmed by Delta" in error.value.reasons
        assert store.unresolved() == []
    finally:
        store.close()
