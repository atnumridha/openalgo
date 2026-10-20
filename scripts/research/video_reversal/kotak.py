"""Read-only Indian-index signal study, never an executable option-P&L claim."""

import argparse
import csv
import hashlib
import html
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .backtest import candidate, path, trigger_hit
from .rr import levels

IST = timezone(timedelta(hours=5, minutes=30))


def previous_daily(daily, day):
    dates = [d for d in daily if d < day]
    return daily[max(dates)] if dates else None


def completed_sessions(rows, start, end):
    grouped = {}
    invalid = Counter()
    raw_days = set()
    for r in rows:
        t = int(r["timestamp"])
        stamp = datetime.fromtimestamp(t, IST)
        day = stamp.date().isoformat()
        minute = stamp.hour * 60 + stamp.minute
        if not start <= day <= end or stamp.weekday() >= 5 or not 555 <= minute < 915:
            continue
        raw_days.add(day)
        if (
            r.get("repaired")
            or t % 60
            or not all(math.isfinite(float(r[k])) for k in ["open", "high", "low", "close"])
            or r["low"] <= 0
            or r["low"] > min(r["open"], r["close"])
            or r["high"] < max(r["open"], r["close"])
        ):
            invalid[day] += 1
            continue
        b = {k: r[k] for k in ["open", "high", "low", "close"]}
        b["time"] = t
        grouped.setdefault(day, []).append(b)
    good = {}
    excluded = []
    for day in sorted(raw_days):
        bars = sorted(grouped.get(day, []), key=lambda b: b["time"])
        opening = int(datetime.fromisoformat(day + "T09:15:00+05:30").timestamp())
        if (
            len(bars) == 360
            and {b["time"] for b in bars} == set(range(opening, opening + 360 * 60, 60))
            and not invalid[day]
        ):
            good[day] = bars
        else:
            excluded.append(day)
    return good, {
        "observed_sessions": len(raw_days),
        "usable_complete_sessions": len(good),
        "expected_execution_minutes": len(raw_days) * 360,
        "valid_execution_minutes": sum(len(v) for v in grouped.values()),
        "invalid_candles": sum(invalid.values()),
        "excluded_sessions": excluded,
        "usable_dates": list(good),
    }


def session_candidates(bars, daily, tick=0.05):
    out = {}
    swings = {"low": [], "high": []}
    exc = {}
    if not daily:
        return out
    for i, b in enumerate(bars):
        prev = bars[i - 1]["close"] if i else daily["close"]
        for side, field, origin in [("short", "high", "low"), ("long", "low", "high")]:
            level = daily[field]
            cross = prev <= level < b["high"] if side == "short" else prev >= level > b["low"]
            if cross:
                targets = [
                    x["price"]
                    for x in swings[origin]
                    if (x["price"] < level if side == "short" else x["price"] > level)
                ]
                exc[side] = {"extreme": level, "target": targets[-1] if targets else None}
            context = exc.get(side)
            if not context:
                continue
            old = context["extreme"]
            context["extreme"] = (max if side == "short" else min)(old, b[field])
            c = candidate(b, side, level, context["target"], old, tick)
            if context["target"] is not None and (
                b["low"] <= context["target"] if side == "short" else b["high"] >= context["target"]
            ):
                context["target"] = None
                c = None
            if c:
                out.setdefault(c["known"], []).append(c)
        if i >= 4:
            w = bars[i - 4 : i + 1]
            p = w[2]
            for field in ["low", "high"]:
                if all(
                    (p[field] < x[field] if field == "low" else p[field] > x[field])
                    for x in w
                    if x is not p
                ):
                    swings[field].append({"price": p[field], "known": b["time"] + 60})
    return out


