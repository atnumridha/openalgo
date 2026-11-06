"""Transient read-only history disconnects recover without unbounded retries."""
import httpx
import pandas as pd
import pytest
from broker.kotak.api import data as module

AUTH = 'fixture-trade:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-api'
CANDLES = [['2026-10-30T14:45:00+05:30', 100, 101, 99, 100, 10, 0]]


def fetch(monkeypatch, results):
    calls = []

    class Client:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            result = results[min(len(calls)-1, len(results)-1)]
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(module, 'get_httpx_client', lambda: Client())
    monkeypatch.setattr(module, '_history_pace', lambda: None)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    broker = module.BrokerData(AUTH)
    return lambda: broker._fetch_history_chunk('nse_fo|53925', '1min', pd.Timestamp('2026-10-30'), pd.Timestamp('2026-10-30')), calls


@pytest.mark.parametrize('error', [httpx.RemoteProtocolError('Server disconnected'), httpx.ReadError('Connection reset')])
def test_a_disconnected_history_get_is_retried_once(monkeypatch, error):
    run, calls = fetch(monkeypatch, [error, httpx.Response(200, json={'status':'success','data':{'candles':CANDLES}})])
    assert run() == CANDLES
    assert len(calls) == 2
    assert calls[0] == calls[1]


def test_repeated_disconnects_stop_after_one_retry(monkeypatch):
    run, calls = fetch(monkeypatch, [httpx.RemoteProtocolError('Server disconnected')])
    with pytest.raises(httpx.RemoteProtocolError):
        run()
    assert len(calls) == 2


def test_a_slow_history_timeout_does_not_start_another_long_request(monkeypatch):
    run, calls = fetch(monkeypatch, [httpx.ReadTimeout('Timed out')])
    with pytest.raises(httpx.ReadTimeout):
        run()
    assert len(calls) == 1


def test_a_rejected_history_request_is_not_retried(monkeypatch):
    run, calls = fetch(monkeypatch, [httpx.Response(401,json={'fault':{'message':'Unauthorized'}})])
    with pytest.raises(Exception, match='HTTP 401'):
        run()
    assert len(calls) == 1
