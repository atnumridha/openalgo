"""$100 USD account sizing, leverage and liquidation-aware compounding."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AccountConfig:
    start_usd: float = 100.0
    max_leverage: float = 25.0
    risk_fraction: float = 0.02
    max_loss_fraction: float = 0.002
    max_notional_fraction: float = 25.0
    contract_btc: float = 0.001
    maintenance_margin_pct: float = 0.25


def contracts_for_trade(
    *,
    equity: float,
    price: float,
    stop_pct: float,
    leverage: float,
    config: AccountConfig = AccountConfig(),
    risk_fraction: float | None = None,
) -> dict:
    """Size to the lower of fixed account risk and max permitted notional.

    The plan's 0.2% is a max price stop, not 0.2% of account equity. Risk is
    fixed to 2% of current equity by default, with no more than the configured
    leverage and no position past the conservative liquidation distance.
    """
    if equity <= 0 or price <= 0 or stop_pct <= 0 or leverage <= 0:
        return {"contracts": 0, "notional_usd": 0.0, "margin_usd": 0.0, "risk_usd": 0.0}
    lev = min(float(leverage), config.max_leverage)
    risk_pct = min(
        config.max_loss_fraction,
        risk_fraction if risk_fraction is not None else config.risk_fraction,
    )
    # Reserve a buffer before estimated liquidation: stop must sit before liq.
    liq_move = 100.0 / lev - config.maintenance_margin_pct
    safe_stop = min(float(stop_pct), liq_move * 0.5)
    if safe_stop <= 0:
        return {"contracts": 0, "notional_usd": 0.0, "margin_usd": 0.0, "risk_usd": 0.0}
    risk_dollars = equity * risk_pct
    risk_limited_notional = risk_dollars * 100 / safe_stop
    max_notional = equity * min(lev, config.max_notional_fraction)
    notional = min(risk_limited_notional, max_notional)
    contracts = int(notional / (price * config.contract_btc))
    actual_notional = contracts * price * config.contract_btc
    return {
        "contracts": contracts,
        "notional_usd": actual_notional,
        "margin_usd": actual_notional / lev,
        "risk_usd": actual_notional * safe_stop / 100,
        "effective_stop_pct": safe_stop,
        "leverage": lev,
        "liquidation_move_pct": liq_move,
        "risk_fraction": risk_pct,
    }


def simulate_account(
    returns_pct: Iterable[float],
    *,
    start_usd: float = 100.0,
    leverage: float = 10.0,
    max_leverage: float = 25.0,
    risk_fraction: float = 0.02,
    max_loss_fraction: float = 0.002,
    maintenance_margin_pct: float = 0.25,
) -> dict:
    """Compound a sequence of trade returns with risk sizing and liquidation cap."""
    lev = min(float(leverage), float(max_leverage))
    equity = float(start_usd)
    curve = [equity]
    peak = equity
    max_dd = 0.0
    liquidations = 0
    wins = 0
    for ret in returns_pct:
        # Return is % of notional; stop risk caps loss at risk_fraction of equity.
        notional_fraction = min(lev, risk_fraction * 100 / max(max_loss_fraction * 100, 1e-9))
        pnl_fraction = float(ret) * notional_fraction / 100
        liquidation_loss = max(0.0, 1 / lev - maintenance_margin_pct / 100)
        if pnl_fraction <= -liquidation_loss:
            pnl_fraction = -min(0.95, liquidation_loss)
            liquidations += 1
        equity *= max(0.01, 1 + pnl_fraction)
        wins += pnl_fraction > 0
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity / peak - 1) * 100)
        curve.append(equity)
    return {
        "start_usd": start_usd,
        "end_usd": equity,
        "return_pct": (equity / start_usd - 1) * 100,
        "max_drawdown_pct": max_dd,
        "trades": len(curve) - 1,
        "win_rate_pct": wins / max(1, len(curve) - 1) * 100,
        "liquidations": liquidations,
        "equity_curve": curve,
    }


def monte_carlo_ruin(
    returns_pct: Iterable[float],
    *,
    start_usd: float = 100.0,
    leverage: float = 10.0,
    risk_fraction: float = 0.02,
    threshold_loss_pct: float = 50.0,
    simulations: int = 2000,
    seed: int = 7,
) -> float:
    """Blockless bootstrap stress: chance a shuffled historical sequence loses X%."""
    values = np.asarray(list(returns_pct), dtype=float)
    if values.size == 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    ruin = 0
    notional_fraction = min(leverage, risk_fraction * 100 / 0.2)
    for _ in range(simulations):
        sample = rng.choice(values, size=values.size, replace=True)
        equity = start_usd
        for ret in sample:
            equity *= max(0.01, 1 + ret * notional_fraction / 100)
            if equity <= start_usd * (1 - threshold_loss_pct / 100):
                ruin += 1
                break
    return ruin / simulations
