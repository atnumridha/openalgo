"""Offline BTCUSD teaching-clip study. Synthetic paths do not establish fills."""

import argparse
import csv
import hashlib
import html
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def candidate(b, side, level, target, previous_extreme, tick):
    short = side == "short"
    if target is None:
        return None
    if short:
        valid = (
            b["close"] < b["open"]
            and b["high"] > level
            and b["high"] > previous_extreme
            and target < b["low"]
        )
    else:
        valid = (
            b["close"] > b["open"]
            and b["low"] < level
            and b["low"] < previous_extreme
            and target > b["high"]
        )
    if not valid:
        return None
    return {
        "id": f"{b['time']}:{side}",
        "side": side,
        "known": b["time"] + 60,
        "expires": b["time"] + 120,
        "trigger": b["low"] if short else b["high"],
        "stop": b["high"] + tick if short else b["low"] - tick,
        "target": target,
        "reference": level,
        "signal": dict(b),
    }


def trigger_hit(c, price, now):
    return c["known"] <= now < c["expires"] and (
        price < c["trigger"] if c["side"] == "short" else price > c["trigger"]
    )


def maker_fill(p, price, now):
    return p["submitted"] < now < p["submitted"] + 15 and (
        price > p["entry"] if p["side"] == "short" else price < p["entry"]
    )


def slice_pnl(side, entry, exit_price, quantity, contract, maker, taker):
    units = quantity * contract
    gross = (exit_price - entry) * units * (-1 if side == "short" else 1)
    fees = (entry * maker + exit_price * taker) * units * 1.18
    return {"gross": gross, "fees": fees, "net": gross - fees}


def signals(minutes, daily, tick):
    by_known = {b["time"] + 86400: b for b in daily}
    out = {}
    swings = {"low": [], "high": []}
    exc = {}
    prior_day = None
    counts = Counter()
    for i, b in enumerate(minutes):
        day = b["time"] // 86400 * 86400
        if day != prior_day:
            exc = {}
            prior_day = day
        gap = i and b["time"] != minutes[i - 1]["time"] + 60
        if gap:
            exc = {}
            swings = {"low": [], "high": []}
        d = by_known.get(day)
        if i and d:
            prev = minutes[i - 1]["close"]
            for side, field, pivot_field in [("short", "high", "low"), ("long", "low", "high")]:
                level = d[field]
                crossing = (
                    prev <= level < b["high"] if side == "short" else prev >= level > b["low"]
                )
                if crossing:
                    eligible = [
                        x
                        for x in swings[pivot_field]
                        if x["known"] <= b["time"]
                        and (x["price"] < level if side == "short" else x["price"] > level)
                    ]
                    target = eligible[-1]["price"] if eligible else None
                    exc[side] = {"level": level, "target": target, "extreme": level}
                    counts["reference_crossings"] += 1
                context = exc.get(side)
                if context:
                    old = context["extreme"]
                    context["extreme"] = (max if side == "short" else min)(old, b[field])
                    c = candidate(b, side, level, context["target"], old, tick)
                    # A target already revisited before candidate completion is
                    # not available as a subsequent first target.
                    if context["target"] is not None and (
                        b["low"] <= context["target"]
                        if side == "short"
                        else b["high"] >= context["target"]
                    ):
                        context["target"] = None
                        c = None
                    if c:
                        out.setdefault(c["known"], []).append(c)
                        counts["candidates"] += 1
        # Pivot at i-2 becomes known only after this right-hand bar closes.
        if i >= 4:
            w = minutes[i - 4 : i + 1]
            pivot = w[2]
            if all(y["time"] == x["time"] + 60 for x, y in zip(w, w[1:], strict=False)):
                for field in ["low", "high"]:
                    if all(
                        (pivot[field] < x[field] if field == "low" else pivot[field] > x[field])
                        for x in w
                        if x is not pivot
                    ):
                        swings[field].append(
                            {"price": pivot[field], "known": b["time"] + 60, "time": pivot["time"]}
                        )
                        swings[field] = swings[field][-3000:]
    return out, dict(counts)


