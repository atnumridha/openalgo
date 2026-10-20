"""Host routing cannot turn a paper action into a live order or clear a halt."""

import json
import os
import time

import httpx
import pytest

from strategies.confluence import cli
from strategies.confluence.paper import PaperBook
from strategies.confluence.strategy import Config


def test_host_defaults_to_auto_standalone_stays_paper(monkeypatch):
    monkeypatch.delenv("STRATEGY_ID", raising=False)
    assert cli.parser().parse_args([]).mode == "paper"
    monkeypatch.setenv("STRATEGY_ID", "confluence")
    assert cli.parser().parse_args([]).mode == "auto"


def test_live_never_falls_back_to_paper_and_mode_is_read_fresh():
    from strategies.confluence.host import Host

    modes = iter(["analyze", "live", "analyze"])

    def respond(request):
        assert request.url.path == "/api/v1/analyzer"
        assert json.loads(request.content) == {"apikey": "test-only"}
        mode = next(modes)
        return httpx.Response(
            200,
            json={"status": "success", "data": {"mode": mode, "analyze_mode": mode == "analyze"}},
        )

    with Host("http://127.0.0.1:5050", "test-only", transport=httpx.MockTransport(respond)) as host:
        assert [host.mode() for _ in range(3)] == ["paper", "live", "paper"]


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"mode": "live"},
        {"mode": "live", "analyze_mode": True},
        {"mode": "analyze", "analyze_mode": "true"},
    ],
)
def test_unknown_or_inconsistent_mode_blocks(data):
    from strategies.confluence.host import Host

    with Host(
        "http://127.0.0.1:5050",
        "test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "success", "data": data})
        ),
    ) as host:
        with pytest.raises(ValueError, match="mode"):
            host.mode()


def test_schedule_resume_preserves_losses_but_never_manual_pause_or_halt():
    from strategies.confluence.host import resume_host_paper

    now = time.time()
    p = PaperBook.fresh(20, now, Config())
    p.state.update(
        cash=19.4,
        day_net=-0.6,
        loss_streak=2,
        paused=True,
        status="stopped",
        stop_reason="schedule",
    )
    assert resume_host_paper(p, "scheduled", now)
    assert p.state["cash"] == 19.4 and p.state["loss_streak"] == 2 and p.state["day_net"] == -0.6
    for reason in ("manual", "unknown", "daily_halt"):
        p.state.update(paused=True, stop_reason=reason)
        assert not resume_host_paper(p, "scheduled", now)
        assert p.state["paused"]
    p.state.update(stop_reason="schedule", halt_day=1)
    assert not resume_host_paper(p, "manual", now)


def test_explicit_host_start_resumes_manual_stop_but_not_risk_pause():
    from strategies.confluence.host import resume_host_paper

    p = PaperBook.fresh(20, time.time(), Config())
    p.stop({}, time.time())
    assert resume_host_paper(p, "manual", time.time())
    p.state.update(paused=True, status="risk reconciliation required")
    assert not resume_host_paper(p, "manual", time.time())


def test_shutdown_reason_needs_current_pid_and_recent_request(tmp_path, monkeypatch):
    from strategies.confluence.host import shutdown_reason

    path = tmp_path / "configs.json"
    monkeypatch.setenv("STRATEGY_ID", "test")
    monkeypatch.setenv("OPENALGO_STRATEGY_CONFIG", str(path))
    request = {"pid": os.getpid(), "at": time.time(), "reason": "schedule"}
    path.write_text(json.dumps({"test": {"shutdown_request": request}}))
    assert shutdown_reason() == "schedule"
    request["pid"] += 1
    path.write_text(json.dumps({"test": {"shutdown_request": request}}))
    assert shutdown_reason() == "manual"


def test_stop_records_reason():
    p = PaperBook.fresh(20, time.time(), Config())
    p.stop({}, time.time(), reason="schedule")
    assert p.state["stop_reason"] == "schedule"


def test_live_gate_missing_evidence_is_specific_and_no_credentials_leak(tmp_path):
    from strategies.confluence.live import readiness

    r = readiness(tmp_path, Config(), armed=False)
    assert not r["ready"] and r["mode"] == "live"
    assert "Live execution is not armed" in r["blockers"]
    assert any("credentials" in issue for issue in r["blockers"])
    assert r["qualification_verified"] is False
    assert any("qualification" in issue for issue in r["warnings"])
    assert "secret" not in json.dumps(r).lower()


def test_real_net_target_plan_converts_to_live_engine():
    from services.crypto_fees import ContractFees, net_target_plan
    from strategies.confluence.live import sized_plan

    p = net_target_plan(
        side=1,
        entry=85000,
        stop=84900,
        quantity=1,
        contract_value=0.001,
        tick=0.5,
        contract=ContractFees("BTCUSD"),
    )
    p.update(quantity=1, margin=3.4)
    converted = sized_plan({"action": "LONG", "selected_plan": p}, Config())
    assert float(converted.reward) == pytest.approx(p["net_target"])
    assert converted.leverage == 25 and converted.profile == "confluence"


