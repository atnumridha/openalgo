"""30-minute LONG / SHORT / WAIT labels and fill-aware forward outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from services.crypto_fees import ContractFees, FeeProfile, fee_pct


@dataclass(frozen=True)
class FeePlan:
    """Fees for one contract under one fee profile, as % of notional per fill.

    Every number comes from ``services.crypto_fees``, the module the Positions
    page and the sandbox use, so a label is charged exactly what a trade
    would be. The Diwali Fee Voucher is a fee credit worth the opening fee
    before GST; ``count_voucher`` decides whether training values it as money.
    Off by default: it is capped at $100 a month and expires, so a strategy
    that is only profitable with it stops being profitable at the cap.
    """

    name: str
    contract: ContractFees = ContractFees(symbol="BTCUSD")
    profile: FeeProfile = FeeProfile(scalper_offer=False)
    slippage_pct_per_market_fill: float = 0.01
    count_voucher: bool = False

    @property
    def scalper_window_minutes(self) -> float | None:
        from services.crypto_fees import scalper_window_minutes

        return scalper_window_minutes(self.contract, self.profile)

    def entry_fee_pct(self, entry_order: str) -> float:
        role = "maker" if entry_order == "limit" else "taker"
        return fee_pct(self.contract, self.profile, role=role)

    def voucher_pct(self, entry_order: str, held_minutes: float) -> float:
        """The voucher a close after ``held_minutes`` earns, as % of notional."""
        if not self.count_voucher:
            return 0.0
        from services.crypto_fees import opening_voucher

        role = "maker" if entry_order == "limit" else "taker"
        before_gst = 100.0 * self.contract.rate(role)
        return opening_voucher(
            self.contract, self.profile, opening_fee=before_gst, held_minutes=held_minutes
        )

    def exit_fee_pct(self, exit_kind: str, held_minutes: float, *, eligible: bool = True) -> float:
        role = "maker" if exit_kind == "target" else "taker"
        return fee_pct(
            self.contract,
            self.profile,
            role=role,
            closing=eligible,
            held_minutes=held_minutes if eligible else None,
        )

    def for_symbol(self, symbol: str) -> FeePlan:
        """The same plan on another futures contract (its own Scalper window)."""
        return replace(self, contract=ContractFees(symbol=symbol.upper()))


FEE_PLANS = {
    "standard": FeePlan("standard", profile=FeeProfile(scalper_offer=False)),
    "scalper": FeePlan("scalper", profile=FeeProfile(scalper_offer=True)),
    "scalper+diwali": FeePlan(
        "scalper+diwali",
        profile=FeeProfile(scalper_offer=True, diwali_offer=True),
        count_voucher=True,
    ),
}


def plan_from_settings(
    symbol: str = "BTCUSD",
    settings: dict[str, Any] | None = None,
    *,
    count_voucher: bool = False,
) -> FeePlan:
    """The operator's own fee profile, from ML settings, for one contract."""
    from services.crypto_fee_service import fee_profile

    return FeePlan(
        "settings",
        contract=ContractFees(symbol=symbol.upper()),
        profile=fee_profile(settings),
        count_voucher=count_voucher,
    )


def _plan(fee_plan: str | FeePlan) -> FeePlan:
    return FEE_PLANS[fee_plan] if isinstance(fee_plan, str) else fee_plan


def _bars_frame(bars: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    frame = bars.copy() if isinstance(bars, pd.DataFrame) else pd.DataFrame(bars)
    needed = {"time", "open", "high", "low", "close"}
    missing = needed - set(frame.columns)
    if missing:
        raise ValueError(f"bars missing columns: {sorted(missing)}")
    return frame.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)


