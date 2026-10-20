"""Coverage-limited long-option diagnostic with dated contract metadata."""

from collections import Counter
from contextlib import closing
from dataclasses import replace
import hashlib
import json
import sqlite3

import numpy as np
import pandas as pd

from services.kotak_assistant.analysis import fees
from .data import INDEX_DB, clean_minutes, IST
from .engine import Candidate, simulate, summarize, wilder

NEO = INDEX_DB.parents[1]
MANIFESTS = [
    NEO
    / "runtime/neo_desk/migration-20261013/backup/data/nifty-13oct-active-nse-20261011/manifest.json",
    NEO / "runtime/neo_desk/datasets/kotak-nifty-20261014/manifest.json",
]


def option_fees(contract, entry, exit_price, day):
    exchange = {"nse_fo": "NFO", "bse_fo": "BFO"}.get(contract["exchange"], contract["exchange"])
    return fees(
        entry * int(contract["lot_size"]), exit_price * int(contract["lot_size"]), exchange, 0, day
    )["total"]


def executable_premiums(d):
    """No fills on zero-volume carried quotes; holes remain visible to replay."""
    return d[np.isfinite(d.volume) & (d.volume > 0)].reset_index(drop=True)


def diagnostic(result, out):
    contracts = []
    frozen = out / "data/option-contracts.json"
    if frozen.exists():
        contracts = json.loads(frozen.read_text())
    else:
        for path in MANIFESTS:
            if path.exists():
                manifest = json.loads(path.read_text())
                if manifest.get("source", {}).get("synthetic") is False:
                    contracts.extend(manifest.get("contracts", []))
        frozen.write_text(json.dumps(contracts, indent=2))
    diagnostics = {}
    for market in ["NIFTY", "BANKNIFTY", "SENSEX"]:
        rows = [
            r
            for r in contracts
            if r["symbol"].startswith(market)
            and all(
                k in r
                for k in [
                    "valid_from",
                    "valid_to",
                    "lot_size",
                    "tick_size",
                    "expiry",
                    "option_type",
                    "strike",
                ]
            )
        ]
        if not rows:
            diagnostics[market] = {
                "status": "Not financially backtestable: no dated contract metadata covering the selected history. Cached premium candles alone cannot establish historical expiry, strike and lot eligibility.",
                "skips": {"dated_contract_metadata_unavailable": True},
            }
            continue
        m = result["markets"][market]
        c = Candidate(**m["candidate"])
        # Explicit separate premium policy. Underlying stops are not option stops.
        c = replace(c, stop_atr=1.5)
        signals = pd.read_csv(out / f"{market}-chosen-signals.csv")
        signals = signals[
            (signals.day >= m["split"]["test"]["first"])
            & (signals.day <= m["split"]["test"]["last"])
        ]
        index = pd.read_parquet(out / "data" / f"{market}.parquet").set_index("time")
        skips = Counter()
        cache = {}
        trades = []
        busy = 0
        counts = {}
        with closing(sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)) as con:
            for s in signals.itertuples(index=False):
                if s.end < busy or counts.get(s.day, 0) >= 3:
                    continue
                if s.end - 60 not in index.index:
                    skips["missing_index_price"] += 1
                    continue
                underlying = float(index.loc[s.end - 60, "close"])
                kind = "CE" if s.side == 1 else "PE"
                eligible = [
                    r
                    for r in rows
                    if r["valid_from"] <= s.day <= r["valid_to"]
                    and r["expiry"] >= s.day
                    and r["option_type"] == kind
                ]
                if not eligible:
                    skips["no_dated_eligible_contract"] += 1
                    continue
                expiry = min(r["expiry"] for r in eligible)
                # Selection uses known expiry/strike metadata and index close only.
                contract = min(
                    (r for r in eligible if r["expiry"] == expiry),
                    key=lambda r: (abs(float(r["strike"]) - underlying), float(r["strike"])),
                )
                symbol = contract["symbol"]
                if float(contract["tick_size"]) != 0.05:
                    skips["unsupported_premium_tick_size"] += 1
                    continue
                if symbol not in cache:
                    saved = out / "data" / f"{symbol}-options.parquet"
                    if saved.exists():
                        cache[symbol] = pd.read_parquet(saved)
                    else:
                        raw = [
                            json.loads(r[0])
                            for r in con.execute(
                                "SELECT payload FROM neo_chart_candle WHERE symbol=? AND interval='1m' AND trading_date BETWEEN ? AND ? ORDER BY timestamp",
                                (symbol, m["split"]["test"]["first"], m["split"]["test"]["last"]),
                            )
                        ]
                        if not raw:
                            cache[symbol] = pd.DataFrame(
                                columns=["time", "open", "high", "low", "close", "volume"]
                            )
                        else:
                            cache[symbol], _ = clean_minutes(pd.DataFrame(raw), True)
                        cache[symbol].to_parquet(saved, index=False)
                d = executable_premiums(cache[symbol])
                if d.empty:
                    skips["no_option_candles"] += 1
                    continue
                prior = d[(d.time < s.end) & (d.time >= s.end - 40 * 60)]
                if (
                    len(prior) < 15
                    or prior.time.iloc[-1] != s.end - 60
                    or (prior.time.diff().dropna() != 60).any()
                    or prior.volume.iloc[-1] <= 0
                ):
                    skips["insufficient_traded_premium_history"] += 1
                    continue
                current = d[d.time == s.end]
                if current.empty:
                    skips["missing_entry_candle"] += 1
                    continue
                previous = prior.close.shift(1)
                tr = pd.concat(
                    [
                        prior.high - prior.low,
                        (prior.high - previous).abs(),
                        (prior.low - previous).abs(),
                    ],
                    axis=1,
                ).max(axis=1)
                atr = float(wilder(tr, 14)[-1])
                if not np.isfinite(atr) or atr <= 0:
                    skips["invalid_premium_atr"] += 1
                    continue
                # Both CE and PE are bought. Use a one-contract-history frame;
                # global overlap and day limits are enforced around this call.
                sig = pd.DataFrame([dict(time=int(s.time), end=int(s.end), side=1, atr=atr)])
                d = d[(d.time >= s.end) & (d.time < s.end + 121 * 60)]
                actual = simulate(
                    d, sig, c, True, slippage=0.1, fee_rate=0, units=int(contract["lot_size"])
                )
                if not actual:
                    skips["unfillable"] += 1
                    continue
                trade = actual[0]
                counts[s.day] = counts.get(s.day, 0) + 1
                busy = (
                    trade["exit_time"]
                    if trade["net"] is not None
                    else int(pd.Timestamp(s.day + " 15:30", tz=IST).timestamp())
                )
                trade.update(
                    symbol=symbol,
                    quantity=int(contract["lot_size"]),
                    option_type=kind,
                    strike=float(contract["strike"]),
                    expiry=expiry,
                    index_entry=underlying,
                    option_policy="1.5 × option ATR; selected index strategy reward multiple and time limit",
                )
                if trade["exit"] is not None:
                    charge = option_fees(contract, trade["entry"], trade["exit"], s.day)
                    trade["fees"] = charge
                    trade["net"] = trade["gross"] - charge
                    trade["net_r"] = trade["net"] / (trade["risk"] * trade["quantity"])
                trades.append(trade)
        pd.DataFrame(trades).to_csv(out / f"{market}-option-trades.csv", index=False)
        diagnostics[market] = {
            "status": "Coverage-limited diagnostic only. Long near-ATM CE/PE, dated contract eligibility, one lot, 1.5 × premium ATR stop, selected reward/holding template, ₹0 brokerage plus dated taxes/charges and ₹0.10 adverse slippage each side. Not an independently selected or qualified option strategy.",
            "summary": summarize(trades),
            "skips": dict(skips),
            "signals_in_final_period": len(signals),
            "contract_validity_windows": sorted(
                set((r["valid_from"], r["valid_to"]) for r in rows)
            ),
        }
    result["options"] = diagnostics
    result["option_source_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (out / "data").glob("*options.parquet")
    }
    result["option_source_sha256"][frozen.name] = hashlib.sha256(frozen.read_bytes()).hexdigest()
    (out / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return diagnostics
