"""Durable broker stop advances, with a fake Kotak transport and isolated DB."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from database import strategy_module_db as store
from services.risk.profit_exit import profit_config
from services.strategy_module import live_protection as protection
from services.strategy_module import state
from services.strategy_module.order_dispatch import DispatchResult, OrderStatusResult


class FakeKotak:
    def __init__(self, order):
        self.order = order
        self.calls = []
        self.before_modify = None
        self.modify_result = DispatchResult(ok=True, broker_order_id="stop-1")
        self.apply_modify = True
        self.available = True

    def fetch(self, api_key, broker_order_id):
        assert api_key == "fake-key" and broker_order_id == "stop-1"
        return OrderStatusResult(
            ok=self.available, order=dict(self.order) if self.available else None
        )

    def modify(self, api_key, order, connection_id):
        self.calls.append(dict(order))
        if self.before_modify:
            self.before_modify()
        if self.apply_modify:
            self.order["trigger_price"] = float(order["trigger_price"])
        return self.modify_result


@pytest.fixture
def held(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ratchet.db'}")
    session = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(store, "engine", engine)
    monkeypatch.setattr(store, "db_session", session)
    store.Base.metadata.create_all(engine)
    strategy, error = store.create_strategy(
        "ratchet-test",
        {
            "name": "Ratchet test",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "product": "NRML",
            "legs": [{"id": 1, "segment": "options", "position": "B", "lots": 1, "sl_pts": 4}],
        },
    )
    assert error is None
    strategy["user_id"] = "ratchet-test"
    run = store.create_run(strategy["id"], "live", "kotak")
    run.broker_connection_id = "connection-1"
    session.commit()
    stop = store.record_order(
        run.id,
        1,
        "protective_stop",
        {
            "symbol": "NIFTY_CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "product": "NRML",
            "pricetype": "SL-M",
            "trigger_price": 96,
            "broker_order_id": "stop-1",
            "position_ref": "position-1",
            "status": "open",
        },
    )
    costs = {
        "brokerage_per_order": 0,
        "exchange_rate": 0,
        "sebi_rate": 0,
        "gst_rate": 0,
        "stamp_buy_rate": 0,
        "stt_sell_rate": 0,
        "slippage_bps": 0,
    }
    config = profit_config({"tick_size": 0.05}, costs)
    state.init_run_state(
        run.id,
        strategy["id"],
        [
            {
                "leg_id": 1,
                "symbol": "NIFTY_CE",
                "exchange": "NFO",
                "quantity": 75,
                "position": "B",
            }
        ],
    )
    with state.run_state(run.id) as active:
        active["legs"]["1"].update(
            position_ref="position-1",
            entry_avg=100,
            qty=75,
            status="open",
            sl_pts=4,
            effective_sl=104,
            highest_price=108,
            profit_protection=config,
            exit_order_id=stop.id,
            exit_kind="protective_stop",
            protective_stop_trigger=96,
        )
    monkeypatch.setattr(protection, "_api_key_for", lambda _: "fake-key")
    monkeypatch.setattr(protection, "_active_kotak_pin", lambda *args: True)
    client = FakeKotak(
        {
            "orderid": "stop-1",
            "symbol": "NIFTY_CE",
            "exchange": "NFO",
            "action": "SELL",
            "quantity": 75,
            "filled_quantity": 0,
            "pending_quantity": 75,
            "average_price": 0,
            "product": "NRML",
            "pricetype": "SL",
            "trigger_price": 96,
            "order_status": "open",
        }
    )
    obj = SimpleNamespace(strategy=strategy, run_id=run.id, stop_id=stop.id, client=client)
    obj.leg = lambda: state.get_run_state(obj.run_id)["legs"]["1"]
    obj.call = lambda: protection.ratchet_stop(strategy, obj.run_id, obj.leg(), client=client)
    yield obj
    state.clear_run_state(obj.run_id)
    session.remove()
    engine.dispose()


def test_advance_persists_intent_before_same_order_modify_and_verifies(held):
    from services.strategy_module import stop_modifications

    def before():
        intent = stop_modifications.get(held.stop_id)
        assert intent["status"] == "pending"
        assert intent["trigger_price"] == 104
        assert float(store.get_order(held.stop_id).trigger_price) == 96
        assert held.leg()["exit_order_id"] == held.stop_id

    held.client.before_modify = before
    result = held.call()
    assert result.status == "verified"
    assert result.trigger_price == 104
    assert float(store.get_order(held.stop_id).trigger_price) == 104
    assert held.leg()["protective_stop_trigger"] == 104
    assert held.client.calls[0]["orderid"] == "stop-1"
    assert int(held.client.calls[0]["quantity"]) == 75
    assert len(store.list_orders(held.run_id)) == 1


@pytest.mark.parametrize("target", [95, 96])
def test_stop_never_widens_or_resends_same_trigger(held, target):
    with state.run_state(held.run_id) as active:
        active["legs"]["1"]["effective_sl"] = target
    assert held.call().status == "noop"
    assert held.client.calls == []


def test_timeout_reconciles_exact_target_without_resubmission(held):
    held.client.modify_result = DispatchResult(ok=False, unknown=True, error="timeout")
    held.client.apply_modify = False
    assert held.call().status == "pending"
    assert float(store.get_order(held.stop_id).trigger_price) == 96
    assert held.call().status == "pending"
    assert len(held.client.calls) == 1
    held.client.order["trigger_price"] = 104
    assert held.call().status == "verified"
    assert len(held.client.calls) == 1


def test_acknowledgement_alone_does_not_claim_verified(held):
    held.client.apply_modify = False
    assert held.call().status == "pending"
    assert float(store.get_order(held.stop_id).trigger_price) == 96
    assert held.leg()["protective_stop_trigger"] == 96


def test_duplicate_call_during_dispatch_does_not_modify_twice(held):
    nested = []
    held.client.before_modify = lambda: nested.append(held.call().status)
    assert held.call().status == "verified"
    assert nested == ["pending"]
    assert len(held.client.calls) == 1
    assert held.call().status == "noop"


def test_restart_reconciles_pending_modify_without_fresh_dispatch(held, monkeypatch):
    held.client.apply_modify = False
    assert held.call().status == "pending"
    store.db_session.remove()
    with state.run_state(held.run_id) as active:
        # A pre-modify checkpoint can lag the durable submitted intent.
        active["legs"]["1"]["effective_sl"] = 96
    held.client.order["trigger_price"] = 104
    monkeypatch.setattr(protection, "_ratchet_client", lambda: held.client)
    assert protection.verify_recovered_run(held.run_id, "fake-key") == []
    assert float(store.get_order(held.stop_id).trigger_price) == 104
    assert held.leg()["effective_sl"] == 104
    assert len(held.client.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", 100),
        ("pending_quantity", 74),
        ("filled_quantity", 1),
        ("product", "MIS"),
        ("symbol", "OTHER"),
        ("trigger_price", 95),
    ],
)
def test_preflight_mismatch_cannot_dispatch(held, field, value):
    held.client.order[field] = value
    assert held.call().status in {"pending", "failed"}
    assert held.client.calls == []
    assert float(store.get_order(held.stop_id).trigger_price) == 96


def test_partial_fill_during_modify_folds_fill_and_retains_existing_exit(held, monkeypatch):
    from services.strategy_module import order_events

    folded = []

    def fold(broker_id, fact):
        folded.append((broker_id, fact))
        store.update_order(held.stop_id, filled_qty=25, avg_fill_price=103)
        with state.run_state(held.run_id) as active:
            active["legs"]["1"]["qty"] = 50

    monkeypatch.setattr(order_events, "apply_order_snapshot", fold)

    def fill():
        held.client.order.update(filled_quantity=25, pending_quantity=50, average_price=103)

    held.client.before_modify = fill
    assert held.call().status == "pending"
    assert folded[0][0] == "stop-1"
    assert held.leg()["qty"] == 50
    assert held.leg()["exit_order_id"] == held.stop_id
    assert float(store.get_order(held.stop_id).trigger_price) == 96
    assert len(held.client.calls) == 1


def test_cancel_race_cannot_verify_or_replace_exit(held, monkeypatch):
    from services.strategy_module import order_events

    def cancel():
        held.client.order.update(order_status="cancelled")

    held.client.before_modify = cancel
    folded = []
    monkeypatch.setattr(order_events, "apply_order_snapshot", lambda *args: folded.append(args))
    assert held.call().status in {"pending", "failed"}
    assert folded and folded[0][1]["order_status"] == "cancelled"
    assert len(store.list_orders(held.run_id)) == 1


def test_failed_durable_intent_cannot_dispatch(held, monkeypatch):
    from services.strategy_module import stop_modifications

    monkeypatch.setattr(stop_modifications, "claim", lambda *args, **kwargs: False)
    assert held.call().status in {"pending", "failed"}
    assert held.client.calls == []


def test_next_earned_stop_can_advance_after_prior_verification(held):
    assert held.call().status == "verified"
    with state.run_state(held.run_id) as active:
        active["legs"]["1"]["effective_sl"] = 108
    assert held.call().status == "verified"
    assert float(store.get_order(held.stop_id).trigger_price) == 108
    assert len(held.client.calls) == 2


@pytest.mark.parametrize(
    "field,value", [("run_id", 999), ("leg_id", 9), ("symbol", "OTHER"), ("action", "BUY")]
)
def test_foreign_durable_order_owner_cannot_be_modified(held, field, value):
    row = store.get_order(held.stop_id)
    setattr(row, field, value)
    store.db_session.commit()
    assert held.call().status == "failed"
    assert held.client.calls == []


def test_uncertain_restart_retains_last_verified_stop_and_reports_issue(held, monkeypatch):
    held.client.apply_modify = False
    assert held.call().status == "pending"
    store.db_session.remove()
    monkeypatch.setattr(protection, "_ratchet_client", lambda: held.client)
    assert protection.verify_recovered_run(held.run_id, "fake-key") == ["NIFTY_CE"]
    assert float(store.get_order(held.stop_id).trigger_price) == 96
    assert len(held.client.calls) == 1


def test_two_database_workers_can_only_claim_once(held):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from services.strategy_module import stop_modifications

    stop = store.order_to_dict(store.get_order(held.stop_id))
    stop_modifications.get(held.stop_id)  # schema creation precedes workers
    barrier = Barrier(2)

    def claim():
        barrier.wait()
        return stop_modifications.claim(stop, 104)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(outcomes) == [False, True]


def test_modify_dispatch_uses_kotak_direct_and_preserves_order_id(monkeypatch):
    from broker.kotak.api import order_api
    from services.strategy_module import order_dispatch

    monkeypatch.setattr(
        order_dispatch, "resolve_live_auth", lambda _: ("fake-token", "kotak", None)
    )
    monkeypatch.setattr(protection, "_active_kotak_pin", lambda *args: True)
    calls = []

    def modify(order, token):
        calls.append((order, token))
        return {"status": "success", "orderid": "stop-1"}, 200

    monkeypatch.setattr(order_api, "modify_order", modify)
    result = order_dispatch.modify_protective_stop(
        api_key="fake-key", connection_id="connection-1", order={"orderid": "stop-1"}
    )
    assert result.ok and not result.unknown
    assert calls == [({"orderid": "stop-1"}, "fake-token")]


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"status": "error", "message": "rejected"}, 200),
        ({"status": "error", "message": "timeout"}, 500),
        ({"status": "success", "orderid": "another-id"}, 200),
    ],
)
def test_modify_dispatch_never_treats_http_success_or_changed_id_as_verified(
    monkeypatch, payload, status
):
    from broker.kotak.api import order_api
    from services.strategy_module import order_dispatch

    monkeypatch.setattr(
        order_dispatch, "resolve_live_auth", lambda _: ("fake-token", "kotak", None)
    )
    monkeypatch.setattr(protection, "_active_kotak_pin", lambda *args: True)
    monkeypatch.setattr(order_api, "modify_order", lambda *args: (payload, status))
    result = order_dispatch.modify_protective_stop(
        api_key="fake-key", connection_id="connection-1", order={"orderid": "stop-1"}
    )
    assert not result.ok and result.unknown


def test_partial_fill_uses_real_cumulative_fold_once_without_second_dispatch(held, monkeypatch):
    from services.strategy_module import engine, order_events

    applied, resized = [], []

    def apply_fill(run_id, leg_id, price, **facts):
        applied.append(facts["filled_qty"])
        with state.run_state(run_id) as active:
            active["legs"][str(leg_id)]["qty"] -= facts["filled_qty"]

    monkeypatch.setattr(engine, "apply_fill", apply_fill)
    monkeypatch.setattr(order_events, "_push_fill", lambda *args: None)
    monkeypatch.setattr(
        protection, "resize_after_partial_stop_fill", lambda *args: resized.append(args)
    )
    held.client.before_modify = lambda: held.client.order.update(
        filled_quantity=25, pending_quantity=50, average_price=103
    )
    assert held.call().status == "pending"
    assert held.call().status == "pending"
    assert applied == [25]
    assert resized == [(held.run_id, 1, "position-1", held.stop_id)]
    assert store.get_order(held.stop_id).filled_qty == 25
    assert held.leg()["qty"] == 50
    assert held.leg()["exit_order_id"] == held.stop_id
    assert len(held.client.calls) == 1


def test_pending_restart_rejects_corrupted_or_weakened_target(held, monkeypatch):
    from services.strategy_module import stop_modifications

    held.client.apply_modify = False
    assert held.call().status == "pending"
    with stop_modifications.Session(store.engine) as session:
        intent = session.get(stop_modifications.StopModification, held.stop_id)
        intent.trigger_price = 95
        session.commit()
    held.client.order["trigger_price"] = 95
    monkeypatch.setattr(protection, "_ratchet_client", lambda: held.client)
    assert protection.verify_recovered_run(held.run_id, "fake-key") == ["NIFTY_CE"]
    assert float(store.get_order(held.stop_id).trigger_price) == 96


def test_verified_restart_restores_broker_floor_when_checkpoint_lags(held, monkeypatch):
    assert held.call().status == "verified"
    with state.run_state(held.run_id) as active:
        leg = active["legs"]["1"]
        leg["effective_sl"] = 96
        leg["highest_price"] = 100
    monkeypatch.setattr(protection, "_verify_working_stop", lambda *args: held.client.order)
    assert protection.verify_recovered_run(held.run_id, "fake-key") == []
    assert held.leg()["effective_sl"] == 104
    assert held.leg()["protective_stop_trigger"] == 104
