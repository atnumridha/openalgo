import copy
from datetime import datetime

import pytest
from sqlalchemy import create_engine

from services.kotak_assistant.analysis import IST
from services.kotak_assistant.monitor import BrokerMonitor
from services.kotak_assistant.store import Store


class ReadOnlyBroker:
    scope = "u:account:live"
    mode = "live"
    user = "u"

    def __init__(self):
        self.now = datetime(2026, 10, 15, 10, 0, tzinfo=IST).timestamp()
        self.fail = False
        self.positions = []
        self.fills = []
        self.orders = []
        self.reads = 0

    def cached(self, key, ttl, loader):
        return loader()

    def books(self, include_cash=True):
        assert include_cash is False
        self.reads += 1
        if self.fail:
            raise ValueError("Broker session unavailable")
        return copy.deepcopy(
            {
                "positions": self.positions,
                "fills": self.fills,
                "orders": self.orders,
                "time": self.now,
            }
        )

    def tracking_metadata(self, *args):
        return {"lot": 65, "tick": 0.05}

    def submit(self, *args):
        pytest.fail("Tracking must never submit an order")

    cancel = submit


def position(qty=130, **extra):
    return dict(
        symbol="NIFTY19OCT2623100CE",
        exchange="NFO",
        product="MIS",
        quantity=qty,
        average_price=100,
        ltp=110,
        pnl=1300,
        **extra,
    )


def fill(ident, side, qty, price, sec=0):
    return {
        "symbol": "NIFTY19OCT2623100CE",
        "exchange": "NFO",
        "product": "MIS",
        "action": side,
        "quantity": qty,
        "average_price": price,
        "orderid": f"order-{ident}",
        "tradeid": str(ident),
        "timestamp": f"15-Oct-2026 09:59:{sec:02}",
    }


@pytest.fixture
def monitor(tmp_path):
    broker = ReadOnlyBroker()
    store = Store(create_engine(f"sqlite:///{tmp_path}/monitor.db"))
    return BrokerMonitor(store, broker, clock=lambda: broker.now), broker, store


def test_auto_discovers_external_fills_partial_exit_and_broker_close_without_orders(monitor):
    m, g, store = monitor
    g.positions = [position()]
    g.fills = [fill(1, "BUY", 130, 100)]
    first = m.snapshot()
    assert first["positions"][0]["average_entry"] == 100
    assert first["positions"][0]["average_entry_verified"] is True
    assert first["positions"][0]["lot"] == 65
    assert first["mode"] == "live"
    g.now += 2
    g.positions = [position(65)]
    g.fills += [fill(2, "SELL", 65, 110, 10)]
    assert m.snapshot()["positions"][0]["quantity"] == 65
    g.now += 2
    g.positions = [position(0)]
    g.fills += [fill(3, "SELL", 65, 120, 20)]
    assert m.snapshot()["positions"][0]["quantity"] == 0
    restarted = BrokerMonitor(store, g, clock=lambda: g.now)
    assert len(restarted.snapshot()["days"]["2026-10-15"]["fills"]) == 3
    assert store.read(m.scope)["positions"][0]["quantity"] == 0


def test_failed_books_keep_last_known_position_and_never_infer_a_close(monitor):
    m, g, store = monitor
    g.positions = [position()]
    g.fills = [fill(1, "BUY", 130, 100)]
    first = m.snapshot()
    g.now += 30
    g.fail = True
    stale = BrokerMonitor(store, g, clock=lambda: g.now).snapshot()
    assert stale["positions"][0]["quantity"] == 130
    assert stale["book_time"] == first["book_time"]
    assert stale["error"] == "Broker session unavailable"


def test_short_positions_other_symbols_and_unverified_carry_basis_are_not_dropped(monitor):
    m, g, _ = monitor
    g.positions = [
        position(-65),
        {**position(2), "symbol": "RELIANCE", "exchange": "NSE"},
        {
            **position(65),
            "symbol": "SENSEX20OCT2680000PE",
            "exchange": "BFO",
            "average_price_basis": "carry_forward_valuation",
        },
    ]
    g.fills = [fill(1, "SELL", 65, 105)]
    result = m.snapshot()
    assert len(result["positions"]) == 3
    assert result["positions"][0]["quantity"] == -65
    assert result["positions"][0]["average_entry"] == 105
    assert result["positions"][2]["average_entry_verified"] is False


def test_repeated_fill_ids_are_deduplicated_and_a_new_cycle_has_the_current_cost_basis(monitor):
    m, g, _ = monitor
    g.positions = [position(65)]
    g.fills = [fill(1, "BUY", 65, 90), fill(2, "SELL", 65, 110, 1), fill(3, "BUY", 65, 100, 2)]
    g.fills += [g.fills[-1]]
    result = m.snapshot()
    assert result["positions"][0]["average_entry"] == 100
    assert len(result["fills"]) == 3


def test_stale_or_malformed_success_does_not_replace_persisted_data(monitor):
    m, g, _ = monitor
    g.positions = [position()]
    m.snapshot()
    original = g.books
    g.books = lambda **kw: {**original(**kw), "positions": None}
    result = m.snapshot()
    assert result["error"]
    assert result["positions"][0]["quantity"] == 130


def test_same_second_opposite_side_fills_do_not_claim_a_verified_ordering(monitor):
    m, g, _ = monitor
    g.positions = [position(65)]
    g.fills = [fill(9, "BUY", 65, 90), fill(10, "SELL", 65, 110), fill(11, "BUY", 65, 100)]
    assert m.snapshot()["positions"][0]["average_entry_verified"] is False


