"""Read-only OHLC sensitivity study; synthetic paths are not recorded ticks."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from strategies.liquidity.setup import VERSION, Config, advance, plan_order

IST = timezone(timedelta(hours=5, minutes=30))


def pivot_references(rows, seconds, frame, minutes):
    result = []
    for i in range(2, len(rows) - 2):
        w = rows[i - 2 : i + 3]
        if any(b["time"] != a["time"] + seconds for a, b in zip(w, w[1:], strict=False)):
            continue
        b = rows[i]
        known = rows[i + 2]["time"] + seconds
        for side, field in [("Low", "low"), ("High", "high")]:
            if not all(
                (b[field] < x[field] if side == "Low" else b[field] > x[field])
                for x in w
                if x is not b
            ):
                continue
            # Minute history refines coarse touches only where available.
            touches = [
                x["time"]
                for x in rows[i + 3 :]
                if x["time"] >= known
                and (x[field] <= b[field] if side == "Low" else x[field] >= b[field])
            ]
            retired = min(touches) if touches else None
            small = [
                x["time"]
                for x in minutes
                if x["time"] >= known
                and (x[field] <= b[field] if side == "Low" else x[field] >= b[field])
            ]
            if small and (retired is None or minutes[0]["time"] <= retired):
                retired = min(small)
            result.append(
                {
                    "id": f"{frame}:{side}:{b['time']}",
                    "side": side,
                    "price": b[field],
                    "known": known,
                    "frame": frame,
                    "retired_at": retired,
                    "pivot_at": b["time"],
                }
            )
    return result


def reference_snapshot(refs, now):
    out = []
    for frame in ["1H", "4H", "1D"]:
        for side in ["Low", "High"]:
            eligible = [
                r
                for r in refs
                if r["frame"] == frame
                and r["side"] == side
                and r["known"] <= now
                and (r["retired_at"] is None or r["retired_at"] >= now - 120 * 60)
            ]
            if eligible:
                r = dict(max(eligible, key=lambda r: r["pivot_at"]))
                if r["retired_at"] is not None and r["retired_at"] + 60 > now:
                    r["retired_at"] = None
                out.append(r)
    return out


def maker_fill(p, price, now):
    return p["submitted"] < now < p["submitted"] + 15 and (
        price < p["entry"] if p["side"] == "buy" else price > p["entry"]
    )


def net_pnl(side, entry, close, qty, product, reserve):
    units = float(product["contract_value"]) * qty
    gross = (close - entry) * units * (1 if side == "buy" else -1)
    fees = (
        (
            entry * float(product["maker_commission_rate"])
            + close * float(product["taker_commission_rate"])
        )
        * units
        * 1.18
    )
    return gross - fees - reserve


def exit_price(side, observed, stop):
    return min(observed, stop) if side == "buy" else max(observed, stop)


def path_prices(b, order):
    vertices = (
        [b["open"], b["low"], b["high"], b["close"]]
        if order == "low-first"
        else [b["open"], b["high"], b["low"], b["close"]]
    )
    for sec in range(60):
        leg = min(sec // 20, 2)
        fraction = (sec - leg * 20) / 19 if leg == 2 else (sec - leg * 20) / 20
        yield b["time"] + sec, vertices[leg] + (vertices[leg + 1] - vertices[leg]) * fraction


def simulate(minutes, refs, product, cfg, start, end, order, planner=None):
    make_plan = planner or plan_order
    tick = float(product["tick_size"])
    state = {}
    pending = position = None
    trades = []
    examples = {}
    stats = Counter()
    stages = Counter()
    reasons = {}
    seen = set()
    submitted = set()
    daily = {}
    halted = False
    recent = []
    previous_time = None

    def selected(now):
        return reference_snapshot(refs, now)

    def close(observed, now, reason):
        nonlocal position, halted
        p = position
        px = observed
        gross = (
            (px - p["entry"])
            * float(product["contract_value"])
            * p["quantity"]
            * (1 if p["side"] == "buy" else -1)
        )
        net = net_pnl(p["side"], p["entry"], px, p["quantity"], product, cfg.slippage)
        row = {
            "setup_id": p["setup_id"],
            "side": p["side"],
            "entry_time": p["opened"],
            "exit_time": now,
            "entry": p["entry"],
            "exit": px,
            "quantity": p["quantity"],
            "gross": gross,
            "fees": gross - net - cfg.slippage,
            "slippage": cfg.slippage,
            "net": net,
            "reason": reason,
        }
        trades.append(row)
        day = datetime.fromtimestamp(now, IST).date().isoformat()
        d = daily.setdefault(day, {"attempts": 0, "net": 0, "streak": 0})
        d["net"] += net
        d["streak"] = d["streak"] + 1 if net < 0 else 0
        if d["net"] <= -cfg.daily_loss or d["streak"] >= 3:
            halted = True
        position = None

    for b in minutes:
        now = b["time"]
        if now >= end:
            break
        gap = previous_time is not None and now != previous_time + 60
        if gap:
            stats["data_gaps"] += 1
            if position:
                close(
                    exit_price(position["side"], b["open"], position["stop"]),
                    now,
                    "gap_adverse_exit",
                )
            if pending:
                stats["pending_cancelled_gap"] += 1
                pending = None
            state = {}
            recent = []
        previous_time = now
        if len(recent) >= 15:
            # Model assumes an uninterrupted feed within covered minutes. It is
            # explicitly not evidence of historical observations or a reconnect.
            state["observed_at"] = now - 1
            q = {"bid": b["open"] - tick, "ask": b["open"] + tick, "time": now}
            advance(state, recent, selected(now), q, cfg, now)
            c = state.get("candidate")
            if c:
                stages[c["stage"]] += 1
        if now >= start and len(recent) >= 15:
            c = state.get("candidate")
            active = c and c["stage"] in ("WATCHING", "TRIGGERED")
            if active or pending or position:
                current_refs = selected(now)
                for stamp, mid in path_prices(b, order):
                    bid = math.floor((mid - tick) / tick + 1e-8) * tick
                    ask = bid + 2 * tick
                    if position:
                        p = position
                        sign = 1 if p["side"] == "buy" else -1
                        executable = bid if sign > 0 else ask
                        net = net_pnl(
                            p["side"], p["entry"], executable, p["quantity"], product, cfg.slippage
                        )
                        p["peak"] = max(p["peak"], net)
                        if p["peak"] > 2:
                            p["floor"] = max(p["floor"], 1.5, p["peak"] - 0.5)
                        stop_hit = sign * (executable - p["stop"]) <= 0
                        target_hit = sign * (executable - p["target"]) >= 0
                        if (
                            stop_hit
                            or net <= p["floor"]
                            or target_hit
                            or stamp - p["opened"] >= cfg.max_hold_seconds
                        ):
                            reason = (
                                "stop"
                                if stop_hit
                                else "net_floor"
                                if net <= p["floor"]
                                else "target"
                                if target_hit
                                else "deadline"
                            )
                            px = (
                                exit_price(p["side"], executable, p["stop"])
                                if stop_hit
                                else executable
                            )
                            close(px, stamp, reason)
                    if pending:
                        if stamp >= pending["submitted"] + 15:
                            stats["unfilled_entries"] += 1
                            pending = None
                        elif maker_fill(pending, mid, stamp):
                            position = dict(
                                pending, opened=stamp, peak=0, floor=-pending["net_risk"]
                            )
                            pending = None
                            stats["assumed_fills"] += 1
                    if c and c["stage"] in ("WATCHING", "TRIGGERED"):
                        state["observed_at"] = stamp - 1
                        advance(
                            state,
                            recent,
                            current_refs,
                            {"bid": bid, "ask": ask, "time": stamp},
                            cfg,
                            stamp,
                        )
                        if c["stage"] == "TRIGGERED":
                            if c["id"] not in seen:
                                seen.add(c["id"])
                                stats["signals"] += 1
                            if c["id"] in submitted or stamp - c["triggered_at"] > 15:
                                continue
                            day = datetime.fromtimestamp(stamp, IST).date().isoformat()
                            d = daily.setdefault(day, {"attempts": 0, "net": 0, "streak": 0})
                            if position or pending:
                                reasons[c["id"]] = "Existing exposure"
                                continue
                            if halted or d["attempts"] >= cfg.max_trades:
                                reasons[c["id"]] = "Daily halt / trade cap"
                                continue
                            # Funding amount is absent: exclude entries whose
                            # maximum hold could cross a scheduled 4h boundary.
                            interval = int(product["product_specs"]["rate_exchange_interval"])
                            if stamp // interval != (stamp + cfg.max_hold_seconds) // interval:
                                reasons[c["id"]] = (
                                    "Funding window excluded (historical rate unavailable)"
                                )
                                continue
                            plan = make_plan(
                                c,
                                {"bid": bid, "ask": ask, "time": stamp},
                                product,
                                cfg,
                                stamp,
                                1_000_000,
                            )
                            if plan.get("blocked"):
                                reasons[c["id"]] = plan["blocked"]
                                ep = bid if c["direction"] == "LONG" else ask
                                target = c["target"]
                                sign = 1 if c["direction"] == "LONG" else -1
                                gross_target = (
                                    sign
                                    * (target - ep)
                                    * float(product["contract_value"])
                                    * cfg.max_quantity
                                )
                                fees = (
                                    (
                                        ep * float(product["maker_commission_rate"])
                                        + target * float(product["taker_commission_rate"])
                                    )
                                    * float(product["contract_value"])
                                    * cfg.max_quantity
                                    * 1.18
                                )
                                best_entry = (
                                    (math.floor(c["trigger"] / tick + 1e-8) + 1) * tick
                                    if sign > 0
                                    else (math.ceil(c["trigger"] / tick - 1e-8) - 1) * tick
                                )
                                best_net = net_pnl(
                                    "buy" if sign > 0 else "sell",
                                    best_entry,
                                    target,
                                    cfg.max_quantity,
                                    product,
                                    cfg.slippage,
                                )
                                examples[c["id"]] = {
                                    "time": stamp,
                                    "setup_id": c["id"],
                                    "direction": c["direction"],
                                    "entry": ep,
                                    "target": target,
                                    "stop_extreme": c["extreme"],
                                    "trigger": c["trigger"],
                                    "best_eligible_net_at_target": best_net,
                                    "gross_at_target": gross_target,
                                    "estimated_target_fees": fees,
                                    "slippage": cfg.slippage,
                                    "net_at_target": gross_target - fees - cfg.slippage,
                                    "reason": plan["blocked"],
                                }
                                continue
                            submitted.add(c["id"])
                            reasons.pop(c["id"], None)
                            examples.pop(c["id"], None)
                            pending = dict(plan, submitted=stamp)
                            d["attempts"] += 1
                            stats["entry_attempts"] += 1
        recent.append(b)
        recent = recent[-120:]
    if position:
        close(minutes[-1]["close"], min(end - 1, minutes[-1]["time"] + 59), "end_of_sample")
    if pending:
        stats["unfilled_entries"] += 1
    equity = peak = drawdown = 0
    for t in trades:
        equity += t["net"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    wins = sum(t["net"] > 0 for t in trades)
    positive = sum(max(0, t["net"]) for t in trades)
    negative = -sum(min(0, t["net"]) for t in trades)
    return {
        "path": order,
        "blocked_examples": list(examples.values()),
        "stats": dict(stats),
        "stages": dict(stages),
        "blocked": dict(Counter(reasons.values())),
        "trades": trades,
        "trade_count": len(trades),
        "wins": wins,
        "losses": sum(t["net"] < 0 for t in trades),
        "win_rate": 100 * wins / len(trades) if trades else None,
        "gross": sum(t["gross"] for t in trades),
        "fees": sum(t["fees"] for t in trades),
        "slippage": sum(t["slippage"] for t in trades),
        "net": equity,
        "profit_factor": positive / negative if negative else None,
        "expectancy": equity / len(trades) if trades else None,
        "max_drawdown": drawdown,
        "halted": halted,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--settings", type=Path, required=True)
    args = parser.parse_args()
    root = args.directory
    manifest = json.loads((root / "manifest.json").read_text())
    product = json.loads((root / "product.json").read_text())
    settings = json.loads(args.settings.read_text())
    settings.update(leverage=2, max_quantity=1)
    cfg = Config(**settings)
    minutes = json.loads((root / "1m.json").read_text())
    start, end = manifest["start"], manifest["end"]
    if any(
        not all(math.isfinite(float(b[k])) for k in ["time", "open", "high", "low", "close"])
        or b["time"] % 60
        or b["low"] <= 0
        or b["low"] > min(b["open"], b["close"])
        or b["high"] < max(b["open"], b["close"])
        for b in minutes
    ):
        raise ValueError("Invalid OHLC")
    refs = []
    for res, seconds, label in [("1h", 3600, "1H"), ("4h", 14400, "4H"), ("1d", 86400, "1D")]:
        refs += pivot_references(
            json.loads((root / f"{res}.json").read_text()), seconds, label, minutes
        )
    covered = [b for b in minutes if start <= b["time"] < end]
    expected = (end - start) // 60
    if (
        len(covered) != expected
        or not covered
        or covered[0]["time"] != start
        or covered[-1]["time"] != end - 60
        or any(b["time"] != a["time"] + 60 for a, b in zip(covered, covered[1:], strict=False))
    ):
        raise ValueError(
            "Incomplete minute coverage: re-fetch missing source candles before running this full-month study"
        )
    report = {
        "symbol": manifest["symbol"],
        "strategy": VERSION,
        "settings": asdict(cfg),
        "period": {
            "start_ist": manifest["start_ist"],
            "end_exclusive_ist": manifest["end_exclusive_ist"],
        },
        "coverage": {
            "expected_minutes": expected,
            "available_minutes": len(covered),
            "coverage_percent": 100 * len(covered) / expected,
            "gaps": sum(
                b["time"] != a["time"] + 60 for a, b in zip(covered, covered[1:], strict=False)
            ),
            "confirmed_references": len(refs),
        },
        "metadata": {
            "contract_value": product["contract_value"],
            "tick_size": product["tick_size"],
            "maker_rate": product["maker_commission_rate"],
            "taker_rate": product["taker_commission_rate"],
            "margin_at_2x": "entry * contract_value / 2",
            "metadata_is_current_not_historical": True,
        },
        "assumptions": [
            "OHLC-only sensitivity study, not recorded tick/order-book replay",
            "Two-tick synthetic spread; both O-L-H-C and O-H-L-C interpolated paths",
            "Fill assumes full size on a later strict trade-through before 15-second cancellation; queue position unknown",
            "All filled results are conditional; historical maker fills and win rate are not established",
            "Current product fee rates plus 18% GST; configured $0.10 cash slippage per completed trade",
            "Funding-boundary entries excluded; no fee waiver or deposits assumed",
            "Collateral not measured historically: ample research collateral; configured margin/risk/notional caps enforced",
            "Persistent daily loss halt has no automatic resume; no parameter search",
        ],
        "code_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), Path("strategies/liquidity/setup.py")]
        },
        "results": [],
    }
    for order in ["low-first", "high-first"]:
        result = simulate(minutes, refs, product, cfg, start, end, order)
        report["results"].append(result)
        print(order, result["trade_count"], result["net"], result["blocked"], flush=True)
        with (root / f"trades-{order}.csv").open("w") as f:
            rows = result["trades"]
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["setup_id", "net"])
            writer.writeheader()
            writer.writerows(rows)
    (root / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ["results", "code_sha256"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
