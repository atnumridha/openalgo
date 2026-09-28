"""Receiver signal preparation; the existing engine owns orders and risk."""

from datetime import datetime, timedelta

import pandas as pd

from services.risk.budget import current_policy
from services.risk.cash_exit import pacing_config
from services.risk.option_structure import STRUCTURE_RECIPE
from services.strategy_module import receiver_rules, scalping


def warm_option_history(strategy, api_key):
    """Resolve and subscribe one exact long-option ATM pair; never place orders.

    Quote and expiry resolution use the same API key whose durable account pin
    is checked on both sides of resolution. Reuse one underlying tick for CE
    and PE, so crossing an ATM boundary cannot warm unrelated strikes.
    """
    from services.kotak_mcx_candles import warm_kotak_mcx_options
    from services.strategy_module.live_protection import _active_kotak_pin
    from services.strategy_module.symbol_resolver import resolve_leg

    pin = strategy.get("broker_connection_id")
    if not pin or not _active_kotak_pin(api_key, pin):
        raise scalping.WaitingForSignal(
            "MCX option warmup requires the strategy's active Kotak connection"
        )
    legs = strategy.get("legs") or []
    if (
        len(legs) != 1
        or legs[0].get("segment") != "options"
        or legs[0].get("position") != "B"
        or legs[0].get("lots") != 1
        or legs[0].get("strike_mode") != "atm"
        or legs[0].get("atm_offset") != "ATM"
    ):
        raise ValueError("Receiver warmup requires one long ATM option lot")
    symbols, underlying_ltp = [], None
    for direction in ("CE", "PE"):
        request = dict(legs[0], option_type=direction, action="BUY", position="B")
        outcome = resolve_leg(
            request,
            strategy["underlying"],
            strategy["underlying_exchange"],
            strategy.get("strategy_type"),
            api_key=api_key,
            underlying_ltp=underlying_ltp,
        )
        if not outcome.ok:
            raise scalping.WaitingForSignal(
                f"MCX ATM {direction} contract unavailable: {outcome.error}"
            )
        underlying_ltp = outcome.underlying_ltp
        symbols.append(outcome.symbol)
    if not _active_kotak_pin(api_key, pin):
        raise scalping.WaitingForSignal("Kotak connection changed during MCX option resolution")
    return warm_kotak_mcx_options(api_key, pin, symbols)


