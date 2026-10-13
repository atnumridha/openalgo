"""Annotations stay on their exact instrument and price scale."""

from datetime import datetime

from .types import IST


def risk_overlay(instrument_id, owned_trade):
    p = owned_trade
    if not p or not p.get("quantity") or not p.get("entry_price"):
        return []
    if instrument_id == p.get("exchange", "") + ":" + p.get("symbol", ""):
        levels = [
            ("BUY " + p.get("direction", ""), p.get("entry_price")),
            ("SL / trail", p.get("option_stop")),
            ("TARGET", p.get("option_target")),
        ]
    elif instrument_id == "NSE_INDEX:NIFTY":
        levels = [
            ("Index entry reference", p.get("index_reference")),
            ("Index SL / trail", p.get("index_stop")),
            ("Index 6R target", p.get("target")),
        ]
    else:
        return []
    return [
        {"label": label, "price": str(price), "run_id": p["run_id"], "kind": "executed_owned"}
        for label, price in levels
        if price is not None
    ]


def chart_view(owner_id, instrument_id, interval):
    from database import neo_desk_db as desk
    from services.strategy_module import state

    if interval not in ("1m", "3m", "5m", "15m", "30m", "1h", "1d"):
        raise ValueError("Choose an available chart interval.")
    exchange, sep, symbol = instrument_id.partition(":")
    if (
        not sep
        or exchange not in ("NFO", "NSE_INDEX", "BFO", "BSE_INDEX", "NSE", "BSE")
        or not symbol
        or len(symbol) > 100
    ):
        raise ValueError("Choose an exact chart instrument.")
    overlays = []
    for rid in desk.managed_run_ids(owner_id):
        p = desk.get_run_protection(owner_id, rid) or {}
        snap = state.get_run_state(rid) or {}
        leg = snap.get("legs", {}).get("1", {})
        overlays += risk_overlay(
            instrument_id,
            {**p, "run_id": rid, "entry_price": leg.get("entry_avg"), "quantity": leg.get("qty")},
        )
    return {
        "instrument_id": instrument_id,
        "interval": interval,
        "overlays": overlays,
        "source": "Native confirmed owned fills and protection",
        "observed_at": datetime.now(IST).isoformat(),
        "preview_note": "Chart indicators are visual; strategy decisions use confirmed 15-minute NIFTY bars. Index 6R is not an option-cash return.",
    }
