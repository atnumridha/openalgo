from dataclasses import asdict
from datetime import datetime, time
from decimal import Decimal as D

from database import neo_desk_db as desk
from database import strategy_module_db as native
from services.strategy_module.signals import start_provider_run

from .presets import get_preset
from .types import IST, EntryResult


def public_setup(s):
    return {
        k: v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, D) else v
        for k, v in asdict(s).items()
    }


def submit_setup(owner_id, setup, selection, mode, *, now=None):
    now = now or datetime.now(IST)
    p = get_preset(setup.profile)
    if p.research_only and mode == "live":
        return EntryResult(False, error="Price Break & Retest is available in Sandbox only.")
    if (
        mode not in ("sandbox", "live")
        or now.tzinfo is None
        or not 0 <= (now - setup.execute_at).total_seconds() <= 5
    ):
        return EntryResult(
            False, error="Signal is no longer fresh; recovered setups are not entered."
        )
    if (
        not selection.ok
        or not selection.contract
        or not selection.quote
        or not selection.quote.fresh(now)
        or selection.contract.option_type != setup.direction
        or selection.quantity != 65
        or selection.contract.lot_size != 65
    ):
        return EntryResult(False, error=selection.error or "Option selection is invalid or stale.")
    config = desk.view(owner_id)
    if not desk.claim(owner_id, setup.key, public_setup(setup), setup.profile, mode):
        return EntryResult(
            False,
            error="Entries stopped, profile changed, signal already claimed or exposure remains managed.",
        )
    c = selection.contract
    leg = {
        "id": 1,
        "segment": "options",
        "expiry": c.expiry.strftime("%d-%b-%y").upper(),
        "lots": 1,
        "position": "B",
        "option_type": c.option_type,
        "strike_mode": "strike",
        "strike": float(c.strike),
        "entry_price": float(selection.limit_price),
        "expected_symbol": c.symbol,
        "expected_quantity": 65,
    }
    cfg = {
        "name": "Neo Desk · " + p.label,
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "strategy_type": "intraday",
        "entry_time": time(9, 45),
        "exit_time": time(15, 29),
        "product": "NRML",
        "pricetype": "LIMIT",
        "legs": [leg],
        "daily_loss_limit_inr": 1000,
    }
    sid = config.get("strategy_id")
    if sid:
        row, error = native.update_strategy(sid, owner_id, cfg)
    else:
        row, error = native.create_strategy(owner_id, cfg)
        sid = row["id"] if row else None
    if error or not sid:
        desk.bind(owner_id, setup.key, None, {}, error or "Native strategy creation failed.")
        return EntryResult(False, error=error)
    desk.configure(owner_id, strategy_id=sid)
    # Only the owner-controlled start path sets live_enabled; this provider cannot enable it.
    protection = {
        **public_setup(setup),
        "option_stop": str(selection.option_stop) if selection.option_stop is not None else None,
        "option_target": None,
        "entry_limit": str(selection.limit_price),
        "tick_size": str(c.tick_size),
        "quantity": 65,
        "controlled": p.controlled,
        "index_peak": str(setup.index_reference),
        "index_stop": str(setup.initial_stop),
        "net_peak": None,
        "net_floor": None,
        "cash_trail_enabled": p.controlled,
        "cash_activation": "1000",
        "cash_distance": "250",
        "mode": mode,
        "symbol": c.symbol,
        "exchange": c.exchange,
    }
    try:
        result = start_provider_run(sid, owner_id, mode)
    except Exception:
        # Possible dispatch is never retried as a replacement. Native run/order records are authoritative.
        desk.configure(
            owner_id,
            activation="Stopped",
            status="Native submission outcome is uncertain. Reconcile before restarting.",
        )
        raise
    desk.bind(owner_id, setup.key, result.run_id, protection, result.error)
    return EntryResult(result.ok, result.run_id, result.error)
