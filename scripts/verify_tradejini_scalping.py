"""Independent raw-data reconstruction; imports no application decision helpers."""

import argparse
import gzip
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
from scripts.verify_tradetron_scalping import fees, fingerprint, load, raw_minutes


def signals(minutes, tf, family):
    grouped = minutes.resample(
        f"{tf}min", origin="start_day", offset="9h15min", closed="right", label="right"
    )
    f = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    f = f[grouped.close.count() == tf]
    ready = f.index.to_series().diff().eq(pd.Timedelta(minutes=tf)).rolling(3).sum().eq(3)
    body = f.close - f.open
    strong = (body.abs() >= (f.high - f.low) / 2) & (f.high > f.low)
    direction = pd.Series("", index=f.index)
    if family == "ema921":
        means = {}
        for period in (9, 21):
            values = [float(f.close.iloc[0])]
            alpha = 2 / (period + 1)
            for c in f.close.iloc[1:]:
                values.append(values[-1] * (1 - alpha) + c * alpha)
            means[period] = pd.Series(values, index=f.index)
        gap = (means[9] - means[21]).round(8)
        for i in range(104, len(f)):
            if not ready.iloc[i] or not strong.iloc[i]:
                continue
            if (
                gap.iloc[i] > 0 >= gap.iloc[i - 1]
                and body.iloc[i] > 0
                and f.close.iloc[i] > max(means[9].iloc[i], means[21].iloc[i])
            ):
                direction.iloc[i] = "CE"
            if (
                gap.iloc[i] < 0 <= gap.iloc[i - 1]
                and body.iloc[i] < 0
                and f.close.iloc[i] < min(means[9].iloc[i], means[21].iloc[i])
            ):
                direction.iloc[i] = "PE"
    else:
        for day, part in minutes.groupby(minutes.index.date):
            expected = pd.date_range(f"{day} 09:16", periods=15, freq="min", tz="Asia/Kolkata")
            if not expected.isin(part.index).all():
                continue
            high, low = part.loc[expected].high.max(), part.loc[expected].low.min()
            if high - low < 20:
                continue
            for at, r in f[
                (f.index > expected[-1]) & (f.index <= expected[-1] + pd.Timedelta(minutes=15))
            ].iterrows():
                if low <= r.close <= high:
                    continue
                prefix = pd.date_range(expected[-1] + pd.Timedelta(minutes=tf), at, freq=f"{tf}min")
                if not prefix.isin(f.index).all():
                    break
                if ready.loc[at] and strong.loc[at]:
                    if r.close > high and body.loc[at] > 0:
                        direction.loc[at] = "CE"
                    if r.close < low and body.loc[at] < 0:
                        direction.loc[at] = "PE"
                break
    return f, direction


def selected_contracts(db, requests):
    quote_map, selected = {}, {}
    for month, g in requests.groupby(requests.day.str[:7]):
        db.register("requests", g)
        p = (
            ROOT
            / f"data/research/five-minute-2026-09-26/public-options/five-minute/NIFTY-options-{month}-5m.parquet"
        )
        quotes = db.execute(
            """SELECT r.id,o.* FROM read_parquet(?) o JOIN requests r
            ON o.bar_close=r.quote_time AND o.option_type=r.direction""",
            [str(p)],
        ).df()
        quote_map.update({int(k): q for k, q in quotes.groupby("id")})
    all_daily = {p.name[:10]: p for p in (ROOT / "data/research/nse-daily/daily").glob("*.json.gz")}
    for day, g in requests.groupby("day"):
        prior = max((d for d in all_daily if d < day), default=None)
        listing = {}
        if prior and (pd.Timestamp(day) - pd.Timestamp(prior)).days <= 7:
            with gzip.open(all_daily[prior], "rt") as s:
                listing = {
                    (r["expiry"], float(r["strike"]), r["option_type"]): r["lot_size"]
                    for r in json.load(s)
                    if r["underlying"] == "NIFTY"
                }
        for r in g.to_dict("records"):
            candidates = []
            for q in quote_map.get(r["id"], pd.DataFrame()).to_dict("records"):
                lot = listing.get((q["expiry"], float(q["strike"]), q["option_type"]), 0)
                if not 0 <= (pd.Timestamp(q["expiry"]) - pd.Timestamp(day)).days <= 7 or lot <= 0:
                    continue
                if (
                    not np.isfinite([q["close"], q["volume"]]).all()
                    or q["close"] <= 0
                    or q["volume"] < 10 * lot
                ):
                    continue
                candidates.append(
                    (q["expiry"], abs(q["strike"] - r["spot"]), q["strike"], lot, q["close"])
                )
            if candidates:
                c = min(candidates)
                selected[r["id"]] = {
                    "expiry": c[0],
                    "strike": c[2],
                    "lot_size": c[3],
                    "observed_premium": c[4],
                    "listing_day": prior,
                }
    return selected


