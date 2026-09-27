"""Disabled-by-default frozen ML Flow adapter; only broker-observed bars score."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.research.costs import execution_economics, validate_cost_dates
from services.research.dataset import digest
from services.research.ml import require_recent_seed
from services.research.ml_artifact import validate_artifact
from services.research.ml_live import entry_plan, score_observed
from services.research.replay import FILTER_RULES
from services.risk.admission import ML_RISK_RECIPE
from services.risk.qualification import final_screen_passes
from services.strategy_module import scalping

IST = ZoneInfo("Asia/Kolkata")
MAX_CONTRACTS = 80


def require_replay_pacing(strategy_id, mode, signal_at, session_close):
    """Apply the filtered replay's next-bar cutoff, filled-entry cap and cooldown."""
    from database import strategy_module_db

    signal = datetime.fromisoformat(signal_at)
    next_bar = signal + timedelta(minutes=1)
    if next_bar.date() != signal.date() or next_bar.strftime("%H:%M") >= session_close:
        raise scalping.WaitingForSignal("ML next-bar entry is beyond the research session close")
    pace = strategy_module_db.ml_filled_entry_pace(strategy_id, mode, signal.date().isoformat())
    if pace["active"]:
        raise scalping.WaitingForSignal("An earlier ML entry still has open exposure")
    if pace["entries"] >= FILTER_RULES["daily_trade_cap"]:
        raise scalping.WaitingForSignal("ML daily filled-entry cap has been reached")
    if pace["last_exit"] and signal - datetime.fromisoformat(pace["last_exit"]) < timedelta(
        minutes=FILTER_RULES["cooldown_minutes"]
    ):
        raise scalping.WaitingForSignal("ML post-exit cooldown has not elapsed")