def simulate_trade(
    bars: pd.DataFrame | list[dict[str, Any]],
    *,
    entry_index: int,
    side: int,
    stop_pct: float,
    target_pct: float,
    max_hold_minutes: int = 28,
    fee_plan: str | FeePlan = "standard",
    entry_order: str = "market",
    entry_price: float | None = None,
    entry_offset_pct: float = 0.0,
    _normalized: bool = False,
) -> dict[str, Any] | None:
    """Simulate one entry and return its net price move, exit type and bars held.

    Entry is at the next bar's open for a market order. A resting limit is
    placed `entry_offset_pct` better than the signal close and fills only when
    a later bar trades through it by one dollar-centivalent step expressed as
    0.005% of price. Stop wins ties; gaps through the stop fill at the open.
    """
    if side not in (-1, 1):
        raise ValueError("side must be +1 (LONG) or -1 (SHORT)")
    if stop_pct <= 0 or target_pct <= 0 or max_hold_minutes <= 0:
        raise ValueError("stop, target and hold must be positive")
    frame = bars if _normalized else _bars_frame(bars)
    if entry_index < 0 or entry_index + 1 >= len(frame):
        return None
    if entry_order not in {"market", "limit"}:
        raise ValueError("entry_order must be market or limit")
    plan = _plan(fee_plan)
    signal_bar = frame.iloc[entry_index]
    minutes_per_bar = _infer_minutes(frame)
    entry_i = entry_index + 1
    if entry_order == "market":
        fill_price = float(frame.iloc[entry_i]["open"] if entry_price is None else entry_price)
        if not np.isfinite(fill_price) or fill_price <= 0:
            return None
    else:
        limit_price = float(signal_bar["close"]) * (1 - side * entry_offset_pct / 100)
        fill_i = None
        fill_price = None
        max_wait = max(1, int(np.ceil(5 / minutes_per_bar)))
        for j in range(entry_i, min(len(frame), entry_i + max_wait)):
            b = frame.iloc[j]
            through = limit_price * 0.00005
            crossed = (
                float(b["low"]) <= limit_price - through
                if side > 0
                else float(b["high"]) >= limit_price + through
            )
            if crossed:
                fill_i, fill_price = j, limit_price
                break
        if fill_i is None:
            return None
        entry_i = fill_i
    entry = float(fill_price)
    stop_price = entry * (1 - side * stop_pct / 100)
    target_price = entry * (1 + side * target_pct / 100)
    max_bars = max(1, int(np.ceil(max_hold_minutes / minutes_per_bar)))
    last_index = min(len(frame) - 1, entry_i + max_bars - 1)
    exit_price = None
    exit_kind = "time"
    exit_i = last_index
    for j in range(entry_i, last_index + 1):
        bar = frame.iloc[j]
        if j > entry_i:
            gap_adverse = side * (float(bar["open"]) - entry) / entry * 100
            if gap_adverse <= -stop_pct:
                exit_price, exit_kind, exit_i = float(bar["open"]), "stop", j
                break
        # Entry is at the first scanned bar's open; the opening gap is not a
        # post-entry gap. Its high/low path is checked below.
        stop_hit = float(bar["low"]) <= stop_price if side > 0 else float(bar["high"]) >= stop_price
        target_hit = (
            float(bar["high"]) >= target_price if side > 0 else float(bar["low"]) <= target_price
        )
        if stop_hit:
            exit_price, exit_kind, exit_i = stop_price, "stop", j
            break
        if target_hit and j > entry_i:
            exit_price, exit_kind, exit_i = target_price, "target", j
            break
    if exit_price is None:
        exit_price = float(frame.iloc[last_index]["close"])
    held_minutes = max(minutes_per_bar, (exit_i - entry_i + 1) * minutes_per_bar)
    gross = side * (exit_price - entry) / entry * 100
    entry_fee = plan.entry_fee_pct(entry_order)
    exit_fee = plan.exit_fee_pct(exit_kind, held_minutes)
    voucher = plan.voucher_pct(entry_order, held_minutes)
    slippage = plan.slippage_pct_per_market_fill * (
        int(entry_order == "market") + int(exit_kind != "target")
    )
    net = gross - entry_fee - exit_fee - slippage + voucher
    label = "LONG" if net > 0 and side > 0 else "SHORT" if net > 0 else "WAIT"
    return {
        "label": label,
        "side": side,
        "entry_index": entry_i,
        "entry_time": int(frame.iloc[entry_i]["time"]),
        "entry_price": entry,
        "exit_index": exit_i,
        "exit_time": int(frame.iloc[exit_i]["time"]),
        "exit_price": exit_price,
        "exit_kind": exit_kind,
        "held_minutes": held_minutes,
        "gross_pct": gross,
        "entry_fee_pct": entry_fee,
        "exit_fee_pct": exit_fee,
        "slippage_pct": slippage,
        "voucher_pct": voucher,
        "net_pct": net,
        "stop_pct": stop_pct,
        "target_pct": target_pct,
        "stop_price": stop_price,
        "target_price": target_price,
    }


