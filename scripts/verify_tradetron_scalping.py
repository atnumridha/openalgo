"""Independently reconstruct saved Tradetron study exits and raw option fill arithmetic.

Does not import application signal, risk, selection or fee functions.
"""

import argparse
import gzip
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
    f = f[valid].set_index("at").sort_index()
    return f[~f.index.strftime("%Y-%m-%d").isin(manifest.get("excluded_sessions", []))]


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
    """Reconstruct each declared signal from OHLC independently of application code."""
    n = len(bars)
    close = bars.close.to_numpy()
    tf = 1 if family == "ema" else 5
    segments = (~bars.index.to_series().diff().eq(pd.Timedelta(minutes=tf))).cumsum()
    age = bars.groupby(segments).cumcount().to_numpy()
    buy, sell = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    if family == "ema":
        ma = {}
        for p in (5, 10):
            v = np.zeros(n)
            v[0] = close[0]
            alpha = 2 / (p + 1)
            for i in range(1, n):
                v[i] = alpha * close[i] + (1 - alpha) * v[i - 1]
            ma[p] = v
        difference = np.round(ma[5] - ma[10], 8)
        buy[1:] = (difference[1:] > 0) & (difference[:-1] <= 0)
        sell[1:] = (difference[1:] < 0) & (difference[:-1] >= 0)
        buy[:49], sell[:49] = False, False
    elif family == "divergence":
        delta = bars.close.diff()
        gains, losses = delta.clip(lower=0), (-delta).clip(lower=0)
        gains.iloc[14], losses.iloc[14] = gains.iloc[1:15].mean(), losses.iloc[1:15].mean()
        g = gains.iloc[14:].ewm(alpha=1 / 14, adjust=False).mean()
        loss = losses.iloc[14:].ewm(alpha=1 / 14, adjust=False).mean()
        rsi = (
            (100 - 100 / (1 + g / loss))
            .where(loss.ne(0), 100)
            .where(g.ne(0) | loss.ne(0), 50)
            .reindex(bars.index)
        )
        for prices, signs, flags in ((bars.low, 1, buy), (bars.high, -1, sell)):
            candidate = prices.shift(2) * signs
            mask = pd.concat(
                [candidate < prices.shift(k) * signs for k in (0, 1, 3, 4)], axis=1
            ).all(axis=1)
            mask &= segments.eq(segments.shift(4))
            pivots = pd.DataFrame(
                {
                    "index": np.arange(n) - 2,
                    "value": prices.shift(2),
                    "rsi": rsi.shift(2),
                    "segment": segments,
                }
            )[mask]
            previous = pivots.groupby("segment").shift()
            passed = (
                (pivots["index"] - previous["index"]).between(5, 60)
                & (pivots.value * signs < previous.value * signs)
                & (pivots.rsi * signs > previous.rsi * signs)
            )
            flags[bars.index.get_indexer(pivots.index[passed])] = True
        both = buy & sell
        buy[both], sell[both] = False, False
    elif family == "squeeze":
        mean = bars.close.rolling(20).mean()
        std = bars.close.rolling(20).std(ddof=0)
        upper, lower = mean + 2 * std, mean - 2 * std
        widths = (upper - lower) / mean
        threshold = widths.shift().rolling(120).quantile(0.1)
        squeezed = widths <= threshold
        gate = squeezed.shift().rolling(5).sum().gt(0).to_numpy() & (age >= 5)
        buy = gate & (bars.close > upper.shift()) & (bars.close.shift() <= upper.shift())
        sell = gate & (bars.close < lower.shift()) & (bars.close.shift() >= lower.shift())
        buy, sell = buy.to_numpy(), sell.to_numpy()
    else:
        true_ranges = np.maximum.reduce(
            [
                bars.high - bars.low,
                (bars.high - bars.close.shift()).abs().fillna(0),
                (bars.low - bars.close.shift()).abs().fillna(0),
            ]
        )
        atr = np.full(n, np.nan)
        atr[13] = true_ranges[:14].mean()
        for i in range(14, n):
            atr[i] = (13 * atr[i - 1] + true_ranges[i]) / 14
        for i in np.flatnonzero(age >= 20):
            row = bars.iloc[i]
            support, resistance = bars.low.iloc[i - 20 : i].min(), bars.high.iloc[i - 20 : i].max()
            upward = row.low <= support < row.close and row.close > row.open
            downward = row.high >= resistance > row.close and row.close < row.open
            if family == "range":
                compact = resistance - support <= 4 * atr[i - 1]
                buy[i] = compact and upward and row.close < (support + resistance) / 2
                sell[i] = compact and downward and row.close > (support + resistance) / 2
            else:
                body, span = abs(row.close - row.open), row.high - row.low
                top = row.high - max(row.close, row.open)
                bottom = min(row.close, row.open) - row.low
                valid = span > 0 and body <= span / 3
                buy[i] = (
                    valid
                    and upward
                    and bottom >= 2 * body
                    and bottom >= span / 2
                    and top <= span / 4
                )
                sell[i] = (
                    valid
                    and downward
                    and top >= 2 * body
                    and top >= span / 2
                    and bottom <= span / 4
                )
    expected = np.where(buy & (age >= 3), "CE", np.where(sell & (age >= 3), "PE", ""))
    mismatch = saved.index[saved.direction.to_numpy() != expected]
    assert len(mismatch) == 0, (family, list(mismatch[:5]))
    assert not saved.exit_ce.any() and not saved.exit_pe.any()
    np.testing.assert_allclose(saved.stop_price, close + np.where(expected == "CE", -15, 15))
    return n


