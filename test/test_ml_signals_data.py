"""Public-feed normalization, pagination and no-lookahead alignment tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from ml_signals import data
from ml_signals.sentiment import build_sentiment_features


def test_binance_kline_array_normalizes_taker_flow():
    raw = [
        [1700000000000, "100", "102", "99", "101", "12", 1700000059999, "1200", 34, "7", "700", "0"]
    ]
    frame = data.normalize_records("binance_futures", raw)
    assert frame.iloc[0]["time"] == 1_700_000_000
    assert frame.iloc[0]["volume"] == 12
    assert frame.iloc[0]["taker_buy_volume"] == 7


def test_deribit_array_normalizes_dvol():
    raw = [[1700000000000, 50, 53, 49, 52]]
    frame = data.normalize_records("deribit_dvol", raw)
    assert frame.iloc[0]["time"] == 1_700_000_000
    assert frame.iloc[0]["close"] == 52


def test_fear_greed_timestamp_is_seconds():
    frame = data.normalize_records(
        "fear_greed", [{"timestamp": "1700000000", "value": "60", "value_classification": "Greed"}]
    )
    assert frame.iloc[0]["time"] == 1_700_000_000
    assert frame.iloc[0]["value"] == 60


class FakeResponse:
    def __init__(self, body):
        self.status_code = 200
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        return FakeResponse(self.pages.pop(0))


def test_binance_pages_advance_time_range_and_keep_all_rows():
    spec = data.SOURCES["binance_futures"]
    t0 = 1_700_000_000
    pages = [
        [
            [
                t0 * 1000 + i * 60000,
                "1",
                "2",
                "0.5",
                "1.5",
                "10",
                t0 * 1000 + 59999 + i * 60000,
                "15",
                5,
                "6",
                "9",
                "0",
            ]
            for i in range(3)
        ],
        [
            [
                (t0 + 180 + i * 60) * 1000,
                "1",
                "2",
                "0.5",
                "1.5",
                "10",
                (t0 + 180 + i * 60) * 1000 + 59999,
                "15",
                5,
                "6",
                "9",
                "0",
            ]
            for i in range(3)
        ],
    ]
    client = FakeClient(pages)
    frame, count, error = data._paginate_source(client, spec, t0, t0 + 360, progress=None)
    assert error is None
    assert count == 2
    assert len(frame) == 6
    assert client.calls[0][1]["limit"] == 1000
    assert client.calls[0][1]["startTime"] != client.calls[0][1].get("start")
    assert client.calls[1][1]["startTime"] > client.calls[0][1]["startTime"]


def test_deribit_pages_walk_backwards_through_continuation():
    spec = data.SOURCES["deribit_dvol"]
    start, end = 1_700_000_000, 1_700_000_000 + 6 * 3600

    def rows(first_hour, count):
        return [[(start + (first_hour + i) * 3600) * 1000, 50, 51, 49, 50 + i] for i in range(count)]

    pages = [
        {"result": {"data": rows(3, 3), "continuation": (start + 3 * 3600) * 1000}},
        {"result": {"data": rows(0, 3), "continuation": None}},
    ]
    client = FakeClient(pages)
    frame, count, error = data._paginate_source(client, spec, start, end, progress=None)
    assert error is None
    assert count == 2
    assert len(frame) == 6
    assert frame["time"].min() == start
    assert client.calls[0][1]["end_timestamp"] == end * 1000
    assert client.calls[1][1]["end_timestamp"] == (start + 3 * 3600) * 1000
    assert client.calls[1][1]["start_timestamp"] == start * 1000


def _sentiment_fixture():
    bars = pd.DataFrame(
        {
            "time": [1000, 1060, 1120, 1180, 1240, 1300],
            "close": [100, 101, 102, 103, 104, 105],
        }
    )
    times = bars["time"].tolist()

    def frame(col, values):
        return pd.DataFrame({"time": times, col: values})

    sources = {
        "delta_mark": frame("close", [100.2, 101.2, 102.2, 103.2, 104.2, 105.2]),
        "delta_spot_index": frame("close", [100, 101, 102, 103, 104, 105]),
        "delta_open_interest": frame("close", [1000, 1010, 1020, 1030, 1040, 1050]),
        "delta_funding": pd.DataFrame({"time": [900, 3600], "close": [0.01, 0.03]}),
        "binance_futures": pd.DataFrame(
            {"time": times, "volume": [10] * 6, "taker_buy_volume": [7] * 6}
        ),
        "binance_premium": frame("close", [0.001] * 6),
        "bybit_oi": pd.DataFrame(
            {
                "time": [700, 1000, 1300, 1600, 1900, 2200],
                "openInterest": [100, 102, 104, 106, 108, 110],
            }
        ),
        "bybit_account_ratio": pd.DataFrame(
            {
                "time": [700, 1000, 1300, 1600, 1900, 2200],
                "buyRatio": [0.51, 0.52, 0.53, 0.54, 0.55, 0.56],
            }
        ),
        "deribit_dvol": frame("close", [50, 51, 52, 53, 54, 55]),
        "coinbase_spot": frame("close", [100.1, 101.1, 102.1, 103.1, 104.1, 105.1]),
        "fear_greed": pd.DataFrame({"time": [800, 1000, 2000], "value": [45, 60, 90]}),
    }
    return bars, sources


def test_sentiment_features_backward_align_and_composite():
    bars, sources = _sentiment_fixture()
    features = build_sentiment_features(bars, frames=sources, interval="1m")
    assert len(features) == len(bars)
    assert features["delta_mark_premium_pct"].iloc[2] > 0
    assert features["binance_taker_buy_ratio"].iloc[2] == 0.7
    # Bybit account-ratio observations are point readings with publication delay.
    assert features["bybit_long_account_ratio"].iloc[2] == 0.52
    assert features["bybit_long_account_ratio"].iloc[3] == 0.52
    assert features["bybit_long_account_ratio"].iloc[4] == 0.53
    assert features["sentiment_composite"].notna().all()
    assert features["sentiment_composite"].between(-1, 1).all()


def test_no_future_sentiment_leaks_back_to_earlier_bar():
    bars, sources = _sentiment_fixture()
    # A 5m observation at 1300 is not public until that 5m bar closes at 1600.
    bars_later = bars.copy()
    bars_later["time"] = [1000, 1060, 1120, 1180, 1240, 1300]
    sources["bybit_oi"] = pd.DataFrame({"time": [1000, 1300], "openInterest": [100, 9999]})
    features = build_sentiment_features(bars_later, frames=sources, interval="1m")
    # The source close is shifted by 5m before backward asof; no 1m bar ending
    # before 1600 is allowed to see the 1300 observation.
    assert features["bybit_open_interest"].iloc[:5].max() < 9999


def test_missing_sentiment_source_is_nan_not_zero():
    bars, sources = _sentiment_fixture()
    sources["deribit_dvol"] = pd.DataFrame(columns=["time", "close"])
    features = build_sentiment_features(bars, frames=sources, interval="1m")
    assert features["deribit_dvol"].isna().all()
    assert features["sentiment_sources_count"].min() > 0


def test_dvol_hour_is_visible_once_closed_and_not_before():
    bars, sources = _sentiment_fixture()
    sources["deribit_dvol"] = pd.DataFrame({"time": [-3600, 0], "close": [50.0, 99.0]})
    features = build_sentiment_features(bars, frames=sources, interval="1m")
    # The hour opening at 0 closes at 3600, after every bar in the fixture.
    assert (features["deribit_dvol"] == 50.0).all()
