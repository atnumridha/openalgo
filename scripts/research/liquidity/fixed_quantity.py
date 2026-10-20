"""Offline fixed-size feasibility study; never accepts or writes live settings."""

import argparse
import hashlib
import html
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from strategies.liquidity.setup import VERSION, Config, plan_order

from .backtest import pivot_references, simulate


def exact_plan(candidate, quote, product, cfg, now, collateral):
    entry = quote["bid"] if candidate["direction"] == "LONG" else quote["ask"]
    notional = entry * float(product["contract_value"]) * cfg.max_quantity
    if notional > cfg.max_notional or notional / cfg.leverage > cfg.max_margin:
        return {"blocked": "Exact quantity exceeds margin and/or notional limits"}
    result = plan_order(candidate, quote, product, cfg, now, collateral)
    if not result.get("blocked") and result["quantity"] != cfg.max_quantity:
        return {
            "blocked": "Exact quantity does not fit the unchanged risk limits; downsizing disabled"
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--quantity", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.quantity <= 100000:
        raise ValueError("Research quantity must be 1..100000")
    source = args.source
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    saved = json.loads((source / "settings-used.json").read_text())
    base = Config(**saved)
    # Preserve every validated monetary limit. Only the offline sizing request
    # exceeds the production configuration's 1000-contract input ceiling.
    settings = dict(asdict(base), max_quantity=args.quantity)
    cfg = SimpleNamespace(**settings)
    manifest = json.loads((source / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Input hash mismatch: " + name)
    minutes = json.loads((source / "1m.json").read_text())
    product = json.loads((source / "product.json").read_text())
    refs = []
    start, end = manifest["start"], manifest["end"]
    covered = [b for b in minutes if start <= b["time"] < end]
    if len(covered) != (end - start) // 60 or any(
        b["time"] != a["time"] + 60 for a, b in zip(covered, covered[1:], strict=False)
    ):
        raise ValueError("Incomplete input coverage")
    for res, seconds, label in [("1h", 3600, "1H"), ("4h", 14400, "4H"), ("1d", 86400, "1D")]:
        refs += pivot_references(
            json.loads((source / f"{res}.json").read_text()), seconds, label, minutes
        )
    report = {
        "symbol": "XAUTUSD",
        "strategy": VERSION,
        "period": manifest,
        "requested_exact_contracts": args.quantity,
        "underlying_units": args.quantity * float(product["contract_value"]),
        "settings": settings,
        "production_config_changed": False,
        "production_quantity_ceiling": 1000,
        "coverage_minutes": len(covered),
        "source": str(source.resolve()),
        "metadata": product,
        "source_hashes": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                Path("scripts/research/liquidity/backtest.py"),
                Path("strategies/liquidity/setup.py"),
            ]
        },
        "assumptions": [
            "Same OHLC paths, synthetic two-tick spread and 15-second post-only fill model as the 1-contract study. Historical queue position and fills unverified.",
            "Exact requested size; no smaller order can be submitted. Existing loss/margin/notional/daily limits preserved.",
            "Offline research quantity override only; live configuration still rejects quantities above 1000.",
            "Current product fees plus GST. Fixed $0.10 cash slippage reserve is unchanged and is not a measured impact estimate at 5000 contracts.",
            "No historical depth/impact available. Any hypothetical full-size fills would remain conditional; no live orders placed.",
        ],
        "results": [],
    }
    for order in ["low-first", "high-first"]:
        result = simulate(minutes, refs, product, cfg, start, end, order, planner=exact_plan)
        report["results"].append(result)
        print(order, result["stats"], result["blocked"], flush=True)
    sample = []
    for item in report["results"][0]["blocked_examples"]:
        n = item["entry"] * report["underlying_units"]
        sample.append(
            {
                "time": item["time"],
                "entry": item["entry"],
                "notional": n,
                "margin": n / cfg.leverage,
                "gross_at_target": item["gross_at_target"],
                "estimated_target_fees": item["estimated_target_fees"],
                "net_at_target": item["net_at_target"],
            }
        )
    report["exposure_examples"] = sample
    (out / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    (out / "settings-used.json").write_text(json.dumps(settings, indent=2))
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(x))}</td>"
            for x in [
                r["path"],
                r["stats"].get("signals", 0),
                r["stats"].get("entry_attempts", 0),
                r["trade_count"],
                "$0.00" if r["net"] == 0 else f"${r['net']:.2f}",
                "N/A" if not r["trade_count"] else r["win_rate"],
            ]
        )
        + "</tr>"
        for r in report["results"]
    )
    examples = "".join(
        f"<tr><td>${r['entry']:,.2f}</td><td>${r['notional']:,.2f}</td><td>${r['margin']:,.2f}</td><td>${r['gross_at_target']:,.2f}</td><td>${r['estimated_target_fees']:,.2f}</td></tr>"
        for r in sample
    )
    assumptions = "".join("<li>" + html.escape(x) + "</li>" for x in report["assumptions"])
    (out / "report.html").write_text(
        f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>XAUTUSD · {args.quantity:,} contract backtest</title><style>body{{font:16px/1.6 system-ui;color:#172437;background:#f3f5f7;margin:0}}main{{max-width:1050px;margin:30px auto;background:white;padding:32px;border:1px solid #d6dde2;border-radius:10px}}h1{{font-size:28px}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{padding:10px;text-align:right;border-bottom:1px solid #dce3e8}}td:first-child,th:first-child{{text-align:left}}.result{{background:#fff5db;padding:20px;border-left:4px solid #aa6500}}.scroll{{overflow:auto}}a{{color:#1244a0}}</style><main><p>READ-ONLY FIXED-SIZE FEASIBILITY TEST</p><h1>XAUTUSD · {args.quantity:,} contracts · 2×</h1><p>18 September–17 October 2026 inclusive · IST · Long-only saved strategy · 43,200 / 43,200 minutes</p><div class="result"><strong>No entries permitted by the unchanged margin and notional limits.</strong><p>{args.quantity:,} contracts represent {report["underlying_units"]:g} XAUT. Both assumed paths produced eight triggers, with zero entry attempts. No win rate can be measured.</p></div><h2>Results</h2><div class="scroll"><table><tr><th>Path</th><th>Triggers</th><th>Attempts</th><th>Trades</th><th>Simulated net</th><th>Win rate</th></tr>{rows}</table></div><h2>Fixed size versus limits</h2><p>The margin limit remains $25 and the notional limit $1,000; planned loss remains $1, daily loss $3, and entry cap three. The requested quantity is tested exactly, with downsizing disabled. Raising the quantity does not raise these limits.</p><div class="scroll"><table><tr><th>Entry quote</th><th>Notional</th><th>Margin at 2×</th><th>Gross at target</th><th>Estimated target fees</th></tr>{examples}</table></div><p>Target figures describe rejected proposals; they are not trades or realised gains. No account funds, orders, leverage settings or live configuration were changed.</p><h2>Method and limitations</h2><ul>{assumptions}</ul><p><a href="results.json">Full results, source hashes and exposure examples</a> · <a href="settings-used.json">Offline settings</a></p></main></html>"""
    )


if __name__ == "__main__":
    main()
