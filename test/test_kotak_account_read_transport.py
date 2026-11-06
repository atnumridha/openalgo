"""Read-only account snapshots escape a failed shared broker connection."""
import httpx
import pytest
from broker.kotak.api import funds, order_api
from utils import httpx_client as shared

AUTH='fixture-session:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-access'


def test_funds_reads_have_an_independent_transport():
    assert funds.get_httpx_client() is not shared.get_httpx_client()
    assert funds.get_httpx_client()._transport._pool._http2 is False


@pytest.mark.parametrize('endpoint', ['/quick/user/orders','/quick/user/trades','/quick/user/positions','/portfolio/v1/holdings'])
def test_account_reads_succeed_when_the_order_transport_is_broken(monkeypatch, endpoint):
    class Broken:
        def request(self, *args, **kwargs):
            raise httpx.RemoteProtocolError('Server disconnected')
    class ReadOnly:
        def request(self, method, url, **kwargs):
            assert method == 'GET'
            assert url == 'https://cis.kotaksecurities.com'+endpoint
            assert kwargs['headers']['Auth']=='fixture-session'
            return httpx.Response(200,json={'stat':'Ok','data':[]})
    monkeypatch.setattr(order_api,'get_httpx_client',lambda:Broken())
    monkeypatch.setattr(order_api,'get_read_only_client',lambda:ReadOnly(), raising=False)
    assert order_api.get_api_response(endpoint, AUTH)=={'stat':'Ok','data':[]}


@pytest.mark.parametrize('method,endpoint', [('POST','/quick/order/rule/ms/place'),('PUT','/quick/order/vr/modify'),('DELETE','/quick/order/cancel'),('GET','/unclassified')])
def test_unclassified_calls_and_mutations_retain_the_original_transport(monkeypatch, method, endpoint):
    class Existing:
        def request(self, actual_method, url, **kwargs):
            assert actual_method==method
            assert kwargs['content']=='fixture-payload'
            return httpx.Response(200,json={'stat':'Ok','transport':'original'})
    class Refuse:
        def request(self,*args,**kwargs):
            pytest.fail('A mutation or unclassified request reached the read-only pool')
    monkeypatch.setattr(order_api,'get_httpx_client',lambda:Existing())
    monkeypatch.setattr(order_api,'get_read_only_client',lambda:Refuse(), raising=False)
    assert order_api.get_api_response(endpoint,AUTH,method,'fixture-payload')=={'stat':'Ok','transport':'original'}
