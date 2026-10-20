"""Read-only per-session presentation of saved conditional expiry replays."""


def daily_rows(case, calendar, initial_capital, no_trade_status):
    cash = initial_capital
    blocked = False
    result = []
    for day in calendar:
        ts = [t for t in case["trades"] if t["session"] == day]
        closed = [t for t in ts if t["net"] is not None]
        if blocked:
            status = "Not evaluated after unresolved trade"
            net = gross = cost = None
        elif any(t["net"] is None for t in ts):
            status = "Unresolved exit"
            net = gross = cost = None
            blocked = True
            cash = None
        elif ts:
            status = "Resolved"
            gross = sum(t["gross"] for t in ts)
            cost = sum(t["fees"] for t in ts)
            net = gross - cost
            cash = ts[-1]["cash_after"]
        else:
            status, net = no_trade_status(day, cash)
            gross = 0 if net == 0 else None
            cost = 0 if net == 0 else None
        result.append(
            {
                "date": day,
                "status": status,
                "trades": len(ts),
                "wins": sum(t["net"] > 0 for t in closed),
                "lots": ",".join(str(t["lots"]) for t in ts),
                "gross": gross,
                "charges": cost,
                "net": net,
                "closing_capital": cash,
                "closed_subset_net": sum(t["net"] for t in closed),
            }
        )
    return result


