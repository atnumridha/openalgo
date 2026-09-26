"""Forward Sandbox collection and explicit, short-lived reviewed live release.

Only server execution hooks accept quotes or ledger evidence. Public operations
accept identifiers and review acknowledgments, never metrics or thresholds.
"""

from datetime import UTC, datetime

from database.strategy_qualification_db import get_store
from services.research.qualification_context import current_binding
from services.risk.qualification import POLICY, evaluate_campaign, final_screen_passes, timestamp


def utcnow():
    return datetime.now(UTC)


def _payload(payload, keys):
    if not isinstance(payload, dict) or set(payload) != set(keys):
        raise ValueError("Supply only the requested campaign identifiers or review fields.")


def _reason(payload):
    reason = payload.get("reason")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        raise ValueError("Record a review reason between 3 and 1000 characters.")
    return reason.strip()


def _matches_review(campaign, payload):
    if (
        type(payload.get("expected_revision")) is not int
        or payload["expected_revision"] != campaign["revision"]
        or payload.get("evidence_digest") != campaign["evidence_digest"]
    ):
        raise ValueError(
            "The evidence changed after you reviewed it. Refresh the campaign and review its latest results."
        )


def _origin_matches(binding):
    origin = binding.get("entry_origin")
    return bool(
        binding.get("workflow_id")
        and isinstance(origin, dict)
        and origin.get("workflow_id") == binding["workflow_id"]
        and origin.get("execution_id")
    )


def _present(owner, campaign, *, binding=None, include_trades=True):
    if campaign is None:
        raise LookupError("Qualification campaign not found")
    problem = None
    if binding is None:
        try:
            binding = current_binding(owner, campaign["strategy_id"])
        except (ValueError, LookupError):
            binding = {}
            problem = "The current strategy, linked Flow or authenticated broker is unavailable."
    matches = (
        binding.get("binding_hash") == campaign["binding_hash"]
        and campaign["status"] != "superseded"
    )
    qualification = evaluate_campaign(
        campaign["final_run"],
        campaign["trades"],
        max_drawdown_pct=campaign["max_drawdown_pct"],
        marks_complete=campaign["marks_complete"],
        risk_breach=campaign["risk_breach"] or binding.get("risk_paused", False),
        binding_current=matches,
        source_current=campaign["source_current"],
    )
    result = {key: value for key, value in campaign.items() if key != "final_run"}
    result["qualification"] = qualification
    result["policy"] = dict(POLICY)
    result["research_reference"] = {
        "id": campaign["final_run_id"],
        "configuration_hash": campaign["final_run"].get("configuration_hash"),
        "metrics": campaign["final_run"].get("report", {}).get("metrics", {}),
        "purpose": "Historical screening reference; forward evidence measures this bound strategy and Flow.",
    }
    if problem:
        result["binding_problem"] = problem
    reconciliation = campaign.get("reconciliation")
    if reconciliation and (
        not matches
        or not campaign["source_current"]
        or reconciliation.get("revision") != campaign["revision"]
        or reconciliation.get("evidence_digest") != campaign["evidence_digest"]
    ):
        result["reconciliation"] = reconciliation | {"status": "stale"}
    approval = campaign.get("approval")
    if approval and approval.get("status") == "approved":
        reason = None
        status = "invalidated"
        if timestamp(approval["expires_at"]) <= utcnow():
            status, reason = (
                "expired",
                "The seven-day release approval expired. Review and approve again.",
            )
        elif not matches:
            reason = "The current strategy, Flow, source, broker account or costs changed."
        elif approval.get("broker_epoch") != binding.get("broker_epoch"):
            reason = "The broker login changed. Review and approve this session again."
        elif binding.get("risk_paused"):
            reason = "The capital profile is paused. Resolve its risk review first."
        elif (
            approval.get("revision") != campaign["revision"]
            or approval.get("evidence_digest") != campaign["evidence_digest"]
            or approval.get("policy_version") != POLICY["version"]
            or not qualification["eligible"]
        ):
            reason = (
                "Forward evidence or qualification policy changed. Reconcile and approve again."
            )
        if reason:
            result["approval"] = approval | {"status": status, "invalidation_reason": reason}
    if not include_trades:
        result.pop("trades", None)
    return result


def overview(owner):
    from database.strategy_module_db import list_strategies

    campaigns = [
        _present(owner, campaign, include_trades=False)
        for campaign in get_store().list_campaigns(owner)
    ]
    strategies = [
        {"id": item["id"], "name": item["name"]} for item in list_strategies(owner)[:1000]
    ]
    return {"campaigns": campaigns, "strategies": strategies, "policy": dict(POLICY)}


def create_campaign(owner, payload):
    _payload(payload, ("strategy_id", "final_run_id"))
    if any(type(payload[key]) is not int or payload[key] <= 0 for key in payload):
        raise ValueError("Choose a saved strategy and completed sealed final run.")
    from database.trading_research_db import get_store as research_store

    run = research_store().get_run(owner, payload["final_run_id"])
    if not run:
        raise LookupError("Sealed final research run not found")
    if not final_screen_passes(run):
        raise ValueError(
            "Choose a complete, profitable sealed final screen with at least 20 trades."
        )
    binding = current_binding(owner, payload["strategy_id"])
    if binding.get("risk_paused"):
        raise ValueError("Resolve the capital pause before enrolling a campaign.")
    # Freeze only required reference fields. Full reports may contain many
    # thousands of historical trades; the research store retains their audit.
    reference = {
        key: run.get(key) for key in ("id", "kind", "status", "frozen_at", "configuration_hash")
    }
    reference["report"] = {
        key: run["report"].get(key) for key in ("metrics", "incomplete_outcomes", "split")
    }
    campaign = get_store().create_campaign(
        owner, payload["strategy_id"], payload["final_run_id"], binding, reference, utcnow()
    )
    return _present(owner, campaign, binding=binding)


