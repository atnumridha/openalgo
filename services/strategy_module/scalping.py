"""Closed-candle scalping adapters. Orders and risk remain in Strategy Module."""

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd

from services.research.ema_scalp import _validate, indicators, signals
from services.research.groww_algorithmic import features as regime_features
from services.research.groww_algorithmic import signals as regime_signals
from services.research.scalp_strategies import ema_reversal_signals, macd_features, macd_signals
from services.research.tradejini_scalping import tradejini_signals
from services.risk import PositionRisk, evaluate_position
from services.risk.budget import current_policy
from services.risk.cash_exit import (
    CASH_RECIPES,
    CASH_RISK_RECIPE,
    TECHNICAL_PROFIT_RECIPES,
    pacing_config,
    recipe_exit,
)

IST = ZoneInfo("Asia/Kolkata")
PROFILES = {
    "ml_forest": "NIFTY Frozen RandomForest",
    "regime50200": "NIFTY EMA 50/200 + Daily Regime",
    "ema915": "NIFTY EMA 9/15 + Bank Nifty",
    "box15": "NIFTY Opening Box Breakout",
    "macd200": "NIFTY MACD + EMA 200",
    "ema5": "NIFTY 5 EMA Reversal",
    "sma_macd": "NIFTY SMA 5/34 Zero-Cross (Research)",
    "bollinger": "NIFTY Bollinger 20/2 Reversal (Research)",
}
TOP_PROFILES = ("regime50200", "ema915", "box15")
ITM_PROFILES = {"ema915", "macd200", "ema5"}


class WaitingForSignal(ValueError):
    """Normal no-entry outcome, not a failed broker order."""


def closed_frame(records, interval, now):
    from services.indicator_service import _market_bar_time, completed_history_records

    minutes = {"1m": 1, "5m": 5}[interval]
    records = completed_history_records(records, interval, now)
    if not records or len(records) > 20000:
        raise WaitingForSignal("Collecting history: no usable completed candles")
    frame = pd.DataFrame(records)
    starts = pd.DatetimeIndex([_market_bar_time(t) for t in frame.timestamp])
    frame.index = starts + pd.Timedelta(minutes=minutes)
    frame = frame[["open", "high", "low", "close"]].astype(float).sort_index()
    _validate(frame)
    if ((starts.second != 0) | (starts.microsecond != 0) | (starts.minute % minutes != 0)).any():
        raise ValueError("Candles are not aligned to the required interval")
    return frame


def closed_daily_frame(records, now):
    """Require complete prior-session history; never use a forming daily close."""
    from database.market_calendar_db import get_effective_session_window
    from services.indicator_service import _market_bar_time, completed_history_records

    records = completed_history_records(records, "D", now)
    if not 272 <= len(records) <= 1000:
        raise WaitingForSignal("Daily regime needs at least 272 completed daily candles")
    frame = pd.DataFrame(records)
    frame.index = pd.DatetimeIndex([_market_bar_time(t) for t in frame.timestamp]).normalize()
    frame = frame[["open", "high", "low", "close"]].astype(float).sort_index()
    _validate(frame)
    previous = now.date() - timedelta(days=1)
    for _ in range(14):
        if get_effective_session_window(previous, "NSE") is not None:
            break
        previous -= timedelta(days=1)
    if frame.index[-1].date() != previous:
        raise WaitingForSignal("Daily regime needs the previous trading session's candle")
    return frame