def main():
    import csv
    import hashlib
    import html
    import json
    from datetime import datetime
    from pathlib import Path

    from services.kotak_assistant.analysis import fees

    from .capital import risk_limited_plan
    from .expiry_rupees import atr_before, valid
    from .kotak import IST

    back = Path("workspace/backtests")
    out = back / "expiry-daily-risk1000"
    out.mkdir(exist_ok=True)
    sources = [
        back / "nifty-expired-cycles-risk1000" / d
        for d in ["2026-09-22", "2026-09-29", "2026-10-06", "2026-10-13"]
    ]
    sources += [
        back / "nifty-19oct-expiry-rupee-study",
        *[back / "nifty-other-expiries-30000" / d for d in ["2026-10-27", "2026-11-03"]],
    ]
    indexroot = back / "kotak-liquidity-sweep-20260919-20261018"
    calendar = sorted(
        {
            datetime.fromtimestamp(b["timestamp"], IST).date().isoformat()
            for b in json.loads((indexroot / "NIFTY-D.json").read_text())
        }
    )
    good = set(
        json.loads((indexroot / "results.json").read_text())["markets"]["NIFTY"]["coverage"][
            "usable_dates"
        ]
    )
    audit = json.loads((back / "nifty-expired-cycles-risk1000/coverage-audit.json").read_text())
    missingmaster = {x["expiry"]: set(x["missing_master_dates"]) for x in audit}
    output = {
        "capital": 30000,
        "planned_loss_per_trade": 1000,
        "studies": [],
        "source_hashes": {},
        "limits": [
            "Native index daily sessions define the calendar. Weekends/non-session dates are omitted.",
            "No eligible recorded setup=0 simulated orders; missing data is unavailable, not zero. Closing cash may remain known when an entry was skipped for missing history.",
            "Unresolved exits make current and subsequent capital unavailable. Closed-subset profit is not a daily total when an exit is unknown.",
            "Requested windows differ by expiry. These are archived, previously inspected, conditional scenarios, not independent validation or actual broker executions.",
        ],
    }
    allrows = []
    for root in sources:
        rp = root / "capital-30000-maxlots-risk1000/results.json"
        report = json.loads(rp.read_text())
        events = json.loads((root / "events.json").read_text())
        expiry = report["expiry"]
        start, end = report["requested_period"]
        days = [d for d in calendar if start <= d <= min(end, expiry)]
        prices = {}
        for e in events:
            symbol = e["contract"]["symbol"]
            if symbol not in prices:
                p = root / (symbol + "-fresh.json")
                if not p.exists():
                    p = root / (symbol + "-cached.json")
                prices[symbol] = json.loads(p.read_text())
        study = {"expiry": expiry, "period": [start, end], "calendar": days, "cases": []}
        output["source_hashes"][str(rp)] = hashlib.sha256(rp.read_bytes()).hexdigest()
        for case in report["cases"]:
            if case["mode"] == "early":
                continue

            def unavailable(day, cash, case=case, expiry=expiry, events=events, prices=prices):
                if day in missingmaster.get(expiry, set()):
                    return "Missing dated contract master", None
                if day not in good:
                    return "Incomplete/invalid index session", None
                es = [e for e in events if e["session"] == day and e["path"] == case["path"]]
                if not es:
                    return "No eligible recorded setup", 0
                reasons = set()
                for e in es:
                    c = e["contract"]
                    rows = prices[c["symbol"]]
                    b = next((b for b in rows if b["timestamp"] == e["entry_time"]), None)
                    if b is None or not valid(b):
                        reasons.add("Missing/invalid entry premium")
                        continue
                    atr = atr_before(rows, e["entry_time"])
                    if atr is None:
                        reasons.add("Missing valid option ATR warmup")
                        continue

                    def charge(buy, sell, fee_day=day):
                        return fees(buy, sell, "NFO", 0, fee_day)["total"]

                    lots, _ = risk_limited_plan(
                        cash,
                        b["open"],
                        atr,
                        c["lotsize"],
                        c["tick_size"],
                        case["reward"],
                        charge,
                        1000,
                    )
                    if not lots:
                        reasons.add("Skipped: cash/risk budget")
                        continue
                    reasons.add("No recorded entry; inspect source")
                missing = any(
                    x.startswith("Missing") or x.startswith("No recorded") for x in reasons
                )
                return "; ".join(sorted(reasons)), None if missing else 0

            rows = daily_rows(case, days, 30000, unavailable)
            for row in rows:
                row.update(
                    expiry=expiry, mode=case["mode"], reward=case["reward"], path=case["path"]
                )
            study["cases"].append(
                {
                    "mode": case["mode"],
                    "reward": case["reward"],
                    "path": case["path"],
                    "rows": rows,
                    "scenario_net": case["net"],
                }
            )
            allrows.extend(rows)
            if case["net"] is not None:
                assert abs(sum(r["net"] or 0 for r in rows) - case["net"]) < 1e-7
        output["studies"].append(study)
    (out / "results.json").write_text(json.dumps(output, indent=2))
    with (out / "daily-results.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(allrows[0]))
        writer.writeheader()
        writer.writerows(allrows)

    def money(x):
        return "Unavailable" if x is None else f"₹{x:,.2f}"

    table = "".join(
        f'<tr data-expiry="{r["expiry"]}" data-mode="{r["mode"]}" data-reward="{r["reward"]}" data-path="{r["path"]}">'
        + "".join(
            "<td>" + html.escape(str(v)) + "</td>"
            for v in [
                r["expiry"],
                r["date"],
                r["trades"],
                r["lots"] or "—",
                money(r["gross"]),
                money(r["charges"]),
                money(r["net"]),
                money(r["closing_capital"]),
                r["status"],
            ]
        )
        + "</tr>"
        for r in allrows
    )
    options = "".join(f"<option>{s['expiry']}</option>" for s in output["studies"])
    periods = "; ".join(
        f"{s['expiry']}: {s['period'][0]}–{s['period'][1]}" for s in output["studies"]
    )
    limits = "".join("<li>" + html.escape(x) + "</li>" for x in output["limits"])
    (out / "report.html").write_text(
        f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Trading day results per expiry</title><style>body{{font:15px/1.6 system-ui;color:#172437;margin:28px}}td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:right}}td:last-child{{text-align:left}}table{{border-collapse:collapse}}.notice{{padding:18px;background:#fff1ce}}select{{padding:9px;margin:8px}}.scroll{{overflow:auto}}</style><h1>Each trading day · each expiry</h1><p class="notice">₹30,000 starting capital per scenario; maximum cash/risk-qualified lots;₹1,000 planned loss per trade after estimated costs. Zero brokerage. Conditional historical simulations; gaps can exceed the risk budget. Missing observations are unavailable, not₹0 profit.</p><label>Expiry <select id="expiry">{options}</select></label><label>SL <select id="mode"><option value="fixed">Fixed</option><option value="delayed">Delayed trailing</option></select></label><label>Target <select id="reward"><option>2</option><option>5</option><option>10</option></select>R</label><label>Underlying path <select id="path"><option>low-first</option><option>high-first</option></select></label><div class="scroll"><table><thead><tr><th>Expiry</th><th>Trading date</th><th>Trades</th><th>Lots per trade</th><th>Gross</th><th>Charges</th><th>Net</th><th>Closing capital</th><th>Status</th></tr></thead><tbody>{table}</tbody></table></div><p><a href="daily-results.csv">Download all daily rows CSV</a> · <a href="results.json">Full data and provenance</a></p><p>Study windows: {periods}</p><ul>{limits}</ul><script>const ids=['expiry','mode','reward','path'];document.getElementById('expiry').value='2026-10-19';function refresh(){{const v=Object.fromEntries(ids.map(id=>[id,document.getElementById(id).value]));document.querySelectorAll('tbody tr').forEach(r=>r.hidden=ids.some(k=>r.dataset[k]!==v[k]));}}ids.forEach(id=>document.getElementById(id).addEventListener('change',refresh));refresh();</script></html>"""
    )
    print(
        "Saved",
        len(allrows),
        "day/scenario rows across",
        len(output["studies"]),
        "expiries; resolved daily sums reconcile.",
    )


if __name__ == "__main__":
    main()
