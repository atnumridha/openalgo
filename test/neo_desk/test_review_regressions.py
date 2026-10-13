from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from threading import BoundedSemaphore, Event
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from test_native_entries import OWNER, isolated
from test_ownership import owned
from test_replay import fixture, request

from database import neo_desk_db as desk
from services.neo_desk import lifecycle
from services.neo_desk import research_jobs as jobs
from services.neo_desk.replay import run_replay
from services.neo_desk.service import NeoDeskService
from services.neo_desk.types import Candle
from test.neo_desk.conftest import when
from utils.db_sessions import remove_all_scoped_sessions


class Host:
    def start(self, o):
        return True, None

    def stop(self, o):
        return True, None

    def status(self, o):
        return {"running": False}


def test_start_and_poll_refuse_unavailable_management(monkeypatch):
    import services.neo_desk.service as module

    monkeypatch.setattr(module, "management_ready", lambda: False, raising=False)
    desk.configure(OWNER, activation="Stopped")
    service = NeoDeskService(
        host=Host(),
        market=SimpleNamespace(
            snapshot=lambda *a: (_ for _ in ()).throw(AssertionError("Must not fetch an entry"))
        ),
    )
    with pytest.raises(ValueError, match="protection"):
        service.command(OWNER, "start", "review-start")
    desk.configure(OWNER, activation="Active")
    assert not service.poll(OWNER, now=when())["acted"]
    assert desk.view(OWNER)["activation"] == "Stopped"


def test_process_stop_does_not_block_independent_squareoff(monkeypatch):
    rid, orders = owned(monkeypatch)
    entered = Event()
    release = Event()
    exited = Event()

    class SlowHost(Host):
        def stop(self, o):
            entered.set()
            assert release.wait(3)
            return True, None

    service = NeoDeskService(host=SlowHost())

    def stop():
        try:
            service.command(OWNER, "stop", "review-stop")
        finally:
            remove_all_scoped_sessions()

    def squareoff():
        try:
            lifecycle.run_schedule_once(OWNER, now=when("15:29"))
            exited.set()
        finally:
            remove_all_scoped_sessions()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(stop)
        assert entered.wait(1)
        second = pool.submit(squareoff)
        try:
            assert exited.wait(0.3), "Subprocess stop blocked independent square-off"
        finally:
            release.set()
        first.result()
        second.result()
    assert len(orders) == 2


def test_exit_broker_io_releases_owner_control_lock(monkeypatch):
    rid, _ = owned(monkeypatch)
    entered = Event()
    release = Event()
    available = Event()

    def slow(*a, **kw):
        entered.set()
        assert release.wait(3)
        return {"ok": True}

    monkeypatch.setattr("services.neo_desk.lifecycle.engine.stop_run", slow)

    def exit():
        try:
            lifecycle.request_owned_exit(OWNER, str(rid), "review", "review-exit")
        finally:
            remove_all_scoped_sessions()

    def control():
        with lifecycle.owner_locks.hold(OWNER):
            available.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(exit)
        assert entered.wait(1)
        second = pool.submit(control)
        try:
            assert available.wait(0.3), "Broker exit blocked owner bookkeeping"
        finally:
            release.set()
        first.result()
        second.result()


def job_body(identity):
    return {
        "request_id": identity,
        "dataset": "fixture",
        "profile": "orb_trail",
        "symbol": "NIFTY",
        "expiry": "2026-10-13",
        "start": "2026-10-13",
        "end": "2026-10-13",
        "compound": False,
    }


def test_eventlet_replay_is_refused_before_queue_or_work(monkeypatch):
    monkeypatch.setattr("utils.runtime.worker_class", lambda: "eventlet")
    monkeypatch.setattr(
        jobs.pool,
        "submit",
        lambda *a: (_ for _ in ()).throw(AssertionError("Must not start green CPU work")),
    )
    with pytest.raises(ValueError, match="gthread"):
        jobs.submit_job("review-jobs", job_body("eventlet"))


def test_commit_failures_do_not_exhaust_queue_capacity(monkeypatch):
    from database import neo_history_db as db

    db.init_db()
    monkeypatch.setattr(jobs, "slots", BoundedSemaphore(3))
    monkeypatch.setattr("utils.runtime.worker_class", lambda: "gthread")
    real = db.db_session.commit
    count = [0]
    submitted = []

    def commit():
        count[0] += 1
        if count[0] <= 3:
            raise OperationalError("fixture", None, Exception("fixture"))
        return real()

    monkeypatch.setattr(db.db_session, "commit", commit)
    monkeypatch.setattr(jobs.pool, "submit", lambda *a: (submitted.append(a), jobs.slots.release()))
    try:
        for i in range(3):
            with pytest.raises(OperationalError):
                jobs.submit_job("review-jobs", job_body("commit-" + str(i)))
            db.db_session.rollback()
        assert jobs.submit_job("review-jobs", job_body("after-failure"))["status"] == "queued"
        assert len(submitted) == 1
    finally:
        db.db_session.rollback()
        db.db_session.query(db.NeoResearchJob).filter_by(owner="review-jobs").delete()
        real()


