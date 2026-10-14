from types import SimpleNamespace

import httpx
import pytest

from services import kotak_saved_login as module

AUTH = (
    "fixture-trade-token:::fixture-sid:::https://cis.kotaksecurities.com:::fixture-api-token:::E43"
)


@pytest.mark.parametrize(
    "http_status,body,expected",
    [
        (200, {"stat": "Ok", "Net": "1000"}, "valid"),
        (200, {"stat": "Not_Ok", "emsg": "Session expired"}, "expired"),
        (401, {"message": "Unauthorized"}, "expired"),
        (403, {"message": "IP address not allowed"}, "unavailable"),
        (424, {"message": "Dependency failure"}, "unavailable"),
        (503, {"message": "Unavailable"}, "unavailable"),
        (200, {}, "unavailable"),
    ],
)
def test_only_definite_broker_expiry_requests_a_new_login(monkeypatch, http_status, body, expected):
    def post(url, **kwargs):
        assert url == "https://cis.kotaksecurities.com/quick/user/limits"
        assert kwargs["follow_redirects"] is False
        return SimpleNamespace(status_code=http_status, json=lambda: body)

    monkeypatch.setattr("utils.httpx_client.get_httpx_client", lambda: SimpleNamespace(post=post))
    assert module.verify_saved_kotak_auth(AUTH) == expected


def test_transient_probe_timeout_does_not_become_expiry(monkeypatch):
    def post(*a, **k):
        raise httpx.ReadTimeout("fixture timeout")

    monkeypatch.setattr("utils.httpx_client.get_httpx_client", lambda: SimpleNamespace(post=post))
    assert module.verify_saved_kotak_auth(AUTH) == "unavailable"


def test_probe_never_sends_credentials_to_a_foreign_endpoint(monkeypatch):
    monkeypatch.setattr(
        "utils.httpx_client.get_httpx_client",
        lambda: pytest.fail("Unsafe endpoint reached transport"),
    )
    assert (
        module.verify_saved_kotak_auth(AUTH.replace("cis.kotaksecurities.com", "attacker.example"))
        == "expired"
    )
