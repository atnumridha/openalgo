"""Deterministic eight-tool confluence. Agreement is not a win probability."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import pandas as pd

from services.crypto_fees import ContractFees, net_target_plan
from services.risk import evaluate_position_state

from .indicators import indicators, option_analysis, pivots, volume_profile


@dataclass(frozen=True)
class Config:
    leverage: int = 25
    min_agreement: int = 6
    adx_min: float = 20
    max_risk: float = 1
    max_margin: float = 5
    max_notional: float = 1000
    slippage: float = 0.10
    gst_pct: float = 18
    net_rr: float = 3
    min_net_profit: float = 1
    max_hold_seconds: int = 29 * 60

    def __post_init__(self):
        if not all(math.isfinite(v) for v in self.__dict__.values()):
            raise ValueError("Configuration must be finite")
        if not isinstance(self.leverage, int) or not 1 <= self.leverage <= 200:
            raise ValueError("Leverage must be 1–200")
        if not 1 <= self.min_agreement <= 8 or not 0 < self.adx_min <= 100:
            raise ValueError("Invalid signal configuration")
        if not (
            0 < self.max_risk <= 1 and 0 < self.max_margin <= 5 and 0 < self.max_notional <= 1000
        ):
            raise ValueError("Risk caps cannot exceed $1 loss / $5 margin / $1,000 notional")
        if (
            self.slippage < 0.1
            or self.gst_pct != 18
            or self.net_rr < 3
            or self.min_net_profit < 1
            or not 0 < self.max_hold_seconds <= 1740
        ):
            raise ValueError("Fees, reserve, reward or holding limits cannot be weakened")


def candle_frame(rows, now):
    b = pd.DataFrame(rows)
    keys = ["time", "open", "high", "low", "close", "volume"]
    if not all(k in b for k in keys):
        raise ValueError("Candle data unavailable")
    b = b[keys].apply(pd.to_numeric, errors="raise")
    b = b[b.time + 60 <= now].sort_values("time").reset_index(drop=True)
    if b.empty or not all(math.isfinite(float(v)) for v in b.to_numpy().ravel()):
        raise ValueError("Invalid candles")
    if (
        (b.low <= 0)
        | (b.high < b[["open", "close", "low"]].max(axis=1))
        | (b.low > b[["open", "close"]].min(axis=1))
        | (b.volume < 0)
    ).any():
        raise ValueError("Invalid candle prices or volume")
    if (b.time % 60 != 0).any() or (b.time.diff().dropna() != 60).any():
        raise ValueError("Missing or duplicate one-minute candles")
    return b


def decide(snapshot, cfg: Config, now):
    out = {
        "strategy": "eight-tool-confluence-v1",
        "symbol": "BTCUSD",
        "asof": now,
        "action": "HOLD",
        "reason": "Waiting for valid data",
        "votes": {},
        "plans": [],
        "score_kind": "indicator_agreement_not_probability",
    }
    try:
        b = candle_frame(snapshot["bars"], now).tail(300)
        if not 0 <= now - (float(b.time.iloc[-1]) + 60) <= 75:
            raise ValueError("Completed candle is stale")
        prior = candle_frame(snapshot["previous_session"], now)
        boundary = math.floor((now + 19800) / 86400) * 86400 - 19800
        if (
            len(prior) != 1440
            or prior.time.iloc[0] != boundary - 86400
            or prior.time.iloc[-1] != boundary - 60
        ):
            raise ValueError("Full previous Asia/Kolkata session is required")
        v = indicators(b)
        p = pivots(prior.high.max(), prior.low.min(), prior.close.iloc[-1])
        va = volume_profile(prior)
        out.update(
            indicators=v,
            cpr={k: p[k] for k in ("pivot", "bc", "tc")},
            camarilla={k: p[k] for k in p if k.startswith(("r", "s"))},
            value_area=va,
            candle_closed=float(b.time.iloc[-1]) + 60,
        )
        bid = float(snapshot["bid"])
        ask = float(snapshot["ask"])
        if (
            not math.isfinite(bid + ask)
            or not 0 < bid < ask
            or not 0 <= now - float(snapshot["quote_time"]) <= 10
        ):
            raise ValueError("Fresh executable bid/ask required")
        if ask - bid > max(v["atr"] * 0.25, 1):
            raise ValueError("Spread exceeds the volatility allowance")
        o = option_analysis(snapshot["options"], (bid + ask) / 2, now)
        out["option_chain"] = o
        c = v["close"]

        def direction(above, below):
            return 1 if above else -1 if below else 0

        votes = {
            "value_area": direction(c > va["vah"], c < va["val"]),
            "cpr": direction(c > p["tc"], c < p["bc"]),
            "camarilla": direction(c > p["r3"], c < p["s3"]),
            "adx": direction(
                v["adx"] >= cfg.adx_min and v["plus_di"] > v["minus_di"],
                v["adx"] >= cfg.adx_min and v["minus_di"] > v["plus_di"],
            ),
            "rsi": direction(55 <= v["rsi"] <= 70, 30 <= v["rsi"] <= 45),
            "macd": direction(
                v["macd_hist"] > 0 and v["macd_hist"] >= v["macd_hist_previous"],
                v["macd_hist"] < 0 and v["macd_hist"] <= v["macd_hist_previous"],
            ),
            "vwma": direction(
                c > v["vwma"] and v["vwma_slope"] > 0, c < v["vwma"] and v["vwma_slope"] < 0
            ),
            "option_chain": o["vote"],
        }
        out["votes"] = votes
        out["agreement"] = {
            name: sum(vote == side for vote in votes.values())
            for name, side in [("LONG", 1), ("SHORT", -1)]
        }
        product = snapshot["product"]
        if (
            product["symbol"] != "BTCUSD"
            or product["contract_type"] != "perpetual_futures"
            or product["state"] != "live"
            or product["trading_status"] != "operational"
        ):
            raise ValueError("BTCUSD product is not operational")
        cv, tick, maker, taker, mm, im = [
            float(product[k])
            for k in (
                "contract_value",
                "tick_size",
                "maker_commission_rate",
                "taker_commission_rate",
                "maintenance_margin",
                "initial_margin",
            )
        ]
        if (
            not all(math.isfinite(x) for x in (cv, tick, maker, taker, mm, im))
            or min(cv, tick, im) <= 0
            or mm < 0
            or min(maker, taker) < 0
        ):
            raise ValueError("Product specifications unavailable")
        if cfg.leverage > 100 / im:
            raise ValueError("Leverage exceeds the product maximum")
        contract = ContractFees("BTCUSD", maker_rate=maker, taker_rate=taker)
        daily_budget = min(cfg.max_risk, float(snapshot.get("daily_budget", cfg.max_risk)))
        collateral = float(snapshot.get("available_collateral", cfg.max_margin))
        if not math.isfinite(collateral + daily_budget) or min(collateral, daily_budget) <= 0:
            raise ValueError("No remaining paper risk budget")
        cash_notional = collateral / (1 / cfg.leverage + maker * (1 + cfg.gst_pct / 100))
        qmax = min(
            10000,
            int(min(cfg.max_notional, cfg.max_margin * cfg.leverage, cash_notional) / (ask * cv)),
        )
        for side in (1, -1):
            name = "LONG" if side == 1 else "SHORT"
            entry = (math.floor(bid / tick) if side == 1 else math.ceil(ask / tick)) * tick
            buffer = max(2 * tick, 0.25 * v["atr"])
            raw = (
                float(b.low.tail(5).min()) - buffer
                if side == 1
                else float(b.high.tail(5).max()) + buffer
            )
            stop = (math.floor(raw / tick) if side == 1 else math.ceil(raw / tick)) * tick
            result = {
                "side": name,
                "fits_risk": False,
                "reason": "No whole-contract quantity fits the limits",
            }
            penalty = float(product.get("product_specs", {}).get("isolated_liq_penalty_factor", 0))
            if not math.isfinite(penalty) or penalty < 0:
                raise ValueError("Invalid liquidation buffer")
            liq_distance = entry * (
                1 / cfg.leverage - mm / 100 - maker * (1 + cfg.gst_pct / 100) - penalty
            )
            if liq_distance <= 0 or abs(entry - stop) > 0.5 * liq_distance:
                result["reason"] = "Stop lacks conservative liquidation room"
            else:
                for qty in range(qmax, 0, -1):
                    reserve = cfg.slippage
                    depth = snapshot.get("bids" if side == 1 else "asks")
                    if depth is not None:
                        remaining = qty
                        cost = 0.0
                        for price, size in depth:
                            taken = min(remaining, float(size))
                            remaining -= taken
                            cost += taken * float(price)
                            if remaining <= 0:
                                break
                        if remaining > 0:
                            continue
                        impact = max(0, side * ((bid if side == 1 else ask) * qty - cost)) * cv
                        reserve = max(reserve, impact)
                    try:
                        plan = net_target_plan(
                            side=side,
                            entry=entry,
                            stop=stop,
                            quantity=qty,
                            contract_value=cv,
                            tick=tick,
                            contract=contract,
                            net_rr=cfg.net_rr,
                            minimum_profit=cfg.min_net_profit,
                            slippage=reserve,
                            gst_pct=cfg.gst_pct,
                        )
                    except ValueError:
                        continue
                    notional = entry * qty * cv
                    margin = notional / cfg.leverage
                    if (
                        plan["net_risk"] <= daily_budget
                        and margin <= min(cfg.max_margin, collateral)
                        and notional <= cfg.max_notional
                    ):
                        result.update(
                            plan,
                            quantity=qty,
                            contract_value=cv,
                            tick=tick,
                            maker_rate=maker,
                            taker_rate=taker,
                            notional=notional,
                            margin=margin,
                            fits_risk=True,
                            reason="Within planned limits",
                            liquidation_distance_estimate=liq_distance,
                        )
                        break
            out["plans"].append(result)
        funding = float(snapshot["next_funding"])
        if not math.isfinite(funding) or funding <= now + cfg.max_hold_seconds + 60:
            raise ValueError("Holding window overlaps funding, or funding time is missing")
        if v["adx"] < cfg.adx_min:
            raise ValueError("ADX indicates insufficient trend strength")
        if abs((bid + ask) / 2 - c) > 0.5 * v["atr"]:
            raise ValueError("Price moved beyond the completed-candle context")
        if abs(c - v["vwma"]) > 2 * v["atr"]:
            raise ValueError("Price is extended beyond VWMA")
        for side, name in [(1, "LONG"), (-1, "SHORT")]:
            plan = next(p for p in out["plans"] if p["side"] == name)
            if (
                out["agreement"][name] >= cfg.min_agreement
                and votes["adx"] == side
                and votes["vwma"] == side
                and plan["fits_risk"]
            ):
                out.update(
                    action=name,
                    reason=f"{out['agreement'][name]}/8 indicators agree; planned fees and risk fit",
                    selected_plan=plan,
                )
                break
        else:
            out["reason"] = "Insufficient directional agreement or no trade fits the risk limits"
    except (KeyError, ValueError, TypeError, OverflowError, ZeroDivisionError) as exc:
        out["action"] = "HOLD"
        out["reason"] = str(exc)
        out.pop("selected_plan", None)
    return out


def profit_floor(peak):
    if peak < 0.5:
        return None
    if peak < 1.5:
        return -0.1
    return peak * (0.6 if peak < 3 else 0.7 if peak < 5 else 0.8)


def manage_position(pos, executable, now, cfg: Config):
    """Net-cost trailing; shared risk core enforces the protective stop."""
    side = pos["side"]
    units = pos["quantity"] * pos["contract_value"]
    exit_fee = executable * units * pos["taker_rate"] * (1 + cfg.gst_pct / 100)
    reserve = pos.get("slippage_reserve", cfg.slippage)
    net = side * (executable - pos["entry"]) * units - pos["entry_fee"] - exit_fee - reserve
    peak = max(pos.get("peak_net", 0), net)
    floor = profit_floor(peak)
    stop = pos["stop"]
    if floor is not None:
        # Solve for net at the stop including the fee charged at THAT price.
        d = Decimal
        u = d(str(units))
        entry = d(str(pos["entry"]))
        cost = d(str(pos["entry_fee"])) + d(str(reserve)) + d(str(floor))
        fee = d(str(pos["taker_rate"])) * (1 + d(str(cfg.gst_pct)) / 100)
        tick = d(str(pos["tick"]))
        raw = (
            (entry * u + cost) / (u * (1 - fee))
            if side == 1
            else (entry * u - cost) / (u * (1 + fee))
        )
        candidate = float(
            (raw / tick).to_integral_value(rounding=ROUND_CEILING if side == 1 else ROUND_FLOOR)
            * tick
        )
        stop = max(stop, candidate) if side == 1 else min(stop, candidate)
    decision = evaluate_position_state(
        {
            "side": "BUY" if side == 1 else "SELL",
            "entry_price": pos["entry"],
            "current_sl": stop,
            "initial_sl": pos["stop"],
            "target": 0,
            "trailing_enabled": False,
        },
        executable,
    )
    reason = (
        "stop"
        if decision.breached
        else "time_limit"
        if now - pos["opened_at"] >= cfg.max_hold_seconds
        else None
    )
    return {
        "net": net,
        "peak_net": peak,
        "stop": stop,
        "planned_floor": floor,
        "exit_reason": reason,
    }
