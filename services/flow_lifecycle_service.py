"""Flow activation and trigger teardown shared by HTTP and strategy controls."""

from __future__ import annotations

from database.flow_db import with_workflow_mutation_lease
from utils.logging import get_logger

logger = get_logger(__name__)


def trigger_node(nodes):
    return next(
        (
            node
            for node in (nodes or [])
            if node.get("type")
            in {
                "start",
                "webhookTrigger",
                "priceAlert",
                "orderUpdateTrigger",
            }
        ),
        None,
    )


def unregister_trigger(workflow_id):
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    get_flow_scheduler().remove_workflow_job(workflow_id, strict=True)
    get_flow_price_monitor().remove_alert(workflow_id)
    get_flow_order_update_monitor().remove_watch(workflow_id)


def register_trigger(workflow_id, trigger_type, trigger_data, api_key):
    """Register the existing trigger contract after active state is durable."""
    from database.flow_db import set_schedule_job_id
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    if trigger_type == "start":
        schedule_type = trigger_data.get("scheduleType")
        if schedule_type and schedule_type != "manual":
            scheduler = get_flow_scheduler()
            scheduler.set_api_key(api_key)
            job_id = scheduler.add_workflow_job(
                workflow_id=workflow_id,
                schedule_type=schedule_type,
                time_str=trigger_data.get("time", "09:15"),
                days=trigger_data.get("days"),
                execute_at=trigger_data.get("executeAt"),
                interval_value=trigger_data.get("intervalValue"),
                interval_unit=trigger_data.get("intervalUnit"),
                market_hours_only=bool(trigger_data.get("marketHoursOnly", False)),
            )
            if not set_schedule_job_id(workflow_id, job_id):
                scheduler.remove_workflow_job(workflow_id)
                raise RuntimeError("Could not record the scheduler job id for this workflow")
    elif trigger_type == "priceAlert":
        get_flow_price_monitor().add_alert(
            workflow_id=workflow_id,
            symbol=trigger_data.get("symbol", ""),
            exchange=trigger_data.get("exchange", "NSE"),
            condition=trigger_data.get("condition", "greater_than"),
            target_price=float(trigger_data.get("price", 0) or 0),
            price_lower=trigger_data.get("priceLower"),
            price_upper=trigger_data.get("priceUpper"),
            percentage=trigger_data.get("percentage"),
            api_key=api_key,
            trigger=trigger_data.get("trigger", "once"),
            expiration=trigger_data.get("expiration", "none"),
        )
    elif trigger_type == "orderUpdateTrigger":
        get_flow_order_update_monitor().add_watch(
            workflow_id=workflow_id,
            api_key=api_key,
            order_id=trigger_data.get("orderId") or None,
            symbol=trigger_data.get("symbol") or None,
            exchange=trigger_data.get("exchange") or None,
            status=trigger_data.get("status", "complete"),
            trigger=trigger_data.get("trigger", "once"),
        )


def execution_blocked(workflow):
    from services.flow_workflow_validator import validate_workflow

    errors = validate_workflow(
        {
            "name": workflow.name,
            "nodes": workflow.nodes or [],
            "edges": workflow.edges or [],
        },
        strict=True,
    )
    if not errors:
        return None
    return {
        "status": "error",
        "error": "Workflow cannot be executed",
        "message": errors[0]["message"],
        "errors": errors,
    }


@with_workflow_mutation_lease
def rollback_activation(workflow_id):
    """Try every compensation; return evidence if any could not complete."""
    from database.flow_db import deactivate_workflow as db_deactivate
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    errors = []
    for undo, what in (
        (
            lambda: get_flow_scheduler().remove_workflow_job(workflow_id, strict=True),
            "scheduler job",
        ),
        (lambda: get_flow_price_monitor().remove_alert(workflow_id), "price alert"),
        (lambda: get_flow_order_update_monitor().remove_watch(workflow_id), "order-update watch"),
        (lambda: db_deactivate(workflow_id), "active flag"),
    ):
        try:
            result = undo()
            if what == "active flag" and not result:
                raise RuntimeError("Could not persist inactive state")
        except Exception as exc:
            logger.exception("Could not roll back %s for workflow %s", what, workflow_id)
            errors.append(f"{what}: {exc}")
    return errors


@with_workflow_mutation_lease
def activate_workflow(workflow_id: int, api_key: str | None) -> tuple[dict, int]:
    from database.flow_db import activate_workflow as db_activate
    from database.flow_db import get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return {"error": "Workflow not found"}, 404
    if workflow.is_active:
        return {"status": "already_active", "message": "Workflow is already active"}, 200
    if not api_key:
        return {"error": "API key not configured"}, 400
    blocked = execution_blocked(workflow)
    if blocked:
        return {**blocked, "error": "Workflow cannot be activated"}, 400
    trigger = trigger_node(workflow.nodes)
    if not trigger:
        return {"error": "No trigger node found in workflow"}, 400
    if not db_activate(workflow_id, api_key=api_key):
        return {"error": "Could not activate workflow"}, 500
    try:
        register_trigger(workflow_id, trigger.get("type"), trigger.get("data", {}), api_key)
        return {
            "status": "success",
            "message": f"Workflow activated with {trigger.get('type')} trigger",
        }, 200
    except Exception as exc:
        errors = rollback_activation(workflow_id)
        error = str(exc)
        if errors:
            error += "; inconsistent Flow state: " + "; ".join(errors)
        return {"error": error}, 400 if isinstance(exc, ValueError) and not errors else 500


@with_workflow_mutation_lease
def deactivate_workflow(workflow_id: int) -> tuple[dict, int]:
    from database.flow_db import deactivate_workflow as db_deactivate
    from database.flow_db import get_workflow, set_schedule_job_id
    from services.flow_executor_service import release_workflow_subscriptions
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    workflow = get_workflow(workflow_id)
    if not workflow:
        return {"error": "Workflow not found"}, 404
    if not workflow.is_active:
        return {"status": "already_inactive", "message": "Workflow is already inactive"}, 200
    try:
        get_flow_scheduler().remove_workflow_job(workflow_id, strict=True)
        if workflow.schedule_job_id:
            set_schedule_job_id(workflow_id, None)
        get_flow_price_monitor().remove_alert(workflow_id)
        get_flow_order_update_monitor().remove_watch(workflow_id)
        release_workflow_subscriptions(workflow_id)
        if not db_deactivate(workflow_id):
            return {"error": "Could not deactivate workflow"}, 500
        return {"status": "success", "message": "Workflow deactivated"}, 200
    except Exception as exc:
        logger.exception("Failed to deactivate workflow %s", workflow_id)
        return {"error": str(exc)}, 500