def path(b, order):
    v = (
        [b["open"], b["low"], b["high"], b["close"]]
        if order == "low-first"
        else [b["open"], b["high"], b["low"], b["close"]]
    )
    for sec in range(60):
        j = min(sec // 20, 2)
        f = (sec - j * 20) / (19 if j == 2 else 20)
        yield b["time"] + sec, v[j] + f * (v[j + 1] - v[j])


def simulate(
    minutes, candidates, product, start, end, quantity, order, slippage, cap_scope="fills"
):
    if cap_scope not in ("fills", "attempts"):
        raise ValueError("Unknown daily cap scope")
    tick = float(product["tick_size"])
    contract = float(product["contract_value"])
    maker = float(product["maker_commission_rate"])
    taker = float(product["taker_commission_rate"])
    effective_slip = math.ceil(slippage / tick - 1e-9) * tick
    pending = position = None
    trades = []
    stats = Counter()
    attempts = {}
    filled_by_day = {}
    used = set()
    seen = set()
    slices = []

    def close_slice(qty, price, stamp, reason):
        nonlocal position
        p = position
        units = qty * contract
        sign = -1 if p["side"] == "short" else 1
        p["gross"] += (price - p["entry"]) * units * sign
        p["fees"] += price * units * taker * 1.18
        p["remaining"] -= qty
        slices.append(
            {"setup_id": p["id"], "time": stamp, "quantity": qty, "price": price, "reason": reason}
        )
        if not p["remaining"]:
            p["exit_time"] = stamp
            p["net"] = p["gross"] - p["fees"] - p["funding_reserve"]
            p["exit_reason"] = reason
            trades.append(p)
            position = None

    last = None
    for b in minutes:
        if not start <= b["time"] < end:
            continue
        if last and b["time"] != last["time"] + 60:
            stats["data_gaps"] += 1
            if position:
                px = b["open"] + (
                    effective_slip if position["side"] == "short" else -effective_slip
                )
                close_slice(position["remaining"], px, b["time"], "gap_exit")
            pending = None
        watch = candidates.get(b["time"], [])
        if not (watch or pending or position):
            last = b
            continue
        for stamp, mid in path(b, order):
            bid = math.floor((mid - tick) / tick + 1e-8) * tick
            ask = bid + 2 * tick
            # Adverse reserve, not a claim about historical booked funding.
            if position and stamp % 28800 == 0 and stamp > position["opened"]:
                position["funding_reserve"] += mid * position["remaining"] * contract * 0.0001
            if pending:
                if stamp >= pending["submitted"] + 15:
                    stats["unfilled_entries"] += 1
                    pending = None
                elif maker_fill(pending, mid, stamp):
                    position = dict(
                        pending,
                        opened=stamp,
                        remaining=quantity,
                        gross=0,
                        fees=pending["entry"] * quantity * contract * maker * 1.18,
                        funding_reserve=0,
                        first_target_hit=False,
                        quantity=quantity,
                        initial_cash_risk=abs(pending["entry"] - pending["stop"])
                        * quantity
                        * contract,
                        notional=pending["entry"] * quantity * contract,
                        margin_at_2x=pending["entry"] * quantity * contract / 2,
                    )
                    pending = None
                    filled_by_day[stamp // 86400] = filled_by_day.get(stamp // 86400, 0) + 1
                    stats["assumed_fills"] += 1
            if position:
                p = position
                short = p["side"] == "short"
                executable = ask if short else bid
                stop_hit = executable >= p["stop"] if short else executable <= p["stop"]
                if stop_hit:
                    adverse = (
                        max(executable, p["stop"]) + effective_slip
                        if short
                        else min(executable, p["stop"]) - effective_slip
                    )
                    close_slice(p["remaining"], adverse, stamp, "stop")
                elif not p["first_target_hit"] and (
                    executable <= p["target"] if short else executable >= p["target"]
                ):
                    qty = quantity * 4 // 5
                    p["first_target_hit"] = True
                    stats["first_target_hits"] += 1
                    px = p["target"] + (effective_slip if short else -effective_slip)
                    close_slice(qty, px, stamp, "first_target_80pct")
                if position and stamp % 86400 == 86399:
                    px = executable + (effective_slip if short else -effective_slip)
                    close_slice(position["remaining"], px, stamp, "utc_day_end")
            for c in watch:
                if c["id"] in used or position or pending:
                    continue
                if not trigger_hit(c, mid, stamp):
                    continue
                if c["id"] not in seen:
                    seen.add(c["id"])
                    stats["triggers"] += 1
                entry = ask if c["side"] == "short" else bid
                if (
                    (entry <= c["target"] or entry >= c["stop"])
                    if c["side"] == "short"
                    else (entry >= c["target"] or entry <= c["stop"])
                ):
                    used.add(c["id"])
                    stats["invalid_entry_geometry"] += 1
                    continue
                day = stamp // 86400
                if (attempts if cap_scope == "attempts" else filled_by_day).get(day, 0) >= 2:
                    used.add(c["id"])
                    stats["daily_cap_rejections"] += 1
                    continue
                used.add(c["id"])
                attempts[day] = attempts.get(day, 0) + 1
                stats["entry_attempts"] += 1
                pending = dict(c, entry=entry, submitted=stamp)
        last = b
    if position and last:
        px = last["close"] + (effective_slip if position["side"] == "short" else -effective_slip)
        close_slice(position["remaining"], px, end - 1, "sample_end")
    if pending:
        stats["unfilled_entries"] += 1
    equity = peak = drawdown = 0
    for t in trades:
        equity += t["net"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    wins = sum(t["net"] > 0 for t in trades)
    profit = sum(max(t["net"], 0) for t in trades)
    loss = -sum(min(t["net"], 0) for t in trades)
    return {
        "path": order,
        "daily_cap_scope": cap_scope,
        "adverse_price_slippage": effective_slip,
        "stats": dict(stats),
        "trades": trades,
        "slices": slices,
        "trade_count": len(trades),
        "wins": wins,
        "losses": sum(t["net"] < 0 for t in trades),
        "win_rate": 100 * wins / len(trades) if trades else None,
        "gross": sum(t["gross"] for t in trades),
        "fees": sum(t["fees"] for t in trades),
        "funding_reserve": sum(t["funding_reserve"] for t in trades),
        "net": equity,
        "profit_factor": profit / loss if loss else None,
        "expectancy": equity / len(trades) if trades else None,
        "max_closed_drawdown": drawdown,
        "max_margin_at_2x": max((t["margin_at_2x"] for t in trades), default=0),
        "max_initial_price_risk": max((t["initial_cash_risk"] for t in trades), default=0),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--quantity", type=int, default=5000)
    args = parser.parse_args()
    root = args.directory
    if args.quantity <= 0 or args.quantity % 5:
        raise ValueError("Quantity must be positive and divisible by five for exact 80/20 exits")
    manifest = json.loads((root / "manifest.json").read_text())
    product = json.loads((root / "product.json").read_text())
    minutes = json.loads((root / "1m.json").read_text())
    daily = json.loads((root / "1d.json").read_text())
    start, end = manifest["start"], manifest["end"]
    if product["symbol"] != "BTCUSD" or product["contract_type"] != "perpetual_futures":
        raise ValueError("BTCUSD futures required")
    for name, digest in manifest["files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Input hash mismatch")
    covered = [b for b in minutes if start <= b["time"] < end]
    if (
        len(covered) != (end - start) // 60
        or covered[0]["time"] != start
        or covered[-1]["time"] != end - 60
        or any(y["time"] != x["time"] + 60 for x, y in zip(covered, covered[1:], strict=False))
    ):
        raise ValueError("Full continuous month required; refetch missing candles")
    if any(
        b["time"] % 60
        or b["low"] <= 0
        or b["high"] < max(b["open"], b["close"])
        or b["low"] > min(b["open"], b["close"])
        for b in minutes
    ):
        raise ValueError("Invalid OHLC")
    candidates, signal_stats = signals(minutes, daily, float(product["tick_size"]))
    signal_stats["candidates_in_test_period"] = sum(
        len(v) for k, v in candidates.items() if start <= k < end
    )
    report = {
        "strategy": "daily-line-fresh-candle-reversal-research-v1",
        "symbol": "BTCUSD",
        "quantity": args.quantity,
        "contract_value": product["contract_value"],
        "underlying_btc": args.quantity * float(product["contract_value"]),
        "leverage_for_margin": 2,
        "start_ist": manifest["start_ist"],
        "end_exclusive_ist": manifest["end_exclusive_ist"],
        "coverage_minutes": len(covered),
        "signal_stats": signal_stats,
        "source_clip_review": {
            "duration_seconds": 107.021,
            "visual_samples_seconds": list(range(0, 107, 10)),
            "findings": "Daily wick reference; completed red then next-candle low break; stop over its high; earlier swing low T1; keep 20%. Illustrative drawing, not observed fills.",
        },
        "assumptions": [
            "Daily reference = previous completed native UTC daily wick high/low. Clip starts after reference selection, so this is an app definition.",
            "Fresh = new excursion high/low after crossing the daily reference; completed opposite-colour candle may close on either side of the reference; a reclaim close is not required.",
            "T1 = latest strict 2+2 confirmed minute swing on the originating side, frozen when the daily reference crosses. This is a historical swing and may have been revisited; it is not guaranteed untouched liquidity.",
            "Next-candle-only strict intrabar trigger, original stop one tick beyond signal wick. Bullish rules mirror the illustrated short.",
            "Main case: two filled trades per UTC day; alternative case: two order submissions. Single position, no forced downsizing or account sizing limits in strategy-only research.",
            "80% exits at T1 as taker; final20% retains original stop until UTC day-end. Runner exit is an app assumption, not supplied by clip.",
            "O-L-H-C and O-H-L-C synthetic one-second paths with two-tick spread. Maker full fill assumes later strict trade-through within15seconds; actual queues/depth unknown.",
            "Current product maker/taker fees plus18%GST; adverse taker price slippage rounded to product tick. Funding reserve0.01% of remaining notional at each8hUTC boundary; not actual booked funding.",
            "5000-contract fills are conditional; historical depth/impact is unavailable. No account capital or return percentage invented. Existing live account limits and configuration are unchanged.",
        ],
        "rates": {
            "maker": product["maker_commission_rate"],
            "taker": product["taker_commission_rate"],
            "tick": product["tick_size"],
        },
        "source_hashes": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__)]
        },
        "results": [],
    }
    for cap_scope in ["fills", "attempts"]:
        for order in ["low-first", "high-first"]:
            for slip in [0.1, 1.0]:
                r = simulate(
                    minutes,
                    candidates,
                    product,
                    start,
                    end,
                    args.quantity,
                    order,
                    slip,
                    cap_scope=cap_scope,
                )
                report["results"].append(r)
                print(cap_scope, order, slip, r["trade_count"], r["win_rate"], r["net"], flush=True)
                rows = r["trades"]
                name = f"trades-{cap_scope}-{order}-slip{r['adverse_price_slippage']:g}.csv"
                with (root / name).open("w") as f:
                    fields = [k for k in rows[0] if k != "signal"] if rows else ["id", "net"]
                    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
    (root / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    (root / "candidates.json").write_text(json.dumps(candidates, indent=2))

    def cash(v):
        return f"${v:,.2f}"

    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(x))}</td>"
            for x in [
                r["daily_cap_scope"],
                r["path"],
                cash(r["adverse_price_slippage"]),
                r["trade_count"],
                f"{r['win_rate']:.1f}%" if r["win_rate"] is not None else "N/A",
                cash(r["gross"]),
                cash(r["fees"]),
                cash(r["funding_reserve"]),
                cash(r["net"]),
                f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None else "N/A",
                cash(r["max_closed_drawdown"]),
            ]
        )
        + "</tr>"
        for r in report["results"]
    )
    assumptions = "".join("<li>" + html.escape(x) + "</li>" for x in report["assumptions"])
    (root / "report.html").write_text(
        f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BTCUSD · video reversal backtest</title><style>body{{font:16px/1.6 system-ui;color:#172437;background:#f3f5f7;margin:0}}main{{max-width:1250px;margin:30px auto;background:white;padding:32px;border:1px solid #d6dde2;border-radius:10px}}h1{{font-size:28px}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{padding:10px;text-align:right;border-bottom:1px solid #dce3e8}}td:first-child,th:first-child{{text-align:left}}.notice{{padding:18px;background:#fff4d7;border-left:4px solid #aa6500}}.scroll{{overflow:auto}}a{{color:#1244a0}}</style><main><p>OFFLINE STRATEGY RESEARCH · CONDITIONAL MAKER FILLS</p><h1>BTCUSD · Daily liquidity-sweep reversal</h1><p>18 September–17 October2026 inclusive · IST · {args.quantity:,} contracts = {report["underlying_btc"]:g} BTC · 2× margin estimate · 43,200 minute candles</p><div class="notice">These results test explicit mechanical assumptions from the supplied teaching clip. They do not establish the presenter's win rate or executable maker fills at this size. Both paths reuse the same data; eight rows are sensitivity cases, not four independent samples.</div><h2>Rules tested</h2><p>Sweep previous daily high → completed red candle at fresh excursion high → next candle breaks its low → post-only short. Stop one tick above signal high. Take80% at the earlier confirmed swing low; hold20% to its original stop or UTC day-end. Sweep the previous daily low and mirror for longs. Main case: at most two filled trades per UTC day; order-attempt cap shown separately.</p><h2>Results in USD</h2><div class="scroll"><table><tr><th>Daily cap</th><th>Assumed path</th><th>Price slip</th><th>Trades</th><th>Net wins</th><th>Gross</th><th>Fees+GST</th><th>Funding reserve</th><th>Net</th><th>Profit factor</th><th>Closed drawdown</th></tr>{rows}</table></div><p>Gross already includes adverse exit-price slippage. Net subtracts ordinary fees and the conservative funding reserve. Expectancy, fills, stops, T1 hits, maximum margin and every simulated trade are recorded in the full JSON and CSVs. Closed-equity drawdown excludes intratrade unrealized excursions.</p><h2>Capital and live eligibility</h2><p>Maximum initial margin across cases at2×: {cash(max(r["max_margin_at_2x"] for r in report["results"]))}. Maximum original price-stop risk: {cash(max(r["max_initial_price_risk"] for r in report["results"]))} before fees and gaps. Existing $25margin/$1,000notional controls would reject5000 contracts; they were left unchanged. Strategy research is calculated separately so those controls do not erase its historical sample. No live orders or strategy starts occurred.</p><h2>Source observations and assumptions</h2><p>Reviewed11visual samples across the107-second clip and matched them to the supplied Hindi narration. The visible material is an explanatory drawing on gold, not a BTC trade record. The previous-day selection, fresh-extreme definition, precise swing pivot and runner exit were not fully specified by the clip.</p><ul>{assumptions}</ul><p><a href="results.json">Full metrics and assumptions</a> · <a href="candidates.json">Causal signal candidates</a> · <a href="manifest.json">Data provenance</a></p></main></html>"""
    )


if __name__ == "__main__":
    main()
