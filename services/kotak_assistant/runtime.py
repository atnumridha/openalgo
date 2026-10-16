"""One idle server monitor per process; database leases serialize account actions."""

import atexit
import threading
import time

from .broker import Gateway
from .execution import Coordinator
from .store import Store

_store = None
_gateways = {}
_lock = threading.Lock()
_stop = threading.Event()
_thread = None


def store():
    global _store
    with _lock:
        if _store is None:
            _store = Store()
        return _store


def controller(user, mode):
    candidate = Gateway(user, mode)
    with _lock:
        gateway = _gateways.setdefault(candidate.scope, candidate)
    return Coordinator(store(), gateway)


def monitor(user):
    from .monitor import BrokerMonitor

    # Reuse the live read cache without invoking Coordinator.reconcile/adopt.
    return BrokerMonitor(store(), controller(user, "live").g)


def cleanup_sessions():
    from database import (
        auth_db,
        market_calendar_db,
        qty_freeze_db,
        scalping_db,
        strategy_module_db,
        token_db_enhanced,
    )

    for module in (
        auth_db,
        token_db_enhanced,
        market_calendar_db,
        scalping_db,
        qty_freeze_db,
        strategy_module_db,
    ):
        if hasattr(module, "db_session"):
            module.db_session.remove()


def _run():
    import logging

    log = logging.getLogger(__name__)
    while not _stop.wait(1):
        try:
            # Reattach recent chart subscriptions after a server restart. This
            # monitor evaluates observations only; it never submits entries.
            from .setup_live import poll_saved

            setups_repo = None
            with _lock:
                current_store = _store
            if current_store is not None and hasattr(current_store, "chart_setup_store"):
                setups_repo = current_store.chart_setup_store
            elif current_store is not None:
                from .setup_data import SetupStore

                setups_repo = SetupStore(current_store.engine)
                current_store.chart_setup_store = setups_repo
            for _, saved in setups_repo.scopes() if setups_repo else []:
                if time.time() - saved.get("last_view", 0) > 3600:
                    continue
                try:
                    c = controller(saved["user"], saved["mode"])
                    if c.scope == saved.get("account_scope"):
                        poll_saved(c, saved["underlying"])
                except Exception as e:
                    log.warning("Kotak chart observations unavailable: %s", e)
                finally:
                    cleanup_sessions()
            for scope, data in store().all():
                if data.get("observer"):
                    if time.time() - data.get("last_attempt", 0) < 5:
                        continue
                    try:
                        observer = monitor(data["user"])
                        if observer.scope == scope:
                            observer.snapshot()
                    except Exception as e:
                        log.warning("Kotak read-only monitor unavailable: %s", e)
                    finally:
                        cleanup_sessions()
                    continue
                active = any(
                    t.get("status") not in ("closed", "rejected")
                    for t in data.get("trades", {}).values()
                )
                recent = any(
                    time.time() - t.get("created", 0) < 86400
                    for t in data.get("trades", {}).values()
                )
                if not active and (not recent or time.time() - data.get("heartbeat", 0) < 5):
                    continue
                try:
                    c = controller(data["user"], data["mode"])
                    if c.scope != scope:
                        continue  # An account change never adopts the old account's intents.
                    c.reconcile()
                except Exception as e:
                    log.warning("Kotak assistant monitor could not reconcile account: %s", e)
                finally:
                    cleanup_sessions()
        except Exception:
            log.exception("Kotak assistant monitor unavailable")


def start():
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_run, name="kotak-home-monitor", daemon=True)
        _thread.start()
    atexit.register(_stop.set)