def check_contract_selection(selection, by_id, db):
    """Check nearest expiry/ITM ranking using all as-of quoted candidates and listings."""
    checked = 0
    for month, part in selection.groupby(selection.day.str[:7]):
        db.register("candidate_requests", part[["id", "quote_time", "option_type"]])
        path = (
            ROOT
            / f"data/research/five-minute-2026-09-26/public-options/five-minute/NIFTY-options-{month}-5m.parquet"
        )
        candidates = db.execute(
            """SELECT r.id,o.* FROM read_parquet(?) o JOIN candidate_requests r
                                  ON r.quote_time=o.bar_close AND r.option_type=o.option_type""",
            [str(path)],
        ).df()
        candidate_map = {int(k): g for k, g in candidates.groupby("id")}
        for day, daily in part.groupby("listing_day"):
            listing_path = ROOT / f"data/research/nse-daily/daily/{day}.json.gz"
            with gzip.open(listing_path, "rt") as stream:
                listings = {
                    (r["expiry"], float(r["strike"]), r["option_type"]): r
                    for r in json.load(stream)
                    if r["underlying"] == "NIFTY"
                }
            for selected in daily.to_dict("records"):
                spot = by_id[selected["id"]]["close"]
                eligible = []
                for q in candidate_map[selected["id"]].to_dict("records"):
                    meta = listings.get((str(q["expiry"]), float(q["strike"]), q["option_type"]))
                    if not meta or not meta.get("lot_size"):
                        continue
                    days = (pd.Timestamp(q["expiry"]) - pd.Timestamp(selected["day"])).days
                    itm = q["strike"] < spot if q["option_type"] == "CE" else q["strike"] > spot
                    if (
                        itm
                        and 1 <= days <= 7
                        and q["close"] > 0
                        and q["volume"] >= 10 * int(meta["lot_size"])
                    ):
                        eligible.append(
                            (
                                str(q["expiry"]),
                                abs(q["strike"] - spot),
                                q["strike"],
                                int(meta["lot_size"]),
                            )
                        )
                expected = min(eligible)
                assert expected[0] == selected["expiry"] and expected[2] == selected["strike"]
                assert expected[3] == selected["lot_size"]
                checked += 1
    return checked


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
    result = {
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