def signals_for_profile(profile, *, five=None, minute=None, bank=None, daily=None):
    """Use the same closed-bar rule functions as the frozen research variants."""
    if profile in {"sma_macd", "bollinger"}:
        from services.research.conlan import rule_signals

        if len(five) < 35:
            raise WaitingForSignal("Research rules need 35 completed five-minute candles")
        return rule_signals(five, profile)
    if profile == "ema915":
        return signals(indicators(five), indicators(bank))
    if profile == "regime50200":
        if len(five) < 200:
            raise WaitingForSignal("EMA 50/200 needs 200 completed five-minute candles")
        return regime_signals(regime_features(five, daily), "timing_50_200")
    if profile == "box15":
        # Research range construction uses pandas' named timezone. Broker candles
        # use ZoneInfo; normalize to avoid mixed-timezone range construction.
        minute = minute.copy()
        minute.index = minute.index.tz_convert("Asia/Kolkata")
        return tradejini_signals(minute, 1, "box")
    if profile == "macd200":
        if len(five) < 604:
            raise WaitingForSignal("MACD needs 604 completed five-minute candles")
        return macd_signals(macd_features(five))
    if profile == "ema5":
        return ema_reversal_signals(five, minute)
    raise ValueError("Unknown scalping profile")


def latest_signal(profile, client, now):
    from services.indicator_service import current_completed_bar_start, fetch_history_cached

    if profile not in PROFILES:
        raise ValueError("Unknown scalping profile")
    interval = "1m" if profile in {"box15", "ema5"} else "5m"
    expected = current_completed_bar_start(interval, "NSE", now)
    if expected is None:
        raise WaitingForSignal("Waiting for the next completed market candle")
    expected = pd.Timestamp(expected) + pd.Timedelta(minutes=1 if interval == "1m" else 5)

    def history(symbol, size, days):
        response = fetch_history_cached(
            client,
            symbol,
            "NSE_INDEX",
            size,
            (now - timedelta(days=days)).date().isoformat(),
            now.date().isoformat(),
            now=now,
        )
        if not response or response.get("status") != "success":
            raise WaitingForSignal(f"Market history unavailable for {symbol} {size}")
        frame = (closed_daily_frame if size == "D" else lambda r, t: closed_frame(r, size, t))(
            response.get("data") or [], now
        )
        return frame

    if profile == "box15":
        result = signals_for_profile(profile, minute=history("NIFTY", "1m", 2))
    else:
        five = history("NIFTY", "5m", 30)
        extra = {}
        if profile == "ema915":
            extra["bank"] = history("BANKNIFTY", "5m", 30)
        elif profile == "regime50200":
            extra["daily"] = history("NIFTY", "D", 600)
        elif profile == "ema5":
            extra["minute"] = history("NIFTY", "1m", 2)
        result = signals_for_profile(profile, five=five, **extra)
    if expected not in result.index or result.loc[expected, "direction"] not in {"CE", "PE"}:
        raise WaitingForSignal("Waiting for a fresh qualifying signal")
    signal = result.loc[expected].to_dict()
    signal["timestamp"] = expected.isoformat()
    # A late evaluation must not turn an old 5-minute signal into a new entry.
    if not 0 <= (now - expected.to_pydatetime()).total_seconds() <= 55:
        raise WaitingForSignal("Signal expired; waiting for the next setup")
    return signal


def index_context(signal, entry):
    sign = 1 if signal["direction"] == "CE" else -1
    stop = float(signal.get("stop_price", signal["low"] if sign == 1 else signal["high"]))
    entry = float(entry)
    distance = sign * (entry - stop)
    if not all(isfinite(p) and p > 0 for p in (entry, stop)) or distance <= 0:
        raise ValueError("Index entry has crossed the signal stop")
    at = datetime.fromisoformat(signal["timestamp"])
    return {
        "direction": signal["direction"],
        "signal_at": at.isoformat(),
        "entry": entry,
        "stop": stop,
        "target": entry + sign * 2 * distance,
        "deadline": (at + timedelta(minutes=15)).isoformat(),
    }