def prepare(strategy, owner, api_key, mode):
    from database import flow_db
    from database import strategy_module_db as store
    from services.flow_openalgo_client import FlowOpenAlgoClient
    from services.indicator_service import current_completed_bar_start, fetch_history_cached
    from services.option_symbol_service import resolve_underlying_quote
    from services.strategy_module.ml_forest import require_replay_pacing
    from services.strategy_module.portfolio_governor import EntryFacts, entry_window_refusal
    from services.strategy_module.signal_review import RULES

    origin = scalping.require_origin(strategy, owner, mode)
    profile = strategy["scalp_profile"]
    if profile not in receiver_rules.PROFILES:
        raise ValueError("Unknown receiver profile")
    now = datetime.now(scalping.IST)
    underlying, exchange = strategy["underlying"], strategy["underlying_exchange"]
    venue = {"NSE_INDEX": "NFO", "BSE_INDEX": "BFO"}.get(exchange, exchange)
    calendar = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange)
    audit = {
        "evaluated_at": now.isoformat(),
        "profile": profile,
        "mode": mode,
        "rule_version": receiver_rules.RULE_VERSION,
        "history": [],
    }
    try:
        gate = entry_window_refusal(
            EntryFacts(mode=mode, has_option_entry=True, entry_exchanges=(venue,)), now
        )
        if gate is not None:
            audit["entry_gate"] = gate.code
            raise scalping.WaitingForSignal(gate.message)
        if venue == "MCX":
            # Poll every minute, including between five-minute signal closes.
            # The collector needs real prior premium bars to price a stop.
            audit["option_history_warmup"] = warm_option_history(strategy, api_key)
            if audit["option_history_warmup"].get("status") == "risk_blocked":
                raise scalping.WaitingForSignal(
                    audit["option_history_warmup"].get("message", "MCX option history is blocked")
                )
        start = current_completed_bar_start("5m", calendar, now)
        if start is None:
            raise scalping.WaitingForSignal("Waiting for a completed receiver candle")
        at = pd.Timestamp(start) + pd.Timedelta(minutes=5)
        if not 0 <= (now - at.to_pydatetime()).total_seconds() <= 55:
            raise scalping.WaitingForSignal("Signal expired; waiting for the next receiver candle")
        # MCX roots must use the current future's candles, never an option or a
        # silently substituted index. The existing client pins collector data.
        symbol, history_exchange = resolve_underlying_quote(underlying, exchange)
        client = FlowOpenAlgoClient(api_key)
        client.broker_connection_id = strategy["broker_connection_id"]
        frames = {}
        for interval in ("5m", "15m"):
            response = fetch_history_cached(
                client,
                symbol,
                history_exchange,
                interval,
                (now - timedelta(days=14)).date().isoformat(),
                now.date().isoformat(),
                now=now,
            )
            if not response or response.get("status") != "success":
                raise scalping.WaitingForSignal(f"Receiver {interval} market history unavailable")
            frames[interval] = scalping.closed_frame(response.get("data") or [], interval, now)
            audit["history"].append(
                {
                    "symbol": symbol,
                    "exchange": history_exchange,
                    "interval": interval,
                    "candles": len(frames[interval]),
                    "last_bar_at": frames[interval].index[-1].isoformat(),
                }
            )
        signal = receiver_rules.evaluate(profile, frames["5m"], frames["15m"], at)
        audit["expected_bar_at"] = at.isoformat()
        audit["technical"] = {
            "profile": profile,
            "bar_at": at.isoformat(),
            "direction": signal["direction"],
            "rules": RULES[profile],
            "metrics": signal["checks"],
            **receiver_rules.diagnostics(signal),
        }
        if not signal["direction"]:
            raise scalping.WaitingForSignal(signal["reason"])
        deadline = at + timedelta(minutes=15)
        exit_time = strategy.get("exit_time") or ("22:45" if venue == "MCX" else "15:15")
        exit_text = (
            exit_time.strftime("%H:%M") if hasattr(exit_time, "strftime") else str(exit_time)[:5]
        )
        if deadline.date() != at.date() or deadline.strftime("%H:%M") > exit_text:
            raise scalping.WaitingForSignal("Too late for a complete fifteen-minute receiver trade")
        context = {
            "direction": signal["direction"],
            "signal_at": at.isoformat(),
            "deadline": deadline.isoformat(),
            "exit_basis": "option_premium",
            "profile": profile,
            "rule_version": receiver_rules.RULE_VERSION,
            "risk_recipe": STRUCTURE_RECIPE,
            "risk_policy_version": current_policy().version,
            "pacing": pacing_config(),
            "automation_epoch": strategy.get("automation_state_updated_at"),
            "underlying": underlying,
            "underlying_exchange": exchange,
            "signal": signal,
        }
        require_replay_pacing(
            strategy["id"], mode, at.isoformat(), exit_text, pacing=context["pacing"]
        )
        if not 0 <= (datetime.now(scalping.IST) - at.to_pydatetime()).total_seconds() <= 55:
            raise scalping.WaitingForSignal("Signal expired while fetching receiver history")
        claim = flow_db.claim_execution_bar(
            origin["execution_id"], origin["workflow_id"], at.to_pydatetime()
        )
        if claim != "claimed":
            raise scalping.WaitingForSignal(
                "This signal was already evaluated"
                if claim == "duplicate"
                else "Signal claim unavailable"
            )
        audit.update(stage="signal_found", reason=signal["reason"])
        return context
    except scalping.WaitingForSignal as exc:
        audit.update(stage="waiting", reason=str(exc))
        raise
    except Exception as exc:
        audit.update(stage="evaluation_failed", reason=str(exc))
        raise
    finally:
        try:
            store.record_event(
                strategy["id"],
                owner,
                "signal_evaluation",
                audit.get("reason", "Receiver evaluated"),
                payload=audit,
            )
        except Exception:
            from utils.logging import get_logger

            get_logger(__name__).exception("Could not record receiver evaluation")