def frozen_model(owner, strategy):
    from database.trading_research_db import get_store
    from services.research.jobs import historical_ml_reason

    run_id = strategy.get("ml_final_run_id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("ML strategy has no frozen final run")
    store = get_store()
    final = store.get_run(owner, run_id)
    if not final or not final_screen_passes(final) or final.get("parent_run_id") is None:
        raise ValueError("ML final historical screen is unavailable or failed")
    parent = store.get_run(owner, final["parent_run_id"])
    reason = historical_ml_reason(final, parent or {})
    if reason:
        raise ValueError(reason)
    if not parent or parent.get("kind") != "ml" or not parent.get("frozen_at"):
        raise ValueError("ML frozen development model is unavailable")
    artifact = (parent.get("report") or {}).get("ml", {}).get("artifact")
    validate_artifact(artifact)
    model_hash = digest(artifact)
    if (
        model_hash != strategy.get("ml_model_hash")
        or model_hash != (parent.get("report") or {}).get("ml", {}).get("model_hash")
        or model_hash != (final.get("report") or {}).get("ml", {}).get("model_hash")
        or parent.get("configuration_hash") != final.get("configuration_hash")
    ):
        raise ValueError(
            "ML model changed after final evaluation; qualification evidence is invalid"
        )
    return final, artifact


def _history_rows(client, symbol, exchange, now, *, minutes=1, volume_required):
    from services.indicator_service import (
        _market_bar_time,
        completed_history_records,
        fetch_history_cached,
    )

    response = fetch_history_cached(
        client,
        symbol,
        exchange,
        f"{minutes}m",
        (now - timedelta(days=14)).date().isoformat(),
        now.date().isoformat(),
        source="api",
        now=now,
    )
    if response.get("status") != "success" or not isinstance(response.get("data"), list):
        raise scalping.WaitingForSignal(f"Broker one-minute history is unavailable for {symbol}")
    source = completed_history_records(response["data"], f"{minutes}m", now)
    if len(source) > 6000:
        raise ValueError(f"Broker history exceeds the {symbol} bar bound")
    rows = []
    for item in source:
        start = _market_bar_time(item.get("timestamp"))
        if start is None or start.second or start.microsecond:
            raise ValueError(f"Broker {symbol} history has an invalid bar start")
        end = start + timedelta(minutes=minutes)
        try:
            prices = {key: float(item[key]) for key in ("open", "high", "low", "close")}
            volume = item.get("volume")
            volume = float(volume) if volume is not None else None
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Broker {symbol} candle has missing prices or volume") from exc
        if volume_required and (volume is None or volume < 0):
            raise ValueError(f"Broker {symbol} option volume is unavailable")
        rows.append({"timestamp": end.isoformat(), "symbol": symbol, **prices, "volume": volume})
    return sorted(rows, key=lambda row: row["timestamp"])


def _contracts(underlying_close, now):
    from database.symbol import SymToken, engine
    from services.option_symbol_service import construct_option_symbol
    from services.strategy_module.symbol_resolver import _parse_expiry

    with Session(engine) as db:
        tokens = list(
            db.scalars(
                select(SymToken).where(SymToken.exchange == "NFO", SymToken.symbol.like("NIFTY%"))
            )
        )
    contracts = []
    for token in tokens:
        expiry = _parse_expiry(token.expiry)
        day_distance = (expiry - now.date()).days if expiry else -1
        option_type = token.symbol[-2:]
        if (
            option_type not in {"CE", "PE"}
            or not 1 <= day_distance <= 7
            or token.strike is None
            or abs(token.strike - underlying_close) > 500
        ):
            continue
        if token.symbol != construct_option_symbol(
            "NIFTY", expiry.strftime("%d%b%y"), token.strike, option_type
        ):
            continue
        if not token.lotsize or not token.tick_size:
            raise ValueError(f"Master contract {token.symbol} lacks lot size or tick size")
        contracts.append(
            {
                "symbol": token.symbol,
                "exchange": "NFO",
                "expiry": expiry.isoformat(),
                "master_expiry": token.expiry,
                "strike": float(token.strike),
                "option_type": option_type,
                "lot_size": int(token.lotsize),
                "multiplier": 1,
                "tick_size": float(token.tick_size),
            }
        )
    if not contracts:
        raise scalping.WaitingForSignal(
            "No eligible current NIFTY option contracts in the broker master"
        )
    if len(contracts) > MAX_CONTRACTS:
        raise ValueError("Eligible NIFTY option universe exceeds the bounded ML adapter")
    return contracts


def observed_data(client, owner, final, now):
    from database.trading_research_db import get_store

    source = get_store().get_dataset(owner, final["dataset_id"])
    if source is None:
        raise ValueError("ML model dataset metadata is unavailable")
    metadata = source["metadata"]
    symbol = metadata["underlying_symbol"]
    if symbol != "NIFTY" or metadata.get("execution_bar_minutes", metadata["bar_minutes"]) != 1:
        raise ValueError("ML adapter requires NIFTY one-minute source rules")
    bar_minutes = metadata["bar_minutes"]
    underlying = _history_rows(
        client, symbol, "NSE_INDEX", now, minutes=bar_minutes, volume_required=False
    )
    days = sorted(
        {
            row["timestamp"][:10]
            for row in underlying
            if row["timestamp"][:10] <= now.date().isoformat()
        }
    )
    if len(days) < 2 or days[-1] != now.date().isoformat():
        raise scalping.WaitingForSignal(
            "Collecting two complete index sessions for the frozen feature recipe"
        )
    try:
        require_recent_seed(days[-2], days[-1])
    except ValueError as exc:
        raise scalping.WaitingForSignal(str(exc)) from exc
    keep = set(days[-2:])
    session_open = metadata.get("session_open", "09:15")
    session_close = metadata["session_close"]
    underlying = [
        row
        for row in underlying
        if row["timestamp"][:10] in keep and session_open < row["timestamp"][11:16] <= session_close
    ]
    prior = [row for row in underlying if row["timestamp"][:10] == days[-2]]
    if (
        not prior
        or prior[0]["timestamp"][11:16]
        != (
            datetime.fromisoformat(f"{days[-2]}T{session_open}:00+05:30")
            + timedelta(minutes=bar_minutes)
        ).strftime("%H:%M")
        or prior[-1]["timestamp"][11:16] != session_close
    ):
        raise scalping.WaitingForSignal(
            "Previous index session is incomplete for the frozen feature seed"
        )
    if any(
        datetime.fromisoformat(b["timestamp"]) - datetime.fromisoformat(a["timestamp"])
        != timedelta(minutes=bar_minutes)
        for a, b in zip(prior, prior[1:], strict=False)
    ):
        raise scalping.WaitingForSignal("Previous index session contains a one-minute gap")
    today = [row for row in underlying if row["timestamp"][:10] == days[-1]]
    if not today or today[0]["timestamp"][11:16] != (
        datetime.fromisoformat(f"{days[-1]}T{session_open}:00+05:30")
        + timedelta(minutes=bar_minutes)
    ).strftime("%H:%M"):
        raise scalping.WaitingForSignal("Current index session has not completed its causal warmup")
    from services.research.ml_live import validate_completed_rows

    validate_completed_rows(today, now, symbol, minutes=bar_minutes)
    contracts = _contracts(today[-1]["close"], now)
    rows = list(underlying)
    for contract in contracts:
        history = _history_rows(client, contract["symbol"], "NFO", now, volume_required=True)
        rows.extend(
            row
            for row in history
            if row["timestamp"][:10] == days[-1]
            and session_open < row["timestamp"][11:16] <= session_close
        )
    return {"metadata": {**metadata, "contracts": contracts}, "rows": rows}


def prepare(strategy, owner, api_key, mode):
    from database import flow_db, trading_risk_db
    from services.flow_openalgo_client import FlowOpenAlgoClient

    origin = scalping.require_origin(strategy, owner, mode)
    final, artifact = frozen_model(owner, strategy)
    config = final["configuration"]
    if config.get("risk_recipe") != ML_RISK_RECIPE:
        raise ValueError("Frozen ML admission risk recipe differs from executable admission")
    if config.get("capital") != 25000:
        raise ValueError("Frozen ML allocation differs from the ₹25,000 research allocation")
    current_costs = trading_risk_db.get_costs(owner)
    if execution_economics(current_costs) != execution_economics(config["costs"]):
        raise ValueError("Current execution rates differ from the frozen ML research rates")
    client = FlowOpenAlgoClient(api_key)
    client.broker_connection_id = strategy["broker_connection_id"]
    now = datetime.now(IST)
    validate_cost_dates(current_costs, [now.date().isoformat()])
    data = observed_data(client, owner, final, now)
    if (
        strategy.get("entry_time") != data["metadata"]["session_open"]
        or strategy.get("exit_time") != data["metadata"]["session_close"]
    ):
        raise ValueError("ML strategy session window differs from frozen research")
    try:
        scored = score_observed(
            data,
            artifact,
            config["costs"],
            capital=25000,
            threshold=config["ml_settings"]["threshold"],
            now=now,
            risk_recipe=config["risk_recipe"],
        )
    except ValueError as exc:
        raise scalping.WaitingForSignal(str(exc)) from exc
    require_replay_pacing(
        strategy["id"], mode, scored["signal_at"], data["metadata"]["session_close"]
    )
    quote = scalping.quote_price(client, scored["symbol"], "NFO")
    snapshot, ledger = trading_risk_db.budget_state(
        owner, mode, datetime.now(IST).date().isoformat()
    )
    if Decimal(str(snapshot["capital"])) != Decimal("25000"):
        raise ValueError(
            f"{mode.title()} capital allocation must be reviewed to ₹25,000 before ML entry"
        )
    plan = entry_plan(
        scored["contract"],
        entry=quote,
        atr=scored["atr"],
        costs=config["costs"],
        capital=25000,
        day=now.date().isoformat(),
        equity=snapshot["equity"],
        peak=snapshot["peak_equity"],
        ledger=ledger,
        paused=snapshot["paused"],
        risk_recipe=config["risk_recipe"],
    )
    if (datetime.now(IST) - datetime.fromisoformat(scored["signal_at"])).total_seconds() > 55:
        raise scalping.WaitingForSignal("Frozen ML signal expired while fetching broker evidence")
    scalping.require_origin(strategy, owner, mode)
    require_replay_pacing(
        strategy["id"], mode, scored["signal_at"], data["metadata"]["session_close"]
    )
    claim = flow_db.claim_execution_bar(
        origin["execution_id"], origin["workflow_id"], datetime.fromisoformat(scored["signal_at"])
    )
    if claim != "claimed":
        raise scalping.WaitingForSignal(
            "ML signal was already evaluated"
            if claim == "duplicate"
            else "ML signal claim unavailable"
        )
    signal_at = datetime.fromisoformat(scored["signal_at"])
    close_at = datetime.fromisoformat(
        f"{signal_at.date().isoformat()}T{data['metadata']['session_close']}:00+05:30"
    )
    return {
        **scored,
        **plan,
        "profile": "ml_forest",
        "exit_basis": "option_premium",
        "deadline": min(
            signal_at + timedelta(minutes=config["ml_settings"]["max_hold_minutes"]), close_at
        ).isoformat(),
        "automation_epoch": strategy.get("automation_state_updated_at"),
    }


def resolved_leg(strategy, context):
    """Keep the scored master contract and adaptive quantity through dispatch."""
    contract = context["contract"]
    leg = strategy["legs"][0]
    if context["symbol"] != contract["symbol"] or context["direction"] != contract["option_type"]:
        raise ValueError("ML scored contract identity changed")
    return {
        "leg_id": leg.get("id") or leg.get("leg_id") or 1,
        "position": "B",
        "symbol": contract["symbol"],
        "exchange": "NFO",
        "segment": "options",
        "lot_size": contract["lot_size"],
        "underlying": "NIFTY",
        "lots": context["lots"],
        "quantity": context["quantity"],
        "expiry": contract["master_expiry"],
        "expiry_fallback": False,
        "expiry_rank": "scored",
        "sl_pts": context["sl_pts"],
        "target_pts": context["target_pts"],
        "trail": {},
        "risk_unit": "points",
        "ltp": None,
        "underlying_ltp": None,
        "scalp_context": dict(context),
    }
