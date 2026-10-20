"""Delta adapter: trades stream, coalescing, and mark vs last-traded price."""

from __future__ import annotations

import time

import pytest

from broker.deltaexchange.streaming import delta_adapter as module
from broker.deltaexchange.streaming.delta_adapter import DeltaWebSocketAdapter, trade_ticks
from broker.deltaexchange.streaming.delta_mapping import DeltaModeMapper


def candle(ticks):
    prices = [price for _, price, _ in ticks]
    return prices[0], max(prices), min(prices), prices[-1], sum(size for _, _, size in ticks)


def test_every_mode_streams_trades():
    for mode in (1, 2, 3):
        assert "trades" in DeltaModeMapper.get_channels(mode)
    assert "ob_l2" in DeltaModeMapper.get_channels(3)


def test_trade_ticks_keep_the_candle_of_every_fill():
    base = 1_791_000_000_000
    fills = [
        (base + 300, 100.0, 1),
        (base + 100, 101.0, 2),  # out of order: Delta delivers bursts unsorted
        (base + 200, 99.0, 3),
        (base + 400, 102.5, 4),
        (base + 500, 100.5, 5),
    ]
    ticks = trade_ticks(fills)
    assert len(ticks) <= 4
    assert candle(ticks) == candle(sorted(fills))
    assert [t for t, _, _ in ticks] == sorted(t for t, _, _ in ticks)


def test_trade_ticks_split_a_burst_at_the_minute_boundary():
    edge = 1_791_000_000_000 - 1_791_000_000_000 % 60_000 + 60_000
    fills = [
        (edge - 200, 100.0, 1),
        (edge - 100, 105.0, 2),
        (edge + 50, 99.0, 4),
        (edge + 80, 98.0, 8),
    ]
    ticks = trade_ticks(fills)
    before = [t for t in ticks if t[0] < edge]
    after = [t for t in ticks if t[0] >= edge]
    assert candle(before) == candle(fills[:2])
    assert candle(after) == candle(fills[2:])


class Captured(DeltaWebSocketAdapter):
    """The adapter with ZeroMQ replaced by a list."""

    def __init__(self):
        self.published = []
        self.logger = module.get_logger("test_delta_adapter")
        self.running = True
        self._lock = module.threading.Lock()
        self.last_values = {}
        self.subscriptions = {}
        self.trade_window = 0.05
        self._trade_pending = {}
        self._trade_timer = None
        self._last_trade_at = {}

    def publish_market_data(self, topic, data):
        self.published.append((topic, data))


@pytest.fixture
def adapter():
    a = Captured()
    a.subscriptions["BTCUSDFUT_CRYPTO_3"] = {
        "symbol": "BTCUSDFUT",
        "exchange": "CRYPTO",
        "br_symbol": "BTCUSD",
        "mode": 3,
        "channels": DeltaModeMapper.get_channels(3),
    }
    return a


def ticker(mark):
    return {
        "type": "ticker",
        "sy": "BTCUSD",
        "d": [{"s": "BTCUSD", "m": str(mark), "q": ["1", "1", "1", "1", None]}],
    }


def test_trade_publishes_price_and_size_without_the_book(adapter):
    adapter._on_data(
        None, {"type": "ob_l2", "sy": "BTCUSD", "a": [["101", "5"]], "b": [["100", "7"]]}
    )
    adapter._on_data(
        None, {"type": "trades", "sy": "BTCUSD", "p": "100.5", "s": 3.0, "t": 1_791_000_000_000_000}
    )
    adapter._flush_trades()
    topic, data = adapter.published[-1]
    assert topic == "CRYPTO_BTCUSDFUT_DEPTH"
    assert data["ltp"] == 100.5
    assert data["last_trade_quantity"] == 3.0
    assert data["last_trade_time"] == 1_791_000_000_000
    assert "depth" not in data
    # The next book update carries the book and no trade quantity, so it is
    # never counted as volume a second time.
    adapter._on_data(
        None, {"type": "ob_l2", "sy": "BTCUSD", "a": [["101", "5"]], "b": [["100", "7"]]}
    )
    _, book = adapter.published[-1]
    assert "depth" in book
    assert "last_trade_quantity" not in book
    assert book["ltp"] == 100.5


def test_mark_snapshot_does_not_drag_ltp_back_from_a_fresh_trade(adapter):
    adapter._on_data(
        None, {"type": "trades", "sy": "BTCUSD", "p": "100.5", "s": 1.0, "t": 1_791_000_000_000_000}
    )
    adapter._flush_trades()
    adapter._on_data(None, ticker(99.0))
    _, data = adapter.published[-1]
    assert data["ltp"] == 100.5
    assert data["mark_price"] == 99.0


def test_mark_stands_in_for_ltp_when_no_trade_is_fresh(adapter):
    adapter._on_data(None, ticker(99.0))
    _, data = adapter.published[-1]
    assert data["ltp"] == 99.0
    adapter._last_trade_at["BTCUSD"] = time.time() - 60
    adapter._on_data(None, ticker(98.0))
    _, data = adapter.published[-1]
    assert data["ltp"] == 98.0


def test_trades_are_collected_for_the_window_then_published(adapter):
    for i, price in enumerate((100.0, 102.0, 99.0, 101.0)):
        adapter._on_data(
            None,
            {
                "type": "trades",
                "sy": "BTCUSD",
                "p": str(price),
                "s": 1.0,
                "t": 1_791_000_000_000_000 + i,
            },
        )
    assert adapter.published == []
    time.sleep(0.2)
    prices = [data["ltp"] for _, data in adapter.published]
    assert prices[-1] == 101.0
    assert max(prices) == 102.0 and min(prices) == 99.0
    assert sum(data["last_trade_quantity"] for _, data in adapter.published) == 4.0