def test_replay_applies_entry_minute_loss_before_a_recovery():
    data = fixture()
    symbol = next(iter(data.contracts))
    minutes = {}
    stamp = when()
    while stamp <= when("15:29"):
        minutes[stamp] = Candle(
            stamp, D(50 if stamp == when() else 60), D(65), D(40 if stamp == when() else 59), D(60)
        )
        stamp += timedelta(minutes=1)
    data.options[symbol] = minutes
    trade = run_replay(data, request())["trades"][0]
    assert trade["exit_time"] == when().isoformat() and D(trade["net"]) < 0
    assert len({b["time"] for b in trade["option_bars"]}) == len(trade["option_bars"])


@pytest.mark.parametrize("missing", ["option", "index", "repaired"])
def test_missing_entry_evidence_is_not_complete_pnl(missing):
    data = fixture()
    symbol = next(iter(data.contracts))
    if missing == "option":
        data.options[symbol] = {}
    elif missing == "index":
        data.index = data.index[:-1]
    else:
        data.options[symbol][when()] = replace(data.options[symbol][when()], repaired=True)
    report = run_replay(data, request())
    assert report["net_complete"] is None and not report["coverage"]["complete"]
    assert report["coverage"]["gaps"]


def test_management_ready_requires_both_running_jobs_and_successful_boot(monkeypatch):
    from time import monotonic

    import services.neo_desk.service as module

    names = ("neo-owned-protection", "neo-independent-squareoff")
    scheduler = SimpleNamespace(
        state=1,
        get_job=lambda name: SimpleNamespace(func=lifecycle.management_pass, next_run_time=when()),
    )
    monkeypatch.setattr("services.strategy_module.scheduler.get_scheduler", lambda: scheduler)
    monkeypatch.setattr(lifecycle, "_management_initialized", True)
    monkeypatch.setattr(lifecycle, "_management_beats", {name: monotonic() for name in names})
    assert lifecycle.management_ready()
    scheduler.get_job = lambda name: (
        None
        if name == names[1]
        else SimpleNamespace(func=lifecycle.management_pass, next_run_time=when())
    )
    assert not lifecycle.management_ready()
    scheduler.get_job = lambda name: SimpleNamespace(
        func=lifecycle.management_pass, next_run_time=when()
    )
    scheduler.state = 2
    assert not lifecycle.management_ready()
    scheduler.state = 1

    def fail():
        raise RuntimeError("fixture boot failure")

    monkeypatch.setattr(lifecycle, "_register_management", fail)
    with pytest.raises(RuntimeError):
        lifecycle.start_management()
    assert not lifecycle.management_ready() and lifecycle.management_status()["message"]
    monkeypatch.setattr(module, "management_ready", lifecycle.management_ready)
    desk.configure(OWNER, activation="Stopped")
    with pytest.raises(ValueError, match="protection"):
        NeoDeskService(host=Host()).command(OWNER, "start", "failed-boot")


def test_restart_clears_only_the_host_transition_fence(monkeypatch):
    desk.configure(
        OWNER, settings={"host_command": "crashed-start", "host_action": "start", "retained": True}
    )
    lifecycle.recover_provider()
    assert desk.view(OWNER)["settings"] == {"retained": True}


def test_stop_fences_a_slow_start_without_reactivation(monkeypatch):
    entered = Event()
    release = Event()
    stopped = Event()
    fenced = Event()
    monkeypatch.setattr("services.neo_desk.service.get_analyze_mode", lambda: True)
    desk.configure(OWNER, activation="Stopped")
    real = desk.configure

    def configure(*a, **kw):
        result = real(*a, **kw)
        if kw.get("settings", {}).get("host_action") == "stop":
            fenced.set()
        return result

    monkeypatch.setattr(desk, "configure", configure)

    class SlowStart(Host):
        def start(self, o):
            entered.set()
            assert release.wait(3)
            return True, None

        def stop(self, o):
            stopped.set()
            return True, None

    service = NeoDeskService(host=SlowStart())

    def call(action):
        try:
            return service.command(OWNER, action, "fence-" + action)
        finally:
            remove_all_scoped_sessions()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(call, "start")
        assert entered.wait(1)
        second = pool.submit(call, "stop")
        try:
            assert fenced.wait(0.3), "Stop bookkeeping waited behind process startup"
        finally:
            release.set()
        first.result()
        second.result()
    assert stopped.is_set() and desk.view(OWNER)["activation"] == "Stopped"
    assert not desk.view(OWNER)["settings"].get("host_command")
