from dataclasses import replace
from datetime import timedelta

from services.neo_desk.overview import market_overview
from test.neo_desk.conftest import bars, when


def test_breadth_coverage():
    quotes = [
        {"ltp": 102, "prev_close": 100},
        {"ltp": 101, "prev_close": 100},
        {"ltp": 99, "prev_close": 100},
        {"ltp": 100, "prev_close": 100},
    ] + [{}] * 46
    result = market_overview({"ltp": 22500}, bars(), quotes, when())
    assert [result[k] for k in ("advances", "declines", "unchanged", "covered", "missing")] == [
        2,
        1,
        1,
        4,
        46,
    ]
    assert result["change"] is None and result["change_pct"] is None


def test_stale_quotes_and_uncertain_rsi_are_explicit():
    history = bars()
    history[-1] = replace(history[-1], repaired=True)
    result = market_overview(
        {
            "ltp": 22500,
            "prev_close": 22400,
            "timestamp": (when() - timedelta(minutes=5)).isoformat(),
        },
        history,
        [{"ltp": 101, "prev_close": 100, "timestamp": (when() - timedelta(minutes=5)).isoformat()}],
        when(),
    )
    assert result["rsi14"] is None and result["covered"] == 0 and not result["fresh"]


def test_native_bulk_quote_results_envelope_is_used(monkeypatch):
    from services.neo_desk.overview import cache, live_overview

    cache.clear()
    monkeypatch.setattr("database.auth_db.get_auth_token", lambda owner: "fixture")
    monkeypatch.setattr("database.token_db.get_symbol_info", lambda *a: True)
    monkeypatch.setattr("services.neo_desk.overview.constituents", lambda: ["A", "B", "C", "D"])
    monkeypatch.setattr(
        "services.quotes_service.get_quotes", lambda *a, **k: (True, {"data": {"ltp": 22500}}, 200)
    )
    monkeypatch.setattr(
        "services.history_service.get_history", lambda *a, **k: (True, {"data": []}, 200)
    )
    data = [
        {"ltp": 102, "prev_close": 100},
        {"ltp": 101, "prev_close": 100},
        {"ltp": 99, "prev_close": 100},
        {"ltp": 100, "prev_close": 100},
    ]
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes",
        lambda *a, **k: (
            True,
            {"results": [{"symbol": str(i), "data": q} for i, q in enumerate(data)]},
            200,
        ),
    )
    result = live_overview("overview-fixture")
    assert result["covered"] == 4 and result["advances"] == 2


def test_official_membership_request_uses_csv_provider_headers(monkeypatch):
    from types import SimpleNamespace

    from services.neo_desk import overview as module

    calls = []

    def get(url, **kw):
        calls.append(kw)
        return SimpleNamespace(
            text="Symbol\n" + "\n".join("S" + str(i) for i in range(50)),
            raise_for_status=lambda: None,
        )

    module.members_cache.clear()
    monkeypatch.setattr(module, "get_httpx_client", lambda: SimpleNamespace(get=get))
    assert len(module.constituents()) == 50
    assert calls[0]["headers"]["Referer"] == "https://www.niftyindices.com/"
    module.members_cache.clear()
