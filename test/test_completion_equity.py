import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from scripts.completion_equity_study import (
    acquire_bounded,
    control_provenance,
    load_verified_prices,
    load_verified_revenues,
    parse_msft_release,
    passive_equal_weight,
    rule_asset_signals,
    trade_cost_breakdown,
)

SOURCES = Path(__file__).resolve().parents[1] / "data/research/completion-2026-09-27-sources"


def test_revenue_parser_uses_confirmed_current_quarter_total():
    payload = """<p>REDMOND, Wash. — April 23, 2015 — Results for the quarter ended March 31, 2015.</p>
      <p>MICROSOFT CORPORATION INCOME STATEMENTS (In millions)</p>
      <table><tr><td>Three Months Ended March 31,</td></tr>
      <tr><td>2014</td><td>2015</td></tr><tr><td>Revenue</td><td>$20,403</td><td>$21,729</td></tr>
      <tr><td>Cost of revenue</td><td>7,161</td></tr><tr><td>Gross margin</td><td>14,568</td></tr></table>
      <table><tr><td>Three Months Ended March 31,</td></tr>
      <tr><td>2015</td><td>2014</td></tr><tr><td>Revenue</td><td>$21,729</td><td>$20,403</td></tr>
      <tr><td>Cost of revenue</td><td>7,161</td></tr><tr><td>Gross margin</td><td>14,568</td></tr></table>""".encode()
    fact = parse_msft_release(payload)
    assert fact["revenue"] == 21_729_000_000
    assert fact["available_at"] == "2015-04-24T00:00:00-04:00"
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_msft_release(
            payload.replace(b"Three Months Ended March 31", b"Three Months Ended June 30")
        )
    with pytest.raises(ValueError, match="millions"):
        parse_msft_release(payload.replace(b"(In millions)", b"(In thousands)"))


def test_revenue_parser_rejects_unrelated_millions_and_statement_unit_conflicts():
    payload = b"""<p>REDMOND, Wash. - April 23, 2015 - Results for the quarter ended March 31, 2015.</p>
    <p>Unrelated previous schedule (In millions)</p>
    <p>INCOME STATEMENTS (In thousands)</p>
    <table><tr><td>Three Months Ended March 31,</td></tr>
    <tr><td>2015</td><td>2014</td></tr>
    <tr><td>Revenue</td><td>21,729</td><td>20,403</td></tr>
    <tr><td>Cost of revenue</td><td>7,161</td></tr>
    <tr><td>Gross margin</td><td>14,568</td></tr></table>"""
    with pytest.raises(ValueError, match="units"):
        parse_msft_release(payload)
    with pytest.raises(ValueError, match="units"):
        parse_msft_release(payload.replace(b"(In thousands)", b"(In millions) (In thousands)"))
    with pytest.raises(ValueError, match="units"):
        parse_msft_release(payload.replace(b"(In thousands)", b""))


def test_external_statement_title_combines_with_table_unit_prefix():
    payload = b"""<p>REDMOND, Wash. - April 23, 2015 - Results for the quarter ended March 31, 2015.</p>
    <p>INCOME STATEMENTS (In millions)</p>
    <table><tr><td>In thousands</td></tr>
    <tr><td>Three Months Ended March 31,</td></tr>
    <tr><td>2015</td><td>2014</td></tr>
    <tr><td>Revenue</td><td>21,729</td><td>20,403</td></tr>
    <tr><td>Cost of revenue</td><td>7,161</td></tr>
    <tr><td>Gross margin</td><td>14,568</td></tr></table>"""
    with pytest.raises(ValueError, match="units"):
        parse_msft_release(payload)
    valid = payload.replace(b"(In millions)", b"").replace(b"In thousands", b"In millions")
    assert parse_msft_release(valid)["revenue"] == 21_729_000_000


def test_revenue_parser_keeps_current_year_column_and_currency_spacer():
    payload = b"""<p>REDMOND, Wash. - April 23, 2015 - Results for the quarter ended March 31, 2015.</p>
    <p>INCOME STATEMENTS (In millions)</p>
    <table><tr><td>Three Months Ended March 31,</td></tr>
    <tr><td></td><td>2015</td><td></td><td>2014</td></tr>
    <tr><td>Revenue</td><td>$</td><td>21,729</td><td>$</td><td>20,403</td></tr>
    <tr><td>Cost of revenue</td><td>7,161</td></tr>
    <tr><td>Gross margin</td><td>14,568</td></tr></table>"""
    assert parse_msft_release(payload)["revenue"] == 21_729_000_000
    missing = payload.replace(b"<td>$</td><td>21,729</td>", b"<td>-</td><td></td>")
    with pytest.raises(ValueError, match="current"):
        parse_msft_release(missing)


def test_control_metadata_uses_actual_group_seed_and_repeat_position():
    assert {
        key: control_provenance(*key, repeat=7)["group_rng_seed"]
        for key in [
            ("sma_macd", "white_noise"),
            ("sma_macd", "bootstrap_preference"),
            ("bollinger", "white_noise"),
            ("bollinger", "bootstrap_preference"),
        ]
    } == {
        ("sma_macd", "white_noise"): 42,
        ("sma_macd", "bootstrap_preference"): 142,
        ("bollinger", "white_noise"): 1042,
        ("bollinger", "bootstrap_preference"): 1142,
    }
    assert control_provenance("bollinger", "bootstrap_preference", repeat=7)["repeat_position"] == 7


