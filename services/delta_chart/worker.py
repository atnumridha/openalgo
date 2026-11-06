"""Reconcile owned protection and the persisted, reviewed scalp profit policy.

Never constructs entries or directional signals. The explicit scalp policy can
expire unfilled entries and tighten/close owned exposure using broker snapshots.
GET routes remain read-only.
"""

import threading
from contextlib import nullcontext


class ProtectionWorker:
    def __init__(self, service, interval=2, context_factory=None):
        self.service = service
        self.context_factory = context_factory or nullcontext
        self.interval = interval
        self.stopped = threading.Event()
        self.thread = None

    def tick(self):
        with self.service.store.db() as db:
            plans = db.execute(
                "SELECT id,user FROM delta_managed_plans WHERE (status NOT IN ('blocked','completed','cancelled','rejected') OR (status='blocked' AND message='Owned protective order no longer satisfies the reviewed plan') OR (status='completed' AND message='Owned position is flat and owned sibling exits are no longer active' AND position_version IS NULL AND entry_price IS NULL AND stop_order_id IS NULL AND target_order_id IS NULL AND close_order_id IS NULL)) ORDER BY rowid LIMIT 100"
            ).fetchall()
        for plan in plans:
            if self.stopped.is_set():
                break
            try:
                self.service.plans.manage(
                    plan["user"],
                    {"plan_id": plan["id"], "decision": "sync"},
                    protection_only=True,
                )
            except Exception:
                # Existing unknown outcomes remain in the durable ledger.  A new
                # round observes/reconciles them; it never invents a retry UUID.
                continue

    def start(self):
        if self.thread is not None:
            return self

        def loop():
            while not self.stopped.is_set():
                with self.context_factory():
                    self.tick()
                self.stopped.wait(self.interval)

        self.thread = threading.Thread(
            target=loop, name="delta-fixed-protection", daemon=True
        )
        self.thread.start()
        return self
