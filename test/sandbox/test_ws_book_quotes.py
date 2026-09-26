"""Sandbox market fills require the executable side of the current book."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sandbox import execution_engine as execution
from sandbox import websocket_execution_engine as ws


def test_ltp_only_tick_cannot_supply_an_executable_quote():
    assert ws._executable_quote({"ltp": 7037.5}) is None


def test_depth_levels_supply_real_bid_ask_and_available_quantity():
    quote = ws._executable_quote(
        {
            "ltp": 100,
            "depth": {
                "buy": [{"price": 99.5, "quantity": 10}],
                "sell": [{"price": 100.5, "quantity": 12}],
            },
        }
    )
    assert quote == {"ltp": 100.0, "bid": 99.5, "ask": 100.5, "bid_qty": 10, "ask_qty": 12}


def test_incomplete_book_cannot_be_filled_from_ltp():
    assert ws._executable_quote(
        {"ltp": 100, "depth": {"buy": [{"price": 99.5, "quantity": 10}], "sell": []}}
    ) is None


def test_market_order_waits_for_real_book_and_uses_ask():
    order = SimpleNamespace(orderid="book-order", order_status="open", price_type="MARKET", action="BUY")
    engine = object.__new__(execution.ExecutionEngine)
    engine._execute_order = MagicMock()
    no_trade = MagicMock()
    no_trade.filter_by.return_value.first.return_value = None
    with patch.object(execution.SandboxTrades, "query", no_trade):
        engine._process_order(order, {"ltp": 100})
        engine._execute_order.assert_not_called()
        engine._process_order(order, {"ltp": 100, "bid": 99.5, "ask": 100.5})
    engine._execute_order.assert_called_once_with(order, 100.5)


def test_triggered_stop_market_waits_for_executable_book():
    order = SimpleNamespace(
        orderid="protective-stop", order_status="trigger pending", price_type="SL-M",
        action="SELL", trigger_price=95,
    )
    engine = object.__new__(execution.ExecutionEngine)
    engine._execute_order = MagicMock()
    engine._publish_order_update_event = MagicMock()
    with patch.object(execution.db_session, "commit"):
        engine._process_trigger_pending_order(order, 94)
    engine._execute_order.assert_not_called()
    assert order.order_status == "open"


def test_limit_order_does_not_invent_a_fill_from_last_trade():
    order = SimpleNamespace(orderid="limit", order_status="open", price_type="LIMIT",
                            action="BUY", price=101)
    engine = object.__new__(execution.ExecutionEngine)
    engine._execute_order = MagicMock()
    no_trade = MagicMock()
    no_trade.filter_by.return_value.first.return_value = None
    with patch.object(execution.SandboxTrades, "query", no_trade):
        engine._process_order(order, {"ltp": 100})
        engine._execute_order.assert_not_called()
        engine._process_order(order, {"ltp": 100, "bid": 99.5, "ask": 100.5})
    engine._execute_order.assert_called_once_with(order, 100.5)


def test_triggered_stop_limit_awaits_executable_book():
    order = SimpleNamespace(orderid="stop-limit", order_status="trigger pending",
                            price_type="SL", action="SELL", trigger_price=95, price=94)
    engine = object.__new__(execution.ExecutionEngine)
    engine._execute_order = MagicMock()
    engine._publish_order_update_event = MagicMock()
    with patch.object(execution.db_session, "commit"):
        engine._process_trigger_pending_order(order, 94)
    engine._execute_order.assert_not_called()
    assert order.order_status == "open"
