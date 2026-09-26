"""Read-only strategy-link checks and trader-facing Flow readiness."""

from __future__ import annotations

from services.strategy_module.workflow_link import STRATEGY_EXECUTION_NODE_TYPES


def reason(code, message, *, strategy_id=None, link=None, blocking=True):
    return {"code": code, "message": message, "strategy_id": strategy_id,
            "link": link, "blocking": blocking}


def strategy_nodes(workflow):
    return [node for node in (getattr(workflow, "nodes", None) or [])
            if node.get("type") in STRATEGY_EXECUTION_NODE_TYPES]


def connection_summary(connection_id):
    # The installed multi-broker store is a legacy SQL table without an ORM
    # model. Read only public lifecycle fields, never credentials or tokens.
    from sqlalchemy import text
    from database import auth_db

    if not connection_id:
        return None
    with auth_db.engine.connect() as connection:
        row = connection.execute(text(
            "SELECT id, user_id, status, is_revoked FROM broker_connections WHERE id = :id"
        ), {"id": connection_id}).mappings().first()
        return dict(row) if row else None


def strategy_link_issues(workflow, *, api_key=None, owner=None):
    """Validate durable links; expired authentication is a readiness concern.

    Runtime availability is deliberately separate: a lost feed must not prevent
    an independently wired protective exit from reaching its owning engine.
    """
    from database import auth_db, strategy_module_db as store

    nodes = strategy_nodes(workflow)
    if not nodes:
        return []
    if api_key is not None:
        owner = auth_db.get_username_by_apikey(api_key)
        if not owner:
            return [reason("missing_owner", "Reconnect this workflow to your account.", link="/apikey")]
    issues = []
    for node in nodes:
        data = node.get("data") or {}
        sid, declared_owner, mode = data.get("strategyId"), data.get("brokerOwner"), data.get("mode")
        link = f"/strategy/{sid}" if type(sid) is int else "/strategy"
        if not declared_owner or (owner is not None and declared_owner != owner):
            issues.append(reason("owner_mismatch", "The workflow and strategy must belong to your account.", strategy_id=sid, link="/strategy"))
            continue
        strategy = store.get_strategy(sid, owner or declared_owner, strict=True) if type(sid) is int else None
        if strategy is None:
            issues.append(reason("missing_strategy", "The linked strategy no longer exists. Select an existing strategy before activating this flow.", strategy_id=sid, link="/strategy"))
            continue
        connection_id = getattr(workflow, "broker_connection_id", None)
        if not connection_id or connection_id != strategy.broker_connection_id:
            issues.append(reason("connection_mismatch", "Select the same broker connection for the workflow and strategy.", strategy_id=sid, link=link))
            continue
        connection = connection_summary(connection_id)
        if not connection or connection["user_id"] != (owner or declared_owner):
            issues.append(reason("missing_connection", "The linked broker connection is unavailable. Select your broker connection again.", strategy_id=sid, link="/broker"))
            continue
        action = "start" if node["type"] == "strategyModuleRun" else data.get("action")
        expected = {"start", "stop"} if strategy.strategy_kind == "batch" else {"long_entry", "short_entry", "long_exit", "short_exit"}
        if action not in expected:
            issues.append(reason("action_mismatch", "Choose an action supported by the linked strategy.", strategy_id=sid, link=link))
        elif mode not in {"sandbox", "live"}:
            issues.append(reason("mode_mismatch", "Choose Sandbox or Live explicitly for this workflow.", strategy_id=sid, link=link))
        elif action in {"start", "long_entry", "short_entry"} and mode == "live" and not strategy.live_enabled:
            issues.append(reason("mode_mismatch", "This workflow requests Live, but its strategy is Sandbox-only.", strategy_id=sid, link=link))
        elif action in {"long_entry", "short_entry"} and mode == "sandbox" and strategy.live_enabled:
            issues.append(reason("mode_mismatch", "Set the signal strategy to Sandbox before enabling sandbox signals.", strategy_id=sid, link=link))
        run_id = getattr(strategy, "current_run_id", None)
        if run_id:
            run = store.get_run(run_id)
            if (run is None or run.strategy_id != sid or run.broker_connection_id != connection_id
                    or run.mode != mode):
                issues.append(reason("active_run_mismatch", "The active run uses a different mode or broker connection. Review it before changing this flow.", strategy_id=sid, link=link))
    return list({(issue["code"], issue["strategy_id"]): issue for issue in issues}.values())


def workflow_readiness(workflow, *, owner=None, last_execution=None):
    from database import strategy_module_db as store

    issues = strategy_link_issues(workflow, owner=owner)
    if issues:
        return {"status": "risk_blocked", "label": "Needs attention", "reasons": issues}
    nodes = strategy_nodes(workflow)
    if nodes:
        connection = connection_summary(getattr(workflow, "broker_connection_id", None))
        if connection and (connection["is_revoked"] or connection["status"] not in {"connected", "authenticated"}):
            expired = connection["status"] == "expired"
            return {"status": "risk_blocked", "label": "Broker expired" if expired else "Broker disconnected",
                    "reasons": [reason("broker_expired" if expired else "broker_unavailable",
                                       "Reconnect your broker to resume market data and new entries.", link="/broker")]}
        for node in nodes:
            data = node.get("data") or {}
            strategy = store.get_strategy(data.get("strategyId"), owner or data.get("brokerOwner"))
            if strategy and strategy.current_run_id:
                return {"status": "already_running", "label": "Strategy running", "reasons": [
                    reason("already_running", "The existing run is being managed; repeated starts will be skipped.",
                           strategy_id=strategy.id, link=f"/strategy/{strategy.id}", blocking=False)]}
    if last_execution and last_execution.status in {"collecting_history", "data_unavailable", "risk_blocked"}:
        details = next((item.get("readiness") for item in reversed(last_execution.logs or [])
                        if isinstance(item.get("readiness"), dict)), None)
        if details:
            return {"status": last_execution.status, "label": details.get("readiness", "Waiting for data"),
                    "reasons": [reason(details.get("reason_code", last_execution.status), details["message"], blocking=False)]}
    return {"status": "waiting" if workflow.is_active else "inactive",
            "label": "Waiting for next check" if workflow.is_active else "Inactive", "reasons": []}
