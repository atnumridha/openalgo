"""Independent raw-price verification of missing StockGro timeframe/session cells."""

import argparse
import json
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Separate verifier utilities, not application signal, risk, selection or cost helpers.
from scripts.verify_tradetron_scalping import (
    check_contract_selection,
    fees,
    fingerprint,
    load,
    raw_minutes,
)


def check_indicator_signals(bars, saved, timeframe):
    close = bars.close.to_numpy()
    averages = {}
    for p in (5, 10):
        value = np.zeros(len(bars))
        value[0] = close[0]
        alpha = 2 / (p + 1)
        for i in range(1, len(bars)):
            value[i] = alpha * close[i] + (1 - alpha) * value[i - 1]
        averages[p] = value
    difference = np.round(averages[5] - averages[10], 8)
    buy, sell = np.zeros(len(bars), dtype=bool), np.zeros(len(bars), dtype=bool)
    buy[1:] = (difference[1:] > 0) & (difference[:-1] <= 0)
    sell[1:] = (difference[1:] < 0) & (difference[:-1] >= 0)
    buy[:49], sell[:49] = False, False
    ready = bars.index.to_series().diff().eq(pd.Timedelta(minutes=timeframe)).rolling(3).sum().eq(3)
    expected = np.where(buy & ready, "CE", np.where(sell & ready, "PE", ""))
    assert (expected == saved.direction.to_numpy()).all(), timeframe
    assert not saved.exit_ce.any() and not saved.exit_pe.any()
    np.testing.assert_allclose(saved.stop_price, close + np.where(expected == "CE", -15, 15))
    return len(bars)


def check_baseline_option_sources(baseline, project_root=ROOT):
    recorded = load(baseline / "ema-1m/option-audit/option-inputs.json")
    assert recorded["manifest_sha256"] == fingerprint(baseline / "registered-experiment.json")
    for path, sha in recorded["inputs"].items():
        assert fingerprint(project_root / path) == sha, path
    return len(recorded["inputs"])