def outcome(path, at, hold, units, scenario, costs):
    slip = Decimal(".001" if scenario == "base" else ".003")
    tick = Decimal(".05")

    def fill(value, buy=False):
        price = Decimal(str(value)) * (1 + slip if buy else 1 - slip)
        return (price / tick).to_integral_value(
            rounding=ROUND_CEILING if buy else ROUND_FLOOR
        ) * tick

    def valid(when):
        if when not in path.index or isinstance(path.loc[when], pd.DataFrame):
            return False
        r = path.loc[when]
        return (
            np.isfinite(r[["open", "high", "low", "close", "volume"]].astype(float)).all()
            and min(r.open, r.high, r.low, r.close, r.volume) > 0
            and r.low <= min(r.open, r.close) <= max(r.open, r.close) <= r.high
        )

    if not valid(at):
        return {"reason": "missing_entry", "entered": False}
    entry = fill(path.loc[at].open, True)
    stop, target = entry - 10, entry + 20
    if stop <= 0:
        return {"reason": "nonpositive_stop", "entered": False}
    fee = fees(entry * units, True, scenario, costs)
    planned = (entry - fill(stop)) * units + fee + fees(fill(stop) * units, False, scenario, costs)
    if entry * units + fee > 20000:
        return {"reason": "unaffordable", "entered": False}
    if planned > 1000:
        return {"reason": "planned_risk_exceeded", "entered": False}
    deadline = at + pd.Timedelta(minutes=hold)
    for t in pd.date_range(at, deadline, freq="min"):
        if not valid(t):
            return {"reason": "missing_path", "entered": True}
        r = path.loc[t]
        ambiguous = False
        when = t
        if r.open <= float(stop):
            px, why = r.open, "sl"
        elif r.open >= float(target):
            px, why = target, "target"
        elif t == deadline:
            px, why = r.open, "time"
        elif r.low <= float(stop):
            px, why = stop, "sl"
            ambiguous = r.high >= float(target)
            when += pd.Timedelta(minutes=1)
        elif r.high >= float(target):
            px, why = target, "target"
            when += pd.Timedelta(minutes=1)
        else:
            continue
        exit_price = fill(px)
        exit_fee = fees(exit_price * units, False, scenario, costs)
        return {
            "reason": "priced",
            "entered": True,
            "entry_price": float(entry),
            "exit_price": float(exit_price),
            "stop": float(stop),
            "target": float(target),
            "entry_fee": float(fee),
            "exit_fee": float(exit_fee),
            "net_pnl": float((exit_price - entry) * units - fee - exit_fee),
            "exit_reason": why,
            "exit_at": when.isoformat(),
            "exit_bar": t.isoformat(),
            "ambiguous": bool(ambiguous),
            "planned_loss": float(planned),
            "premium_with_entry_fees": float(entry * units + fee),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder.resolve()
    m = load(folder / "registered-experiment.json")
    for n, sha in m["source_hashes"].items():
        assert fingerprint(ROOT / n) == sha, n
    assert fingerprint(ROOT / m["plan_path"]) == m["plan_sha256"]
    minute = raw_minutes(m)
    requests = pd.read_parquet(folder / "requests.parquet")
    nsignal = 0
    for family in ("ema921", "box"):
        for tf in (1, 3):
            group = f"{family}-{tf}m"
            f, d = signals(minute, tf, family)
            saved = pd.read_parquet(folder / f"{group}-signals.parquet")
            pd.testing.assert_frame_equal(f, saved[f.columns], check_names=False, check_freq=False)
            assert (d.to_numpy() == saved.direction.to_numpy()).all(), group
            req = requests[requests.group == group]
            at = pd.DatetimeIndex(req.signal_time).tz_convert("Asia/Kolkata")
            pd.testing.assert_index_equal(at, d[d != ""].index, check_names=False)
            assert (req.direction.to_numpy() == d[d != ""].to_numpy()).all()
            assert (req.spot.to_numpy() == f.loc[at].close.to_numpy()).all()
            assert (req.quote_time == req.signal_time.dt.floor("5min")).all()
            assert (
                req.day == req.signal_time.dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
            ).all()
            nsignal += len(saved)
    evidence = load(folder / "option-inputs.json")
    assert evidence["manifest_sha256"] == fingerprint(folder / "registered-experiment.json")
    for n, sha in evidence["inputs"].items():
        assert fingerprint(ROOT / n) == sha, n
    selections = pd.read_parquet(folder / "option-selections.parquet")
    with duckdb.connect() as db:
        db.execute("SET memory_limit='512MB'")
        db.execute("SET threads=2")
        db.execute("SET TimeZone='Asia/Kolkata'")
        expected = selected_contracts(db, requests)
        assert set(expected) == set(selections.id)
        for s in selections.to_dict("records"):
            for k, v in expected[s["id"]].items():
                assert s[k] == v, (s["id"], k)
            req = requests.set_index("id").loc[s["id"]]
            assert s["option_type"] == req["direction"], (s["id"], "option_type")
            for k in requests.columns:
                if k != "id":
                    assert s[k] == req[k], (s["id"], k)
        paths = []
        for year, g in selections.groupby(selections.day.str[:4]):
            db.register("selected", g)
            p = (
                ROOT
                / f"data/research/five-minute-2026-09-26/public-options/raw/NIFTY_{year}.parquet"
            )
            paths.append(
                db.execute(
                    """SELECT s.id,o.timestamp AS bar_open,o.open,o.high,o.low,o.close,
                o.volume,o.source,o.granularity,o.underlying FROM read_parquet(?) o JOIN selected s
                ON o.date=s.day AND o.expiry=s.expiry AND o.strike=s.strike AND o.option_type=s.option_type
                AND o.timestamp>=s.signal_time AND o.timestamp<=s.signal_time+INTERVAL 15 MINUTE
                ORDER BY s.id,o.timestamp""",
                    [str(p)],
                ).df()
            )
        raw = pd.concat(paths, ignore_index=True)
        raw["bar_open"] = pd.to_datetime(raw.bar_open, utc=True).dt.tz_convert("Asia/Kolkata")
        pd.testing.assert_frame_equal(raw, pd.read_parquet(folder / "option-paths.parquet"))
    raw = raw[
        (raw.source == "upstox_expired") & (raw.granularity == "1min") & (raw.underlying == "NIFTY")
    ]
    price = {int(i): g.set_index("bar_open") for i, g in raw.groupby("id")}
    lookup = selections.set_index("id")
    assert requests.id.is_unique and selections.id.is_unique
    checks = priced = 0
    for spec in m["specs"]:
        req = requests[requests.group == f"{spec['family']}-{spec['timeframe']}m"]
        for scenario in ("base", "stress"):
            actual = load(folder / spec["id"] / f"options-{scenario}.json")
            actual_by_id = {r["id"]: r for r in actual}
            counts, skipped = Counter(), Counter()
            until = None
            seen = []
            for r in req.to_dict("records"):
                at = r["signal_time"].tz_convert("Asia/Kolkata")
                end = at + pd.Timedelta(minutes=spec["hold"])
                if end.strftime("%H:%M") > "15:25":
                    skipped["late_signal"] += 1
                    continue
                if until is not None and at < until:
                    skipped["position_open"] += 1
                    continue
                if counts[r["day"]] >= 3:
                    skipped["daily_three_entry_cap"] += 1
                    continue
                seen.append(r["id"])
                saved = actual_by_id[r["id"]]
                assert saved["timestamp"] == at.isoformat() and saved["direction"] == r["direction"]
                if r["id"] not in expected:
                    want = {"reason": "no_observed_atm_with_prior_listing", "entered": False}
                else:
                    q = price.get(
                        r["id"], pd.DataFrame(index=pd.DatetimeIndex([], tz="Asia/Kolkata"))
                    )
                    want = outcome(
                        q, at, spec["hold"], int(lookup.loc[r["id"]].lot_size), scenario, m["costs"]
                    )
                for k, v in want.items():
                    assert saved[k] == v, (spec["id"], scenario, r["id"], k, saved[k], v)
                if want["entered"]:
                    counts[r["day"]] += 1
                    until = pd.Timestamp(want.get("exit_at", end))
                checks += 1
                priced += want["reason"] == "priced"
            assert seen == [r["id"] for r in actual]
            report = load(folder / spec["id"] / "results.json")
            assert report["skipped"][scenario] == dict(skipped)
            values = [r["net_pnl"] for r in actual if r["reason"] == "priced"]
            stats = report["options"][scenario]["affordable_at_initial_capital"]
            assert stats["count"] == len(values)
            if values:
                assert abs(stats["mean_net_pnl"] - np.mean(values)) < 1e-8
                assert stats["win_rate"] == sum(v > 0 for v in values) / len(values)
    report = {
        "hashes_match": True,
        "signal_rows_verified": nsignal,
        "contract_selections_verified": len(expected),
        "admission_and_execution_checks": checks,
        "priced_outcomes_verified": priced,
        "option_source_hashes_verified": len(evidence["inputs"]),
        "protected_sessions_evaluated": 0,
        "verifier_sha256": fingerprint(Path(__file__)),
    }
    with (folder / "verification.json").open("w") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
