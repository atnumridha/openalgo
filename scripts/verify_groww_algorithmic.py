"""Independent Groww algorithmic study audit from source minutes, listings and option prices."""

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


def reconstruct(minutes, manifest):
    # Independent anchored aggregation, daily lookup and scalar signal logic.
    f = minutes[["open", "high", "low", "close"]].copy()
    groups = ((f.index.hour * 60 + f.index.minute - 556) // 5).astype(int)
    f["day"], f["bucket"] = f.index.strftime("%Y-%m-%d"), groups
    rows, stamps = [], []
    for (day, bucket), g in f.groupby(["day", "bucket"], sort=True):
        end = pd.Timestamp(day, tz="Asia/Kolkata") + pd.Timedelta(minutes=560 + 5 * bucket)
        if len(g) != 5 or list(g.index) != list(
            pd.date_range(end - pd.Timedelta(minutes=4), end, freq="min")
        ):
            continue
        stamps.append(end)
        rows.append([g.open.iloc[0], g.high.max(), g.low.min(), g.close.iloc[-1]])
    f = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(stamps))
    daily = pd.read_csv(ROOT / manifest["daily_path"])
    days = pd.to_datetime(daily.timestamp, utc=True).dt.tz_convert("Asia/Kolkata")
    use = (
        (days.dt.strftime("%Y-%m-%d") <= manifest["last"])
        & np.isfinite(daily.Close)
        & daily.Close.gt(0)
    )
    dates, close = pd.DatetimeIndex(days[use]), daily.loc[use, "Close"].to_numpy()
    vol = np.full(len(close), np.nan)
    returns = np.diff(close) / close[:-1]
    for i in range(20, len(close)):
        vol[i] = np.std(returns[i - 20 : i])
    contexts = []
    for at in f.index:
        j = dates.searchsorted(at.normalize(), side="left") - 1
        assert j >= 271 and dates[j] < at.normalize()
        contexts.append(
            (
                close[j],
                close[j - 19 : j + 1].mean(),
                close[j - 199 : j + 1].mean(),
                vol[j],
                np.median(vol[j - 251 : j + 1]),
            )
        )
    prices = f.close.to_numpy()
    emas = {}
    for length in (50, 200):
        v = np.empty(len(f))
        v[0] = prices[0]
        for i in range(1, len(f)):
            v[i] = (2 / (length + 1)) * prices[i] + (1 - 2 / (length + 1)) * v[i - 1]
        emas[length] = v
    diff = np.round(emas[50] - emas[200], 8)
    z = np.full(len(f), np.nan)
    for i in range(19, len(f)):
        window = prices[i - 19 : i + 1]
        if window.std() != 0:
            z[i] = (prices[i] - window.mean()) / window.std()
    outputs = {}
    for family in ("mean_z20", "mean_daily10", "trend_50_200", "timing_50_200"):
        out = f.copy()
        out["direction"], out["stop_price"] = "", np.nan
        for i in range(19 if family.startswith("mean") else 199, len(f)):
            if not all(
                f.index[k] - f.index[k - 1] == pd.Timedelta(minutes=5) for k in range(i - 2, i + 1)
            ):
                continue
            b = f.iloc[i]
            dc, ma20, ma200, v, median = contexts[i]
            if family == "mean_z20":
                buy = z[i] > -2 and z[i - 1] <= -2 and b.close > b.open
                sell = z[i] < 2 and z[i - 1] >= 2 and b.close < b.open
            elif family == "mean_daily10":
                buy = prices[i] < 0.9 * ma20 <= prices[i - 1]
                sell = prices[i] > 1.1 * ma20 >= prices[i - 1]
            else:
                buy = diff[i] > 0 and diff[i - 1] <= 0
                sell = diff[i] < 0 and diff[i - 1] >= 0
                if family == "timing_50_200":
                    buy = buy and dc > ma200 and v <= median
                    sell = sell and dc < ma200 and v <= median
            if buy or sell:
                out.loc[out.index[i], ["direction", "stop_price"]] = [
                    "CE" if buy else "PE",
                    b.low if buy else b.high,
                ]
        outputs[family] = out
    return outputs


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
    minutes = raw_minutes(m)
    expected = reconstruct(minutes, m)
    requests = pd.read_parquet(folder / "requests.parquet")
    assert requests.id.is_unique
    for family, frame in expected.items():
        saved = pd.read_parquet(folder / f"signals-{family}.parquet")
        pd.testing.assert_frame_equal(
            frame, saved, check_names=False, check_freq=False, rtol=1e-10, atol=1e-10
        )
        signals = frame[frame.direction != ""]
        req = requests[requests.family == family]
        pd.testing.assert_index_equal(
            pd.DatetimeIndex(req.signal_time).tz_convert("Asia/Kolkata"),
            signals.index,
            check_names=False,
        )
        assert (req.direction.to_numpy() == signals.direction.to_numpy()).all()
        assert (req.spot.to_numpy() == signals.close.to_numpy()).all()
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
        frame = expected[spec["family"]]
        signals = frame[frame.direction != ""]
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
            assert actual["stop_price"] == row.stop_price
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
        "signal_rows_verified": sum(len(f) for f in expected.values()),
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
