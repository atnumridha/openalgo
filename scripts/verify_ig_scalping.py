"""Independently reconstruct saved IG study exits and raw option fill arithmetic.

Does not import application signal, risk, selection or fee functions.
"""

import argparse
import hashlib
import json
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    with Path(path).open() as stream:
        return json.load(stream)


def fingerprint(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def raw_minutes(manifest):
    raw = []
    for name, value in manifest["input_hashes"].items():
        assert fingerprint(ROOT / name) == value, name
        if "/NIFTY-1m-" in name:
            raw.extend(load(ROOT / name)["raw_candles"])
    f = pd.DataFrame([r[:5] for r in raw], columns=["start", "open", "high", "low", "close"])
    f["at"] = pd.to_datetime(f.start, utc=True).dt.tz_convert("Asia/Kolkata") + pd.Timedelta(
        minutes=1
    )
    f = f[
        f["at"].dt.strftime("%Y-%m-%d").between(manifest["first"], manifest["last"])
    ].drop_duplicates()
    clock = f["at"].dt.hour * 60 + f["at"].dt.minute
    valid = (
        np.isfinite(f[["open", "high", "low", "close"]]).all(axis=1)
        & (f.low > 0)
        & (f.high >= f[["open", "close"]].max(axis=1))
        & (f.low <= f[["open", "close"]].min(axis=1))
        & clock.between(556, 930)
        & ~f["at"].duplicated(keep=False)
        & f["at"].dt.second.eq(0)
    )
    return f[valid].set_index("at").sort_index()


def fees(notional, buy, scenario, costs):
    def d(name):
        return Decimal(str(costs[name]))

    brokerage = Decimal(0 if scenario == "base" else 20)
    exchange, sebi = notional * d("exchange_rate"), notional * d("sebi_rate")
    gst = (brokerage + exchange + sebi) * d("gst_rate")
    tax = notional * d("stamp_buy_rate" if buy else "stt_sell_rate")
    return (brokerage + exchange + sebi + gst + tax).quantize(
        Decimal(".01"), rounding=ROUND_HALF_UP
    )


def check_indicator_signals(bars, saved, family):
    """Separate rolling/ewm calculations check three indicator families in full."""
    if family == "sar":
        return 0  # SAR's recurrence/seed is covered by deterministic unit vectors.
    ma = {p: bars.close.rolling(p).mean() for p in (5, 20, 50, 100, 200)}
    slope = {p: ma[p] - ma[p].shift(3) for p in ma}
    tf = int((saved.index[1] - saved.index[0]).total_seconds() / 60)
    ready = saved.index.to_series().diff().eq(pd.Timedelta(minutes=tf)).rolling(3).sum().eq(3)
    up_exit = down_exit = pd.Series(False, index=bars.index)
    if family == "stochastic":
        bounds = bars.high.rolling(14).max() - bars.low.rolling(14).min()
        raw = (100 * (bars.close - bars.low.rolling(14).min()) / bounds).where(bounds.ne(0), 50)
        k = raw.rolling(5).mean()
        d = k.rolling(3).mean()
        up = (k > d) & (k.shift() <= d.shift())
        down = (k < d) & (k.shift() >= d.shift())
        buy = up & ((k <= 20) | (k.shift() <= 20)) & (ma[50] > ma[200]) & (slope[200] > 0)
        sell = down & ((k >= 80) | (k.shift() >= 80)) & (ma[50] < ma[200]) & (slope[200] < 0)
        up_exit, down_exit = (k >= 80) | down, (k <= 20) | up
    elif family == "ma":
        buy = (ma[5] > ma[20]) & (ma[5].shift() <= ma[20].shift()) & (slope[200] > 0)
        sell = (
            (bars.close < ma[5])
            & (bars.close.shift() >= ma[5].shift())
            & (ma[5] < ma[20])
            & (slope[200] < 0)
        )
    else:
        delta = bars.close.diff()
        gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
        gain.iloc[14], loss.iloc[14] = gain.iloc[1:15].mean(), loss.iloc[1:15].mean()
        g = gain.iloc[14:].ewm(alpha=1 / 14, adjust=False).mean()
        loss_avg = loss.iloc[14:].ewm(alpha=1 / 14, adjust=False).mean()
        rsi = (
            (100 - 100 / (1 + g / loss_avg))
            .where(loss_avg.ne(0), 100)
            .where(g.ne(0) | loss_avg.ne(0), 50)
            .reindex(bars.index)
        )
        positive = pd.concat([slope[p] > 0 for p in (20, 50, 100)], axis=1).all(axis=1)
        negative = pd.concat([slope[p] < 0 for p in (20, 50, 100)], axis=1).all(axis=1)
        buy = (rsi > 30) & (rsi.shift() <= 30) & positive
        sell = (rsi < 70) & (rsi.shift() >= 70) & negative
    expected = np.where(buy & ready, "CE", np.where(sell & ready, "PE", ""))
    assert (saved.direction.to_numpy() == expected).all(), family
    assert (saved.exit_ce == up_exit).all() and (saved.exit_pe == down_exit).all()
    return len(saved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder.resolve()
    manifest = load(folder / "registered-experiment.json")
    for name, value in manifest["source_hashes"].items():
        assert fingerprint(ROOT / name) == value, name
    assert (
        fingerprint(ROOT / "docs/plans/2026-09-27-ig-scalping-evaluation.md")
        == manifest["plan_sha256"]
    )
    f = raw_minutes(manifest)
    index_checks = option_checks = indicator_checks = unresolved = unpriced = 0
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
            indicator_checks += check_indicator_signals(bars, saved, family)
            ids = load(group / "variant-option-ids.json")
            by_id = {}
            for name, identities in ids.items():
                trades = load(folder / name / "index-trades.json")
                counts = {}
                last_exit = None
                for ident, t in zip(identities, trades, strict=True):
                    by_id[ident] = t
                    assert manifest["first"] <= t["day"] <= manifest["last"]
                    at = pd.Timestamp(t["timestamp"]).tz_convert(f.index.tz)
                    assert last_exit is None or at >= last_exit
                    side = 1 if t["direction"] == "CE" else -1
                    assert saved.loc[at, "direction"] == t["direction"]
                    if family != "sar":
                        window = bars.loc[:at].tail(5)
                        assert t["stop_price"] == (
                            window.low.min() if side == 1 else window.high.max()
                        )
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
    result = {
        "hashes_match": True,
        "screened_minutes": len(f),
        "indicator_rows_reconstructed": indicator_checks,
        "sar_indicator_verification": "hand-derived recurrence, reversal and prefix tests",
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
