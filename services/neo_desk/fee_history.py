"""Durable, owner-scoped estimates derived from saved execution facts."""

import copy
import json
from datetime import datetime
from hashlib import sha256

from database import neo_history_db as db
from utils.keyed_locks import KeyedLocks

from .fees import FEE_ESTIMATE_VERSION, estimate_charges
from .types import IST

_locks = KeyedLocks(name="neo-fee-estimates")


def saved_charge_estimate(owner, mode, fills, plan, cost_plan):
    fingerprint = sha256(
        json.dumps(fills, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with _locks.hold((owner, mode, cost_plan)):
        db.init_db()
        saved = db.db_session.get(db.NeoFeeEstimate, (owner, mode, cost_plan))
        if saved and saved.input_hash == fingerprint and saved.version == FEE_ESTIMATE_VERSION:
            return copy.deepcopy(saved.payload)
        estimate = estimate_charges(fills, None, plan)
        estimate.update(
            storage="SQL saved estimate",
            calculated_at=datetime.now(IST).isoformat(),
            input_hash=fingerprint,
            cost_plan=cost_plan,
        )
        try:
            if saved is None:
                saved = db.NeoFeeEstimate(owner=owner, mode=mode, cost_plan=cost_plan)
                db.db_session.add(saved)
            saved.input_hash = fingerprint
            saved.version = FEE_ESTIMATE_VERSION
            saved.payload = estimate
            db.db_session.commit()
        except Exception:
            db.db_session.rollback()
            raise
        return copy.deepcopy(estimate)