def build_labels(
    bars: pd.DataFrame | list[dict[str, Any]],
    *,
    stop_pct: float,
    target_pct: float,
    max_hold_minutes: int = 28,
    fee_plan: str | FeePlan = "standard",
    entry_order: str = "market",
) -> tuple[np.ndarray, pd.DataFrame]:
    """Build LONG/SHORT/WAIT labels for every bar; unused tail labels are None."""
    frame = _bars_frame(bars)
    arrays = {
        column: frame[column].to_numpy(dtype=float)
        for column in ("time", "open", "high", "low", "close")
    }
    minutes_per_bar = _infer_minutes(frame)
    labels = np.full(len(frame), None, dtype=object)
    records: list[dict[str, Any]] = []
    for signal_index in range(0, len(frame) - 1):
        side_results = []
        for side in (1, -1):
            result = _simulate_trade_arrays(
                arrays,
                entry_index=signal_index,
                side=side,
                stop_pct=stop_pct,
                target_pct=target_pct,
                max_hold_minutes=max_hold_minutes,
                fee_plan=fee_plan,
                entry_order=entry_order,
                minutes_per_bar=minutes_per_bar,
            )
            if result is None:
                continue
            side_results.append(result)
            records.append({"signal_index": signal_index, **result})
        profitable_results = [result for result in side_results if result["net_pct"] > 0]
        if profitable_results:
            labels[signal_index] = max(profitable_results, key=lambda result: result["net_pct"])[
                "label"
            ]
        elif side_results:
            labels[signal_index] = "WAIT"
    return labels, pd.DataFrame(records)


def _simulate_trade_arrays(
    arrays: dict[str, np.ndarray],
    *,
    entry_index: int,
    side: int,
    stop_pct: float,
    target_pct: float,
    max_hold_minutes: int,
    fee_plan: str | FeePlan,
    entry_order: str,
    minutes_per_bar: float,
) -> dict[str, Any] | None:
    if entry_order != "market" or entry_index < 0 or entry_index + 1 >= len(arrays["open"]):
        return None
    plan = _plan(fee_plan)
    entry_index = entry_index + 1
    entry = float(arrays["open"][entry_index])
    if not np.isfinite(entry) or entry <= 0:
        return None
    stop_price = entry * (1 - side * stop_pct / 100)
    target_price = entry * (1 + side * target_pct / 100)
    max_bars = max(1, int(np.ceil(max_hold_minutes / minutes_per_bar)))
    last_index = min(len(arrays["close"]) - 1, entry_index + max_bars - 1)
    exit_index = last_index
    exit_kind = "time"
    exit_price = None
    for current_index in range(entry_index, last_index + 1):
        if current_index > entry_index:
            gap_adverse = side * (arrays["open"][current_index] - entry) / entry * 100
            if gap_adverse <= -stop_pct:
                exit_index = current_index
                exit_kind = "stop"
                exit_price = float(arrays["open"][current_index])
                break
        stop_hit = (
            arrays["low"][current_index] <= stop_price
            if side > 0
            else arrays["high"][current_index] >= stop_price
        )
        target_hit = (
            arrays["high"][current_index] >= target_price
            if side > 0
            else arrays["low"][current_index] <= target_price
        )
        if stop_hit:
            exit_index = current_index
            exit_kind = "stop"
            exit_price = stop_price
            break
        if target_hit and current_index > entry_index:
            exit_index = current_index
            exit_kind = "target"
            exit_price = target_price
            break
    if exit_price is None:
        exit_price = float(arrays["close"][last_index])
    held_minutes = max(minutes_per_bar, (exit_index - entry_index + 1) * minutes_per_bar)
    gross = side * (exit_price - entry) / entry * 100
    entry_fee = plan.entry_fee_pct(entry_order)
    exit_fee = plan.exit_fee_pct(exit_kind, held_minutes)
    voucher = plan.voucher_pct(entry_order, held_minutes)
    slippage = plan.slippage_pct_per_market_fill * (
        int(entry_order == "market") + int(exit_kind != "target")
    )
    net = gross - entry_fee - exit_fee - slippage + voucher
    return {
        "label": "LONG" if net > 0 and side > 0 else "SHORT" if net > 0 else "WAIT",
        "side": side,
        "entry_index": entry_index,
        "entry_time": int(arrays["time"][entry_index]),
        "entry_price": entry,
        "exit_index": exit_index,
        "exit_time": int(arrays["time"][exit_index]),
        "exit_price": exit_price,
        "exit_kind": exit_kind,
        "held_minutes": held_minutes,
        "gross_pct": gross,
        "entry_fee_pct": entry_fee,
        "exit_fee_pct": exit_fee,
        "slippage_pct": slippage,
        "voucher_pct": voucher,
        "net_pct": net,
        "stop_pct": stop_pct,
        "target_pct": target_pct,
        "stop_price": stop_price,
        "target_price": target_price,
    }


