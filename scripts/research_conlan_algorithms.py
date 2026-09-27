"""Offline, reproducible Conlan algorithm study on local user archives.

Requires explicit --current-kotak-assumption. Reads app SQLite in read-only mode;
does not install strategies, alter live fees, or submit orders. Refuses to
overwrite outputs. Run from the repository with the research environment.
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from scripts.research_ema_scalp import (
    FIRST,
    LAST,
    SOURCE,
    file_hash,
    run_variant,
    screen_broker,
    write_json,
)
from scripts.research_ig_scalping import diagnostics
from scripts.research_tradejini_scalping import prepare_options
from services.research import conlan, jobs
from services.research.dataset import digest
from services.research.ema_scalp import option_outcome, summarize
from services.research.ig_scalping import bars_from_minutes
from services.research.replay import validate_configuration
from services.research.tradetron_scalping import regular_sessions
from services.risk.budget import BudgetPolicy


def read_inputs():
    url = make_url(dotenv_values(ROOT / ".env")["DATABASE_URL"])
    if not url.drivername.startswith("sqlite"):
        raise ValueError("This offline runner requires a local SQLite research store")
    with sqlite3.connect("file:" + url.database + "?mode=ro", uri=True) as db:
        costs = db.execute("SELECT costs FROM trading_risk_settings").fetchall()
        if len(costs) != 1:
            raise ValueError("Select a single owner explicitly before using a multi-owner store")
        saved = json.loads(costs[0][0])
        if saved.get("broker") != "kotak" or saved.get("exchange") != "NFO":
            raise ValueError("Expected the saved Kotak NFO cost schedule")
        rows = db.execute("SELECT id,content FROM tr_dataset ORDER BY id").fetchall()
        datasets = [(i, json.loads(raw)) for i, raw in rows]
        protected = {day for _, data in datasets for day in data["sessions"][-60:]}
        protected.update(
            day
            for day, role in db.execute("SELECT session_day,role FROM tr_session_use")
            if role != "development"
        )
    costs = saved | {
        "schedule_id": "RESEARCH ASSUMPTION: current Kotak charges",
        "source": "User-approved current Kotak charges applied retrospectively; not historical verified rates. Original saved schedule retained in manifest.",
        "effective_from": FIRST,
        "effective_to": "2026-07-21",
    }
    return saved, costs, protected, datasets


def load_minutes(symbol, protected):
    interval = 5 if symbol == "BANKNIFTY" else 1
    paths = sorted(SOURCE.glob(f"{symbol}-{interval}m-*.json"))
    if not paths:
        raise ValueError(f"No archived {interval}-minute history for {symbol}")
    frame, audit = screen_broker(paths, interval)
    days = frame.index.strftime("%Y-%m-%d")
    frame = regular_sessions(frame[(days >= FIRST) & (days <= LAST) & ~days.isin(protected)])
    return frame, audit, {str(p.relative_to(ROOT)): file_hash(p) for p in paths}


def option_study(out, minute, five, costs, manifest_hash):
    frames = {family: conlan.rule_signals(five, family) for family in conlan.FAMILIES}
    requests = []
    for family, frame in frames.items():
        frame.to_parquet(out / f"signals-{family}.parquet")
        for at, row in frame[frame.direction.ne("")].iterrows():
            requests.append(
                {
                    "id": len(requests),
                    "family": family,
                    "day": at.strftime("%Y-%m-%d"),
                    "timestamp": at.isoformat(),
                    "signal_time": at.tz_convert("UTC"),
                    "quote_time": at.floor("5min").tz_convert("UTC"),
                    "direction": row.direction,
                    "spot": float(row.close),
                }
            )
    requests = pd.DataFrame(requests)
    requests.to_parquet(out / "requests.parquet", index=False)
    selections, paths = prepare_options(requests, out, manifest_hash) if len(requests) else ({}, {})
    ids = {(r["family"], r["timestamp"]): r["id"] for r in requests.to_dict("records")}
    results = []
    for family, frame in frames.items():
        for hold in (5, 10, 15):
            name = f"{family}-hold{hold}"
            folder = out / name
            folder.mkdir()
            trades, skipped = run_variant(frame, minute, hold)
            write_json(folder / "index-trades.json", trades)
            result = {
                "id": name,
                "family": family,
                "hold_minutes": hold,
                "index": summarize(trades),
                "skipped": skipped,
                "options": {},
            }
            for scenario, fees in [
                ("base", costs),
                ("stress", costs | {"slippage_bps": 30.0, "brokerage_per_order": 20.0}),
            ]:
                rows = []
                for trade in trades:
                    ident = ids[(family, trade["timestamp"])]
                    if trade["r"] is None:
                        value = {"reason": "unresolved_index_exit"}
                    elif ident not in selections:
                        value = {"reason": "no_observed_atm_with_prior_listing"}
                    else:
                        bars = paths.get(
                            ident, pd.DataFrame(index=pd.DatetimeIndex([], tz="Asia/Kolkata"))
                        ).copy()
                        bars.index += pd.Timedelta(minutes=1)
                        contract = {
                            "lot_size": int(selections[ident]["lot_size"]),
                            "multiplier": 1,
                            "tick_size": 0.05,
                        }
                        value = option_outcome(trade, bars, contract, fees, capital=25000)
                    rows.append(
                        {
                            "id": ident,
                            "timestamp": trade["timestamp"],
                            "direction": trade["direction"],
                            **value,
                        }
                    )
                write_json(folder / f"options-{scenario}.json", rows)
                result["options"][scenario] = diagnostics(rows)
            write_json(folder / "results.json", result)
            results.append(result)
            print(name, result["options"]["base"]["affordable_at_initial_capital"], flush=True)
    return results


def primitive_study(out, minute, bank):
    five = bars_from_minutes(minute, 5)
    events = conlan.cusum_events(np.log(five.close).diff(), 0.002)
    barrier_results = []
    for hold in (5, 10, 15):
        selected = events[(events + pd.Timedelta(minutes=hold)).strftime("%H:%M") <= "15:25"]
        for mode in ("fixed", "volatility"):
            volatility = (
                np.log(five.close).diff().ewm(span=20, min_periods=20).std()
                if mode == "volatility"
                else None
            )
            labels = conlan.triple_barriers(
                five.close,
                selected,
                horizon=pd.Timedelta(minutes=hold),
                upper=2 if volatility is not None else 0.002,
                lower=-1 if volatility is not None else -0.001,
                volatility=volatility,
                bar_interval="5min",
            )
            # Minute scalp horizons must be complete; no next-session vertical exits.
            labels = labels[
                labels.exit_at.map(lambda t: t.date() if pd.notna(t) else None)
                == pd.Series(labels.index.date, index=labels.index)
            ]
            labels.to_parquet(out / f"cusum-{mode}-{hold}m.parquet")
            known = labels.dropna(subset=["label"])
            weights = conlan.event_uniqueness(known.exit_at, five.index) if len(known) else []
            barrier_results.append(
                {
                    "mode": mode,
                    "hold_minutes": hold,
                    "events": len(selected),
                    "observed_labels": len(known),
                    "unavailable": len(selected) - len(known),
                    "label_counts": {str(k): int(v) for k, v in known.label.value_counts().items()},
                    "average_uniqueness": float(np.mean(weights)) if len(weights) else None,
                    "not_a_trade_win_rate": True,
                }
            )
    daily_frames = {}
    for symbol, frame in [("NIFTY", minute), ("BANKNIFTY", bank)]:
        daily_frames[symbol] = (
            frame.resample("D")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna()
        )
    closes = pd.concat({s: f.close for s, f in daily_frames.items()}, axis=1).dropna()
    signals = pd.concat(
        {s: conlan.rule_signals(f, "bollinger").signal for s, f in daily_frames.items()}, axis=1
    ).reindex(closes.index)
    controls = conlan.preference_controls(
        closes, signals, repeats=100, window=100, seed=42, max_positions=1, fee_bps=0.0
    )
    reference_equity = pd.Series(
        [r["equity"] for r in controls["reference"]["equity"]], index=closes.index
    )
    controls["reference"]["metrics"] = conlan.equity_metrics(
        reference_equity, closes.NIFTY.pct_change(fill_method=None)
    )
    controls["benchmark"] = (
        "Observed NIFTY daily close returns, aligned sessions; gross abstract comparison only."
    )
    controls["limitation"] = (
        "Two index proxies, daily, fractional exposure, gross of instrument costs; max one asset to test ranking competition. Not the original five-stock portfolio and not executable option P&L."
    )
    write_json(out / "preference-controls.json", controls)
    write_json(out / "barrier-diagnostics.json", barrier_results)
    grid = []
    for bands in (10, 20, 30):
        candidate_signals = pd.concat(
            {
                s: conlan.rule_signals(f, "bollinger", band_window=bands).signal
                for s, f in daily_frames.items()
            },
            axis=1,
        ).reindex(closes.index)
        for window in (50, 100, 150):
            candidate = conlan.preference_portfolio(
                closes, candidate_signals, conlan.rolling_sharpe(closes, window), max_positions=1
            )
            grid.append(
                {"band_window": bands, "preference_window": window, "metrics": candidate["metrics"]}
            )
            write_json(out / f"portfolio-grid-{bands}-{window}.json", candidate)
    write_json(
        out / "portfolio-grid.json",
        {
            "candidates": grid,
            "selection_is_exploratory": True,
            "cost_basis": "gross abstract index proxies",
        },
    )
    return {
        "portfolio_grid": grid,
        "cusum_barriers": barrier_results,
        "preference_controls": {k: v for k, v in controls.items() if k != "reference"},
        "preference_reference": controls["reference"]["metrics"],
        "alternative_revenue_model": {
            "status": "not_testable",
            "reason": "No company revenue release history with publication timestamps exists in the supplied NIFTY/BANKNIFTY datasets. Release-aware adapter and event-classifier pipeline implemented and unit tested; no fabricated accuracy.",
        },
    }


def ml_study(out, datasets, protected, costs):
    results = []
    for ident, data in datasets:
        if data["metadata"].get("execution_bar_minutes") != 1:
            continue
        if set(data["sessions"][:-60]) & protected:
            raise ValueError("Development data intersects protected final sessions")
        for hold in (5, 10, 15):
            configuration = validate_configuration(data, "trend_breakout_filtered", {}, costs)
            configuration.update(
                risk_policy_version=BudgetPolicy().version,
                implementation_hash=jobs.implementation_hash(),
                ml_settings={
                    "folds": 3,
                    "min_train_sessions": 10,
                    "estimators": 100,
                    "threshold": 0.5,
                    "max_hold_minutes": hold,
                },
            )
            name = f"ml-dataset{ident}-hold{hold}"
            print("Running", name, flush=True)
            try:
                report = jobs.run_ml_experiment(data, configuration)
                write_json(
                    out / f"{name}.json",
                    {
                        "configuration": configuration,
                        "dataset_hash": data["content_hash"],
                        "report": report,
                    },
                )
                result = {
                    "id": name,
                    "dataset": data["name"],
                    "metrics": report["metrics"],
                    "accuracy": report["ml"]["accuracy"],
                    "diagnostics": report["ml"]["diagnostics"],
                    "stress": report["stress"]["metrics"],
                    "split": report["split"],
                    "status": "completed",
                }
            except ValueError as exc:
                result = {"id": name, "status": "not_testable", "reason": str(exc)}
            results.append(result)
            write_json(out / "ml-progress.json", results)
            print(name, result.get("metrics", result.get("reason")), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--current-kotak-assumption", action="store_true", required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    saved, costs, protected, datasets = read_inputs()
    minute, audit, hashes = load_minutes("NIFTY", protected)
    bank, bank_audit, bank_hashes = load_minutes("BANKNIFTY", protected)
    files = [
        "scripts/research_conlan_algorithms.py",
        "scripts/research_ema_scalp.py",
        "scripts/research_tradejini_scalping.py",
        "scripts/research_ig_scalping.py",
        "services/research/conlan.py",
        "services/research/ema_scalp.py",
        "services/research/ig_scalping.py",
        "services/research/tradetron_scalping.py",
        "services/research/tradejini_scalping.py",
        "services/research/ml.py",
        "services/research/ml_prediction.py",
        "services/research/jobs.py",
        "services/research/replay.py",
        "services/research/costs.py",
        "services/research/analytics.py",
        "services/risk/budget.py",
        "services/risk/position.py",
        "services/risk/models.py",
    ]
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "reference_repository": "https://github.com/chrisconlan/algorithmic-trading-with-python",
        "reference_revision": "ebe01087c7d9172db72bc3c9adc1eee5e882ac49",
        "first": FIRST,
        "last": LAST,
        "source_hashes": {n: file_hash(ROOT / n) for n in files},
        "input_hashes": hashes | bank_hashes,
        "dataset_hashes": {str(i): d["content_hash"] for i, d in datasets},
        "saved_costs": saved,
        "research_costs": costs,
        "cost_assumption": "Current Kotak charges applied retrospectively with user approval; saved live schedule unchanged. Stress: 30bps slippage and Rs20/order.",
        "protected_dates": sorted(protected),
        "protected_sessions_evaluated": 0,
        "seed": 42,
        "option_capital_scenario": 25000,
        "option_premium_budget": 20000,
        "option_outcomes_are_not_portfolio_returns": True,
        "ml_capital_policy": 10000,
        "ml_policy_reason": "Canonical shared replay risk policy; not comparable to 25k one-lot affordability study. Live settings unchanged.",
        "live_enabled": False,
        "strategy_installation": "optional uninstalled templates",
        "data_audit": {
            "nifty": audit,
            "banknifty": bank_audit,
            "evaluated_sessions": len(set(minute.index.date)),
        },
        "evaluation_status": "Previously studied development data; no fresh holdout claims",
        "data_rights": "Public options archive provenance retained; redistribution rights unverified. Private exploratory study only.",
    }
    write_json(out / "manifest.json", manifest)
    for relative in files:
        target = out / "source-snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    results = {
        "option_variants": option_study(
            out, minute, bars_from_minutes(minute, 5), costs, file_hash(out / "manifest.json")
        )
    }
    write_json(out / "option-results.json", results)
    results["components"] = primitive_study(out, minute, bank)
    money_flow_audit = []
    for ident, data in datasets:
        selected = set(data["sessions"][:-60]) - protected
        frame = pd.DataFrame(
            [
                r
                for r in data["rows"]
                if r["timestamp"][:10] in selected
                and r["symbol"] != data["metadata"]["underlying_symbol"]
            ]
        )
        valid_count = unknown_count = 0
        for _, group in frame.groupby(["symbol", frame.timestamp.str[:10]]):
            group = group.set_index("timestamp")
            group.index = pd.DatetimeIndex(group.index)
            flow = conlan.money_flow(group.sort_index())
            valid_count += int(flow.chaikin_money_flow.notna().sum())
            unknown_count += int(flow.chaikin_money_flow.isna().sum())
        money_flow_audit.append(
            {
                "dataset_id": ident,
                "valid_cmf_observations": valid_count,
                "warmup_or_zero_range_unavailable": unknown_count,
                "signal_rule": "No standalone CMF trading rule is specified in the source repository.",
            }
        )
    results["components"]["money_flow"] = money_flow_audit
    write_json(out / "components.json", results["components"])
    results["ml"] = ml_study(out, datasets, protected, costs)
    current, *_ = read_inputs()
    if digest(current) != digest(saved):
        raise ValueError(
            "Saved cost schedule changed during the study; investigate before comparing"
        )
    if any(file_hash(ROOT / n) != sha for n, sha in manifest["source_hashes"].items()):
        raise ValueError(
            "Research implementation changed during the study; rerun with frozen source"
        )
    results.update(live_enabled=False, saved_costs_unchanged=True, protected_sessions_evaluated=0)
    write_json(out / "results.json", results)
    print("Completed study:", out, flush=True)


if __name__ == "__main__":
    main()
