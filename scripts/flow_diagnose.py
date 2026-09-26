"""Explain why a Flow workflow is not placing orders.

Checks every gate an order has to pass and prints the ones that are shut. Run
it on the machine that is not trading:

    uv run python scripts/flow_diagnose.py 107

Read-only: it never executes the workflow and never places an order.

Deliberately does not import ``app.py``. Importing that starts the WebSocket
proxy and the schedulers as a side effect, which on a live machine either
fights the running instance for port 8765 or brings up a second copy of the
trading stack. The database layer is plain SQLAlchemy with its own
``scoped_session``, so loading ``.env`` is all this needs.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, time

# Runnable from anywhere, including scripts/ itself.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse(value: str, default: time) -> time:
    try:
        parts = [int(p) for p in str(value).split(":")]
        return time(*parts[:3])
    except (TypeError, ValueError):
        return default


def diagnose(workflow_id: int) -> int:
    from dotenv import load_dotenv

    load_dotenv()

    import pytz

    from database.flow_db import get_workflow, get_workflow_api_key
    from services.flow_readiness_service import strategy_nodes, workflow_readiness
    from services.flow_workflow_validator import validate_workflow

    wf = get_workflow(workflow_id)
    if not wf:
        print(f"No workflow with id {workflow_id}.")
        return 1

    print(f"Workflow {workflow_id}: {wf.name}\n")
    blockers: list[str] = []

    # Both intraday time gates and candle scheduling use IST explicitly.
    local = datetime.now()
    ist = datetime.now(pytz.timezone("Asia/Kolkata"))
    print(f"  server local time : {local.strftime('%Y-%m-%d %H:%M')}")
    print(f"  IST               : {ist.strftime('%Y-%m-%d %H:%M')}")
    print("  time gates        : Asia/Kolkata (IST)")

    # 2. Activation.
    print(f"\n  is_active         : {bool(wf.is_active)}")
    print(f"  schedule job      : {wf.schedule_job_id}")
    print(f"  webhook enabled   : {bool(wf.webhook_enabled)}")
    if not wf.is_active:
        blockers.append(
            "Workflow is not activated, so nothing triggers it. Activate it in the "
            "editor."
        )
    elif not wf.schedule_job_id and not wf.webhook_enabled:
        blockers.append(
            "Active but has no schedule job and no webhook, so no trigger reaches it. "
            "Deactivate and reactivate to re-register the schedule."
        )

    # 3. Credentials.
    api_key = get_workflow_api_key(wf)
    print(f"  api key stored    : {bool(api_key)}")
    if not api_key:
        blockers.append(
            "No API key stored on the workflow. Reactivate it while logged in so the "
            "key is captured."
        )

    # 4. Graph completeness - the same strict check activation and every trigger
    # path applies before touching the broker.
    errors = validate_workflow(
        {"name": wf.name, "nodes": wf.nodes or [], "edges": wf.edges or []},
        strict=True,
    )
    print(f"  graph validation  : {'clean' if not errors else errors[0]['message']}")
    if errors:
        blockers.append(f"Graph is not runnable: {errors[0]['message']}")

    # Strategy workflows declare their mode; a global switch is not authority.
    linked_nodes = strategy_nodes(wf)
    if linked_nodes:
        modes = sorted({str(node.get("data", {}).get("mode", "missing")) for node in linked_nodes})
        print(f"  execution modes   : {', '.join(modes)}")
        readiness = workflow_readiness(wf)
        print(f"  readiness         : {readiness['label']}")
        blockers.extend(item["message"] for item in readiness["reasons"] if item["blocking"])
    else:
        print("  execution mode    : inspect the workflow's order nodes and account settings")

    # 6. Time windows, against the clock the executor will actually use.
    windows = [
        (n.get("id"), (n.get("data") or {}))
        for n in (wf.nodes or [])
        if n.get("type") == "timeWindow"
    ]
    if windows:
        now_t = ist.time()
        print("\n  time windows (IST):")
        open_any = False
        for nid, data in windows:
            start = _parse(data.get("startTime", "00:00"), time(0, 0))
            end = _parse(data.get("endTime", "23:59"), time(23, 59))
            is_open = start <= now_t <= end if start <= end else now_t >= start or now_t <= end
            if data.get("invertCondition"):
                is_open = not is_open
            open_any = open_any or is_open
            print(
                f"    {nid:<6} {start.strftime('%H:%M')}-{end.strftime('%H:%M')}  "
                f"{'OPEN' if is_open else 'closed'}"
            )
        if not open_any:
            blockers.append(
                "Every time window is closed right now, so no leg can fire until one "
                "opens."
            )

    print()
    if blockers:
        print(f"{len(blockers)} reason(s) orders are not being placed:\n")
        for i, blocker in enumerate(blockers, 1):
            print(f"  {i}. {blocker}\n")
    else:
        print(
            "No configuration blocker found. Market-data readiness and entry conditions\n"
            "are checked at execution time. Open the latest execution for its outcome."
        )
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: uv run python scripts/flow_diagnose.py <workflow_id>")
        return 2
    try:
        return diagnose(int(sys.argv[1]))
    finally:
        from utils.db_sessions import remove_all_scoped_sessions

        remove_all_scoped_sessions()


if __name__ == "__main__":
    raise SystemExit(main())
