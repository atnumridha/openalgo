"""Offline purchased-option premium replay. Conditional fills, never broker orders."""

import argparse
import csv
import hashlib
import html
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from services.kotak_assistant.analysis import fees

from .kotak import IST


def snap(value, tick, up=False):
    return round(
        (math.ceil if up else math.floor)(value / tick + (-1e-9 if up else 1e-9)) * tick, 8
    )


def valid(b):
    return (
        not b.get("repaired", False)
        and b.get("volume", 0) > 0
        and all(math.isfinite(float(b[k])) for k in ["open", "high", "low", "close"])
        and 0 < b["low"] <= min(b["open"], b["close"])
        and b["high"] >= max(b["open"], b["close"])
    )


def premium_plan(open_price, atr, qty, tick, reward, fee):
    entry = snap(open_price + 0.1, tick, True)
    stop = snap(entry - 1.5 * atr, tick, True)
    if not 0 < stop < entry:
        return None
    stop_fill = max(tick, snap(stop - 0.1, tick))
    risk = (entry - stop_fill) * qty + fee(entry * qty, stop_fill * qty)
    lo, hi = entry, entry + reward * risk / qty + max(1, entry * 0.1)

    def net(x):
        return (x - entry) * qty - fee(entry * qty, x * qty)

    while net(hi) < reward * risk:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if net(mid) >= reward * risk:
            hi = mid
        else:
            lo = mid
    target = snap(hi, tick, reward == 2)
    if target <= entry:
        return None
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_rupees": risk,
        "planned_net_reward_r": net(target) / risk,
    }


def replay(rows, start, cutoff, plan, qty, fee, tick, trailing=False):
    trail_policy = (
        trailing
        if isinstance(trailing, dict)
        else {"activation_r": 1, "gap_r": 1, "minimum_lock_r": 0}
    )
    by_time = {int(b["timestamp"]): b for b in rows}
    stop = plan["stop"]
    peak_net = 0.0
    updates = []
    for now in range(start, cutoff, 60):
        b = by_time.get(now)
        if b is None or not valid(b):
            return {
                "exit": None,
                "exit_time": now,
                "reason": "missing_or_invalid_bar",
                "gross": None,
                "fees": None,
                "net": None,
            }
        if b["low"] <= stop:
            price = max(tick, snap(min(b["open"], stop) - 0.1, tick))
            reason = "trailing_stop" if updates else "stop"
        elif b["high"] > plan["target"] + tick:
            price = plan["target"]
            reason = "target"
        elif now == cutoff - 60:
            price = max(tick, snap(b["close"] - 0.1, tick))
            reason = "15:15_cutoff"
        else:
            if trailing:
                mark_fill = max(tick, snap(b["close"] - 0.1, tick))
                mark_net = (mark_fill - plan["entry"]) * qty - fee(
                    plan["entry"] * qty, mark_fill * qty
                )
                peak_net = max(peak_net, mark_net)
                if peak_net >= trail_policy["activation_r"] * plan["risk_rupees"]:
                    floor_net = max(
                        trail_policy["minimum_lock_r"] * plan["risk_rupees"],
                        peak_net - trail_policy["gap_r"] * plan["risk_rupees"],
                    )
                    lo, hi = plan["entry"], b["close"]

                    def protected(trigger):
                        fill = max(tick, snap(trigger - 0.1, tick))
                        return (fill - plan["entry"]) * qty - fee(plan["entry"] * qty, fill * qty)

                    for _ in range(60):
                        mid = (lo + hi) / 2
                        if protected(mid) >= floor_net:
                            hi = mid
                        else:
                            lo = mid
                    proposed = snap(hi, tick, True)
                    if stop < proposed < b["close"]:
                        stop = proposed
                        updates.append(
                            {
                                "effective_from": now + 60,
                                "stop": stop,
                                "protected_net": protected(stop),
                                "peak_net": peak_net,
                            }
                        )
            continue
        gross = (price - plan["entry"]) * qty
        charge = fee(plan["entry"] * qty, price * qty)
        return {
            "exit": price,
            "exit_time": now + 60,
            "reason": reason,
            "gross": gross,
            "fees": charge,
            "net": gross - charge,
            "stop_updates": updates,
            "final_stop": stop,
        }
    return {
        "exit": None,
        "exit_time": cutoff,
        "reason": "no_execution_window",
        "gross": None,
        "fees": None,
        "net": None,
    }


