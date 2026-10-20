"""How many contracts a suggestion is worth, and what the trade costs.

Pure arithmetic: the balance, the contract and the fee profile arrive as
arguments, so this is tested without an exchange.

The rule the operator chose: size so that hitting the stop loses a set share
of the available USD balance, fees included, and never use more leverage than
the cap. With ``entry`` the price, ``cv`` the contract value, ``stop`` and
``fees`` as fractions of notional:

    contracts = floor(balance x risk% / (entry x cv x (stop + fees)))

capped so that ``contracts x entry x cv <= balance x max_leverage``. When even
one contract would risk more than the budget, the trade is refused and the
amount it would risk is stated, rather than quietly sending one.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from services.crypto_fees import (
    ContractFees,
    FeeProfile,
    fill_fee,
    opening_voucher,
    scalper_window_minutes,
)


@dataclass(frozen=True)
class Sizing:
    ok: bool
    contracts: int = 0
    notional: float = 0.0
    margin: float = 0.0
    leverage: float = 0.0
    risk_amount: float = 0.0
    risk_budget: float = 0.0
    entry_fee: float = 0.0
    exit_fee_in_window: float = 0.0
    exit_fee_after_window: float = 0.0
    voucher_if_in_window: float = 0.0
    loss_at_stop: float = 0.0
    profit_at_target: float = 0.0
    reward_risk_after_fees: float | None = None
    capped_by_leverage: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def size_trade(
    *,
    side: int,
    entry: float,
    stop_pct: float,
    target_pct: float,
    balance: float,
    risk_pct: float,
    max_leverage: float,
    contract_value: float,
    contract: ContractFees,
    profile: FeeProfile,
    hold_minutes: float,
    voucher_earned_this_month: float = 0.0,
) -> Sizing:
    """Contracts and every dollar figure for one suggested trade.

    Fees are taken at taker rates on both sides, which is what a market entry
    and a stop pay. The closing fee is shown both inside the Scalper Offer
    window (often zero) and after it. Risk is judged on the worse of the two,
    so the size holds however long the trade stays open.
    """
    if side not in (1, -1):
        return Sizing(ok=False, reason="There is no trade to size: the signal says WAIT.")
    if entry <= 0 or contract_value <= 0:
        return Sizing(ok=False, reason="The price or the contract size is not known yet.")
    if stop_pct <= 0:
        return Sizing(ok=False, reason="The stop distance is not set.")
    if balance <= 0:
        return Sizing(ok=False, reason="There is no available USD balance to size this trade from.")

    budget = balance * risk_pct / 100
    per_contract = entry * contract_value
    stop_price = entry * (1 - side * stop_pct / 100)

    def fees_for(contracts: int) -> tuple[float, float, float]:
        opening = fill_fee(contract, profile, notional=contracts * per_contract, role="taker")
        in_window = fill_fee(
            contract,
            profile,
            notional=contracts * contract_value * stop_price,
            role="taker",
            closing=True,
            held_minutes=0.0,
        ).total
        after = fill_fee(
            contract, profile, notional=contracts * contract_value * stop_price, role="taker"
        ).total
        return opening.total, in_window, after

    one_open, _one_in, one_after = fees_for(1)
    loss_one = per_contract * stop_pct / 100 + one_open + one_after
    if loss_one > budget:
        return Sizing(
            ok=False,
            risk_budget=budget,
            risk_amount=loss_one,
            reason=(
                f"One contract would lose ${loss_one:,.2f} at the stop, fees included, which is "
                f"more than your ${budget:,.2f} risk budget ({risk_pct:g}% of ${balance:,.2f}). "
                "Raise the risk %, add funds, or wait for a tighter stop."
            ),
        )

    contracts = max(1, math.floor(budget / loss_one))
    max_by_leverage = math.floor(balance * max_leverage / per_contract)
    capped = contracts > max_by_leverage
    if capped:
        contracts = max_by_leverage
    if contracts < 1:
        return Sizing(
            ok=False,
            risk_budget=budget,
            reason=(
                f"One contract is ${per_contract:,.2f} of exposure, more than "
                f"{max_leverage:g}x leverage allows on ${balance:,.2f}."
            ),
        )

    entry_fee, exit_in_window, exit_after = fees_for(contracts)
    notional = contracts * per_contract
    move_to_stop = notional * stop_pct / 100
    move_to_target = notional * target_pct / 100
    loss_at_stop = move_to_stop + entry_fee + exit_after
    window = scalper_window_minutes(contract, profile)
    target_exit_fee = (
        exit_in_window if window is not None and hold_minutes <= window else exit_after
    )
    profit_at_target = move_to_target - entry_fee - target_exit_fee
    voucher = opening_voucher(
        contract,
        profile,
        opening_fee=entry_fee / (1 + profile.gst_pct / 100),
        held_minutes=min(hold_minutes, window) if window is not None else None,
        earned_this_month=voucher_earned_this_month,
    )
    return Sizing(
        ok=True,
        contracts=int(contracts),
        notional=notional,
        margin=notional / max_leverage,
        leverage=max_leverage,
        risk_amount=loss_at_stop,
        risk_budget=budget,
        entry_fee=entry_fee,
        exit_fee_in_window=exit_in_window,
        exit_fee_after_window=exit_after,
        voucher_if_in_window=voucher,
        loss_at_stop=loss_at_stop,
        profit_at_target=profit_at_target,
        reward_risk_after_fees=(profit_at_target / loss_at_stop) if loss_at_stop > 0 else None,
        capped_by_leverage=capped,
    )
