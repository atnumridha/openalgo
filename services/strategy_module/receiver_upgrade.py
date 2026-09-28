"""Reviewable upgrade plans for untouched option receiver templates."""

from copy import deepcopy

from services.strategy_module.receiver_rules import RECEIVER_NAMES


class UnsupportedReceiver(ValueError):
    """Preserve an edited, ambiguous or actively trading configuration."""


def _leg_shape(leg):
    """Compare the whole saved leg, allowing only identity/cosmetic metadata.

    Keep this independent of the HTTP validator so the dry-run never imports
    the application or connects to its databases. Unknown controls are edits,
    even when the old factory payload did not happen to include their keys.
    """
    if not isinstance(leg, dict):
        raise UnsupportedReceiver("Malformed receiver leg")
    shaped = {
        key: value for key, value in leg.items() if key not in {"id", "leg_id", "label", "name"}
    }
    if shaped.get("trail") is None:
        shaped.pop("trail", None)
    return shaped


def _shape(nodes, edges):
    shaped = []
    for node in nodes:
        data = deepcopy(node.get("data") or {})
        data.pop("label", None)
        shaped.append({"id": node.get("id"), "type": node.get("type"), "data": data})
    if len({n["id"] for n in shaped}) != len(shaped):
        raise UnsupportedReceiver("Duplicate node identity")
    return (
        sorted(shaped, key=lambda n: str(n["id"])),
        sorted(
            [
                {
                    k: v
                    for k, v in edge.items()
                    if k not in {"label", "style", "animated", "selected"}
                }
                for edge in edges
            ],
            key=lambda e: str(e.get("id")),
        ),
    )


def plan(strategy, workflow):
    """Return exact proposed changes; no database, mode or activation mutation.

    Existing account settings and user risk limits are deliberately preserved.
    The receiver's new technical stop still must pass all shared admission gates.
    """
    from services.strategy_module.starter_pack import legacy_starter_definitions
    from services.strategy_module.starter_workflows import (
        WORKFLOW_SPECS,
        _definition,
        legacy_definition,
    )

    profile = RECEIVER_NAMES.get(strategy.get("name"))
    if not profile:
        raise UnsupportedReceiver("Not one of the nine option receiver templates")
    if strategy.get("status") != "stopped" or strategy.get("current_run_id"):
        raise UnsupportedReceiver("Receiver has active or unresolved exposure")
    if strategy.get("scalp_profile") not in (None, profile):
        raise UnsupportedReceiver("Receiver already has different rules")
    if (
        not strategy.get("broker_connection_id")
        or workflow.get("broker_connection_id") != strategy["broker_connection_id"]
    ):
        raise UnsupportedReceiver("Workflow and strategy broker pins differ")
    template = next(r for r in legacy_starter_definitions() if r["name"] == strategy["name"])
    for key in ("strategy_kind", "underlying", "underlying_exchange", "strategy_type"):
        if strategy.get(key) != template[key]:
            raise UnsupportedReceiver(f"Edited receiver {key}")
    legs = strategy.get("legs") or []
    if len(legs) != 1:
        raise UnsupportedReceiver("Receiver must have its one original long-option leg")
    if _leg_shape(legs[0]) != _leg_shape(template["legs"][0]):
        raise UnsupportedReceiver("Edited receiver leg controls; manual review required")
    if strategy.get("trail_sl_to_entry") or strategy.get("lock_profit"):
        raise UnsupportedReceiver("Custom receiver risk controls; manual review required")
    mode = "live" if strategy.get("live_enabled") else "sandbox"
    spec = next(r for r in WORKFLOW_SPECS if r[0] == strategy["name"])
    args = (spec[0], strategy["id"], *spec[1:], strategy["user_id"])
    old, new = legacy_definition(*args), _definition(*args)
    for graph in (old, new):
        next(n for n in graph["nodes"] if n["id"] == "run")["data"]["mode"] = mode
    actual = _shape(workflow["nodes"], workflow["edges"])
    if strategy.get("scalp_profile") == profile and actual == _shape(new["nodes"], new["edges"]):
        return None
    if strategy.get("scalp_profile") is not None or actual != _shape(old["nodes"], old["edges"]):
        raise UnsupportedReceiver("Edited or unrecognized receiver graph; manual review required")
    retained = {n["id"]: n for n in workflow["nodes"]}
    for node in new["nodes"]:
        source = retained.get(node["id"])
        if source:
            if "position" in source:
                node["position"] = deepcopy(source["position"])
            if "label" in (source.get("data") or {}):
                node["data"]["label"] = source["data"]["label"]
    return {
        "strategy_id": strategy["id"],
        "workflow_id": workflow["id"],
        "name": strategy["name"],
        "mode": mode,
        "active": bool(workflow.get("is_active")),
        "strategy_changes": {"scalp_profile": profile},
        "workflow_changes": {k: new[k] for k in ("nodes", "edges", "description")},
    }