@pytest.mark.skipif(
    os.getenv("OPENALGO_EQUITY_SOURCE_SMOKE") != "1",
    reason="opt-in check of local Git-ignored vendor cache",
)
def test_all_releases_match_independent_controller_facts():
    expected = json.loads((SOURCES / "MSFT-revenue-controller-extraction.json").read_text())
    actual = load_verified_revenues(SOURCES)
    assert len(actual) == len(expected) == 48
    assert [(x["period_end"], x["revenue"]) for x in actual] == [
        (x["period_end"], x["revenue"]) for x in expected
    ]


def test_price_close_is_observable_only_at_completed_new_york_close(tmp_path):
    import datetime

    manifest = []
    for symbol in ("AAPL", "MSFT", "AMZN", "GOOGL", "JPM", "XOM", "JNJ", "PG"):
        payload = json.dumps(
            {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": symbol,
                                "currency": "USD",
                                "instrumentType": "EQUITY",
                                "exchangeTimezoneName": "America/New_York",
                            },
                            "timestamp": [
                                int(
                                    datetime.datetime(
                                        2024, 1, 2, 14, 30, tzinfo=datetime.UTC
                                    ).timestamp()
                                ),
                                int(
                                    datetime.datetime(
                                        2024, 1, 3, 14, 30, tzinfo=datetime.UTC
                                    ).timestamp()
                                ),
                            ],
                            "indicators": {"adjclose": [{"adjclose": [100, 101]}]},
                        }
                    ]
                }
            }
        ).encode()
        filename = f"price-{symbol}.json"
        (tmp_path / filename).write_bytes(payload)
        manifest.append(
            {
                "file": filename,
                "url": f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=10y",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "observations": 2,
            }
        )
    (tmp_path / "price-manifest.json").write_text(json.dumps(manifest))
    prices = load_verified_prices(tmp_path, asof="2024-01-03T20:59:00Z")
    assert prices.shape[1] == 8
    assert prices.index.tz is not None
    assert len(prices) == 1
    assert prices.index[-1] <= pd.Timestamp("2024-01-03T20:59:00Z")
    assert prices.index[-1].tz_convert("America/New_York").hour == 16
    assert prices.index.is_monotonic_increasing and prices.notna().all().all()


@pytest.mark.skipif(
    os.getenv("OPENALGO_EQUITY_SOURCE_SMOKE") != "1",
    reason="opt-in check of local Git-ignored vendor cache",
)
def test_all_cached_prices_align():
    prices = load_verified_prices(SOURCES)
    assert prices.shape == (2514, 8)
    assert prices.index[-1].date().isoformat() == "2026-09-25"


def test_bounded_acquisition_refuses_overwrite_and_rejects_wrong_hash(tmp_path):
    payload = b"verified"
    destination = tmp_path / "price-AAPL.json"
    manifest = {
        "file": "price-AAPL.json",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=10y",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    assert acquire_bounded(destination, manifest, fetch=lambda _: payload) == payload
    assert (
        acquire_bounded(destination, manifest, fetch=lambda _: pytest.fail("redownload")) == payload
    )
    destination.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash"):
        acquire_bounded(destination, manifest, fetch=lambda _: payload)


def test_asset_rules_use_only_adjusted_closes_seen_at_decision():
    idx = pd.date_range("2020-01-01", periods=80, freq="D", tz="America/New_York")
    closes = pd.DataFrame({"A": list(range(1, 81)), "B": list(range(81, 1, -1))}, index=idx)
    before = rule_asset_signals(closes, "sma_macd")
    changed = closes.copy()
    changed.iloc[-1] *= 100
    pd.testing.assert_frame_equal(
        before.iloc[:-1], rule_asset_signals(changed, "sma_macd").iloc[:-1]
    )
    assert set(before.stack().unique()) <= {-1, 0, 1}


def test_passive_benchmark_charges_buy_and_final_sell_per_side():
    idx = pd.date_range("2020-01-01", periods=2, freq="D", tz="UTC")
    closes = pd.DataFrame({"A": [100, 100], "B": [200, 200]}, index=idx)
    gross = passive_equal_weight(closes, fee_bps=0)
    net = passive_equal_weight(closes, fee_bps=100)
    assert gross["equity"][-1]["equity"] == pytest.approx(1)
    assert net["equity"][-1]["equity"] == pytest.approx((1 - 0.01) / (1 + 0.01))
    assert len(net["trades"]) == 2


def test_trade_ledger_reconciles_gross_and_two_sided_fees():
    idx = pd.date_range("2020-01-01", periods=2, freq="D", tz="UTC")
    closes = pd.DataFrame({"A": [100, 110]}, index=idx)
    trade = passive_equal_weight(closes, fee_bps=10)["trades"][0]
    detail = trade_cost_breakdown(trade, closes, fee_bps=10)
    assert detail["net_pnl"] == pytest.approx(
        detail["gross_pnl"] - detail["entry_fee"] - detail["exit_fee"]
    )
