"""A broken multiplexed broker connection must not pin chart-only requests.

The running chart repeatedly saw closed HTTP/2 stream errors while a fresh
HTTP/1.1 connection returned the same candles. Pin this transport boundary;
existing quote/history tests cover responses and bounded retries.
"""
from broker.kotak.api import data
from utils import httpx_client as shared


def test_chart_requests_do_not_use_the_order_connection_pool():
    market = data.get_httpx_client()
    orders = shared.get_httpx_client()
    assert market is not orders, 'market data must not reuse a stuck order/API pool'


def test_chart_connections_do_not_multiplex_on_the_failed_http2_session():
    market = data.get_httpx_client()
    assert market._transport._pool._http2 is False
    assert market._transport._pool._http1 is True


def test_market_requests_bound_connect_and_pool_waits(monkeypatch):
    import httpx
    import pandas as pd

    timeouts = []
    class Client:
        def get(self, url, **kwargs):
            timeouts.append(httpx.Timeout(kwargs['timeout']))
            if '/historical/' in url:
                return httpx.Response(200, json={'status': 'SUCCESS', 'data': {'candles': [[1, 100, 101, 99, 100, 10, 0]]}})
            return httpx.Response(200, json=[{'ltp': 100}])

    monkeypatch.setattr(data, 'get_httpx_client', lambda: Client())
    monkeypatch.setattr(data, '_history_pace', lambda: None)
    broker = data.BrokerData('session:::sid:::https://cis.kotaksecurities.com:::access')
    assert broker._make_quotes_request('nse_cm|Nifty 50') == [{'ltp': 100}]
    assert broker._fetch_history_chunk('nse_fo|123', '1min', pd.Timestamp('2026-11-05'), pd.Timestamp('2026-11-05')) == [[1, 100, 101, 99, 100, 10, 0]]
    assert [(t.connect, t.pool, t.read) for t in timeouts] == [(5.0, 5.0, 15.0), (5.0, 5.0, 20.0)]
