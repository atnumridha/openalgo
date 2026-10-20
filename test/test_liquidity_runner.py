"""Hosted lifecycle regressions using temporary ledgers and no network services."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from strategies.confluence.live import backend
from strategies.liquidity import runner
from strategies.liquidity.execution import types
from strategies.liquidity.setup import Config


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    cfg = Config()
    BaseLedger, _ = types(cfg)
    events = []
    close_requests = []
    failures = {"close": 0, "shutdown": False}
    product = {
        "id": 27,
        "symbol": "BTCUSD",
        "contract_type": "perpetual_futures",
        "state": "live",
        "trading_status": "operational",
        "contract_value": ".001",
        "tick_size": ".5",
        "maker_commission_rate": ".0002",
        "taker_commission_rate": ".0005",
        "maintenance_margin": ".25",
        "maintenance_margin_scaling_factor": ".00000125",
        "initial_margin": ".5",
        "product_specs": {
            "isolated_liq_penalty_factor": ".0005",
            "rate_exchange_interval": 28800,
        },
    }

    class Ledger(BaseLedger):
        def close(self):
            events.append("ledger_closed")
            super().close()

    class Host:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            events.append("host_closed")

        def mode(self):
            return "paper"

    class Feed:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            events.append("feed_closed")

        def product(self, symbol):
            assert symbol == "BTCUSD"
            return product

        def market(self):
            return {
                "bid": 100000,
                "ask": 100000.5,
                "bids": [[100000, 100]],
                "asks": [[100000.5, 100]],
                "quote_time": time.time(),
                "trades": [],
            }

        def context(self, now):
            end = int(now // 60) * 60
            return {
                "bars": [
                    {
                        "time": end - (i + 1) * 60,
                        "open": 100000,
                        "close": 100000,
                        "high": 100010,
                        "low": 99990,
                    }
                    for i in reversed(range(20))
                ],
                "references": [],
            }

    class Broker:
        def __init__(self, *_):
            pass

        def restore(self, position):
            assert position["id"] == "owned-test-position"

    class Engine:
        def __init__(self, ledger, *_):
            self.ledger = ledger

        async def manage(self):
            events.append("manage")

        async def stop(self, reason):
            events.append("stop:" + reason)
            self.ledger.pause(reason)
            if reason == "operator_pause":
                close_requests.append(self.ledger.get("close_requested"))
                if failures["close"]:
                    failures["close"] -= 1
                    raise TimeoutError("Synthetic transient close failure")
            elif failures["shutdown"]:
                raise TimeoutError("Synthetic unresolved shutdown")
            self.ledger.set("position", None)

        async def submit(self, *_args, **_kwargs):
            pytest.fail("Lifecycle tests must never submit entries")

    def forbidden(*_args, **_kwargs):
        pytest.fail("Lifecycle tests must never access an account")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(runner, "directory", lambda _sid: tmp_path)
    monkeypatch.setattr(runner, "types", lambda _cfg: (Ledger, None))
    monkeypatch.setattr(runner, "Host", Host)
    monkeypatch.setattr(runner, "Feed", Feed)
    monkeypatch.setattr(runner, "broker_type", lambda: Broker)
    monkeypatch.setattr(runner, "Engine", Engine)
    monkeypatch.setattr(runner, "read_connected_snapshot", forbidden)
    monkeypatch.setattr(runner, "execution_credentials", forbidden)
    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    monkeypatch.setenv("OPENALGO_START_REASON", "scheduled")

    def run(action, *, daily_halt=False, iterations=2):
        ledger = BaseLedger(tmp_path / "paper.sqlite")
        try:
            ledger.set("paper_seed", {"capital": 100})
            ledger.set("position", {"id": "owned-test-position"})
            ledger.set("command", {"action": action})
            if daily_halt:
                ledger.set("daily_halt_day", backend()[-1].day(time.time()))
        finally:
            ledger.close()

        asyncio.run(runner.run("test", cfg, iterations=iterations))
        ledger = BaseLedger(tmp_path / "paper.sqlite")
        try:
            result = {
                name: ledger.get(name)
                for name in ("view", "position", "close_requested", "daily_halt_day")
            }
        finally:
            ledger.close()

        assert events[-3:] == ["feed_closed", "host_closed", "ledger_closed"]
        assert events.index("stop:operator_stop") < events.index("feed_closed")
        # The runner must also release the real local process lock.
        with backend()[-1].InstanceLock(tmp_path / "controller.lock"):
            pass
        return result

    return SimpleNamespace(run=run, events=events, failures=failures, close_requests=close_requests)


def test_rejected_daily_halt_resume_keeps_management_running(lifecycle):
    result = lifecycle.run("resume", daily_halt=True)

    assert lifecycle.events.count("manage") >= 2
    assert result["daily_halt_day"]
    assert result["view"]["status"] == "stopped"
    assert result["position"] is None


def test_transient_close_failure_retains_request_and_retries(lifecycle):
    lifecycle.failures["close"] = 1
    result = lifecycle.run("close")

    assert lifecycle.close_requests == [True, True]
    assert "manage" in lifecycle.events
    assert result["close_requested"] is False
    assert result["view"]["status"] == "stopped"
    assert result["position"] is None


def test_failed_shutdown_records_unresolved_exposure_before_releasing_resources(lifecycle):
    lifecycle.failures["shutdown"] = True
    result = lifecycle.run("pause", iterations=1)

    assert result["position"] == {"id": "owned-test-position"}
    assert result["view"]["status"] == "unresolved"
    assert result["view"]["execution_enabled"] is False
    assert result["view"]["message"] == "TimeoutError"
