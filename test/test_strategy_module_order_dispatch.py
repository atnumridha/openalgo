"""Strategy-module order dispatch.

What matters here is which pipe an order goes down, what happens when
authorisation is missing, and that a rule-driven exit closes a position rather
than adding to it.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Imported for their side effect: patch() resolves a dotted target by importing
# it, and "services.place_order_service" is only an attribute of the services
# package once the submodule has been imported somewhere.
#
# restx_api goes first deliberately. services.place_order_service imports
# restx_api.schemas, and restx_api imports options_multiorder, which imports
# place_order_service straight back - so making place_order_service the entry
# point of that cycle fails with a partially initialised module. The app never
# hits it because restx_api is always loaded first; this mirrors that order.
import restx_api  # noqa: F401
import services.cancel_order_service  # noqa: F401
import services.orderstatus_service  # noqa: F401
import services.place_order_service  # noqa: F401
import services.sandbox_service  # noqa: F401
from services.strategy_module import order_dispatch as od

TEST_CONNECTION_ID = "test-kotak-connection"


@pytest.fixture(autouse=True)
def connected_kotak_pin():
    """Model an owned Kotak connection for order-pipe tests, never a real broker."""
    with patch(
        "services.strategy_module.live_protection._connection_for_api_key",
        return_value=(TEST_CONNECTION_ID, "kotak"),
    ):
        yield

# ---------------------------------------------------------------------------
# Exit action
# ---------------------------------------------------------------------------


def test_an_exit_reverses_the_side_the_leg_actually_holds():
    assert od.exit_action("B") == "SELL"
    assert od.exit_action("S") == "BUY"
    assert od.exit_action("b") == "SELL"


def test_an_exit_refuses_to_guess_a_side():
    # PORTED DEFECT. The original derives the exit action from the leg's
    # CONFIGURED side, which defaults to "B" for every leg including short ones.
    # A rule-driven exit on a short leg therefore placed another SELL and
    # doubled the position instead of covering it. Refusing beats defaulting.
    for bad in (None, "", "LONG", "SHORT", "x"):
        with pytest.raises(ValueError):
            od.exit_action(bad)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _order():
    order = od.build_order(
        symbol="NIFTY28MAY2624000CE",
        exchange="NFO",
        action="SELL",
        quantity=75,
        product="NRML",
        strategy_name="Iron condor weekly",
    )
    order.update(_strategy_broker="kotak", _strategy_connection_id=TEST_CONNECTION_ID)
    return order


def test_a_sandbox_run_goes_to_the_sandbox_pipe():
    with patch("services.sandbox_service.sandbox_place_order") as sandbox:
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-1"}, 200)

        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order(), intent="entry")

    assert result.ok is True
    assert result.broker_order_id == "SB-1"
    assert sandbox.call_count == 1


def test_exit_intent_uses_the_execution_pipe_without_an_entry_gate():
    with patch("services.sandbox_service.sandbox_place_order") as sandbox:
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-EXIT"}, 200)

        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order(), intent="exit")

    assert result.ok is True
    assert result.broker_order_id == "SB-EXIT"


@pytest.mark.parametrize("intent", ["entry", "exit"])
def test_manual_dispatch_does_not_acquire_signal_automation_semantics(intent):
    from services.strategy_module import automation_control

    with (
        patch.object(automation_control, "require_automation_entry", create=True,
                     side_effect=AssertionError("manual orders must not consult automation")),
        patch("services.sandbox_service.sandbox_place_order", return_value=(
            True, {"status": "success", "orderid": "SB-MANUAL"}, 200,
        )),
    ):
        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order(), intent=intent)

    assert result.ok is True
    assert result.broker_order_id == "SB-MANUAL"


def test_signal_exit_dispatch_bypasses_automation_even_when_state_read_fails():
    from services.strategy_module import automation_control

    with (
        patch.object(automation_control, "require_automation_entry", create=True,
                     side_effect=AssertionError("exits must not consult automation")),
        patch("services.sandbox_service.sandbox_place_order", return_value=(
            True, {"status": "success", "orderid": "SB-EXIT"}, 200,
        )),
    ):
        result = od.dispatch_signal_order(
            strategy_id=1, user_id="owner", mode="sandbox", api_key="k",
            order=_order(), intent="exit",
        )

    assert result.ok is True
    assert result.broker_order_id == "SB-EXIT"


def test_signal_entry_dispatch_fails_closed_when_durable_read_is_unavailable():
    from database import strategy_module_db as store

    with (
        patch.object(store.engine, "connect", side_effect=RuntimeError("database offline")),
        patch("services.sandbox_service.sandbox_place_order") as sandbox,
    ):
        result = od.dispatch_signal_order(
            strategy_id=1, user_id="owner", mode="sandbox", api_key="k",
            order=_order(), intent="entry",
        )

    assert result.ok is False
    assert "unavailable" in result.error.lower()
    sandbox.assert_not_called()


def test_a_sandbox_retry_cancel_uses_the_run_pipe_not_the_global_toggle():
    with patch("services.sandbox_service.sandbox_cancel_order") as sandbox:
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-RETRY"}, 200)

        result = od.cancel_exit_order(
            mode="sandbox",
            api_key="k",
            broker_order_id="SB-RETRY",
        )

    assert result.ok is True
    assert result.broker_order_id == "SB-RETRY"
    assert sandbox.call_args.args[0] == {"orderid": "SB-RETRY"}


def test_live_entry_refuses_before_broker_write_without_verified_stop_contract():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        live.return_value = (True, {"status": "success", "orderid": "250101000123"}, 200)

        result = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="entry")

    assert result.rejected is True
    assert "protective stop" in result.error.lower()
    live.assert_not_called()


def test_bounded_buy_entry_uses_fresh_ask_and_tick_aligned_limit():
    from datetime import UTC, datetime

    from services.strategy_module import portfolio_governor

    moment = datetime(2026, 9, 25, 9, 30, tzinfo=UTC)
    quote = {"data": {"bid": 99.5, "ask": 100, "bid_qty": 100,
                      "ask_qty": 100, "timestamp": moment.isoformat()}}
    order = od.build_order(symbol="RELIANCE", exchange="NSE", action="BUY",
                           quantity=10, product="MIS", strategy_name="test")
    with (
        patch.object(portfolio_governor, "_facts_now", return_value=moment),
        patch("services.quotes_service.get_quotes", return_value=(True, quote, 200)),
        patch("database.token_db.get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)),
    ):
        bounded, error = od.bounded_live_entry_order(order, "tok", "kotak")

    assert error is None
    assert bounded["pricetype"] == "LIMIT"
    assert bounded["price"] == "100.50"


def test_bounded_entry_refuses_stale_quote_before_broker_write():
    from datetime import UTC, datetime, timedelta

    from services.strategy_module import portfolio_governor

    moment = datetime(2026, 9, 25, 9, 30, tzinfo=UTC)
    quote = {"data": {"bid": 99.5, "ask": 100, "bid_qty": 100,
                      "ask_qty": 100, "timestamp": (moment - timedelta(seconds=11)).isoformat()}}
    with (
        patch.object(portfolio_governor, "_facts_now", return_value=moment),
        patch("services.quotes_service.get_quotes", return_value=(True, quote, 200)),
        patch("database.token_db.get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)),
    ):
        bounded, error = od.bounded_live_entry_order(_order(), "tok", "kotak")

    assert bounded is None
    assert "quote" in error.lower()


def test_bounded_sell_entry_uses_bid_and_downward_tick_cap():
    from datetime import UTC, datetime

    from services.strategy_module import portfolio_governor

    moment = datetime(2026, 9, 25, 9, 30, tzinfo=UTC)
    quote = {"data": {"bid": 99.5, "ask": 100, "bid_qty": 100,
                      "ask_qty": 100, "timestamp": moment.isoformat()}}
    with (
        patch.object(portfolio_governor, "_facts_now", return_value=moment),
        patch("services.quotes_service.get_quotes", return_value=(True, quote, 200)),
        patch("database.token_db.get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)),
    ):
        bounded, error = od.bounded_live_entry_order(_order(), "tok", "kotak")

    assert error is None
    assert bounded["pricetype"] == "LIMIT"
    assert bounded["price"] == "99.05"


@pytest.mark.parametrize(
    ("action", "executable", "expected"),
    [("BUY", "100.01", "100.50"), ("SELL", "99.99", "99.50")],
)
def test_limit_cap_never_rounds_past_half_percent(action, executable, expected):
    with patch("database.token_db.get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)):
        cap = od._limit_price_from_quote("RELIANCE", "NSE", action, Decimal(executable))

    assert cap == Decimal(expected)


@pytest.mark.parametrize(
    ("action", "executable"),
    [("BUY", "100.01"), ("SELL", "99.99")],
)
def test_limit_cap_refuses_when_no_marketable_tick_fits(action, executable):
    with patch("database.token_db.get_symbol_info", return_value=SimpleNamespace(tick_size=1)):
        cap = od._limit_price_from_quote("RELIANCE", "NSE", action, Decimal(executable))

    assert cap is None


def test_live_buy_admission_uses_limit_cap_for_cash_reservation():
    from datetime import UTC, datetime

    from services.strategy_module import portfolio_governor

    moment = datetime(2026, 9, 25, 9, 30, tzinfo=UTC)
    quote = {"data": {"bid": 99.5, "ask": 100, "bid_qty": 100,
                      "ask_qty": 100, "timestamp": moment.isoformat()}}
    leg = {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 10, "position": "B"}
    with (
        patch.object(portfolio_governor, "_facts_now", return_value=moment),
        patch("services.quotes_service.get_quotes", return_value=(True, quote, 200)),
        patch("database.token_db.get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)),
    ):
        admission_price = portfolio_governor._entry_price(leg, "live", "tok", "kotak")

    assert admission_price == 100.50


def test_live_entry_rechecks_quote_and_refuses_if_cap_exceeds_reservation():
    order = od.build_order(symbol="RELIANCE", exchange="NSE", action="BUY",
                           quantity=10, product="MIS", strategy_name="test",
                           pricetype="LIMIT", price=100.50)
    order.update(_strategy_broker="kotak", _strategy_connection_id=TEST_CONNECTION_ID)
    with (
        patch.object(od, "live_entry_protection_reason", return_value=None),
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch.object(od, "bounded_live_entry_order", return_value=({**order, "price": "101.00"}, None)),
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        result = od.dispatch_order(mode="live", api_key="k", order=order, intent="entry")

    assert result.rejected is True
    assert "reserved limit" in result.error.lower()
    live.assert_not_called()


def test_a_live_exit_uses_the_broker_pipe_with_resolved_auth():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        live.return_value = (True, {"status": "success", "orderid": "250101000123"}, 200)

        result = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")

    assert result.ok is True
    assert result.broker_order_id == "250101000123"
    args = live.call_args[0]
    assert args[1] == "tok"
    assert args[2] == "kotak"


def test_a_live_retry_cancel_calls_the_resolved_broker_directly():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.cancel_order_service.import_broker_module") as import_broker,
    ):
        broker_module = import_broker.return_value
        broker_module.cancel_order.return_value = ({"status": "success"}, 200)

        result = od.cancel_exit_order(
            mode="live",
            api_key="k",
            broker_order_id="LIVE-RETRY",
        )

    assert result.ok is True
    assert result.broker_order_id == "LIVE-RETRY"
    broker_module.cancel_order.assert_called_once_with("LIVE-RETRY", "tok")


def test_a_sandbox_status_poll_uses_the_sandbox_orderstatus_pipe():
    broker_fact = {
        "orderid": "SB-WORKING",
        "order_status": "cancelled",
        "filled_quantity": 0,
    }
    with patch("services.sandbox_service.sandbox_get_order_status") as sandbox:
        sandbox.return_value = (True, {"status": "success", "data": broker_fact}, 200)

        result = od.fetch_order_status(
            mode="sandbox",
            api_key="k",
            broker_order_id="SB-WORKING",
        )

    assert result.ok is True
    assert result.order == broker_fact
    assert sandbox.call_args.args[0] == {"orderid": "SB-WORKING"}
    assert sandbox.call_args.args[1] == "k"


def test_a_live_status_poll_uses_resolved_auth_and_the_broker_orderbook():
    broker_fact = {
        "orderid": "LIVE-WORKING",
        "order_status": "complete",
        "filled_quantity": 25,
        "average_price": 101.25,
    }
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.orderbook_service.get_orderbook_with_auth") as status,
    ):
        status.return_value = (
            True,
            {"status": "success", "data": {"orders": [broker_fact], "statistics": {}}},
            200,
        )

        result = od.fetch_order_status(
            mode="live",
            api_key="k",
            broker_order_id="LIVE-WORKING",
        )

    assert result.ok is True
    assert result.order == broker_fact
    status.assert_called_once_with("tok", "kotak", None)


def test_live_status_poll_ignores_analyzer_and_requires_exact_broker_id():
    matching = {
        "orderid": "LIVE-123",
        "order_status": "complete",
        "filled_quantity": 25,
        "average_price": 101.25,
    }
    sandbox_lookalike = {"orderid": "LIVE-123", "order_status": "cancelled"}
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.orderstatus_service.get_analyze_mode", return_value=True),
        patch("services.sandbox_service.sandbox_get_order_status") as sandbox,
        patch("services.orderbook_service.get_orderbook_with_auth") as live_book,
    ):
        sandbox.return_value = (True, {"status": "success", "data": sandbox_lookalike}, 200)
        live_book.return_value = (
            True,
            {"status": "success", "data": {"orders": [
                {"orderid": "OTHER", "order_status": "complete"}, matching,
            ], "statistics": {}}},
            200,
        )
        result = od.fetch_order_status(
            mode="live", api_key="k", broker_order_id="LIVE-123"
        )

    assert result.ok is True
    assert result.order == matching
    assert sandbox.call_count == 0
    live_book.assert_called_once_with("tok", "kotak", None)

    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.orderstatus_service.get_analyze_mode", return_value=True),
        patch(
            "services.orderbook_service.get_orderbook_with_auth",
            return_value=(True, {"status": "success", "data": {"orders": [
                {"orderid": "LIVE-123-OTHER", "order_status": "complete"}
            ], "statistics": {}}}, 200),
        ),
    ):
        absent = od.fetch_order_status(
            mode="live", api_key="k", broker_order_id="LIVE-123"
        )
    assert absent.ok is False
    assert absent.order is None


def test_live_complete_status_requires_exact_tradebook_fill_evidence():
    # Kotak's mapped orderbook has the requested quantity but omits both the
    # cumulative fill quantity and average fill price.
    order = {"orderid": "LIVE-123", "order_status": "complete", "quantity": 25}
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch(
            "services.orderbook_service.get_orderbook_with_auth",
            return_value=(True, {"status": "success", "data": {"orders": [order], "statistics": {}}}, 200),
        ),
        patch("services.tradebook_service.get_tradebook_with_auth") as trades,
    ):
        trades.return_value = (
            True,
            {"status": "success", "data": [
                {"orderid": "OTHER", "quantity": 25, "average_price": 999},
                {"orderid": "LIVE-123", "quantity": 10, "average_price": 100},
                {"orderid": "LIVE-123", "quantity": 15, "average_price": 102},
            ]},
            200,
        )
        result = od.fetch_order_status(mode="live", api_key="k", broker_order_id="LIVE-123")

    assert result.ok is True
    assert result.order["filled_quantity"] == 25
    assert result.order["average_price"] == 101.2
    trades.assert_called_once_with("tok", "kotak", None)

    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch(
            "services.orderbook_service.get_orderbook_with_auth",
            return_value=(True, {"status": "success", "data": {"orders": [order], "statistics": {}}}, 200),
        ),
        patch(
            "services.tradebook_service.get_tradebook_with_auth",
            return_value=(False, {"status": "error", "message": "temporarily unavailable"}, 500),
        ),
    ):
        unavailable = od.fetch_order_status(mode="live", api_key="k", broker_order_id="LIVE-123")
    assert unavailable.ok is False

    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch(
            "services.orderbook_service.get_orderbook_with_auth",
            return_value=(True, {"status": "success", "data": {"orders": [{
                **order, "filled_quantity": 0, "average_price": 0,
            }], "statistics": {}}}, 200),
        ),
        patch(
            "services.tradebook_service.get_tradebook_with_auth",
            return_value=(False, {"status": "error", "message": "temporarily unavailable"}, 500),
        ),
    ):
        contradictory = od.fetch_order_status(
            mode="live", api_key="k", broker_order_id="LIVE-123"
        )
    assert contradictory.ok is False


@pytest.mark.parametrize(
    ("book_status", "trades"),
    [
        ("cancelled", []),
        ("rejected", [{"orderid": "OTHER", "quantity": 25, "average_price": 100}]),
        ("open", []),
        ("open", [{"orderid": "OTHER", "quantity": 25, "average_price": 100}]),
    ],
)
def test_live_status_without_fill_fields_cannot_infer_zero_from_no_exact_trades(
    book_status, trades
):
    # A cancelled/open order might have part-filled even though the tradebook
    # view is empty or has only another order's fills.
    book_order = {"orderid": "LIVE-123", "order_status": book_status, "quantity": 25}
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch(
            "services.orderbook_service.get_orderbook_with_auth",
            return_value=(True, {"status": "success", "data": {
                "orders": [book_order], "statistics": {},
            }}, 200),
        ),
        patch(
            "services.tradebook_service.get_tradebook_with_auth",
            return_value=(True, {"status": "success", "data": trades}, 200),
        ),
    ):
        result = od.fetch_order_status(mode="live", api_key="k", broker_order_id="LIVE-123")

    assert result.ok is False
    assert result.order is None


def test_account_snapshot_reads_the_actual_orderbook_envelope():
    broker_order = {"orderid": "LIVE-1", "symbol": "NIFTY28MAY2624000CE"}
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch(
            "services.orderbook_service.get_orderbook_with_auth",
            return_value=(
                True,
                {"status": "success", "data": {"orders": [broker_order], "statistics": {}}},
                200,
            ),
        ) as orders,
        patch(
            "services.positionbook_service.get_positionbook_with_auth",
            return_value=(True, {"status": "success", "data": []}, 200),
        ) as positions,
    ):
        snapshot = od.fetch_account_snapshot(mode="live", api_key="k")

    assert snapshot.orders_ok is True
    assert snapshot.positions_ok is True
    assert snapshot.orders == (broker_order,)
    assert orders.call_args.args == ("tok", "kotak", None)
    assert positions.call_args.args == ("tok", "kotak", None)


def test_an_unknown_mode_is_refused_rather_than_defaulted():
    # Defaulting an unrecognised mode to live would place a real order for a
    # run the operator believed was on paper.
    result = od.dispatch_order(mode="", api_key="k", order=_order(), intent="entry")

    assert result.ok is False
    assert "Unknown run mode" in result.error


def test_a_live_order_is_not_attempted_when_the_broker_session_is_gone():
    # Refusing and saying so leaves a recoverable situation. Attempting it
    # without auth and reporting success would not.
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=(None, None)),
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        result = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")

    assert result.ok is False
    assert "expired" in result.error or "not available" in result.error
    assert live.call_count == 0


def test_dispatch_does_not_go_through_the_semi_automatic_approval_queue():
    # place_order() routes API-key orders into Action Center when semi-auto is
    # on. A stop-loss exit that waits for a human to approve it is not a stop
    # loss, so this module calls place_order_with_auth instead.
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.place_order_service.place_order_with_auth") as live,
        patch("services.place_order_service.place_order") as queued,
    ):
        live.return_value = (True, {"status": "success", "orderid": "1"}, 200)

        od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")

    assert live.call_count == 1
    assert queued.call_count == 0


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_a_rejection_is_reported_with_its_reason_and_any_reference():
    with patch("services.sandbox_service.sandbox_place_order") as sandbox:
        sandbox.return_value = (
            False,
            {"status": "error", "message": "Insufficient margin", "orderid": "SB-9"},
            400,
        )

        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order(), intent="entry")

    assert result.ok is False
    assert result.error == "Insufficient margin"
    # A rejected order can still carry a reference, and the audit row is more
    # useful with it than without.
    assert result.broker_order_id == "SB-9"


def test_a_raising_pipe_becomes_a_failed_result_not_an_exception():
    # The engine places orders in a loop across legs. One raising placement
    # must not abort the others or unwind the run.
    with patch("services.sandbox_service.sandbox_place_order", side_effect=RuntimeError("boom")):
        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order(), intent="entry")

    assert result.ok is False
    assert result.error


def test_live_timeout_after_send_has_unknown_outcome_without_a_confirmed_order_id():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch(
            "services.place_order_service.place_order_with_auth",
            side_effect=TimeoutError("reply lost after send"),
        ),
    ):
        result = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")

    assert result.outcome == "unknown"
    assert result.rejected is False
    assert result.broker_order_id is None


def test_live_generic_server_failure_after_send_is_unknown_but_broker_rejection_is_final():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        live.return_value = (
            False,
            {"status": "error", "message": "Failed to place order due to internal error"},
            500,
        )
        uncertain = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")
        live.return_value = (False, {"status": "error", "message": "Insufficient margin"}, 400)
        rejected = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")

    assert uncertain.outcome == "unknown"
    assert uncertain.broker_order_id is None
    assert rejected.outcome == "rejected"
    assert rejected.error == "Insufficient margin"


def test_live_success_without_broker_order_id_remains_unknown_for_recovery():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch(
            "services.place_order_service.place_order_with_auth",
            return_value=(True, {"status": "success"}, 200),
        ),
    ):
        result = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")

    assert result.outcome == "unknown"
    assert result.broker_order_id is None


def test_a_pipe_answering_with_something_other_than_a_dict_does_not_crash():
    with patch("services.sandbox_service.sandbox_place_order", return_value=(True, None, 200)):
        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order(), intent="entry")

    assert result.ok is True
    assert result.broker_order_id is None


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def test_the_payload_matches_what_the_rest_of_the_order_path_sends():
    order = od.build_order(
        symbol="RELIANCE",
        exchange="NSE",
        action="buy",
        quantity=10,
        product="MIS",
        strategy_name="Test",
    )

    assert order["action"] == "BUY"
    assert order["quantity"] == "10"  # string, like every other caller
    assert order["price"] == "0"
    assert order["trigger_price"] == "0"
    assert order["strategy"] == "Test"
    assert order["pricetype"] == "MARKET"


# ---------------------------------------------------------------------------
# The analyzer toggle must not decide a run's pipe
# ---------------------------------------------------------------------------


def test_a_live_order_is_not_diverted_by_the_platform_analyzer_toggle():
    # The one control this module is built around, exercised against the real
    # place_order_with_auth rather than a mock of it. That distinction matters:
    # every other test here mocks that function, so the diversion it is meant
    # to prevent was invisible.
    #
    # place_order_with_auth consults the global toggle BEFORE it looks at the
    # broker arguments. Without force_live, an operator turning the analyzer on
    # to try something elsewhere would send a live run's exits to the sandbox,
    # which reports success, so the engine would close the leg and finalise the
    # run while the real broker position stayed open with nothing managing it.
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "kotak")),
        patch("services.place_order_service.get_analyze_mode", return_value=True),
        patch("services.sandbox_service.sandbox_place_order") as sandbox,
        patch("services.place_order_service.import_broker_module") as import_broker,
        # The symbol is not in this suite's throwaway master contract, and an
        # order that fails validation never reaches the branch under test.
        patch(
            "services.place_order_service.validate_order_data",
            return_value=(True, {}, None),
        ),
    ):
        broker_module = import_broker.return_value
        broker_module.place_order_api.return_value = (
            SimpleNamespace(status=200),
            {},
            "BROKER-1",
        )

        result = od.dispatch_order(mode="live", api_key="k", order=_order(), intent="exit")

    # The broker was called and the sandbox was not, despite the toggle.
    assert sandbox.call_count == 0, "a live run must not be diverted into the sandbox"
    assert result.ok is True, f"dispatch failed: {result}"
    assert broker_module.place_order_api.call_count == 1
    assert result.ok is True
    assert result.broker_order_id == "BROKER-1"


def test_a_sandbox_order_still_goes_to_the_sandbox_with_the_toggle_off():
    # The other direction: a sandbox run must never reach a real broker,
    # whatever the platform toggle says.
    with (
        patch("services.place_order_service.get_analyze_mode", return_value=False),
        patch("services.sandbox_service.sandbox_place_order") as sandbox,
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-1"}, 200)

        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order(), intent="entry")

    assert sandbox.call_count == 1
    assert live.call_count == 0
    assert result.broker_order_id == "SB-1"
