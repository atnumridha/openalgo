"""Execution-only prospective receipts; never a public evidence upload API."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from utils.logging import get_logger

logger = get_logger(__name__)
_flow_origin = ContextVar("qualification_flow_origin", default=None)


@contextmanager
def flow_origin(workflow_id, execution_id, graph_hash):
    token = _flow_origin.set(
        {"workflow_id": workflow_id, "execution_id": execution_id, "workflow_hash": graph_hash}
    )
    try:
        yield
    finally:
        _flow_origin.reset(token)


def current_flow_origin():
    origin = _flow_origin.get()
    if not origin or not all(origin.values()):
        return None
    from database import flow_db

    with Session(flow_db.engine) as db:
        row = db.scalar(
            select(flow_db.FlowWorkflowExecution).where(
                flow_db.FlowWorkflowExecution.id == origin["execution_id"],
                flow_db.FlowWorkflowExecution.workflow_id == origin["workflow_id"],
                flow_db.FlowWorkflowExecution.status == "running",
            )
        )
        return dict(origin) if row is not None else None


def entry_release_reason(metadata):
    from database import trading_risk_db as ledger
    from services.research import qualification

    if not ledger.policy_enabled(metadata["owner"]):
        return None
    return qualification.live_release_reason(
        metadata["owner"],
        int(metadata["strategy_id"]),
        metadata.get("strategy_config"),
        ledger.POLICY.version,
        ledger.get_costs(metadata["owner"]),
    )


def live_session_reason(metadata, auth_token, broker, connection_id):
    """The token being dispatched must be the freshly reviewed broker session."""
    from database import trading_risk_db as ledger
    from services.research.dataset import digest
    from services.research.qualification_context import _broker_identity

    try:
        if not ledger.policy_enabled(metadata["owner"]):
            return None
        identity = _broker_identity(metadata["owner"], connection_id)
        epoch = digest({"account": identity["broker_account_hash"], "token": auth_token})
        if broker != identity["broker"] or epoch != identity["broker_epoch"]:
            return "The broker token changed after quote validation; reassess the entry"
    except Exception:
        logger.exception("Could not verify the broker token at the release boundary")
        return "The authenticated release session is unavailable; new entry is blocked"
    return None


def _capture_quote(metadata, api_key, order):
    from database import auth_db
    from services import quotes_service
    from services.research.qualification_context import _broker_identity
    from services.strategy_module import live_protection, portfolio_governor

    owner = metadata["owner"]
    if auth_db.verify_api_key(api_key) != owner:
        raise ValueError("The execution API key does not belong to this strategy owner")
    connection_id, broker = live_protection._connection_for_api_key(api_key)
    identity = _broker_identity(owner, connection_id)
    token = auth_db.get_auth_token_fresh(owner)
    ok, response, _ = quotes_service.get_quotes(
        order["symbol"], order["exchange"], auth_token=token, broker=broker
    )
    refreshed_identity = _broker_identity(owner, connection_id)
    if refreshed_identity != identity:
        raise ValueError("The authenticated broker account changed during quote capture")
    if not ok or not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise ValueError("Prospective broker quote is unavailable")
    data = response["data"]
    native = portfolio_governor._quote_timestamp(data.get("timestamp") or data.get("lstup_time"))
    if native is None:
        raise ValueError("Prospective broker quote has no native market timestamp")
    now = datetime.now(UTC)
    receipt = {
        key: float(Decimal(str(data.get(key)))) for key in ("bid", "ask", "bid_qty", "ask_qty")
    }
    quantity = int(order["quantity"])
    if not all(Decimal(str(value)).is_finite() for value in receipt.values()):
        raise ValueError("Quote numbers must be finite")
    if (
        not (0 < receipt["bid"] < receipt["ask"])
        or min(receipt["bid_qty"], receipt["ask_qty"]) < quantity
    ):
        raise ValueError("Quote lacks executable two-sided depth")
    if not 0 <= (now - native).total_seconds() <= 5:
        raise ValueError("Prospective broker quote is stale or future dated")
    return {
        **receipt,
        "broker_connection_id": connection_id,
        "broker": identity["broker"],
        "broker_account_hash": identity["broker_account_hash"],
        "symbol": order["symbol"],
        "exchange": order["exchange"],
        "action": order["action"],
        "quantity": quantity,
        "market_at": native.astimezone(UTC).isoformat(),
        "captured_at": now.isoformat(),
        "source": "authenticated_broker",
    }


def before_dispatch(metadata, mode, intent, api_key, order):
    if not metadata:
        return None
    if mode == "live":
        if intent != "entry":
            return None
        try:
            return entry_release_reason(metadata)
        except Exception:
            logger.exception("Live release could not be verified")
            return "Live release evidence is unavailable; new entry is blocked"
    if mode != "sandbox" or intent == "protection":
        return None
    try:
        from services.research import qualification

        registration = qualification.get_registration(metadata["owner"], metadata.get("trade_ref"))
        if registration is None:
            return None
        if metadata.get("order_id") is None:
            raise ValueError("The order has no durable intent for qualification")
        quote = _capture_quote(metadata, api_key, order)
        if not qualification.record_quote(
            metadata["owner"], metadata["trade_ref"], metadata["order_id"], quote
        ):
            raise ValueError("Prospective quote could not be recorded")
    except Exception:
        logger.exception("Prospective paper execution evidence is unavailable")
        if intent == "entry":
            return "Prospective paper quote evidence is unavailable; new entry is blocked"
        # An unrecorded/illiquid exit still must get to the ordinary exit pipe.
    return None