def trade_context(profile, signal, entry):
    if profile not in PROFILES:
        raise ValueError("Unknown scalping profile")
    # Validate the original technical signal; its index target is not the new exit.
    original = {} if profile == "box15" else index_context(signal, entry)
    at = datetime.fromisoformat(signal["timestamp"])
    return original | {
        "direction": signal["direction"],
        "signal_at": at.isoformat(),
        "deadline": (at + timedelta(minutes=15)).isoformat(),
        "exit_basis": "option_premium",
        "profile": profile,
        "risk_recipe": CASH_RISK_RECIPE,
        "risk_policy_version": current_policy().version,
        "pacing": pacing_config(),
    }


def require_origin(strategy, owner, mode):
    """Fresh identity/epoch check, repeated under the account admission lock."""
    from database import trading_risk_db
    from database.strategy_module_db import strategy_to_dict
    from services.research.qualification_context import (
        _read_workflows,
        strategy_digest,
        workflow_digest,
    )
    from services.research.qualification_execution import current_flow_origin
    from services.strategy_module.automation_control import _read_strategy, require_automation_entry
    from services.strategy_module.workflow_link import validate_workflow_link

    origin = current_flow_origin()
    if not origin:
        raise ValueError("Use the linked Flow automation to run this scalping strategy")
    allowed, reason = require_automation_entry(strategy["id"], owner)
    if not allowed:
        raise ValueError(reason)
    current = _read_strategy(strategy["id"], owner)
    current_config = strategy_to_dict(current) if current is not None else None
    if current_config is None or strategy_digest(current_config) != strategy_digest(strategy):
        raise ValueError("Saved scalping rules changed during evaluation")
    if current_config.get("automation_state_updated_at") != strategy.get(
        "automation_state_updated_at"
    ):
        raise ValueError("Scalping automation was restarted during evaluation")
    if not trading_risk_db.policy_enabled(owner):
        raise ValueError("The shared capital profile must remain enabled for scalping")
    if bool(current.live_enabled) != (mode == "live"):
        raise ValueError("Saved scalping mode changed during evaluation")
    flows = _read_workflows(owner, current_config)
    link, error = validate_workflow_link(current, flows, require_sandbox=False)
    if (
        error
        or link is None
        or link.mode != mode
        or not link.active
        or link.workflow_id != origin["workflow_id"]
    ):
        raise ValueError(error or "Scalping Flow mode or activation does not match")
    if workflow_digest(flows) != origin["workflow_hash"]:
        raise ValueError("Scalping Flow changed during evaluation")
    return origin


def dispatch_reason(metadata, mode):
    if not metadata:
        return None
    try:
        stamp = datetime.fromisoformat(metadata["signal_at"])
        if not 0 <= (datetime.now(IST) - stamp).total_seconds() <= 55:
            return "Scalping signal expired before order submission"
        require_origin(metadata["strategy"], metadata["owner"], mode)
    except (ValueError, TypeError, KeyError):
        return "Scalping execution identity or automation changed before submission"
    return None


def prepare(strategy, owner, api_key, mode):
    """Re-evaluate on the server; HTTP start/webhook data cannot supply a signal."""
    from database import flow_db, trading_risk_db
    from services.flow_openalgo_client import FlowOpenAlgoClient

    origin = require_origin(strategy, owner, mode)
    if not trading_risk_db.policy_enabled(owner):
        raise ValueError("Enable the shared capital profile and verified costs in Research first")
    client = FlowOpenAlgoClient(api_key)
    client.broker_connection_id = strategy["broker_connection_id"]
    now = datetime.now(IST)
    signal = latest_signal(strategy["scalp_profile"], client, now)
    profile = strategy["scalp_profile"]
    context = trade_context(
        profile, signal, None if profile == "box15" else quote_price(client, "NIFTY", "NSE_INDEX")
    )
    from services.strategy_module.ml_forest import require_replay_pacing

    require_replay_pacing(
        strategy["id"], mode, signal["timestamp"], "15:20", pacing=context["pacing"]
    )
    context["automation_epoch"] = strategy.get("automation_state_updated_at")
    if datetime.fromisoformat(context["deadline"]).strftime("%H:%M") > "15:20":
        raise WaitingForSignal("Too late for a complete 15-minute scalp")
    if (datetime.now(IST) - datetime.fromisoformat(context["signal_at"])).total_seconds() > 55:
        raise WaitingForSignal("Signal expired while fetching market data")
    claim = flow_db.claim_execution_bar(
        origin["execution_id"], origin["workflow_id"], datetime.fromisoformat(context["signal_at"])
    )
    if claim != "claimed":
        raise WaitingForSignal(
            "This signal was already evaluated"
            if claim == "duplicate"
            else "Signal claim unavailable"
        )
    return context