def preview_counts(
    bars, *, stop_pct: float, target_pct: float, max_hold_minutes: int, fee_plan: str
) -> dict[str, Any]:
    labels, trades = build_labels(
        bars,
        stop_pct=stop_pct,
        target_pct=target_pct,
        max_hold_minutes=max_hold_minutes,
        fee_plan=fee_plan,
    )
    counts = {name: int(np.sum(labels == name)) for name in ("LONG", "SHORT", "WAIT")}
    return {
        "counts": counts,
        "trades": int(len(trades)),
        "win_pct": float((trades["net_pct"] > 0).mean()) if len(trades) else 0.0,
    }


def _infer_minutes(frame: pd.DataFrame) -> float:
    if len(frame) < 2:
        return 1.0
    diffs = pd.to_numeric(frame["time"], errors="coerce").diff().dropna()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return 1.0
    return max(1 / 60, float(diffs.median()) / 60)


@dataclass(frozen=True)
class Outcomes:
    """Every bar's LONG and SHORT trade, simulated the way simulate_trade does.

    Arrays are indexed by signal bar; ``net`` is NaN where no trade exists
    (the last bar, which has no next open). ``exit_index`` is the bar the
    trade closed on, -1 where there is none.
    """

    net: dict[int, np.ndarray]
    exit_index: dict[int, np.ndarray]
    held_minutes: dict[int, np.ndarray]
    exit_kind: dict[int, np.ndarray]


#: exit_kind codes in Outcomes.
EXIT_STOP, EXIT_TARGET, EXIT_TIME = 1, 2, 3


