from types import SimpleNamespace

from flask import Flask

from blueprints.kotak_assistant import kotak_assistant_bp
from services.kotak_assistant.analysis import DEFAULTS


def client(monkeypatch):
    import blueprints.kotak_assistant as bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(kotak_assistant_bp)
    c = SimpleNamespace(state=lambda: {"settings": dict(DEFAULTS)}, clock=lambda: 1792122360)
    monkeypatch.setattr(bp, "desk", lambda *args: c)
    monkeypatch.setattr(bp.runtime, "cleanup_sessions", lambda: None)
    cl = app.test_client()
    with cl.session_transaction() as session:
        session["user"] = "u"
        session["broker"] = "kotak"
    return cl


def test_cash_planner_is_read_only_and_uses_server_cost_settings(monkeypatch):
    cl = client(monkeypatch)
    response = cl.post(
        "/kotak-assistant/api/cash-plan",
        json={
            "entry": 100,
            "quantity": 65,
            "tick": 0.05,
            "lot": 65,
            "exchange": "NFO",
            "loss_budget": 500,
            "target_multiple": 3,
        },
    )
    assert response.status_code == 200
    p = response.json["data"]
    assert p["risk"] <= 500 and p["reward"] >= 1500
    assert p["risk_policy"]["kind"] == "cash_budget"


def test_cash_planner_rejects_fractional_units(monkeypatch):
    cl = client(monkeypatch)
    response = cl.post(
        "/kotak-assistant/api/cash-plan",
        json={
            "entry": 100,
            "quantity": 65.5,
            "tick": 0.05,
            "lot": 65,
            "exchange": "NFO",
            "loss_budget": 500,
            "target_multiple": 3,
        },
    )
    assert response.status_code == 409


def test_setup_replay_is_read_only_and_cannot_create_live_checkpoint(tmp_path, monkeypatch):
    from test_kotak_setup_data import epoch, window
    from test_kotak_setup_live import controller

    import blueprints.kotak_assistant as bp
    from services.kotak_assistant import setup_live

    cl = client(monkeypatch)
    c = controller(tmp_path, epoch(16, 9, 20))
    c.g.history_range = lambda *a: []
    monkeypatch.setattr(bp, "desk", lambda *a: c)
    monkeypatch.setattr(setup_live, "session_window", window)
    r = cl.get(
        "/kotak-assistant/api/setup-replay",
        query_string={
            "until": epoch(16, 9, 19),
            "underlying": "NIFTY",
            "strategy": "opening_reversal",
        },
    )
    assert r.status_code == 200, r.json
    assert r.json["data"]["read_only"] and not r.json["data"]["eligible"]
    assert setup_live.repository(c).read(setup_live.scope_for(c, "NIFTY")) == ({}, 0)


def test_selected_opening_contract_gets_cash_plan_without_option_history(monkeypatch):
    import blueprints.kotak_assistant as bp

    cl = client(monkeypatch)
    now = 1792122360
    leg = {"symbol": "NIFTY19OCT2622600PE", "lotsize": 65, "tick_size": 0.05, "ask": 100}
    chain = {"atm_strike": 22600, "chain": [{"strike": 22600, "pe": leg}]}
    g = SimpleNamespace(
        mode="live",
        cached=lambda key, ttl, loader: loader(),
        quote=lambda *a: {"ltp": 100, "ask": 100, "bid": 99.95, "time": now},
        history=lambda *a: [],
        session_open=lambda *a: True,
        ladder=lambda *a: chain,
        metadata=lambda *a: {"lot": 65, "tick": 0.05},
        _cache={("chain", "NIFTY", "19OCT26", 8): (now, chain)},
    )
    c = SimpleNamespace(g=g, clock=lambda: now, reconcile=lambda: None)
    monkeypatch.setattr(bp, "desk", lambda *a: c)
    monkeypatch.setattr(bp, "public_state", lambda c: {"settings": dict(DEFAULTS), "trades": []})
    monkeypatch.setattr(
        bp.setup_live,
        "refresh",
        lambda *a: {
            "strategy": "opening_reversal",
            "direction": None,
            "reason": "Waiting",
            "eligible": False,
        },
    )
    response = cl.get(
        "/kotak-assistant/api/snapshot",
        query_string={
            "expiry": "19OCT26",
            "symbol": leg["symbol"],
            "strategy": "opening_reversal",
        },
    )
    assert response.status_code == 200, response.json
    selected = response.json["data"]["selected_contract"]
    assert (selected["symbol"], selected["side"], selected["strike"]) == (
        leg["symbol"],
        "PE",
        22600,
    )
    p = selected["plan"]
    assert p["fits"] and p["risk"] <= 500 and p["reward"] >= 1500
    assert p["risk_policy"]["kind"] == "cash_budget"
    assert "selected_plan" not in response.json["data"]  # never load a cash stop as an ATR stop