def test_later_empty_or_reduced_fill_report_cannot_erase_saved_fills(monitor):
    m, g, store = monitor
    g.positions = [position(65)]
    g.fills = [fill(1, "BUY", 65, 100)]
    m.snapshot()
    g.now += 2
    g.fills = []
    result = BrokerMonitor(store, g, clock=lambda: g.now).snapshot()
    assert len(result["days"]["2026-10-15"]["fills"]) == 1
    assert result["positions"][0]["average_entry_verified"] is True


@pytest.mark.parametrize("bad_id", [None, "", "  ", False])
def test_missing_raw_fill_identity_preserves_previous_snapshot(monitor, bad_id):
    m, g, _ = monitor
    g.positions = [position(65)]
    g.fills = [fill(1, "BUY", 65, 100)]
    first = m.snapshot()
    g.now += 2
    g.fills = [{**fill(2, "BUY", 65, 110), "tradeid": bad_id}]
    result = m.snapshot()
    assert result["error"]
    assert result["fills"] == first["fills"]


def test_background_observer_continues_without_a_browser(monkeypatch):
    from types import SimpleNamespace

    from services.kotak_assistant import runtime

    calls = []
    scope = "u:account:live:observer"
    data = {"scope": scope, "observer": True, "user": "u", "last_attempt": 0}
    stop = iter([False, True])
    monkeypatch.setattr(runtime, "_stop", SimpleNamespace(wait=lambda _: next(stop)))
    monkeypatch.setattr(runtime, "store", lambda: SimpleNamespace(all=lambda: [(scope, data)]))
    monkeypatch.setattr(
        runtime,
        "monitor",
        lambda user: SimpleNamespace(scope=scope, snapshot=lambda: calls.append(user)),
    )
    monkeypatch.setattr(runtime, "cleanup_sessions", lambda: None)
    runtime._run()
    assert calls == ["u"]


def test_an_empty_position_book_without_a_matching_close_is_not_reported_as_flat(monitor):
    m, g, _ = monitor
    g.positions = [position(65)]
    g.fills = [fill(1, "BUY", 65, 100)]
    m.snapshot()
    g.now += 2
    g.positions, g.fills = [], []
    result = m.snapshot()
    assert result["error"]
    assert result["positions"][0]["quantity"] == 65


def test_new_immutable_fills_survive_a_lagging_position_report_and_allow_recovery(monitor):
    m, g, _ = monitor
    buy = fill(1, "BUY", 130, 100)
    g.positions, g.fills = [position(130)], [buy]
    m.snapshot()
    g.now += 2
    g.fills.append(fill(2, "SELL", 65, 110, 10))
    lagging = m.snapshot()
    assert lagging["error"]
    assert len(lagging["fills"]) == 2
    g.now += 2
    g.positions, g.fills = [position(65)], [buy]
    recovered = m.snapshot()
    assert recovered["error"] is None
    assert recovered["positions"][0]["quantity"] == 65
    assert recovered["positions"][0]["average_entry_verified"] is True


def test_monitor_route_is_authenticated_and_independent_of_the_order_ticket_mode(monkeypatch):
    from types import SimpleNamespace

    from flask import Flask

    import blueprints.kotak_assistant as bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp.kotak_assistant_bp)
    calls = []
    monkeypatch.setattr(bp.runtime, "cleanup_sessions", lambda: None)
    monkeypatch.setattr(
        bp.runtime,
        "monitor",
        lambda user: (
            calls.append(user)
            or SimpleNamespace(snapshot=lambda: {"mode": "live", "positions": []})
        ),
    )
    monkeypatch.setattr(bp, "current_mode", lambda: "analyze")
    client = app.test_client()
    assert client.get("/kotak-assistant/api/broker-monitor").status_code == 401
    with client.session_transaction() as session:
        session.update(user="u", broker="fyers")
    assert client.get("/kotak-assistant/api/broker-monitor").status_code == 403
    with client.session_transaction() as session:
        session["broker"] = "kotak"
    response = client.get("/kotak-assistant/api/broker-monitor")
    assert response.json["data"]["mode"] == "live"
    assert calls == ["u"]


def test_daily_tracker_counts_external_entries_once_and_persists_cash_milestones(monitor):
    m, g, store = monitor
    g.fills = [fill("1", "BUY", 65, 100, 0), fill("2", "SELL", 65, 140, 1)]
    first = m.snapshot()["discipline"]
    assert first["entries"] == 1 and first["profit_reached"] and first["net"] > 2000
    g.fills = []
    m = BrokerMonitor(store, g, clock=g.clock if hasattr(g, "clock") else lambda: g.now)
    second = m.snapshot()["discipline"]
    assert second["entries"] == 1 and second["profit_reached_at"] == first["profit_reached_at"]
    g.fills = [fill("3", "BUY", 65, 100, 2), fill("4", "SELL", 65, 40, 3)]
    third = m.snapshot()["discipline"]
    assert third["entries"] == 2 and third["loss_reached"] and third["net"] < -1000


def test_observer_retains_controller_cash_milestones(monitor):
    m, g, store = monitor
    with store.lock(g.scope) as owner:
        store.save(
            g.scope,
            {
                "day": {
                    "discipline": {
                        "date": "2026-10-15",
                        "profit_reached": True,
                        "profit_reached_at": g.now - 1,
                        "profit_reached_net": 2500,
                        "entries": 0,
                        "entry_ids": [],
                    }
                }
            },
            owner,
        )
    d = m.snapshot()["discipline"]
    assert d["profit_reached"] and d["profit_reached_net"] == 2500