def detail(owner, campaign_id):
    return _present(owner, get_store().get_campaign(owner, campaign_id))


def reconcile(owner, campaign_id, payload):
    _payload(payload, ("reason", "costs_confirmed", "expected_revision", "evidence_digest"))
    reason = _reason(payload)
    if payload.get("costs_confirmed") is not True:
        raise ValueError("Confirm the dated cost assumptions before reconciliation.")
    _refresh_from_ledger(owner, campaign_id)
    campaign = detail(owner, campaign_id)
    _matches_review(campaign, payload)
    blocking = {"execution", "resolved", "binding", "risk", "drawdown", "source_evidence"}
    if any(
        not check["passed"] and check["code"] in blocking
        for check in campaign["qualification"]["checks"]
    ):
        raise ValueError(
            "Resolve incomplete executions, open positions, risk and configuration checks before reconciliation."
        )
    updated = get_store().reconcile(
        owner, campaign_id, campaign["revision"], campaign["evidence_digest"], reason, utcnow()
    )
    return _present(owner, updated)


def _refresh_from_ledger(owner, campaign_id):
    campaign = get_store().get_campaign(owner, campaign_id)
    if campaign is None:
        raise LookupError("Qualification campaign not found")
    if campaign["source_current"]:
        return
    from services.strategy_module.trading_budget import _sync_qualification

    # An explicit review is the bounded recovery path for terminal updates whose
    # original delivery failed. Never creates orders or requests broker data.
    for trade in campaign["trades"]:
        _sync_qualification(owner, "sandbox", trade["trade_ref"])


def approve(owner, campaign_id, payload):
    _payload(payload, ("reason", "acknowledged", "expected_revision", "evidence_digest"))
    reason = _reason(payload)
    if payload.get("acknowledged") is not True:
        raise ValueError(
            "Explicitly acknowledge the reviewed Sandbox evidence before live approval."
        )
    campaign = get_store().get_campaign(owner, campaign_id)
    if campaign is None:
        raise LookupError("Qualification campaign not found")
    _matches_review(campaign, payload)
    binding = current_binding(owner, campaign["strategy_id"])
    presented = _present(owner, campaign, binding=binding)
    if not presented["qualification"]["eligible"]:
        raise ValueError("The campaign must meet every qualification check before live approval.")
    updated = get_store().approve(
        owner,
        campaign_id,
        campaign["revision"],
        campaign["evidence_digest"],
        binding,
        reason,
        utcnow(),
    )
    return _present(owner, updated)


def revoke(owner, campaign_id, payload):
    _payload(payload, ("reason",))
    return _present(owner, get_store().revoke(owner, campaign_id, _reason(payload), utcnow()))


def get_registration(owner, trade_ref):
    return get_store().get_registration(owner, trade_ref)


def register_entry(owner, strategy_id, trade_ref):
    # Legacy Sandbox execution incurs no broker/context lookups when unenrolled.
    if get_store().active_campaign(owner, strategy_id) is None:
        return None
    binding = current_binding(owner, strategy_id)
    if not _origin_matches(binding):
        raise ValueError("Run this campaign through its bound Flow to collect forward evidence.")
    if binding.get("risk_paused"):
        raise ValueError("The capital profile is paused.")
    return get_store().register_entry(owner, strategy_id, trade_ref, binding, utcnow())


def record_quote(owner, trade_ref, order_id, quote):
    return get_store().record_quote(owner, trade_ref, order_id, quote, utcnow())


def record_trade(owner, trade_ref, risk_row):
    return get_store().record_trade(owner, trade_ref, risk_row, utcnow())


def live_release_reason(owner, strategy_id, strategy_config, risk_policy_version, costs):
    """Return None only for a current reviewed release; this never activates it."""
    campaign = get_store().active_campaign(owner, strategy_id)
    if campaign is None:
        return "No forward qualification campaign exists for this strategy."
    try:
        binding = current_binding(owner, strategy_id, strategy_config=strategy_config, costs=costs)
    except (ValueError, LookupError):
        return "The current strategy, Flow, broker session or cost assumptions need review."
    if binding.get("risk_policy_version") != risk_policy_version or binding.get("costs") != costs:
        return "The capital rules or cost assumptions changed after review."
    if not _origin_matches(binding):
        return "Live entries must originate from the Flow reviewed in this campaign."
    presented = _present(owner, campaign, binding=binding)
    approval = presented.get("approval") or {}
    if approval.get("status") != "approved":
        return (
            approval.get("invalidation_reason")
            or "A current, explicit live release approval is required."
        )
    if not presented["qualification"]["eligible"]:
        return "The campaign no longer meets every qualification check."
    return None