def atr_before(rows, start):
    prior = sorted((b for b in rows if b["timestamp"] < start), key=lambda b: b["timestamp"])
    run = []
    for b in prior:
        if not valid(b) or (run and b["timestamp"] != run[-1]["timestamp"] + 60):
            run = []
        if valid(b):
            run.append(b)
    if len(run) < 15 or run[-1]["timestamp"] != start - 60:
        return None
    tr = [
        max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"]))
        for a, b in zip(run, run[1:], strict=False)
    ]
    atr = sum(tr[:14]) / 14
    for x in tr[14:]:
        atr = (atr * 13 + x) / 14
    return atr if atr > 0 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--trailing", action="store_true")
    args = parser.parse_args()
    root = args.directory
    out = root / "trailing" if args.trailing else root
    out.mkdir(parents=True, exist_ok=True)
    events = json.loads((root / "events.json").read_text())
    prices = {}
    for symbol in {e["contract"]["symbol"] for e in events}:
        p = root / (symbol + "-fresh.json")
        if not p.exists():
            p = root / (symbol + "-cached.json")
        prices[symbol] = json.loads(p.read_text())
    report = {
        "expiry": "2026-10-19",
        "requested_period": ["2026-09-19", "2026-10-18"],
        "cases": [],
        "trailing": args.trailing,
        "assumptions": [
            "Only NIFTY has matching 19-OCT-26 index option contracts in the connected instrument master. Market on19Oct has not opened at study time; data ends16Oct.",
            "One lot=65units; nearest-ATM CE for bullish or PE for bearish, selected using index price when a strict next-candle break is observed. No switching to a better-covered strike.",
            "Underlying candidates require2R room to the known swing using actual adverse index reference entry. This is a separate premium execution template, not a literal index-stop conversion.",
            "Buy at next minute open plus0.10 premium slippage, rounded up; SL1.5x completed Wilder ATR14 of option premium, rounded tighter. Net2R/5R/10R targets include estimated round-trip costs and stop slippage; higher caps round down.",
            "A whole position exits at target, SL or15:15. Max2 entries/day, one position. Stop first if a minute contains both stop and target. Gap stops use adverse open. Missing/invalid/zero-volume observations leave outcome unresolved and block further entries for that session.",
            "Historical OHLC does not prove maker queue fills, bid/ask, available quantity or actual executions. Conditional market-price fill proxy only; no claim that maker-only entries would execute.",
            "Current instrument metadata confirms expiry/tick/lot.65unit lot is assumed unchanged across older sessions; the archived14Oct contract snapshot supports that day only. Pre14Oct results have historical metadata uncertainty.",
            "Brokerage is zero as requested; existing dated NFO estimator adds STT, exchange fees, SEBI, GST and stamp duty. Charges are estimates pending contract notes. No exercise settlement: all positions must close intraday.",
            "This is coverage-limited, in-sample research, not a complete one-month option result. Low-first/high-first assumptions refer to underlying signal timing; option exits always use adverse same-bar sequencing. No live settings changed.",
        ],
        "source_hashes": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), Path("services/kotak_assistant/analysis.py")]
        },
        "input_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.glob("*.json")
            if p.name not in ["results.json", "validation.json"]
        },
    }
    if args.trailing:
        report["assumptions"].append(
            "Trailing activates at completed-candle estimated net peak>=1R initial cash risk. Protect peak minus1R, at least net breakeven, including fees and0.10 exit slippage; ratchet only. Close-based update effective next minute, never same-bar high/low hindsight. Targets remain fixed; realised trailing wins may be below2R. Gaps can exceed protected floors. Minute data cannot establish second-by-second trailing."
        )
    for order in ["low-first", "high-first"]:
        for reward in [2, 5, 10]:
            trades = []
            skips = Counter()
            busy = 0
            counts = Counter()
            for e in sorted((x for x in events if x["path"] == order), key=lambda x: x["observed"]):
                day = e["session"]
                start = e["entry_time"]
                cutoff = int(datetime.fromisoformat(day + "T15:15:00+05:30").timestamp())
                if start >= cutoff:
                    skips["too_late"] += 1
                    continue
                if start < busy or counts[day] >= 2:
                    skips["position_or_daily_cap"] += 1
                    continue
                c = e["contract"]
                rows = prices[c["symbol"]]
                by_time = {int(b["timestamp"]): b for b in rows}
                b = by_time.get(start)
                if b is None or not valid(b):
                    skips["entry_premium_unavailable"] += 1
                    continue
                atr = atr_before(rows, start)
                if atr is None:
                    skips["option_atr_warmup_unavailable"] += 1
                    continue

                def charge(buy, sell, fee_day=day):
                    return fees(buy, sell, "NFO", 0, fee_day)["total"]

                plan = premium_plan(b["open"], atr, c["lotsize"], c["tick_size"], reward, charge)
                if not plan:
                    skips["invalid_plan"] += 1
                    continue
                t = replay(
                    rows,
                    start,
                    cutoff,
                    plan,
                    c["lotsize"],
                    charge,
                    c["tick_size"],
                    trailing=args.trailing,
                )
                t.setdefault("stop_updates", [])
                t.setdefault("final_stop", plan["stop"])
                trades.append(
                    dict(
                        session=day,
                        symbol=c["symbol"],
                        quantity=c["lotsize"],
                        strike=c["strike"],
                        expiry="2026-10-19",
                        opened=start,
                        atr=atr,
                        **plan,
                        **t,
                    )
                )
                counts[day] += 1
                busy = t["exit_time"] if t["net"] is not None else cutoff
            closed = [t for t in trades if t["net"] is not None]
            complete = all(t["net"] is not None for t in trades)
            summary = {
                "path": order,
                "reward": reward,
                "entries": len(trades),
                "resolved": len(closed),
                "unresolved": len(trades) - len(closed),
                "wins": sum(t["net"] > 0 for t in closed),
                "gross": sum(t["gross"] for t in closed),
                "fees": sum(t["fees"] for t in closed),
                "closed_subset_net": sum(t["net"] for t in closed),
                "net": sum(t["net"] for t in closed) if complete else None,
                "skips": dict(skips),
                "trades": trades,
            }
            report["cases"].append(summary)
            with (out / f"trades-{order}-{reward}R.csv").open("w") as f:
                if trades:
                    writer = csv.DictWriter(f, fieldnames=list(trades[0]))
                    writer.writeheader()
                    writer.writerows(trades)
            print({k: v for k, v in summary.items() if k not in ["trades"]})
    (out / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))

    def money(n):
        return "Unavailable" if n is None else f"₹{n:,.2f}"

    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(x))}</td>"
            for x in [
                c["path"],
                f"1:{c['reward']}",
                c["entries"],
                c["resolved"],
                c["unresolved"],
                c["wins"],
                money(c["gross"]),
                money(c["fees"]),
                money(c["net"]),
                money(c["closed_subset_net"]),
            ]
        )
        + "</tr>"
        for c in report["cases"]
    )
    title_suffix = " · Trailing SL" if args.trailing else ""
    comparison = ""
    if args.trailing:
        baseline = json.loads((root / "results.json").read_text())
        fixed = next(c for c in baseline["cases"] if c["reward"] == 2 and c["path"] == "low-first")
        current = next(c for c in report["cases"] if c["reward"] == 2 and c["path"] == "low-first")
        comparison = f'<h2>Fixed versus trailing SL</h2><p>1:2 target: fixed SL net {money(fixed["net"])}; trailing SL net {money(current["net"])}. Trailing activates at +1R completed-candle net profit and protects peak minus1R. Updates apply next minute; the stop never loosens. Targets remain unchanged, but trailing exits can realise less than2R.</p><p><a href="../report.html">Original fixed-SL report</a></p>'
    limits = "".join("<li>" + html.escape(x) + "</li>" for x in report["assumptions"])
    (out / "report.html").write_text(
        f'<!doctype html><html lang="en"><meta charset="utf-8"><title>NIFTY19Oct expiry · rupee study</title><style>body{{font:16px/1.6 system-ui;margin:35px;color:#172437}}table{{border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:right}}.notice{{background:#fff1ce;padding:20px}}</style><h1>NIFTY ·19October2026 expiry · One lot{title_suffix}</h1><p class="notice">Conditional premium replay, not actual trading P&amp;L. Coverage-limited19Sept–18Oct request, last available session16Oct. Missing outcomes remain unavailable.₹0 brokerage, estimated other charges included. No maker-fill verification.</p>{comparison}<table><tr><th>Underlying path</th><th>Net target</th><th>Entries</th><th>Resolved</th><th>Unresolved</th><th>Net wins</th><th>Closed gross</th><th>Closed charges</th><th>Total net</th><th>Closed subset net</th></tr>{rows}</table><h2>Assumptions and coverage</h2><ul>{limits}</ul><p><a href="results.json">Full results and per-trade prices</a></p></html>'
    )


if __name__ == "__main__":
    main()
