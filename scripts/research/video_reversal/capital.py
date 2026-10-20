"""Cash-funded maximum-lot option replay; offline research only."""

import math


def affordable_lots(cash, entry, lot_size, entry_fee):
    lots = max(0, math.floor(cash / (entry * lot_size)))
    while lots and lots * entry * lot_size + entry_fee(lots * entry * lot_size) > cash + 1e-9:
        lots -= 1
    return lots


def risk_limited_plan(cash, open_price, atr, lot_size, tick, reward, fee, max_loss):
    from .expiry_rupees import premium_plan, snap

    entry = snap(open_price + 0.1, tick, True)
    lots = affordable_lots(cash, entry, lot_size, lambda turnover: fee(turnover, 0))
    while lots:
        plan = premium_plan(open_price, atr, lots * lot_size, tick, reward, fee)
        if plan is None:
            return 0, None
        if max_loss is None or plan["risk_rupees"] <= max_loss + 1e-9:
            return lots, plan
        lots -= 1
    return 0, None


def event_in_window(event, study):
    start, end = study["requested_period"]
    return start <= event["session"] <= min(end, study["expiry"])


def main():
    import argparse
    import csv
    import hashlib
    import html
    import json
    from collections import Counter
    from datetime import datetime
    from pathlib import Path

    from services.kotak_assistant.analysis import fees

    from .expiry_rupees import atr_before, premium_plan, replay, snap, valid

    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--capital", type=float, default=30000)
    parser.add_argument("--max-loss", type=float)
    args = parser.parse_args()
    if not math.isfinite(args.capital) or args.capital <= 0:
        parser.error("Positive capital required")
    if args.max_loss is not None and (not math.isfinite(args.max_loss) or args.max_loss <= 0):
        parser.error("Positive max-loss required")
    root = args.directory
    suffix = f"-risk{args.max_loss:g}" if args.max_loss is not None else ""
    out = root / f"capital-{args.capital:g}-maxlots{suffix}"
    out.mkdir(parents=True, exist_ok=True)
    study = (
        json.loads((root / "study.json").read_text())
        if (root / "study.json").exists()
        else {"expiry": "2026-10-19", "requested_period": ["2026-09-19", "2026-10-18"]}
    )
    events = [
        e for e in json.loads((root / "events.json").read_text()) if event_in_window(e, study)
    ]
    data = {}
    paths = [root / "events.json", root / "contracts-current.json"]
    for symbol in {e["contract"]["symbol"] for e in events}:
        path = root / (symbol + "-fresh.json")
        if not path.exists():
            path = root / (symbol + "-cached.json")
        data[symbol] = json.loads(path.read_text())
        paths.append(path)
    modes = {
        "fixed": False,
        "early": True,
        "delayed": {"activation_r": 2, "gap_r": 1.5, "minimum_lock_r": 1},
    }
    modes = {name: modes[name] for name in study.get("modes", modes)}
    if args.max_loss is not None:
        modes.pop("early", None)
    report = {
        "starting_capital": args.capital,
        "max_planned_loss_per_trade": args.max_loss,
        "expiry": study["expiry"],
        "requested_period": study["requested_period"],
        "cases": [],
        "source_hashes": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                Path("scripts/research/video_reversal/expiry_rupees.py"),
                Path("services/kotak_assistant/analysis.py"),
            ]
        },
        "input_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "assumptions": [
            "Cash-funded NIFTY19Oct2026-expiry CE/PE purchases. Starting cash30000INR; maximum whole lots from adverse premium entry plus estimated entry charges.65units/lot, no leverage or extra deposits. Realised net profits/losses roll into the next trade. Not a live capital/risk-setting change.",
            "Every policy starts independently at30000. Same causal signal source and premiumATR template as the one-lot study. Max2entries/day and one position at a time. Policies may take different later entries because holding periods differ.",
            "Fixed: originalSL remains. Early: activate at1R completed-close net peak, protect peak minus1R (at least net0). Delayed: activate at2R, protect max(1R,peak minus1.5R). Ratchet only; updates effective next minute. Targets2R/5R/10R remain fixed, not a minimum realised profit guarantee.",
            "Entry next minute open plus0.10slippage; initialSL1.5x completed option WilderATR14. Costs enter both net-R target and stop calculations.0brokerage and dated NFO estimated taxes/charges. Stop-first on ambiguous minute, adverse gap fills, target must trade through. Minute replay cannot establish second-by-second trailing.",
            "Missing/invalid/zero-volume price while open makes ending equity unavailable and terminates that scenario. Never recycle unknown proceeds to fund subsequent trades. Closed-subset P&L is shown separately and is not a full result.",
            "Coverage-limited requested19Sept–18Oct. Supported trades begin5Oct and history ends16Oct; not complete one-month or19Oct expiry-day performance. Older65-unit lot metadata is assumed unchanged;14Oct archive supports that day only.",
            "OHLC conditional fills do not verify maker queue, spread or available depth. Sizing to all affordable cash may not be executable at the assumed price; entry-minute total volume is only a diagnostic, not a fill guarantee. No quantity-driven impact model beyond0.10slippage.",
            "Drawdown below is closed-trade equity drawdown; it excludes unrealised intratrade drawdown. Planned SL loss can be exceeded by gaps. Each scenario is in-sample; no independent validation or proven best-strategy claim.",
        ],
    }
    if (root / "study.json").exists():
        report["input_hashes"]["study.json"] = hashlib.sha256(
            (root / "study.json").read_bytes()
        ).hexdigest()
        report["assumptions"][0] = (
            f"Cash-funded NIFTY {study['expiry']} expiry purchases. Each case starts independently at {args.capital:g} INR; maximum whole lots after estimated entry charges; no leverage. Realised cash rolls after resolved exits."
        )
        report["assumptions"][5] = study["coverage_note"]
        report["assumptions"].append(
            study.get(
                "metadata_note",
                "Other-expiry stress test with unchanged signals and SL rules. Contracts share underlying dates; this is not an independent chronological holdout. Archived13Oct contracts are restricted to their documented validity window; current27Oct/03Nov metadata applied historically remains an assumption.",
            )
        )
    if args.max_loss is not None:
        report["assumptions"].append(
            f"Maximum planned loss per trade {args.max_loss:g}INR including estimated roundtrip charges and0.10exit slippage. Reduce lots without changing the ATR stop. Skip if one lot cannot fit. Not a daily cap or guaranteed realised maximum: gaps/extra slippage can exceed it. Cash and risk constraints both apply; all earlier reports preserved."
        )
    for order in ["low-first", "high-first"]:
        for mode, trail in modes.items():
            for reward in [2, 5, 10]:
                cash = args.capital
                peak = cash
                dd = 0
                busy = 0
                counts = Counter()
                skips = Counter()
                trades = []
                complete = True
                for e in sorted(
                    (x for x in events if x["path"] == order), key=lambda x: x["observed"]
                ):
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
                    rows = data[c["symbol"]]
                    b = next((x for x in rows if int(x["timestamp"]) == start), None)
                    if b is None or not valid(b):
                        skips["entry_premium_unavailable"] += 1
                        continue
                    atr = atr_before(rows, start)
                    if atr is None:
                        skips["option_atr_warmup_unavailable"] += 1
                        continue

                    def charge(buy, sell, fee_day=day):
                        return fees(buy, sell, "NFO", 0, fee_day)["total"]

                    entry = snap(b["open"] + 0.1, c["tick_size"], True)
                    cash_lots = affordable_lots(
                        cash, entry, c["lotsize"], lambda turnover: charge(turnover, 0)
                    )
                    lots, plan = risk_limited_plan(
                        cash,
                        b["open"],
                        atr,
                        c["lotsize"],
                        c["tick_size"],
                        reward,
                        charge,
                        args.max_loss,
                    )
                    if not lots:
                        skips[
                            "risk_budget_or_invalid_plan"
                            if cash_lots
                            else "insufficient_cash_one_lot"
                        ] += 1
                        continue
                    qty = lots * c["lotsize"]
                    premium = plan["entry"] * qty
                    entry_cost = charge(premium, 0)
                    assert premium + entry_cost <= cash + 1e-8
                    if args.max_loss is None:
                        assert (lots + 1) * c["lotsize"] * entry + charge(
                            (lots + 1) * c["lotsize"] * entry, 0
                        ) > cash - 1e-8
                    else:
                        assert plan["risk_rupees"] <= args.max_loss + 1e-8
                        if lots < cash_lots:
                            next_plan = premium_plan(
                                b["open"],
                                atr,
                                (lots + 1) * c["lotsize"],
                                c["tick_size"],
                                reward,
                                charge,
                            )
                            assert next_plan["risk_rupees"] > args.max_loss
                    t = replay(
                        rows, start, cutoff, plan, qty, charge, c["tick_size"], trailing=trail
                    )
                    before = cash
                    if t["net"] is not None:
                        cash += t["net"]
                        peak = max(peak, cash)
                        dd = max(dd, peak - cash)
                    else:
                        complete = False
                    trades.append(
                        dict(
                            session=day,
                            symbol=c["symbol"],
                            expiry=study["expiry"],
                            opened=start,
                            lots=lots,
                            quantity=qty,
                            cash_before=before,
                            premium_paid=premium,
                            entry_charges=entry_cost,
                            cash_unspent=before - premium - entry_cost,
                            planned_risk_pct=100 * plan["risk_rupees"] / before,
                            entry_bar_volume=b["volume"],
                            quantity_exceeds_entry_bar_volume=qty > b["volume"],
                            cash_after=cash if complete else None,
                            **plan,
                            **t,
                        )
                    )
                    counts[day] += 1
                    busy = t["exit_time"]
                    if not complete:
                        break
                if not trades:
                    complete = False
                closed = [t for t in trades if t["net"] is not None]
                case = {
                    "path": order,
                    "mode": mode,
                    "reward": reward,
                    "entries": len(trades),
                    "resolved": len(closed),
                    "unresolved": len(trades) - len(closed),
                    "wins": sum(t["net"] > 0 for t in closed),
                    "gross": sum(t["gross"] for t in closed),
                    "fees": sum(t["fees"] for t in closed),
                    "net": cash - args.capital if complete else None,
                    "ending_cash": cash if complete else None,
                    "closed_subset_net": sum(t["net"] for t in closed),
                    "closed_drawdown": dd,
                    "drawdown_complete": complete,
                    "min_lots": min((t["lots"] for t in trades), default=0),
                    "max_lots": max((t["lots"] for t in trades), default=0),
                    "max_planned_loss": max((t["risk_rupees"] for t in trades), default=0),
                    "max_realised_loss": max((max(0, -t["net"]) for t in closed), default=0),
                    "realised_losses_over_budget": sum(
                        t["net"] < -args.max_loss - 1e-8 for t in closed
                    )
                    if args.max_loss is not None
                    else None,
                    "max_planned_risk_pct": max((t["planned_risk_pct"] for t in trades), default=0),
                    "skips": dict(skips),
                    "trades": trades,
                }
                report["cases"].append(case)
                with (out / f"{order}-{mode}-{reward}R.csv").open("w") as f:
                    if trades:
                        writer = csv.DictWriter(
                            f, fieldnames=sorted(set().union(*(t.keys() for t in trades)))
                        )
                        writer.writeheader()
                        writer.writerows(trades)
                print({k: v for k, v in case.items() if k not in ["trades", "skips"]}, flush=True)
    (out / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))

    def money(x):
        return "Unavailable" if x is None else f"₹{x:,.2f}"

    rows = "".join(
        "<tr>"
        + "".join(
            "<td>" + html.escape(str(v)) + "</td>"
            for v in [
                c["path"],
                c["mode"],
                f"1:{c['reward']}",
                c["entries"],
                c["unresolved"],
                f"{c['min_lots']}–{c['max_lots']}",
                money(c["gross"]),
                money(c["fees"]),
                money(c["net"]),
                money(c["ending_cash"]),
                money(c["closed_drawdown"]) + (" (partial)" if not c["drawdown_complete"] else ""),
                f"{c['max_planned_risk_pct']:.1f}%",
                money(c["max_planned_loss"]),
                money(c["max_realised_loss"]),
            ]
        )
        + "</tr>"
        for c in report["cases"]
        if c["mode"] != "early"
    )
    display_note = "Display filtered at your request: the losing early-trailing mode is hidden. Full results retain every tested mode; removing rows does not improve or independently validate the retained strategies."
    if (root / "study.json").exists():
        display_note = "This stress test runs the retained fixed and delayed SL modes only, following the prior study selection. All their outcomes, including losses and incomplete cases, remain visible."
    risk_note = (
        f" Planned per-trade loss capped at ₹{args.max_loss:,.0f}, including estimated costs. Lot size reduced; original ATR stop retained. Gaps can exceed this budget."
        if args.max_loss is not None
        else ""
    )
    limits = "".join("<li>" + html.escape(x) + "</li>" for x in report["assumptions"])
    (out / "report.html").write_text(
        f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>₹30000 maximum-lot study</title><style>body{{font:15px/1.6 system-ui;margin:30px;color:#172437}}table{{border-collapse:collapse;font-size:13px}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:right}}.notice{{padding:18px;background:#fff1ce}}.scroll{{overflow:auto}}</style><h1>NIFTY {html.escape(report["expiry"])} expiry ·₹{args.capital:,.0f} · Maximum affordable lots</h1><p class="notice">Conditional historical premium replay.0brokerage; estimated charges included. Capital rolls after each closed trade. Maximum lots within cash and configured risk limits, with no leverage.{risk_note} Not a complete month or verified maker execution.</p><p>{display_note}</p><div class="scroll"><table><tr><th>Signal path</th><th>SL mode</th><th>Target</th><th>Entries</th><th>Unknown</th><th>Lots/trade</th><th>Gross</th><th>Charges</th><th>Net</th><th>Ending capital</th><th>Closed drawdown</th><th>Max planned SL risk</th><th>Max planned loss</th><th>Max realised loss</th></tr>{rows}</table></div><h2>Method and limits</h2><ul>{limits}</ul><p><a href="results.json">Full metrics and per-trade prices, lots and capital</a></p></html>'
    )


if __name__ == "__main__":
    main()
