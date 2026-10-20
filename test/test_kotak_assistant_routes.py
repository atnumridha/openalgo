from flask import Flask
import pytest

from blueprints.kotak_assistant import kotak_assistant_bp


def app():
    a = Flask(__name__)
    a.secret_key = "test"
    a.register_blueprint(kotak_assistant_bp)
    return a


def test_routes_require_session():
    c = app().test_client()
    assert c.get("/kotak-assistant/api/snapshot").status_code == 401
    assert c.post("/kotak-assistant/api/entry", json={"ticket": "x"}).status_code == 401


def test_routes_reject_other_broker():
    c = app().test_client()
    with c.session_transaction() as s:
        s["user"] = "u"
        s["broker"] = "deltaexchange"
    assert c.get("/kotak-assistant/api/snapshot").status_code == 403


@pytest.mark.parametrize('underlying,exchange,index_exchange', [
    ('NIFTY', 'NFO', 'NSE_INDEX'),
    ('BANKNIFTY', 'NFO', 'NSE_INDEX'),
    ('SENSEX', 'BFO', 'BSE_INDEX'),
])
def test_snapshot_routes_each_index_and_its_chain(monkeypatch, tmp_path, underlying, exchange, index_exchange):
    import blueprints.kotak_assistant as bp
    from sqlalchemy import create_engine
    from test_kotak_assistant_analysis import SETTINGS
    from test_kotak_assistant_execution import Fake
    from services.kotak_assistant.execution import Coordinator
    from services.kotak_assistant.store import Store

    g = Fake()
    g._cache = {}
    g.cached = lambda key, ttl, loader: loader()
    reads = []
    def quote(symbol, ex):
        reads.append((symbol, ex))
        return {'ltp': 50000, 'time': g.clock()}
    g.quote = quote
    g.history = lambda symbol, ex, interval: []
    g.session_open = lambda *a: False
    chain = {'atm_strike': 50000, 'chain': [{'strike': 50000, 'ce': None, 'pe': None}]}
    def ladder(symbol, expiry, count):
        g._cache[('chain', symbol, expiry, count)] = (g.clock(), chain)
        return chain
    g.ladder = ladder
    c = Coordinator(Store(create_engine(f'sqlite:///{tmp_path}/snapshot.db')), g, clock=g.clock)
    c.configure(SETTINGS)
    monkeypatch.setattr(bp, 'desk', lambda mode=None: c)
    monkeypatch.setattr(bp.runtime, 'cleanup_sessions', lambda: None)
    client = app().test_client()
    with client.session_transaction() as session:
        session['user'], session['broker'] = 'u', 'kotak'
    response = client.get('/kotak-assistant/api/snapshot', query_string={
        'underlying': underlying, 'expiry': '27OCT26',
    })
    assert response.status_code == 200, response.json
    result = response.json['data']
    assert result['underlying'] == underlying
    assert result['exchange'] == exchange
    assert result['index_quote']['ltp'] == 50000
    assert reads == [(underlying, index_exchange)]
    assert result['chain'] == chain


def test_preview_entry_exit_and_mode_change(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from test_kotak_assistant_analysis import SETTINGS
    from test_kotak_assistant_execution import Fake

    import blueprints.kotak_assistant as bp
    from services.kotak_assistant.execution import Coordinator
    from services.kotak_assistant.store import Store

    store = Store(create_engine(f"sqlite:///{tmp_path}/routes.db"))
    gateways = {}

    def controller(user, mode):
        key = (user, mode)
        if key not in gateways:
            g = Fake()
            g.user = user
            g.mode = mode
            g.scope = f"{user}:account:{mode}"
            g.credentials = lambda: ("fixture", "fixture")
            gateways[key] = g
        return Coordinator(store, gateways[key], clock=gateways[key].clock)

    monkeypatch.setattr(bp.runtime, "controller", controller)
    monkeypatch.setattr(bp.runtime, "start", lambda: None)
    monkeypatch.setattr(bp.runtime, "cleanup_sessions", lambda: None)
    monkeypatch.setattr(bp, "current_mode", lambda: "live")
    client = app().test_client()
    with client.session_transaction() as s:
        s["user"] = "u"
        s["broker"] = "kotak"
    assert (
        client.post(
            "/kotak-assistant/api/config", json={"mode": "live", "settings": SETTINGS}
        ).status_code
        == 200
    )
    order = {
        "symbol": "NIFTY15OCT2622600CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 65,
        "entry": 100,
        "sl": 90,
        "target": 122,
    }
    response = client.post("/kotak-assistant/api/preview", json={"mode": "live", "order": order})
    assert response.status_code == 200
    ticket = response.json["data"]["ticket"]
    entered = client.post("/kotak-assistant/api/entry", json={"mode": "live", "ticket": ticket})
    assert entered.status_code == 200
    tid = entered.json["data"]["id"]
    g = gateways[("u", "live")]
    g.fill("1", 65)
    controller("u", "live").reconcile()
    assert (
        client.post(
            "/kotak-assistant/api/exit",
            json={"mode": "live", "trade_id": tid, "request_id": "exit"},
        ).status_code
        == 200
    )
    monkeypatch.setattr(bp, "current_mode", lambda: "analyze")
    assert (
        client.post(
            "/kotak-assistant/api/entry", json={"mode": "live", "ticket": ticket}
        ).status_code
        == 409
    )
    with client.session_transaction() as s:
        s["user"] = "v"
    assert (
        client.post(
            "/kotak-assistant/api/exit",
            json={"mode": "live", "trade_id": tid, "request_id": "foreign"},
        ).status_code
        == 409
    )


def test_mutations_require_csrf_in_protected_app():
    from flask_wtf.csrf import CSRFProtect

    a = app()
    CSRFProtect(a)
    client = a.test_client()
    with client.session_transaction() as s:
        s["user"] = "u"
        s["broker"] = "kotak"
    assert (
        client.post("/kotak-assistant/api/entry", json={"mode": "live", "ticket": "x"}).status_code
        == 400
    )