def quote_price(client, symbol, exchange):
    from services.strategy_module.portfolio_governor import GovernorPolicy, _quote_timestamp

    response = client.get_quotes(symbol, exchange)
    data = response.get("data") or {}
    price = float(data.get("ltp") or 0)
    if response.get("status") != "success" or not isfinite(price) or price <= 0:
        raise ValueError("Current market quote unavailable")
    stamp = _quote_timestamp(data.get("timestamp"))
    policy = GovernorPolicy()
    if (
        stamp is None
        or not -policy.max_quote_future_seconds
        <= (datetime.now(IST) - stamp).total_seconds()
        <= policy.max_quote_age_seconds
    ):
        raise ValueError("Fresh native quote timestamp required")
    return price


def require_option_liquidity(leg, context, client):
    """ATM presets require a fresh completed option candle with >=10 lots volume."""
    from services.indicator_service import (
        _market_bar_time,
        completed_history_records,
        fetch_history_cached,
    )

    now = datetime.now(IST)
    response = fetch_history_cached(
        client,
        leg["symbol"],
        leg["exchange"],
        "5m",
        (now - timedelta(days=2)).date().isoformat(),
        now.date().isoformat(),
        now=now,
    )
    rows = completed_history_records((response or {}).get("data") or [], "5m", now)
    expected = pd.Timestamp(context["signal_at"]).floor("5min") - pd.Timedelta(minutes=5)
    if (
        not rows
        or response.get("status") != "success"
        or _market_bar_time(rows[-1].get("timestamp")) != expected
    ):
        raise WaitingForSignal("Waiting for the completed option candle at the signal time")
    row = rows[-1]
    try:
        volume = float(row.get("volume", 0))
        prices = [float(row[c]) for c in ("open", "high", "low", "close")]
        opening, high, low, close = prices
        valid = (
            all(isfinite(x) and x > 0 for x in prices)
            and low <= min(opening, close) <= max(opening, close) <= high
        )
    except (TypeError, ValueError, KeyError):
        valid, volume = False, 0
    if not valid or not isfinite(volume) or volume < int(leg["lot_size"]) * 10:
        raise WaitingForSignal("Option liquidity needs at least 10 lots in the completed candle")


