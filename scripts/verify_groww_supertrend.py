"""Independent Groww study audit from source minutes, listings and option prices."""

import argparse
import json
import sys
from collections import Counter
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_tradejini_scalping import selected_contracts
from scripts.verify_tradetron_scalping import fees, fingerprint, load, raw_minutes


def reconstruct(minutes):
    f = minutes[["open", "high", "low", "close"]].copy()
    ranges = pd.concat(
        [f.high - f.low, (f.high - f.close.shift()).abs(), (f.low - f.close.shift()).abs()], axis=1
    ).max(axis=1)
    seed = ranges.iloc[9:].copy()
    seed.iloc[0] = ranges.iloc[:10].mean()
    atr = seed.ewm(alpha=0.1, adjust=False).mean().reindex(f.index)
    upper, lower, line, trend = [np.full(len(f), np.nan) for _ in range(4)]
    trend[:9] = 0
    for i in range(9, len(f)):
        upper[i] = (f.high.iloc[i] + f.low.iloc[i]) / 2 + 3 * atr.iloc[i]
        lower[i] = (f.high.iloc[i] + f.low.iloc[i]) / 2 - 3 * atr.iloc[i]
        if i == 9:
            trend[i] = -1
        else:
            if f.close.iloc[i - 1] <= upper[i - 1]:
                upper[i] = min(upper[i], upper[i - 1])
            if f.close.iloc[i - 1] >= lower[i - 1]:
                lower[i] = max(lower[i], lower[i - 1])
            if line[i - 1] == upper[i - 1]:
                trend[i] = 1 if f.close.iloc[i] > upper[i] else -1
            else:
                trend[i] = -1 if f.close.iloc[i] < lower[i] else 1
        line[i] = lower[i] if trend[i] == 1 else upper[i]
    f["atr"], f["upper"], f["lower"], f["supertrend"], f["trend"] = (
        atr,
        upper,
        lower,
        line,
        trend.astype(int),
    )
    ready = np.zeros(len(f), dtype=bool)
    for i in range(99, len(f)):
        ready[i] = all(
            f.index[j] - f.index[j - 1] == pd.Timedelta(minutes=1) for j in range(i - 2, i + 1)
        )
    f["ready"] = ready
    f["direction"] = ""
    f["stop_price"] = np.nan
    f["setup_at"] = ""
    for i in range(100, len(f)):
        a, b = f.iloc[i - 1], f.iloc[i]
        if (
            not ready[i - 1]
            or not ready[i]
            or f.index[i] - f.index[i - 1] != pd.Timedelta(minutes=1)
        ):
            continue
        if not a.trend == trend[i - 2] == b.trend or not a.low <= a.supertrend <= a.high:
            continue
        direction = ""
        if a.trend == 1 and a.close > a.supertrend and b.close > a.high and b.low > a.low:
            direction = "CE"
        if a.trend == -1 and a.close < a.supertrend and b.close < a.low and b.high < a.high:
            direction = "PE"
        if direction:
            f.loc[f.index[i], ["direction", "stop_price", "setup_at"]] = [
                direction,
                a.low if direction == "CE" else a.high,
                f.index[i - 1].isoformat(),
            ]
    return f


def index_exit(at, row, minutes, hold, reward):
    deadline = at + pd.Timedelta(minutes=hold)
    first = at + pd.Timedelta(minutes=1)
    if first not in minutes.index:
        return {"entered": False, "reason": "missing_entry", "r": None}
    entry = minutes.loc[first, "open"]
    sign = 1 if row.direction == "CE" else -1
    stop = row.stop_price
    risk = sign * (entry - stop)
    if risk <= 0:
        return {"entered": False, "reason": "entry_through_stop", "r": None}
    target = entry + sign * reward * risk
    base = {"entered": True, "entry_price": entry, "stop": stop, "target": target}
    for t in pd.date_range(first, deadline, freq="min"):
        if t not in minutes.index:
            return base | {"reason": "missing_minute", "r": None}
        b = minutes.loc[t]
        ambiguous = False
        stopped = b.low <= stop if sign == 1 else b.high >= stop
        won = b.high >= target if sign == 1 else b.low <= target
        if sign * (b.open - stop) <= 0:
            px, reason = b.open, "sl"
        elif sign * (b.open - target) >= 0:
            px, reason = b.open, "target"
        elif stopped:
            px, reason, ambiguous = stop, "sl", won
        elif won:
            px, reason = target, "target"
        elif t == deadline:
            px, reason = b.close, "time"
        else:
            continue
        points = sign * (px - entry)
        return base | {
            "reason": reason,
            "r": points / risk,
            "points": points,
            "exit_price": px,
            "exit_at": t.isoformat(),
            "ambiguous": bool(ambiguous),
        }


