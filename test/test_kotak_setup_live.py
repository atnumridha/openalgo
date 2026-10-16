from types import SimpleNamespace

from test_kotak_setup_data import bar, epoch, window

from database.engine_factory import create_db_engine
from services.kotak_assistant import setup_live
from services.kotak_assistant.store import Store


def controller(tmp_path, now):
    g = SimpleNamespace(user="u", account="a", scope="u:a:live", mode="live")
    g.cached = lambda key, ttl, loader: loader()
    g.drain_setup_events = lambda *args: {"events": [], "dropped": 0, "connection": "connection-1"}
    return SimpleNamespace(
        scope=g.scope,
        g=g,
        store=Store(create_db_engine(f"sqlite:///{tmp_path}/live.db")),
        clock=lambda: now,
    )


def test_snapshot_is_labelled_and_saved_without_account_or_order_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_live, "session_window", window)
    c = controller(tmp_path, epoch(16, 9, 18))
    result = setup_live.refresh(
        c,
        "NIFTY",
        [bar(epoch(16, 9, 15))],
        [],
        {"ltp": 100, "time": c.clock(), "source": "Broker snapshot"},
        "opening_reversal",
        "confirmed",
    )
    assert result["source"] == "Broker snapshot"
    assert "sampled" in " ".join(result["evidence"]).lower()
    state, version = setup_live.repository(c).read(setup_live.scope_for(c, "NIFTY"))
    assert version == 1 and state["underlying"] == "NIFTY"


def test_session_closed_prices_do_not_generate_signals_or_tape(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_live, "session_window", window)
    c = controller(tmp_path, epoch(16, 8, 0))
    result = setup_live.refresh(
        c, "NIFTY", [], [], {"ltp": 100, "time": c.clock()}, "opening_reversal", "confirmed"
    )
    assert result["eligible"] is False
    assert result["stage"] == "market_closed"
    assert setup_live.repository(c).events(setup_live.scope_for(c, "NIFTY"), 0, c.clock()) == []


def test_events_are_processed_at_their_observed_time_not_receipt(tmp_path, monkeypatch):
    from services.kotak_assistant import setups

    monkeypatch.setattr(setup_live, "session_window", window)
    c = controller(tmp_path, epoch(16, 9, 18) + 2)
    times = []
    original = setups.advance_opening

    def spy(state, bars, event, now, session_id, session_start):
        if event:
            times.append((event["time"], now))
        return original(state, bars, event, now, session_id, session_start)

    monkeypatch.setattr(setups, "advance_opening", spy)
    c.g.drain_setup_events = lambda *a: {
        "events": [
            {"id": "1", "time": c.clock() - 2, "price": 101, "source": "Live feed"},
            {"id": "2", "time": c.clock() - 1, "price": 99, "source": "Live feed"},
        ],
        "dropped": 0,
        "connection": "connection-1",
    }
    setup_live.refresh(
        c,
        "NIFTY",
        [],
        [],
        {"ltp": 99, "time": c.clock(), "source": "Live feed"},
        "opening_reversal",
        "confirmed",
    )
    assert times == [(c.clock() - 2, c.clock() - 2), (c.clock() - 1, c.clock() - 1)]


def test_live_index_invalidation_and_missed_quotes_do_not_resurrect(tmp_path, monkeypatch):
    from services.kotak_assistant import setups

    monkeypatch.setattr(setup_live, "session_window", window)
    c = controller(tmp_path, epoch(16, 9, 18) + 2)
    monkeypatch.setattr(
        setups,
        "trend_setup",
        lambda *a, **kw: {
            "strategy": "trend",
            "version": "1.0",
            "mode": "confirmed",
            "stage": "ready",
            "direction": "CE",
            "reason": "ready",
            "evidence": [],
            "setup_id": "frozen",
            "eligible": True,
            "invalidation": 90,
            "entry_zone": {"lower": 100, "upper": 102},
            "expires": c.clock() + 120,
            "signal_candle": {"time": c.clock() - 62, "closed_at": c.clock() - 2},
        },
    )
    one = [bar(epoch(16, 9, 17))]
    first = setup_live.refresh(
        c, "NIFTY", one, [], {"ltp": 89, "time": c.clock(), "source": "Broker snapshot"}
    )
    assert first["stage"] == "blocked" and not first["eligible"]
    second = setup_live.refresh(
        c, "NIFTY", one, [], {"ltp": 101, "time": c.clock(), "source": "Broker snapshot"}
    )
    assert second["stage"] == "blocked" and not second["eligible"]


def test_history_loading_does_not_leave_a_preload_quote_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_live, "session_window", window)
    c = controller(tmp_path, epoch(16, 9, 20))
    c.g.quote = lambda *args: {"ltp": 101, "time": c.clock(), "source": "Broker snapshot"}
    result = setup_live.refresh(
        c, "NIFTY", [], [], {"ltp": 100, "time": c.clock() - 20, "source": "Broker snapshot"}
    )
    assert result["chart_fresh"] is True


def test_quote_retry_crossing_session_close_cannot_leave_setup_live(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_live, "session_window", window)
    c = controller(tmp_path, epoch(16, 15, 29) + 59)

    def quote(*args):
        c.clock = lambda: epoch(16, 15, 30) + 1
        return {"ltp": 101, "time": c.clock(), "source": "Broker snapshot"}

    c.g.quote = quote
    result = setup_live.refresh(c, "NIFTY", [], [], {"ltp": 100, "time": c.clock() - 20})
    assert result["stage"] == "market_closed" and not result["eligible"]