def protect_leg(leg, context, client):
    """New contexts preserve technical stops; recorded contexts retain their recipe."""
    from services.strategy_module.symbol_resolver import _parse_expiry

    expiry = _parse_expiry(leg["expiry"])
    if expiry is None:
        raise ValueError("Option expiry is unavailable")
    days = (expiry - datetime.now(IST).date()).days
    profile = context.get("profile", "ema915")
    minimum_days = 1 if profile in ITM_PROFILES else 0
    if not minimum_days <= days <= 7 or leg.get("expiry_fallback"):
        raise ValueError(f"Scalping requires an expiry {minimum_days}–7 days away")
    quantity = int(leg["quantity"])
    if quantity <= 0 or quantity != int(leg["lot_size"]):
        raise ValueError("Scalping requires exactly one option lot")
    if context.get("risk_recipe") in TECHNICAL_PROFIT_RECIPES:
        from services.strategy_module.executable_price import executable_quote
        premium = float(executable_quote(leg, client.get_quotes(leg["symbol"], leg["exchange"])).ask)
    else:
        premium = quote_price(client, leg["symbol"], leg["exchange"])
    if premium * quantity > 20000:
        raise ValueError("One option lot exceeds the ₹20,000 premium ceiling")
    if profile in {"box15", "regime50200"}:
        require_option_liquidity(leg, context, client)
    # Retain the profile technical distance; new recipes skip when its risk cannot fit.
    # Unversioned recorded contexts retain their legacy premium protection.
    step = Decimal("0.05")
    stop_points = (
        Decimal("10")
        if profile == "box15"
        else (
            min(Decimal("800") / quantity, Decimal(str(premium)) * Decimal("0.2")) / step
        ).to_integral_value(rounding=ROUND_DOWN)
        * step
    )
    if stop_points <= 0 or stop_points >= premium:
        raise ValueError("Option stop cannot be represented at the price tick")
    target_points = 20 if profile == "box15" else None
    if context.get("risk_recipe") in CASH_RECIPES:
        stop, target, gross = recipe_exit(premium, stop_points, leg, context["risk_recipe"])
        stop_points = Decimal(str(premium)) - stop
        target_points = float(target - Decimal(str(premium)))
        context["gross_planned_risk"] = float(gross)
    leg.update(
        sl_pts=float(stop_points),
        target_pts=target_points,
        trail={},
        risk_unit="points",
    )
    context["premium_stop_points"] = float(stop_points)
    context["premium_target_points"] = leg["target_pts"]
    context["option_symbol"] = leg["symbol"]
    leg["scalp_context"] = dict(context)
    return leg


def exit_reason(context, now, price):
    if now >= datetime.fromisoformat(context["deadline"]):
        return "scheduler"
    if price is None or context.get("exit_basis") == "option_premium":
        return None
    risk = PositionRisk(
        entry_price=context["entry"],
        quantity=1,
        side="BUY" if context["direction"] == "CE" else "SELL",
        stop_price=context["stop"],
        target_price=context["target"],
    )
    decision = evaluate_position(risk, price)
    if decision.breached:
        return "overall_sl" if decision.reason.value == "sl" else "overall_target"
    return None


def monitor(*, deadlines_only=False):
    """One shared job; durable run context survives worker restarts."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from database import strategy_module_db as store
    from services.flow_openalgo_client import FlowOpenAlgoClient
    from services.strategy_module import engine
    from utils.logging import get_logger

    logger = get_logger(__name__)
    with Session(store.engine) as db:
        rows = list(
            db.execute(
                select(
                    store.SmStrategyRun.id,
                    store.SmStrategyRun.scalp_context,
                    store.SmStrategyRun.broker_connection_id,
                    store.SmStrategy.user_id,
                )
                .join(store.SmStrategy, store.SmStrategy.id == store.SmStrategyRun.strategy_id)
                .where(
                    store.SmStrategyRun.stopped_at.is_(None),
                    store.SmStrategy.scalp_profile.is_not(None),
                )
            )
        )
    # The separate deadline-only job performs no broker calls. Record intent
    # for every due run; the existing stop reconciler owns all order I/O.
    for run_id, context, connection_id, owner in rows:
        try:
            reason = exit_reason(context, datetime.now(IST), None) if context else "error"
            if not deadlines_only and not reason and context.get("exit_basis") != "option_premium":
                client = FlowOpenAlgoClient(engine._api_key_for(owner))
                client.broker_connection_id = connection_id
                price = quote_price(client, "NIFTY", "NSE_INDEX")
                reason = exit_reason(context, datetime.now(IST), price)
            if reason:
                if not store.request_run_stop(run_id, reason):
                    logger.error("Could not persist scalp exit for run %s", run_id)
        except Exception:
            logger.exception(
                "Scalping check unavailable for run %s; premium stop remains managed", run_id
            )
        finally:
            store.db_session.remove()


def monitor_deadlines():
    monitor(deadlines_only=True)
