"""ML worker: scheduling, the retrain queue and the smart-exit hand-off."""

from __future__ import annotations

import threading
import time

import pytest

# Imported here, not lazily inside a test: the repository root has an
# __init__.py, so a first import of openalgo.ta from inside a test can resolve
# "openalgo" to this checkout instead of the SDK.
from ml_signals import features  # noqa: F401
from ml_signals import worker, worker_store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_store, "WORKER_DIR", tmp_path / "worker")
    monkeypatch.setattr(worker_store, "LIVE_DIR", tmp_path / "worker" / "live")
    monkeypatch.setattr(worker_store, "STATUS_FILE", tmp_path / "worker" / "status.json")


def _worker(monkeypatch, *, versions=None, settings=None):
    from database import ml_settings_db
    from ml_signals import train

    w = worker.MlWorker()
    values = {
        "symbols": ["BTCUSD", "ETHUSD"],
        "retrain_enabled": True,
        "retrain_hour_ist": 3,
        "retrain_minute_ist": 30,
        "smart_exit_enabled": True,
        "smart_exit_confirmations": 2,
        "max_hold_minutes": 28,
        **(settings or {}),
    }
    monkeypatch.setattr(ml_settings_db, "get_settings", lambda: dict(values))
    known = versions or {}
    monkeypatch.setattr(train, "current_version", lambda symbol=None: known.get(symbol))
    return w


def test_a_symbol_with_no_model_is_queued_at_once(monkeypatch):
    w = _worker(monkeypatch, versions={"BTCUSD": "v1"})
    w._refresh_settings()
    assert w._train_queue == ["ETHUSD"]


def test_the_nightly_slot_is_the_next_one_in_ist(monkeypatch):
    w = _worker(monkeypatch, versions={"BTCUSD": "v1", "ETHUSD": "v1"})
    w._refresh_settings()
    when = w._next_train_for["BTCUSD"]
    assert time.time() < when <= time.time() + 24 * 3600
    from datetime import datetime

    import pytz

    slot = datetime.fromtimestamp(when, pytz.timezone("Asia/Kolkata"))
    assert (slot.hour, slot.minute) == (3, 30)


def test_retrains_run_one_at_a_time_off_the_loop(monkeypatch):
    w = _worker(monkeypatch, versions={"BTCUSD": "v1", "ETHUSD": "v1"})
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_retrain(symbol):
        calls.append(symbol)
        started.set()
        release.wait(2)

    monkeypatch.setattr(w, "_retrain", fake_retrain)
    w._train_queue = ["BTCUSD", "ETHUSD"]
    w._run_due_retrains()
    assert started.wait(1)
    # The loop returned while BTC trains, and ETH waits its turn.
    w._run_due_retrains()
    assert calls == ["BTCUSD"] and w._train_queue == ["ETHUSD"]
    release.set()
    w._training.join(1)
    w._run_due_retrains()
    w._training.join(1)
    assert calls == ["BTCUSD", "ETHUSD"]


def test_a_retrain_request_from_the_page_is_picked_up(monkeypatch):
    w = _worker(monkeypatch, versions={"BTCUSD": "v1", "ETHUSD": "v1"})
    monkeypatch.setattr(w, "_retrain", lambda symbol: None)
    worker_store.request_retrain(["ETHUSD", "ETHUSD"])
    w._run_due_retrains()
    assert w._training_symbol == "ETHUSD"
    assert worker_store.take_requests() == []


def test_the_smart_exit_is_sent_once(monkeypatch):
    from ml_signals import local_api

    w = _worker(monkeypatch, versions={"BTCUSD": "v1", "ETHUSD": "v1"})
    w._refresh_settings()
    sent = []
    monkeypatch.setattr(local_api, "send_exit", lambda trade, reason, detail: sent.append(reason) or True)
    trade = {
        "key": "7:1",
        "symbol": "BTCUSD",
        "interval": "5m",
        "side": "LONG",
        "entry_status": "complete",
        "opened_at": time.time() - 29 * 60,
        "contracts": 10,
        "contract_value": 0.001,
        "last_price": 60_000,
        "pnl_pct": 0.0,
    }
    w._smart_exit(trade, time.time())
    w._smart_exit(trade, time.time())
    assert sent == ["hold_cap"]


def test_a_refused_exit_is_tried_again(monkeypatch):
    from ml_signals import local_api

    w = _worker(monkeypatch, versions={"BTCUSD": "v1", "ETHUSD": "v1"})
    w._refresh_settings()
    sent = []
    monkeypatch.setattr(local_api, "send_exit", lambda trade, reason, detail: sent.append(reason) and False)
    trade = {
        "key": "7:1",
        "symbol": "BTCUSD",
        "side": "LONG",
        "entry_status": "complete",
        "opened_at": time.time() - 29 * 60,
    }
    w._smart_exit(trade, time.time())
    w._smart_exit(trade, time.time())
    assert sent == ["hold_cap", "hold_cap"]


def test_trades_file_updates_do_not_lose_each_other(tmp_path):
    def add(key):
        def change(trades):
            trades[key] = {"opened_at": time.time()}
            return trades

        return change

    threads = [threading.Thread(target=worker_store.update_trades, args=(add(f"k{i}"),)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(worker_store.read_trades()) == 20