def simulate_session(bars, candidates, order, tick=0.05, rr_policy=None):
    pos = None
    used = set()
    trades = []
    stats = Counter()
    cutoff = bars[0]["time"] + 360 * 60

    def close(qty, price, now, reason):
        nonlocal pos
        sign = 1 if pos["side"] == "long" else -1
        pos["points"] += qty * sign * (price - pos["entry"])
        pos["remaining"] -= qty
        if pos["remaining"] < 1e-9:
            pos["exit_time"] = now
            pos["reason"] = reason
            pos["initial_risk_points"] = abs(pos["entry"] - pos["stop"])
            pos["r_multiple"] = pos["points"] / pos["initial_risk_points"]
            trades.append(pos)
            pos = None

    for b in bars:
        watch = candidates.get(b["time"], [])
        if not watch and not pos:
            continue
        for now, mid in path(b, order):
            if pos:
                short = pos["side"] == "short"
                stop = mid >= pos["stop"] if short else mid <= pos["stop"]
                if stop:
                    close(
                        pos["remaining"],
                        max(mid, pos["stop"]) if short else min(mid, pos["stop"]),
                        now,
                        "stop",
                    )
                elif not pos["t1_hit"] and (
                    mid <= pos["target"] if short else mid >= pos["target"]
                ):
                    pos["t1_hit"] = True
                    close(pos.get("first_fraction", 0.8), pos["target"], now, "first_target")
                if (
                    pos
                    and pos["t1_hit"]
                    and pos.get("runner_target") is not None
                    and (mid <= pos["runner_target"] if short else mid >= pos["runner_target"])
                ):
                    close(pos["remaining"], pos["runner_target"], now, "runner_target")
                if pos and now == cutoff - 1:
                    close(pos["remaining"], mid, now, "15:15_cutoff")
            for c in watch:
                if c["id"] in used or pos or not trigger_hit(c, mid, now):
                    continue
                used.add(c["id"])
                stats["triggers"] += 1
                if len(trades) >= 2:
                    stats["daily_cap_rejections"] += 1
                    continue
                short = c["side"] == "short"
                entry = min(mid, c["trigger"] - tick) if short else max(mid, c["trigger"] + tick)
                # A gap already beyond the target cannot become a hindsight win.
                if (
                    (mid <= c["target"] or entry >= c["stop"])
                    if short
                    else (mid >= c["target"] or entry <= c["stop"])
                ):
                    stats["invalid_geometry"] += 1
                    continue
                rr_plan = levels(c, entry, rr_policy, tick) if rr_policy is not None else {}
                if rr_plan is None:
                    stats["below_2R_or_invalid_projection"] += 1
                    continue
                pos = dict(
                    c,
                    entry=entry,
                    opened=now,
                    remaining=1.0,
                    points=0.0,
                    t1_hit=False,
                    option_direction="BUY PE" if short else "BUY CE",
                )
                pos.update(rr_plan)
                # A final-second signal has no post-cutoff life.
                if now == cutoff - 1:
                    close(1.0, mid, now, "15:15_cutoff")
    if pos:
        raise ValueError("Position not resolved before session cutoff")
    return trades, dict(stats)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--start", default="2026-09-18")
    parser.add_argument("--end", default="2026-10-17")
    args = parser.parse_args()
    root = args.directory
    start, end = args.start, args.end
    if date.fromisoformat(start) > date.fromisoformat(end):
        parser.error("Start date must not follow end date")
    fetch = json.loads((root / "fetch-manifest.json").read_text())
    report = {
        "strategy": "daily-liquidity-sweep-video-interpretation",
        "period_inclusive": [start, end],
        "execution_window_ist": "09:15–15:15",
        "markets": {},
        "source_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "Underlying index reference-point study. Long means BUY CE direction; short means BUY PE direction, not selling the index or shorting options.",
            "No option premium execution, monetary P&L, brokerage/taxes or option win rate is claimed. Zero brokerage does not remove taxes; those require actual premium fills and dated contract metadata.",
            "Index references cannot rest maker orders. Maker-only eligibility belongs to the selected option book; historical option bid/ask, queues and dated expiry/strike selection are incomplete.",
            "Previous completed native daily wick H/L; strict2+2 swings from current session only supply T1. No extra reclaim-close requirement. Signal may close on either side of swept reference.",
            "Next-candle strict break; signal high/low +one0.05point buffer is index stop. Take80% at origin swing and hold20% with original stop until15:15. Reference entry uses the adverse of the observed break price or trigger±0.05; gaps never obtain a missing trigger price. This is not an executable option fill.",
            "Two reference entries per session; one position. Both assumed O-L-H-C and O-H-L-C minute paths shown; not recorded intrabar events.",
            "Only complete, unrepaired360-minute sessions are tested. Partial/invalid sessions are excluded, not patched. This is not full375-minute exchange-session coverage.",
            "No live orders, strategy activation, stop changes or account-sizing changes were made.",
        ],
    }
    for symbol in ["NIFTY", "BANKNIFTY", "SENSEX"]:
        for suffix in ["1m", "D"]:
            file = f"{symbol}-{suffix}.json"
            info = fetch["files"][file]
            if hashlib.sha256((root / file).read_bytes()).hexdigest() != info["sha256"]:
                raise ValueError("Input hash mismatch")
        raw = json.loads((root / f"{symbol}-1m.json").read_text())
        sessions, audit = completed_sessions(raw, start, end)
        daily = {}
        for item in json.loads((root / f"{symbol}-D.json").read_text()):
            label = datetime.fromtimestamp(int(item["timestamp"]), IST).date().isoformat()
            valid = (
                all(math.isfinite(float(item[k])) for k in ["open", "high", "low", "close"])
                and item["low"] > 0
                and item["low"] <= min(item["open"], item["close"])
                and item["high"] >= max(item["open"], item["close"])
            )
            daily[label] = item if valid else None
        expected_days = [day for day in daily if start <= day <= end]
        audit["native_daily_sessions_in_period"] = len(expected_days)
        audit["missing_entire_sessions"] = sorted(
            set(expected_days) - set(audit["usable_dates"]) - set(audit["excluded_sessions"])
        )
        result = {"coverage": audit, "results": []}
        for order in ["low-first", "high-first"]:
            trades = []
            stats = Counter()
            candidates = 0
            missing = []
            for day, bars in sessions.items():
                d = previous_daily(daily, day)
                if not d:
                    missing.append(day)
                    continue
                cs = session_candidates(bars, d)
                candidates += sum(len(v) for v in cs.values())
                ts, ss = simulate_session(bars, cs, order)
                trades.extend(dict(t, session=day) for t in ts)
                stats.update(ss)
            wins = sum(t["points"] > 0 for t in trades)
            equity = peak = dd = 0
            for t in trades:
                equity += t["points"]
                peak = max(peak, equity)
                dd = max(dd, peak - equity)
            row = {
                "path": order,
                "candidates": candidates,
                "reference_entries": len(trades),
                "long_ce": sum(t["side"] == "long" for t in trades),
                "short_pe": sum(t["side"] == "short" for t in trades),
                "positive_reference_outcomes": wins,
                "reference_win_rate": 100 * wins / len(trades) if trades else None,
                "weighted_index_points": equity,
                "average_r": sum(t["r_multiple"] for t in trades) / len(trades) if trades else None,
                "max_closed_drawdown_points": dd,
                "missing_daily_refs": missing,
                "stats": dict(stats),
                "trades": trades,
            }
            result["results"].append(row)
            with (root / f"{symbol}-{order}-signals.csv").open("w") as f:
                fields = [
                    "session",
                    "side",
                    "option_direction",
                    "opened",
                    "entry",
                    "stop",
                    "target",
                    "exit_time",
                    "points",
                    "r_multiple",
                    "t1_hit",
                    "reason",
                ]
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(trades)
            print(symbol, order, len(trades), row["reference_win_rate"], equity, flush=True)
        report["markets"][symbol] = result
    (root / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(x))}</td>"
            for x in [
                symbol,
                m["coverage"]["usable_complete_sessions"],
                r["path"],
                r["long_ce"],
                r["short_pe"],
                r["reference_entries"],
                f"{r['reference_win_rate']:.1f}%" if r["reference_win_rate"] is not None else "N/A",
                f"{r['weighted_index_points']:+.2f}",
                f"{r['average_r']:+.2f}" if r["average_r"] is not None else "N/A",
            ]
        )
        + "</tr>"
        for symbol, m in report["markets"].items()
        for r in m["results"]
    )
    limits = "".join("<li>" + html.escape(x) + "</li>" for x in report["limitations"])
    coverage = "".join(
        f"<li>{symbol}: {m['coverage']['valid_execution_minutes']:,}/{m['coverage']['expected_execution_minutes']:,} valid minutes; excluded sessions: {', '.join(m['coverage']['excluded_sessions']) or 'none'}.</li>"
        for symbol, m in report["markets"].items()
    )
    (root / "report.html").write_text(
        f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kotak Neo · Liquidity sweep research</title><style>body{{font:16px/1.6 system-ui;color:#172437;background:#f3f5f7;margin:0}}main{{max-width:1150px;margin:30px auto;padding:32px;background:white;border:1px solid #d6dde2;border-radius:10px}}h1{{font-size:28px}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{padding:10px;text-align:right;border-bottom:1px solid #dce3e8}}td:first-child,th:first-child{{text-align:left}}.notice{{background:#fff5dc;padding:20px;border-left:4px solid #aa6500}}.scroll{{overflow:auto}}</style><main><p>READ-ONLY KOTAK NEO RESEARCH</p><h1>Daily liquidity sweep · NIFTY / BANKNIFTY / SENSEX</h1><p>{html.escape(start)}–{html.escape(end)} inclusive ·09:15–15:15IST · Two directions · Up to two reference entries per session</p><div class="notice"><strong>These are index-pattern outcomes, not option trades or rupee profits.</strong><p>Fresh authenticated Kotak history was retrieved. Complete execution windows are tested; invalid sessions are excluded. Historical option fills and maker execution are not established.</p></div><h2>Signal results</h2><div class="scroll"><table><tr><th>Index</th><th>Sessions</th><th>Assumed path</th><th>CE direction</th><th>PE direction</th><th>Entries</th><th>Positive points</th><th>Weighted index points</th><th>Mean R</th></tr>{rows}</table></div><p>80%/20% weighted reference-point outcomes use one normalized index unit. They cannot be converted to option P&amp;L, multiplied by option lot size, or compared across indices as currency. Each row reuses its index's same data under a different assumed intrabar path.</p><h2>Coverage</h2><ul>{coverage}</ul><h2>Method and limits</h2><ul>{limits}</ul><p>Zero brokerage is retained as the user's Kotak account preference. Fees and net option P&amp;L are unavailable for this index-only study; unavailable is not zero.</p><p><a href="results.json">Full results</a> · <a href="fetch-manifest.json">Source hashes and retrieval record</a></p></main></html>"""
    )


if __name__ == "__main__":
    main()