def trade_outcomes(
    bars: pd.DataFrame | list[dict[str, Any]],
    *,
    stop_pct: float | np.ndarray,
    target_pct: float | np.ndarray,
    max_hold_minutes: int = 28,
    fee_plan: str | FeePlan = "standard",
) -> Outcomes:
    """Vectorised market-entry outcomes for every bar, both sides.

    The same rules as simulate_trade with a market entry: enter at the next
    bar's open, the stop wins a tie, a gap through the stop fills at the open,
    the target is not taken on the entry bar, and a trade still open after the
    hold closes at that bar's close. Fees come from the plan, so the Scalper
    Offer window is judged on the minutes actually held. One pass per bar of
    the hold rather than one Python loop per signal bar, so a year of minute
    bars takes seconds and no per-trade objects.

    ``stop_pct`` and ``target_pct`` may be arrays with one value per bar, for
    levels scaled to each bar's volatility.
    """
    frame = _bars_frame(bars)
    n = len(frame)
    stop_pct = np.broadcast_to(np.asarray(stop_pct, dtype=float), (n,))
    target_pct = np.broadcast_to(np.asarray(target_pct, dtype=float), (n,))
    if max_hold_minutes <= 0 or np.any(stop_pct <= 0) or np.any(target_pct <= 0):
        raise ValueError("stop, target and hold must be positive")
    plan = _plan(fee_plan)
    o = frame["open"].to_numpy(dtype=float)
    h = frame["high"].to_numpy(dtype=float)
    low = frame["low"].to_numpy(dtype=float)
    c = frame["close"].to_numpy(dtype=float)
    minutes_per_bar = _infer_minutes(frame)
    max_bars = max(1, int(np.ceil(max_hold_minutes / minutes_per_bar)))
    entry_i = np.arange(n) + 1
    has_entry = entry_i < n
    safe_entry_i = np.minimum(entry_i, n - 1)
    entry = np.where(has_entry, o[safe_entry_i], np.nan)
    has_entry &= np.isfinite(entry) & (entry > 0)
    last_i = np.minimum(n - 1, entry_i + max_bars - 1)

    entry_fee = plan.entry_fee_pct("market")
    held_values = np.arange(1, max_bars + 1) * minutes_per_bar
    exit_fee_target = {
        k: plan.exit_fee_pct("target", max(minutes_per_bar, m))
        for k, m in enumerate(held_values, 1)
    }
    exit_fee_other = {
        k: plan.exit_fee_pct("stop", max(minutes_per_bar, m)) for k, m in enumerate(held_values, 1)
    }
    voucher_by_bars = np.array(
        [0.0] + [plan.voucher_pct("market", max(minutes_per_bar, m)) for m in held_values]
    )

    nets: dict[int, np.ndarray] = {}
    exits: dict[int, np.ndarray] = {}
    helds: dict[int, np.ndarray] = {}
    kinds: dict[int, np.ndarray] = {}
    for side in (1, -1):
        stop_price = entry * (1 - side * stop_pct / 100)
        target_price = entry * (1 + side * target_pct / 100)
        exit_price = np.full(n, np.nan)
        exit_at = np.full(n, -1, dtype=np.int64)
        kind = np.zeros(n, dtype=np.int8)
        open_ = has_entry.copy()
        for k in range(max_bars):
            j = entry_i + k
            live = open_ & (j <= last_i)
            if not live.any():
                break
            jj = np.minimum(j, n - 1)
            if k > 0:
                gap = side * (o[jj] - entry) / entry * 100 <= -stop_pct
                hit = live & gap
                exit_price[hit], exit_at[hit], kind[hit] = o[jj][hit], jj[hit], EXIT_STOP
                open_ &= ~hit
                live &= ~hit
            stop_hit = (low[jj] <= stop_price) if side > 0 else (h[jj] >= stop_price)
            target_hit = (h[jj] >= target_price) if side > 0 else (low[jj] <= target_price)
            hit = live & stop_hit
            exit_price[hit], exit_at[hit], kind[hit] = stop_price[hit], jj[hit], EXIT_STOP
            open_ &= ~hit
            live &= ~hit
            if k > 0:
                hit = live & target_hit
                exit_price[hit], exit_at[hit], kind[hit] = target_price[hit], jj[hit], EXIT_TARGET
                open_ &= ~hit
        timed = open_
        exit_price[timed] = c[last_i[timed]]
        exit_at[timed] = last_i[timed]
        kind[timed] = EXIT_TIME

        bars_held = np.where(has_entry, exit_at - entry_i + 1, 0)
        held = np.maximum(minutes_per_bar, bars_held * minutes_per_bar)
        gross = side * (exit_price - entry) / entry * 100
        fee_target = np.array(
            [
                exit_fee_target.get(int(b), exit_fee_target[max_bars])
                for b in bars_held.clip(1, max_bars)
            ]
        )
        fee_other = np.array(
            [
                exit_fee_other.get(int(b), exit_fee_other[max_bars])
                for b in bars_held.clip(1, max_bars)
            ]
        )
        exit_fee = np.where(kind == EXIT_TARGET, fee_target, fee_other)
        slippage = plan.slippage_pct_per_market_fill * (1 + (kind != EXIT_TARGET).astype(float))
        voucher = voucher_by_bars[bars_held.clip(1, max_bars)]
        net = gross - entry_fee - exit_fee - slippage + voucher
        net[~has_entry] = np.nan
        exit_at[~has_entry] = -1
        nets[side], exits[side], helds[side], kinds[side] = net, exit_at, held, kind
    return Outcomes(net=nets, exit_index=exits, held_minutes=helds, exit_kind=kinds)
