"""Live signal engine: request shapes, forming-bar split, alignment and window parity."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml_signals import data, live, predict
from ml_signals.features import build_features
from ml_signals.sentiment import build_sentiment_features


class ConstantModel:
    classes_ = np.asarray([0, 1, 2])

    def predict_proba(self, x):
        return np.tile([0.2, 0.7, 0.1], (len(x), 1))


def minute_bars(start: int, count: int) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 84_000 * np.exp(np.cumsum(rng.normal(0, 0.0004, count)))
    return pd.DataFrame(
        {
            "time": start + np.arange(count) * 60,
            "open": close,
            "high": close * 1.0005,
            "low": close * 0.9995,
            "close": close,
            "volume": rng.uniform(10, 200, count),
        }
    )


def model_entry(columns: list[str], *, decision=None) -> dict:
    from ml_signals.decision import DecisionParams, Payoff

    return {
        "version": "unit",
        "model": ConstantModel(),
        "metrics": {},
        "promoted": False,
        "columns": columns,
        "medians": {},
        "decision": decision
        or DecisionParams(
            interval="1m",
            min_edge_pct=0.05,
            long=Payoff(avg_win_pct=0.4, avg_loss_pct=0.2),
            short=Payoff(avg_win_pct=0.4, avg_loss_pct=0.2),
        ),
    }


@pytest.mark.parametrize("name", sorted(data.SOURCES))
def test_live_request_never_reaches_past_now(name):
    # Delta answers an end time after now with an empty candle stamped in the
    # future, which would read as a bar that has not opened.
    spec = data.SOURCES[name]
    params = live.live_params(spec, 1_791_000_030)
    for key in ("end", "endTime", "end_timestamp"):
        if key in params:
            value = params[key]
            if isinstance(value, str):
                value = int(pd.Timestamp(value).timestamp())
            elif key in ("endTime", "end_timestamp"):
                value = int(value) // 1000
            assert value <= 1_791_000_030


def test_merge_frames_upserts_by_time_and_drops_rows_below_floor():
    existing = pd.DataFrame({"time": [60, 120, 180], "close": [1.0, 2.0, 3.0]})
    update = pd.DataFrame({"time": [180, 240], "close": [3.5, 4.0]})
    merged = live.merge_frames(existing, update, floor=120)
    assert merged["time"].tolist() == [120, 180, 240]
    assert merged["close"].tolist() == [2.0, 3.5, 4.0]


def test_snapshot_splits_forming_and_closed_bar():
    start = 1_791_000_000 - 3 * 86400
    price = minute_bars(start, 3 * 1440 + 7)
    now = float(price["time"].iloc[-1] + 25)
    features = build_features(price, interval="1m", sentiment_frames={})
    entry = model_entry(list(features.select_dtypes(include=[np.number]).columns))
    snapshot = live.build_snapshot("1m", {"delta_btcusd": price}, now, entry)
    last = int(price["time"].iloc[-1])
    assert snapshot["forming"]["time"] == last
    assert snapshot["forming"]["closes_at"] == last + 60
    assert snapshot["closed"]["time"] == last - 60
    # 0.7 x 0.4 - 0.3 x 0.2 = 0.22% expected after fees, above the 0.05% edge.
    forming = snapshot["forming"]
    assert forming["action"] == "LONG"
    assert forming["p_long"] == pytest.approx(0.7)
    assert forming["ev_long_pct"] == pytest.approx(0.22)
    close = float(price["close"].iloc[-1])
    assert forming["stop_price"] == pytest.approx(close * (1 - forming["stop_pct"] / 100))
    assert forming["target_price"] == pytest.approx(close * (1 + forming["target_pct"] / 100))
    assert forming["stop_price"] < close < forming["target_price"]

    # Once the minute has passed with no new candle, the last one is closed.
    later = live.build_snapshot("1m", {"delta_btcusd": price}, now + 60, entry)
    assert later["forming"] is None
    assert later["closed"]["time"] == last


def test_snapshot_without_model_explains_instead_of_signalling():
    price = minute_bars(1_791_000_000 - 86400, 1440)
    now = float(price["time"].iloc[-1] + 5)
    snapshot = live.build_snapshot("5m", {"delta_btcusd": price}, now, None)
    assert snapshot["message"]
    assert "action" not in (snapshot["forming"] or {})


def test_forming_bar_sees_the_latest_reading_but_not_later_ones():
    bars = pd.DataFrame({"time": [0, 900], "close": [100.0, 101.0]})
    oi = pd.DataFrame({"time": [600, 950, 1000, 1100], "openInterest": [10.0, 20.0, 30.0, 40.0]})
    frames = {"bybit_oi": oi}
    # Without as_of the forming bar (opened 900) is aligned to its close at
    # 1800, which in live use is in the future.
    closed = build_sentiment_features(bars, frames=frames, interval="15m")
    assert closed["bybit_open_interest"].iloc[1] == 40.0
    # At 1300 only readings whose 5-minute bucket had closed by then count:
    # 950 closes at 1250, 1000 at 1300, 1100 not until 1400.
    live_view = build_sentiment_features(bars, frames=frames, interval="15m", as_of=1300)
    assert live_view["bybit_open_interest"].iloc[1] == 30.0
    # A closed bar's alignment is unchanged by as_of.
    assert live_view["bybit_open_interest"].iloc[0] == closed["bybit_open_interest"].iloc[0]


def test_predict_window_matches_full_history(monkeypatch):
    start = 1_791_000_000 - 20 * 86400
    price = minute_bars(start, 20 * 1440)
    funding = pd.DataFrame(
        {
            "time": start + np.arange(20 * 24) * 3600,
            "close": np.random.default_rng(3).normal(0.01, 0.002, 20 * 24),
        }
    )
    frames = {"delta_btcusd": price, "delta_funding": funding}

    def load_frame(name, *, start=None, end=None):
        frame = frames.get(name, pd.DataFrame(columns=["time"]))
        if start is not None and not frame.empty:
            frame = frame[frame["time"] >= start]
        return frame.reset_index(drop=True)

    full = build_features(
        predict._resample(price, 15), interval="15m", sentiment_frames={"delta_funding": funding}
    )
    entry = model_entry(list(full.select_dtypes(include=[np.number]).columns))
    entry["model"] = type(
        "Echo",
        (),
        {
            "classes_": np.asarray([0, 1, 2]),
            "predict_proba": lambda self, x: np.column_stack(
                [
                    np.zeros(len(x)),
                    np.tanh(np.abs(x[:, entry["columns"].index("sent_funding_z")])),
                    np.zeros(len(x)),
                ]
            ),
        },
    )()
    monkeypatch.setattr(data, "load_frame", load_frame)
    monkeypatch.setattr(predict, "load_active_model", lambda: entry)
    monkeypatch.setattr(live, "recent_frames", lambda: {})

    window_from = int(price["time"].iloc[-1]) - 86400
    rows = predict.predict("15m", window_from, None)
    assert rows
    expected = np.tanh(np.abs(full["sent_funding_z"].to_numpy()))
    times = predict._resample(price, 15)["time"].to_numpy() // 900 * 900
    by_time = dict(zip(times.tolist(), expected.tolist(), strict=True))
    for row in rows:
        assert row["time"] >= window_from // 900 * 900
        assert row["p_long"] == pytest.approx(by_time[row["time"]], abs=1e-9)
