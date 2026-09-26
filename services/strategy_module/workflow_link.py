"""Pure validation of explicit strategy/Flow links; no database singletons."""

from dataclasses import dataclass

STRATEGY_EXECUTION_NODE_TYPES = frozenset({"strategyModuleRun", "strategySignal"})
ENTRY_SIGNAL_ACTIONS = frozenset({"start", "long_entry", "short_entry"})
EXIT_SIGNAL_ACTIONS = frozenset({"stop", "long_exit", "short_exit"})


@dataclass(frozen=True, slots=True)
class WorkflowLink:
    workflow_id: int
    active: bool
    mode: str
    broker_owner: str
    broker_connection_id: str | None


def validate_workflow_link(
    strategy, workflows, *, require_sandbox: bool = True
) -> tuple[WorkflowLink | None, str | None]:
    """Resolve exactly one admission node, allowing same-strategy protective exits."""
    strategy_id = getattr(strategy, "id", None)
    if type(strategy_id) is not int or strategy_id <= 0:
        return None, "Strategy ID must be a positive integer."
    owner = getattr(strategy, "user_id", None)
    if not isinstance(owner, str) or not owner.strip():
        return None, "Strategy owner is invalid."
    strategy_connection = getattr(strategy, "broker_connection_id", None)
    if strategy_connection is not None and (
        not isinstance(strategy_connection, str) or not strategy_connection.strip()
    ):
        return None, "Strategy broker connection is invalid."

    if not workflows:
        return None, f"No Flow workflow is explicitly linked to strategy {strategy_id}."
    if len(workflows) != 1:
        return None, f"Multiple Flow workflows are linked to strategy {strategy_id}."

    workflow = workflows[0]
    workflow_id = getattr(workflow, "id", None)
    if type(workflow_id) is not int or workflow_id <= 0:
        return None, "Linked Flow workflow has an invalid ID."
    nodes = getattr(workflow, "nodes", None)
    if not isinstance(nodes, list) or any(
        not isinstance(node, dict) or type(node.get("type")) is not str for node in nodes
    ):
        return None, f"Flow workflow {workflow_id} has malformed nodes."
    run_nodes = [node for node in nodes if node.get("type") in STRATEGY_EXECUTION_NODE_TYPES]
    if any(not isinstance(node.get("data"), dict) for node in run_nodes):
        return None, f"Flow workflow {workflow_id} has malformed nodes."
    signal_actions = {"long_entry", "long_exit", "short_entry", "short_exit"}
    for node in run_nodes:
        if node.get("type") != "strategySignal":
            continue
        action = node["data"].get("action")
        if not isinstance(action, str) or action not in ENTRY_SIGNAL_ACTIONS | EXIT_SIGNAL_ACTIONS:
            return None, f"Flow workflow {workflow_id} has an invalid signal action."
        if (node["data"].get("strategyId") == strategy_id
                and getattr(strategy, "strategy_kind", None) == "signal"
                and action not in signal_actions):
            return None, f"Flow workflow {workflow_id} uses a batch action for a signal strategy."
    if any(
        type(node["data"].get("strategyId")) is not int
        or node["data"]["strategyId"] <= 0
        for node in run_nodes
    ):
        return None, f"Flow workflow {workflow_id} has malformed run-node strategy IDs."
    entry_nodes = [
        node for node in run_nodes
        if node["data"]["strategyId"] == strategy_id
        and (node["type"] == "strategyModuleRun" or node["data"]["action"] in ENTRY_SIGNAL_ACTIONS)
    ]
    if not entry_nodes:
        return None, f"Flow workflow {workflow_id} has no entry node for strategy {strategy_id}."
    if len(entry_nodes) != 1:
        return None, f"Flow workflow {workflow_id} has multiple entry nodes for strategy {strategy_id}."

    data = entry_nodes[0]["data"]
    mode = data.get("mode")
    if not isinstance(mode, str) or mode not in {"sandbox", "live"}:
        return None, f"Flow workflow {workflow_id} has an invalid mode."
    if require_sandbox and mode != "sandbox":
        return None, f"Flow workflow {workflow_id} is not in sandbox mode."
    broker_owner = data.get("brokerOwner")
    if not isinstance(broker_owner, str) or not broker_owner.strip():
        return None, f"Flow workflow {workflow_id} has an invalid broker owner."
    if broker_owner != owner:
        return None, f"Flow workflow {workflow_id} has a different broker owner."
    for node in run_nodes:
        if node is entry_nodes[0]:
            continue
        other_data = node["data"]
        other_mode = other_data.get("mode")
        if not isinstance(other_mode, str) or other_mode not in {"sandbox", "live"}:
            return None, f"Flow workflow {workflow_id} has an invalid mode."
        if require_sandbox and other_mode != "sandbox":
            return None, f"Flow workflow {workflow_id} contains a non-sandbox run node."
        if other_mode != mode:
            return None, f"Flow workflow {workflow_id} contains run nodes in different modes."
        other_owner = other_data.get("brokerOwner")
        if not isinstance(other_owner, str) or not other_owner.strip():
            return None, f"Flow workflow {workflow_id} has an invalid broker owner."
        if other_owner != broker_owner:
            return None, (
                f"Flow workflow {workflow_id} contains a run node for a different broker owner."
            )
    if any(node["data"]["strategyId"] != strategy_id for node in run_nodes):
        return None, "Shared Flow workflow controls more than one strategy; admission is unsafe"
    workflow_connection = getattr(workflow, "broker_connection_id", None)
    if workflow_connection is not None and (
        not isinstance(workflow_connection, str) or not workflow_connection.strip()
    ):
        return None, f"Flow workflow {workflow_id} has an invalid broker connection."
    if workflow_connection != strategy_connection:
        return None, f"Flow workflow {workflow_id} has a different broker connection."
    active = getattr(workflow, "is_active", None)
    if type(active) is not bool:
        return None, f"Flow workflow {workflow_id} has an invalid activation state."

    return WorkflowLink(workflow_id, active, mode, broker_owner, workflow_connection), None