def test_live_recovery_detected_without_initializing_a_new_ledger(tmp_path):
    from strategies.confluence.live import live_types, recovery_needed

    path = tmp_path / "live.sqlite"
    assert not recovery_needed(path) and not path.exists()
    Store, _ = live_types(Config())
    store = Store(path)
    try:
        store.set("position", {"id": "owned-trade"})
        assert recovery_needed(path)
        store.set("position", None)
        store.prepare("unknown", "POST", "/orders", {"client_order_id": "owned-order"})
        assert recovery_needed(path)
        store.resolve("unknown", {}, "rejected")
        assert not recovery_needed(path)
    finally:
        store.close()


def test_live_engine_enforces_caps_and_journals_before_entry(tmp_path):
    import asyncio
    from decimal import Decimal as D

    from strategies.confluence.live import backend, live_types

    Engine, _, Market, _, Risk, _, _ = backend()
    Store, _ = live_types(Config())
    store = Store(tmp_path / "live.sqlite")
    store.bind()

    class Broker:
        async def entry(self, t):
            assert store.get("position")["id"] == t["id"]

    engine = Engine.Engine(store, Broker(), Market.Book(), Risk.Product())

    def plan(risk):
        return Risk.SizedTrade(
            "buy",
            D(85000),
            D(84900),
            D(86500),
            1,
            D(risk),
            D("1.3"),
            D("3.4"),
            D(".1"),
            25,
            "confluence",
        )

    try:
        assert not asyncio.run(engine.submit(plan("1.1"), "1"))
        assert store.get("position") is None
        assert asyncio.run(engine.submit(plan(".3"), "1"))
        assert not asyncio.run(engine.submit(plan(".3"), "2"))
    finally:
        store.close()


def test_live_preflight_verifies_25x_and_never_changes_account(tmp_path):
    import asyncio

    from strategies.confluence.live import backend, live_types

    _, _, Market, _, Risk, _, _ = backend()
    Store, Broker = live_types(Config())
    store = Store(tmp_path / "live.sqlite")

    class Rest:
        leverage = "25"

        async def get(self, path, params=None, auth=True):
            return {
                "/users/trading_preferences": {"user_id": 1, "default_auto_topup": False},
                "/sub_accounts": [{"id": 1, "margin_mode": "isolated"}],
                "/positions": {"size": 0},
                "/products/27/orders/leverage": {"leverage": self.leverage},
                "/wallet/balances": [{"asset_symbol": "USD", "available_balance": "16"}],
            }[path]

        async def pages(self, *a):
            return []

    rest = Rest()
    broker = Broker(rest, Risk.Product(), Market.Book(), store)
    try:
        assert asyncio.run(broker.preflight()) == 16
        rest.leverage = "200"
        with pytest.raises(RuntimeError, match="leverage_25"):
            asyncio.run(broker.preflight())
    finally:
        store.close()


def test_auto_live_missing_connection_monitors_without_starting_paper(
    tmp_path, monkeypatch, capsys
):
    class Host:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def mode(self):
            return "live"

    from strategies.confluence import observer

    def monitor(*args):
        args[-1]({"status": "monitoring", "execution_enabled": False})
        return 0

    monkeypatch.setattr(observer, "run", monitor)
    monkeypatch.setattr(cli, "Host", Host)

    def forbidden(*a, **k):
        raise AssertionError("Live selection must never start paper")

    monkeypatch.setattr(cli, "run_paper", forbidden)
    assert (
        cli.main(
            [
                "--mode",
                "auto",
                "--db",
                str(tmp_path / "paper.sqlite"),
                "--execution-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert "monitoring" in capsys.readouterr().out
    assert not (tmp_path / "paper.sqlite").exists()


def test_auto_mode_recovers_live_before_starting_paper(tmp_path, monkeypatch):
    from strategies.confluence import live

    class Host:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def mode(self):
            return "paper"

    monkeypatch.setattr(cli, "Host", Host)
    monkeypatch.setattr(live, "recovery_needed", lambda path: True)

    async def recover(*args):
        return 2

    monkeypatch.setattr(live, "run", recover)

    def forbidden(*a, **k):
        raise AssertionError("Cannot ignore real exposure")

    monkeypatch.setattr(cli, "run_paper", forbidden)
    assert cli.main(["--mode", "auto", "--db", str(tmp_path / "paper.sqlite")]) == 2


def test_paper_mode_change_cancels_pending_without_creating_real_order(tmp_path, monkeypatch):
    from test_confluence_paper import NOW, quote, signal

    from strategies.confluence.paper import Ledger

    cfg = Config()
    path = tmp_path / "paper.sqlite"
    with Ledger(path) as ledger:
        p = PaperBook.fresh(20, NOW, cfg)
        p.step(quote(), signal(), NOW)
        ledger.save(p)

    class Feed:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def market(self):
            return quote(time.time())

    class Host:
        def mode(self):
            return "live"

    monkeypatch.setattr(cli, "DeltaPublic", Feed)
    args = cli.parser().parse_args(["--db", str(path), "--iterations", "1"])
    assert cli.run_paper(args, cfg, Host()) == 90
    with Ledger(path, readonly=True) as ledger:
        state = ledger.report()["state"]
    assert state["pending"] is None and state["position"] is None
    assert state["cash"] == 20 and state["stop_reason"] == "mode_change"
