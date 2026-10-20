"""Continue public signal monitoring while account access/activation is unavailable."""

from __future__ import annotations

import signal
import time

import httpx

from .data import DeltaPublic
from .strategy import decide


def run(args, cfg, host, emit):
    from .live import readiness

    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    count = 0
    last = None
    try:
        with DeltaPublic() as feed:
            while not stopped and (not args.iterations or count < args.iterations):
                start = time.monotonic()
                count += 1
                try:
                    requested = host.mode()
                except ValueError:
                    requested = None
                if requested == "paper" and args.mode == "auto":
                    return 90
                gate = readiness(args.execution_root, cfg, args.arm_live)
                if requested == "live" and gate["ready"]:
                    return 90
                try:
                    context = feed.context(time.time())
                    quote = feed.market()
                    decision = decide({**context, **quote}, cfg, time.time())
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    decision = {"action": "HOLD", "reason": "Public data unavailable"}
                output = {
                    "mode": "live",
                    "requested_mode": requested,
                    "status": "monitoring",
                    "execution_enabled": False,
                    "blockers": gate["blockers"],
                    "decision": decision,
                    "capital_basis": "Planning cap only; account collateral not verified",
                }
                key = (
                    int(time.time() // 60),
                    requested,
                    tuple(gate["blockers"]),
                    decision.get("action"),
                    decision.get("reason"),
                )
                if key != last:
                    emit(output)
                    last = key
                while not stopped and time.monotonic() - start < 1:
                    time.sleep(0.05)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    emit({"mode": "live", "status": "monitor stopped", "execution_enabled": False})
    return 0
