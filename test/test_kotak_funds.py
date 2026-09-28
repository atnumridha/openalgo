"""Kotak cash includes today's transfers without folding in pledged collateral."""

import httpx
import pytest

from broker.kotak.api import funds


@pytest.fixture
def fetch_funds(monkeypatch):
    def fetch(payload):
        def respond(request):
            assert request.url.path == "/quick/user/limits"
            return httpx.Response(200, json=payload)

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(funds, "get_httpx_client", lambda: client)
            return funds.get_margin_data("token:::sid:::https://broker.invalid:::access")

    return fetch


def limits(**overrides):
    payload = {
        "stat": "Ok",
        "CollateralValue": "8345.16",
        "Collateral": "0",
        "RmsPayInAmt": "1654.84",
        "RmsPayOutAmt": "0",
        "Net": "10000",
        "MarginUsed": "0",
        "UnrealizedMtomPrsnt": "0",
        "RealizedMtomPrsnt": "0",
    }
    return payload | overrides


def test_same_day_deposit_is_included_in_cash(fetch_funds):
    # Sanitized values from the reported discrepancy: opening 8345.16,
    # deposit 1654.84 and Kotak net 10000, with no collateral or used margin.
    assert fetch_funds(limits()) == {
        "availablecash": "10000.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }


@pytest.mark.parametrize(
    "opening,pay_in,pay_out,expected",
    [
        ("8345.16", "1654.84", "1000", "9000.00"),
        ("10000", "0", "0", "10000.00"),
        ("-100", "200", "0", "100.00"),
        ("100", "0", "200", "-100.00"),
        ("0.1", "0.2", "0", "0.30"),
    ],
)
def test_cash_transfers_are_applied_once(fetch_funds, opening, pay_in, pay_out, expected):
    result = fetch_funds(limits(CollateralValue=opening, RmsPayInAmt=pay_in, RmsPayOutAmt=pay_out))
    assert result["availablecash"] == expected


def test_collateral_margin_and_mtm_stay_separate_from_cash(fetch_funds):
    result = fetch_funds(
        limits(
            CollateralValue="179542.80",
            RmsPayInAmt="1500",
            RmsPayOutAmt="250",
            Collateral="222565.50",
            MarginUsed="250",
            Net="403108.30",
            UnrealizedMtomPrsnt="-25",
            RealizedMtomPrsnt="100",
        )
    )
    assert result == {
        "availablecash": "180792.80",
        "collateral": "222565.50",
        "utiliseddebits": "250.00",
        "m2munrealized": "-25.00",
        "m2mrealized": "100.00",
    }


def test_missing_transfer_fields_preserve_cash_balance(fetch_funds):
    payload = limits(CollateralValue="10000")
    del payload["RmsPayInAmt"], payload["RmsPayOutAmt"]
    assert fetch_funds(payload)["availablecash"] == "10000.00"


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "not-a-number", None])
def test_invalid_transfer_does_not_publish_a_cash_balance(fetch_funds, invalid):
    assert fetch_funds(limits(RmsPayInAmt=invalid)) == {}