def check_reused_baseline(folder, manifest):
    for path, sha in manifest["reused_hashes"].items():
        assert fingerprint(ROOT / path) == sha, path
    prior_root = ROOT / manifest["baseline_root"]
    old = load(prior_root / "ema-1m-r2-hold15/results.json")
    saved = load(folder / "reused-baseline.json")
    for key in (
        "index",
        "options",
        "skipped",
        "raw_signals",
        "unresolved_reasons",
        "index_periods",
    ):
        assert old[key] == saved[key], key
    assert saved["spec"]["reused"] and saved["spec"]["window"] == "all"
    assert saved["spec"]["timeframe"] == 1 and saved["spec"]["hold"] == 15
    pd.testing.assert_frame_equal(
        pd.read_parquet(folder / "ema-1m/signals-and-exits.parquet"),
        pd.read_parquet(prior_root / "ema-1m/signals-and-exits.parquet"),
    )
    old_manifest = load(prior_root / "registered-experiment.json")
    assert old_manifest["input_hashes"] == manifest["input_hashes"]
    assert old_manifest["costs"] == manifest["costs"]
    assert load(prior_root / "verification.json")["hashes_match"]
    return len(manifest["reused_hashes"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder.resolve()
    manifest = load(folder / "registered-experiment.json")
    for name, value in manifest["source_hashes"].items():
        assert fingerprint(ROOT / name) == value, name
    assert fingerprint(ROOT / manifest["plan_path"]) == manifest["plan_sha256"]
    f = raw_minutes(manifest)
    index_checks = option_checks = indicator_checks = unresolved = unpriced = selection_checks = 0
    hashed = set()
    with duckdb.connect() as db:
        db.execute("SET memory_limit='512MB'")
        db.execute("SET threads=2")
        for group in sorted(
            p for p in folder.iterdir() if (p / "variant-option-ids.json").exists()
        ):
            family, tf = group.name.split("-")
            tf = int(tf[:-1])
            aggregate = f.resample(
                f"{tf}min", origin="start_day", offset="9h15min", closed="right", label="right"
            )
            bars = aggregate.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            bars = bars[aggregate["close"].count() == tf]
            saved = pd.read_parquet(group / "signals-and-exits.parquet")
            pd.testing.assert_index_equal(saved.index, bars.index, check_names=False)
            np.testing.assert_allclose(
                saved[["open", "high", "low", "close"]], bars[["open", "high", "low", "close"]]
            )
            indicator_checks += check_indicator_signals(bars, saved, tf)
            ids = load(group / "variant-option-ids.json")
            by_id = {}
            for name, identities in ids.items():
                spec = next(s for s in manifest["specs"] if s["id"] == name)
                assert not spec["reused"]
                bounds = {"all": (555, 930), "opening": (555, 615), "closing": (870, 930)}[
                    spec["window"]
                ]
                trades = load(folder / name / "index-trades.json")
                counts = {}
                last_exit = None
                for ident, t in zip(identities, trades, strict=True):
                    by_id[ident] = t
                    assert manifest["first"] <= t["day"] <= manifest["last"]
                    at = pd.Timestamp(t["timestamp"]).tz_convert(f.index.tz)
                    assert last_exit is None or at >= last_exit
                    clock = at.hour * 60 + at.minute
                    assert bounds[0] <= clock < bounds[1]
                    side = 1 if t["direction"] == "CE" else -1
                    assert saved.loc[at, "direction"] == t["direction"]
                    assert t["stop_price"] == t["close"] - side * 15
                    if t["entered"]:
                        counts[t["day"]] = counts.get(t["day"], 0) + 1
                        assert counts[t["day"]] <= 3
                        last_exit = pd.Timestamp(
                            t.get("exit_at", at + pd.Timedelta(minutes=t["hold_minutes"]))
                        )
                    if t["r"] is None:
                        unresolved += 1
                        continue
                    entry = float(f.loc[at + pd.Timedelta(minutes=1), "open"])
                    risk = side * (entry - t["stop"])
                    assert entry == t["entry_price"] and risk > 0
                    target = entry + side * 2 * risk
                    assert target == t["target"]
                    deadline = at + pd.Timedelta(minutes=t["hold_minutes"])
                    assert deadline.strftime("%H:%M") <= "15:25"
                    for stamp in pd.date_range(at + pd.Timedelta(minutes=1), deadline, freq="min"):
                        bar = f.loc[stamp]
                        if side * (bar.open - t["stop"]) <= 0:
                            price, reason = float(bar.open), "sl"
                        elif side * (bar.open - target) >= 0:
                            price, reason = float(bar.open), "target"
                        elif bar.low <= t["stop"] if side == 1 else bar.high >= t["stop"]:
                            price, reason = t["stop"], "sl"
                        elif bar.high >= target if side == 1 else bar.low <= target:
                            price, reason = target, "target"
                        elif stamp == deadline:
                            price, reason = float(bar.close), "time"
                        elif (
                            stamp in saved.index
                            and saved.loc[stamp, "exit_ce" if side == 1 else "exit_pe"]
                        ):
                            price, reason = float(bar.close), "indicator"
                        else:
                            continue
                        assert price == t["exit_price"] and reason == t["reason"], (
                            name,
                            at,
                            reason,
                            t["reason"],
                        )
                        assert stamp == pd.Timestamp(t["exit_at"])
                        assert abs(side * (price - entry) / risk - t["r"]) < 1e-9
                        index_checks += 1
                        break
            audit = group / "option-audit"
            if not (audit / "option-selections.parquet").exists():
                assert not any(t["r"] is not None for t in by_id.values())
                continue
            for name, value in load(audit / "option-inputs.json")["inputs"].items():
                if name not in hashed:
                    assert fingerprint(ROOT / name) == value, name
                    hashed.add(name)
            selection = pd.read_parquet(audit / "option-selections.parquet")
            lookups = {
                s: {r["id"]: r for r in load(audit / f"options-{s}.json")}
                for s in ("base", "stress")
            }
            if selection.empty:
                continue
            selection_checks += check_contract_selection(selection, by_id, db)
            for year, part in selection.groupby(selection.day.str[:4]):
                db.register("selected", part)
                quotes = db.execute(
                    """SELECT s.id,o.timestamp,o.open,o.high,o.low,o.close,o.volume FROM read_parquet(?) o
                    JOIN selected s ON o.date=s.day AND o.expiry=s.expiry AND o.strike=s.strike
                    AND o.option_type=s.option_type AND o.timestamp>=s.signal_time AND o.timestamp<=s.exit_time
                    ORDER BY s.id,o.timestamp""",
                    [
                        str(
                            ROOT
                            / f"data/research/five-minute-2026-09-26/public-options/raw/NIFTY_{year}.parquet"
                        )
                    ],
                ).df()
                grouped = {int(k): g for k, g in quotes.groupby("id")}
                for row in part.to_dict("records"):
                    assert row["listing_day"] < row["day"] <= manifest["last"]
                    assert row["quote_time"] <= row["signal_time"]
                    assert (row["signal_time"] - row["quote_time"]).total_seconds() < 300
                    assert 1 <= (pd.Timestamp(row["expiry"]) - pd.Timestamp(row["day"])).days <= 7
                    spot = by_id[row["id"]]["close"]
                    assert (
                        row["strike"] < spot if row["option_type"] == "CE" else row["strike"] > spot
                    )
                    q = grouped.get(row["id"], pd.DataFrame())
                    if lookups["base"][row["id"]]["reason"] != "priced":
                        unpriced += 1
                        continue
                    assert q.timestamp.nunique() == len(q)
                    assert (
                        len(q)
                        == int((row["exit_time"] - row["signal_time"]).total_seconds() / 60) + 1
                    )
                    assert (q.volume > 0).all()
                    for scenario in ("base", "stress"):
                        result = lookups[scenario][row["id"]]
                        assert result["reason"] == "priced"
                        tick = Decimal(".05")
                        slip = Decimal(".001" if scenario == "base" else ".003")
                        entry = (
                            Decimal(str(q.iloc[0].open)) * (1 + slip) / tick
                        ).to_integral_value(rounding=ROUND_CEILING) * tick
                        exit_price = (
                            Decimal(str(q.iloc[-1].open)) * (1 - slip) / tick
                        ).to_integral_value(rounding=ROUND_FLOOR) * tick
                        premium, proceeds = (
                            entry * int(row["lot_size"]),
                            exit_price * int(row["lot_size"]),
                        )
                        entry_fee = fees(premium, True, scenario, manifest["costs"])
                        cost = entry_fee + fees(proceeds, False, scenario, manifest["costs"])
                        net = (proceeds - premium - cost).quantize(Decimal(".01"))
                        assert (
                            float(entry) == result["entry_price"]
                            and float(exit_price) == result["exit_price"]
                        )
                        assert float(cost) == result["costs"] and float(net) == result["net_pnl"]
                        assert (premium + entry_fee <= 20000) == result["affordable"]
                        option_checks += 1
            print("Verified", group.name, flush=True)
    reused_checks = check_reused_baseline(folder, manifest)
    baseline_root = ROOT / manifest["baseline_root"]
    baseline_option_inputs = check_baseline_option_sources(baseline_root)
    result = {
        "reused_baseline_files_checked": reused_checks,
        "reused_baseline_option_sources_checked": baseline_option_inputs,
        "baseline_option_input_manifest_sha256": fingerprint(
            baseline_root / "ema-1m/option-audit/option-inputs.json"
        ),
        "new_cells": 8,
        "reused_cells": 1,
        "hashes_match": True,
        "screened_minutes": len(f),
        "indicator_rows_reconstructed": indicator_checks,
        "asof_contract_rankings_checked": selection_checks,
        "index_outcomes_reconstructed": index_checks,
        "unresolved_index_outcomes": unresolved,
        "option_base_stress_fill_fee_checks": option_checks,
        "unpriced_selected_options": unpriced,
        "protected_sessions_evaluated": 0,
        "verifier_sha256": fingerprint(Path(__file__)),
    }
    with (folder / "verification.json").open("w") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