def option_check(trade, path, lot, scenario, costs):
    start, end = pd.Timestamp(trade["timestamp"]), pd.Timestamp(trade["exit_at"])
    expected = pd.date_range(start, end, freq="min")
    if not path.index.is_unique or not expected.isin(path.index).all():
        return {"reason": "missing_or_untradeable_minute"}
    f = path.loc[expected]
    valid = (
        np.isfinite(f[["open", "high", "low", "close", "volume"]]).all(axis=1)
        & f[["open", "high", "low", "close", "volume"]].gt(0).all(axis=1)
        & f.low.le(f[["open", "close"]].min(axis=1))
        & f.high.ge(f[["open", "close"]].max(axis=1))
    )
    if not valid.all():
        return {"reason": "missing_or_untradeable_minute"}
    slip = Decimal(".001" if scenario == "base" else ".003")
    tick = Decimal(".05")
    entry = (Decimal(str(f.iloc[0].open)) * (1 + slip) / tick).to_integral_value(
        rounding=ROUND_CEILING
    ) * tick
    exit_price = (Decimal(str(f.iloc[-1].open)) * (1 - slip) / tick).to_integral_value(
        rounding=ROUND_FLOOR
    ) * tick
    buy = fees(entry * lot, True, scenario, costs)
    sell = fees(exit_price * lot, False, scenario, costs)
    return {
        "reason": "priced",
        "entry_price": float(entry),
        "exit_price": float(exit_price),
        "units": lot,
        "entry_fill_at": start.isoformat(),
        "exit_fill_at": end.isoformat(),
        "premium_with_entry_fees": float(entry * lot + buy),
        "affordable": entry * lot + buy <= 20000,
        "gross_pnl": float((exit_price - entry) * lot),
        "costs": float(buy + sell),
        "net_pnl": float(((exit_price - entry) * lot - buy - sell).quantize(Decimal(".01"))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder.resolve()
    m = load(folder / "registered-experiment.json")
    for name, sha in m["source_hashes"].items():
        assert fingerprint(ROOT / name) == sha, name
    assert fingerprint(ROOT / m["plan_path"]) == m["plan_sha256"]
    assert fingerprint(Path(m["transcript_path"])) == m["transcript_sha256"]
    minutes = raw_minutes(m)
    expected = reconstruct(minutes)
    saved = pd.read_parquet(folder / "signals.parquet")
    pd.testing.assert_frame_equal(
        expected, saved, check_names=False, check_freq=False, rtol=1e-10, atol=1e-10
    )
    requests = pd.read_parquet(folder / "requests.parquet")
    signals = expected[expected.direction != ""]
    assert requests.id.is_unique
    pd.testing.assert_index_equal(
        pd.DatetimeIndex(requests.signal_time).tz_convert("Asia/Kolkata"),
        signals.index,
        check_names=False,
    )
    assert (requests.direction.to_numpy() == signals.direction.to_numpy()).all()
    assert (requests.spot.to_numpy() == signals.close.to_numpy()).all()
    assert (requests.quote_time == requests.signal_time.dt.floor("5min")).all()
    assert (
        requests.day == requests.signal_time.dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
    ).all()
    evidence = load(folder / "option-inputs.json")
    assert evidence["manifest_sha256"] == fingerprint(folder / "registered-experiment.json")
    for name, sha in evidence["inputs"].items():
        assert fingerprint(ROOT / name) == sha, name
    selection = pd.read_parquet(folder / "option-selections.parquet")
    assert selection.id.is_unique
    with duckdb.connect() as db:
        db.execute("SET memory_limit='512MB'")
        db.execute("SET threads=2")
        db.execute("SET TimeZone='Asia/Kolkata'")
        ranked = selected_contracts(db, requests)
        assert set(ranked) == set(selection.id)
        lookup = requests.set_index("id")
        for s in selection.to_dict("records"):
            for k, v in ranked[s["id"]].items():
                assert s[k] == v, (s["id"], k)
            assert s["option_type"] == lookup.loc[s["id"]].direction
            for k in requests.columns:
                if k != "id":
                    assert s[k] == lookup.loc[s["id"], k]
        pieces = []
        for year, g in selection.groupby(selection.day.str[:4]):
            db.register("selected", g)
            p = (
                ROOT
                / f"data/research/five-minute-2026-09-26/public-options/raw/NIFTY_{year}.parquet"
            )
            pieces.append(
                db.execute(
                    """SELECT s.id,o.timestamp AS bar_open,o.open,o.high,o.low,o.close,o.volume,
                o.source,o.granularity,o.underlying FROM read_parquet(?) o JOIN selected s
                ON o.date=s.day AND o.expiry=s.expiry AND o.strike=s.strike AND o.option_type=s.option_type
                AND o.timestamp>=s.signal_time AND o.timestamp<=s.signal_time+INTERVAL 15 MINUTE
                ORDER BY s.id,o.timestamp""",
                    [str(p)],
                ).df()
            )
        raw = pd.concat(pieces, ignore_index=True)
        raw["bar_open"] = pd.to_datetime(raw.bar_open, utc=True).dt.tz_convert("Asia/Kolkata")
        pd.testing.assert_frame_equal(raw, pd.read_parquet(folder / "option-paths.parquet"))
    raw = raw[
        (raw.source == "upstox_expired") & (raw.granularity == "1min") & (raw.underlying == "NIFTY")
    ]
    paths = {int(i): g.set_index("bar_open") for i, g in raw.groupby("id")}
    lots = selection.set_index("id").lot_size.to_dict()
    index_checks = option_checks = 0
    top = load(folder / "results.json")
    for spec in m["specs"]:
        report = load(folder / spec["id"] / "results.json")
        assert report == next(r for r in top["variants"] if r["spec"]["id"] == spec["id"])
        trades = load(folder / spec["id"] / "index-trades.json")
        by_at = {r["timestamp"]: r for r in trades}
        counts, skips = Counter(), Counter()
        until = None
        seen = []
        for at, row in signals.iterrows():
            end = at + pd.Timedelta(minutes=spec["hold"])
            day = at.strftime("%Y-%m-%d")
            if end.strftime("%H:%M") > "15:25":
                skips["late_signal"] += 1
                continue
            if until is not None and at < until:
                skips["position_open"] += 1
                continue
            if counts[day] >= 3:
                skips["daily_three_entry_cap"] += 1
                continue
            seen.append(at.isoformat())
            actual = by_at[at.isoformat()]
            want = index_exit(at, row, minutes, spec["hold"], spec["reward"])
            assert actual["stop_price"] == row.stop_price and actual["setup_at"] == row.setup_at
            assert (
                actual["direction"] == row.direction and actual["reward_multiple"] == spec["reward"]
            )
            for k, v in want.items():
                if isinstance(v, (float, np.floating)):
                    assert abs(actual[k] - v) < 1e-9, (at, k)
                else:
                    assert actual[k] == v, (at, k)
            if want["entered"]:
                counts[day] += 1
                until = pd.Timestamp(want.get("exit_at", end))
            index_checks += 1
        assert seen == [t["timestamp"] for t in trades]
        assert dict(skips) == report["skipped"]
        for scenario in ("base", "stress"):
            rows = load(folder / spec["id"] / f"options-{scenario}.json")
            assert [r["id"] for r in rows] == [t["id"] for t in trades]
            for r, t in zip(rows, trades, strict=True):
                req = requests.set_index("id").loc[t["id"]]
                assert req.timestamp == t["timestamp"] and req.direction == t["direction"]
                if t["r"] is None:
                    want = {"reason": "unresolved_index_exit"}
                elif t["id"] not in lots:
                    want = {"reason": "no_observed_atm_with_prior_listing"}
                else:
                    q = paths.get(
                        t["id"], pd.DataFrame(index=pd.DatetimeIndex([], tz="Asia/Kolkata"))
                    )
                    want = option_check(t, q, int(lots[t["id"]]), scenario, m["costs"])
                for k, v in want.items():
                    assert r[k] == v, (spec["id"], r["id"], scenario, k, r[k], v)
                option_checks += 1
            values = [r["net_pnl"] for r in rows if r["reason"] == "priced" and r["affordable"]]
            stats = report["options"][scenario]["affordable_at_initial_capital"]
            assert stats["count"] == len(values)
            if values:
                assert abs(stats["mean_net_pnl"] - np.mean(values)) < 1e-8
                assert stats["win_rate"] == sum(v > 0 for v in values) / len(values)
    report = {
        "hashes_match": True,
        "signal_rows_verified": len(expected),
        "contract_selections_verified": len(selection),
        "index_outcomes_verified": index_checks,
        "option_outcomes_checked": option_checks,
        "option_source_hashes_verified": len(evidence["inputs"]),
        "protected_sessions_evaluated": 0,
        "verifier_sha256": fingerprint(Path(__file__)),
        "verifier_dependencies": {
            str(Path(p).relative_to(ROOT)): fingerprint(Path(p))
            for p in [
                ROOT / "scripts/verify_tradejini_scalping.py",
                ROOT / "scripts/verify_tradetron_scalping.py",
            ]
        },
    }
    with (folder / "verification.json").open("w") as s:
        json.dump(report, s, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
