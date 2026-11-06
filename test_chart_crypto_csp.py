import importlib.util
from pathlib import Path
from flask import Flask

spec = importlib.util.spec_from_file_location('chart_csp', Path(__file__).with_name('csp.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def make_app():
    app = Flask(__name__)
    module.apply_csp_middleware(app)
    app.add_url_rule('/trading', endpoint='chart', view_func=lambda: 'chart')
    app.add_url_rule('/dashboard', endpoint='dashboard', view_func=lambda: 'dashboard')
    return app

def test_delta_history_is_allowed_on_the_chart_only(monkeypatch):
    monkeypatch.setenv('CSP_ENABLED', 'TRUE')
    monkeypatch.setenv('CSP_CONNECT_SRC', "'self' wss: ws: https://cdn.socket.io")
    client = make_app().test_client()
    chart = client.get('/trading').headers['Content-Security-Policy']
    assert 'https://api.india.delta.exchange' in chart
    assert 'https://api.india.delta.exchange' not in client.get('/dashboard').headers['Content-Security-Policy']
    assert "default-src 'self'" in chart
    assert 'connect-src https:' not in chart

def test_explicit_closed_connection_policy_is_preserved(monkeypatch):
    monkeypatch.setenv('CSP_ENABLED', 'TRUE')
    monkeypatch.setenv('CSP_CONNECT_SRC', "'none'")
    header = make_app().test_client().get('/trading').headers['Content-Security-Policy']
    assert "connect-src 'none'" in header
    assert 'api.india.delta.exchange' not in header
