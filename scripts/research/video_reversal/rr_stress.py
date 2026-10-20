"""Offline before-cost index-R stress comparison; no option P&L claim."""

import argparse
import csv
import hashlib
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .kotak import IST, completed_sessions, previous_daily, session_candidates, simulate_session

POLICIES = [
    {"name": "100% at2R", "first_r": 2, "runner_r": None, "first_fraction": 1, "min_room_r": 2},
    {
        "name": "100% at5R (projected)",
        "first_r": 5,
        "runner_r": None,
        "first_fraction": 1,
        "min_room_r": 2,
    },
    {
        "name": "100% at10R (projected)",
        "first_r": 10,
        "runner_r": None,
        "first_fraction": 1,
        "min_room_r": 2,
    },
    {
        "name": "80% at2R +20% at5R",
        "first_r": 2,
        "runner_r": 5,
        "first_fraction": 0.8,
        "min_room_r": 2,
    },
    {
        "name": "80% at2R +20% at10R",
        "first_r": 2,
        "runner_r": 10,
        "first_fraction": 0.8,
        "min_room_r": 2,
    },
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.source
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    original = json.loads((root / "results.json").read_text())
    fetch = json.loads((root / "fetch-manifest.json").read_text())
    start, end = original["period_inclusive"]
    report = {
        "period_inclusive": [start, end],
        "minimum_structural_room_r": 2,
        "source_directory": str(root.resolve()),
        "policies": POLICIES,
        "markets": {},
        "source_hashes": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                Path("scripts/research/video_reversal/rr.py"),
                Path("scripts/research/video_reversal/kotak.py"),
                Path("scripts/research/video_reversal/backtest.py"),
            ]
        },
        "limits": [
            "These are before-cost index-reference R/point results, not option net rupees or tradable index fills.",
            "At least2R room to the first known swing is required at the actual adverse observed entry. Higher5R/10R levels are projections and may pass opposing structure.",
            "Stop remains fixed; no widening or automatic breakeven. Up to two entries/session; exit any remainder15:15IST. Realised R can be below the planned reward due to stops, gaps or cutoff.",
            "Full-size2R/5R/10R cases compare target distance.80/20cases preserve partial profit-taking: full wins are2.6R and3.6R respectively, not5R/10R for the entire position.",
            "Same data and two synthetic intrabar paths. In-sample comparisons, no holdout validation or parameter search claim.",
            "Policies can take different entries: longer holds block subsequent signals under the single-position rule. This compares complete policies, not identical-entry target-only exits.",
            "Ordinary option charges and zero brokerage cannot be translated from index points without historical contracts/premium fills. Live settings were not changed.",
        ],
    }
    for symbol in ["NIFTY", "BANKNIFTY", "SENSEX"]:
        for suffix in ["1m", "D"]:
            name = f"{symbol}-{suffix}.json"
            assert (
                hashlib.sha256((root / name).read_bytes()).hexdigest()
                == fetch["files"][name]["sha256"]
            )
        sessions, audit = completed_sessions(
            json.loads((root / f"{symbol}-1m.json").read_text()), start, end
        )
        daily = {}
        for b in json.loads((root / f"{symbol}-D.json").read_text()):
            label = datetime.fromtimestamp(int(b["timestamp"]), IST).date().isoformat()
            daily[label] = (
                b
                if b["low"] > 0
                and b["low"] <= min(b["open"], b["close"])
                and b["high"] >= max(b["open"], b["close"])
                else None
            )
        result = {"coverage": audit, "cases": []}
        for n, policy in enumerate(POLICIES):
            for order in ["low-first", "high-first"]:
                trades = []
                stats = Counter()
                for day, bars in sessions.items():
                    previous = previous_daily(daily, day)
                    if not previous:
                        continue
                    cs = session_candidates(bars, previous)
                    ts, ss = simulate_session(bars, cs, order, rr_policy=policy)
                    trades.extend(dict(t, session=day) for t in ts)
                    stats.update(ss)
                wins = sum(t["points"] > 0 for t in trades)
                rs = [t["r_multiple"] for t in trades]
                equity = peak = dd = 0
                for r in rs:
                    equity += r
                    peak = max(peak, equity)
                    dd = max(dd, peak - equity)
                pos = sum(max(r, 0) for r in rs)
                neg = -sum(min(r, 0) for r in rs)
                row = {
                    "policy": policy["name"],
                    "path": order,
                    "entries": len(trades),
                    "positive_outcomes": wins,
                    "win_rate": 100 * wins / len(trades) if trades else None,
                    "sum_normalized_r": sum(rs),
                    "expectancy_r": sum(rs) / len(rs) if rs else None,
                    "profit_factor_r": pos / neg if neg else None,
                    "max_closed_drawdown_r": dd,
                    "weighted_index_points": sum(t["points"] for t in trades),
                    "stats": dict(stats),
                    "trades": trades,
                }
                result["cases"].append(row)
                with (out / f"{symbol}-policy{n + 1}-{order}.csv").open("w") as f:
                    fields = [
                        "session",
                        "side",
                        "option_direction",
                        "entry",
                        "stop",
                        "target",
                        "runner_target",
                        "structural_room_r",
                        "opened",
                        "exit_time",
                        "points",
                        "r_multiple",
                        "reason",
                    ]
                    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(trades)
                print(
                    symbol,
                    n + 1,
                    order,
                    len(trades),
                    row["win_rate"],
                    row["sum_normalized_r"],
                    flush=True,
                )
        report["markets"][symbol] = result
    (out / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))

    def f(n):
        return "N/A" if n is None else f"{n:+.2f}"

    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(x))}</td>"
            for x in [
                s,
                c["policy"],
                c["path"],
                c["entries"],
                f"{c['win_rate']:.1f}%" if c["win_rate"] is not None else "N/A",
                f(c["sum_normalized_r"]),
                f(c["expectancy_r"]),
                f(c["weighted_index_points"]),
            ]
        )
        + "</tr>"
        for s, m in report["markets"].items()
        for c in m["cases"]
    )
    limits = "".join("<li>" + html.escape(v) + "</li>" for v in report["limits"])
    (out / "report.html").write_text(
        f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Liquidity sweep ·2R/5R/10R stress test</title><style>body{{font:16px/1.6 system-ui;color:#172437;background:#f3f5f7;margin:0}}main{{max-width:1250px;background:white;margin:30px auto;padding:30px;border:1px solid #d6dde2;border-radius:10px}}h1{{font-size:28px}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:9px;border-bottom:1px solid #dce3e8;text-align:right}}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){{text-align:left}}.scroll{{overflow:auto}}.notice{{padding:18px;background:#fff4d8;border-left:4px solid #aa6500}}</style><main><h1>Liquidity sweep · Minimum2R stress test</h1><p>{start}–{end} inclusive · NIFTY / BANKNIFTY / SENSEX · Both CE/PE directions</p><div class="notice"><strong>No verified net rupee P&amp;L.</strong><p>Results are normalized index-price R and weighted points before option fees. Every entry requires at least2R structural room.5R/10R levels are projected stress targets, not confirmed liquidity destinations.</p></div><h2>Comparisons</h2><div class="scroll"><table><tr><th>Index</th><th>Policy</th><th>Assumed path</th><th>Entries</th><th>Positive outcomes</th><th>Sum normalized R</th><th>Mean R</th><th>Weighted index points</th></tr>{rows}</table></div><h2>Interpretation</h2><p>Each trade's initial price risk is1R. Summed R describes equal-risk normalization, not account returns or fixed-lot cash profits. A position that reaches2R on80% then loses the remaining20% at its original SL returns1.4R before costs. Reaching both2R/5R pays2.6R; reaching2R/10R pays3.6R. Cutoff exits can produce smaller outcomes.</p><ul>{limits}</ul><p>Coverage remains18valid NIFTY sessions,19BANKNIFTY and18SENSEX. One invalid session each excluded for NIFTY and SENSEX.</p><p><a href="results.json">Full results and assumptions</a></p></main></html>"""
    )


if __name__ == "__main__":
    main()
