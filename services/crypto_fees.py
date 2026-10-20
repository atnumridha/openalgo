"""Delta Exchange India trading fees, as one pure calculation.

Every surface that shows a crypto P&L after fees, or that trains on one, takes
its numbers from here: the Positions page, the sandbox, the ML labels and the
ML trade sizing. ``frontend/src/lib/cryptoFees.ts`` is the TypeScript copy and
``test/crypto_fees/vectors.json`` is the contract between the two, exactly as
``test/risk/vectors.json`` binds the risk core to its browser twin.

No I/O of any kind: a contract's rates and the operator's fee profile arrive
as arguments. ``services/crypto_fee_service.py`` is what reads them.

The schedule (Delta's fees page and product API, October 2026):

* A fee is a rate on notional, ``contracts x contract_value x price``.
  Futures pay 0.05% taker and 0.02% maker; options, MOVE and spreads 0.01%;
  spot 0.1%. Each product reports its own rates, which win over these.
* Option, MOVE and spread fees are capped at a share of the premium paid,
  3.5% at present, so a deep out-of-the-money contract is not charged more
  than it costs.
* 18% GST is added to every fee.
* Scalper Offer, for an account that has joined it: the closing leg of a
  futures position pays nothing when the position was opened and closed
  within 30 minutes on BTCUSD and ETHUSD, or 15 minutes on other futures.
  It never applies to options, PAXGUSD, SLVONUSD or XAUTUSD, and it covers
  partial closes.
* Diwali Scalper Offer, automatic for an account in the Scalper Offer: a
  BTCUSD futures position opened and closed within 30 minutes also gets the
  cash-paid opening fee back as a Fee Voucher. The voucher is a fee credit,
  not cash, so it is reported beside the net P&L and never inside it. It is
  capped at $100 per calendar month (IST) across the main account and its
  sub-accounts, expires 90 days after credit, and is not earned on a fee
  that was itself paid with a voucher. A partial close earns the matching
  share of the opening fee. Delta's own examples quote it before GST, so
  that is how it is modelled: the GST on the opening fee is not credited.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

FUTURES_TYPES = frozenset({"perpetual_futures", "futures"})
PREMIUM_TYPES = frozenset(
    {
        "call_options",
        "put_options",
        "move_options",
        "options_combos",
        "spreads",
        "turbo_call_options",
        "turbo_put_options",
    }
)

#: Rates by contract type, as fractions of notional, for when a product's own
#: rates are not to hand.
DEFAULT_RATES = {
    "futures": (0.0002, 0.0005),
    "premium": (0.0001, 0.0001),
    "spot": (0.001, 0.001),
}


def net_target_plan(*, side, entry, stop, quantity, contract_value, tick, contract,
                    net_rr=3, minimum_profit=1, slippage=0.1, gst_pct=18):
    """Solve a vanilla futures target after full fees, tax and an exit reserve.

    Maker entry/target; taker protective exit. Promotions and vouchers are not
    budgeted. Target rounding is away from entry so it cannot underfund reward.
    This is a planned result, not a guaranteed fill or maximum possible loss.
    """
    def d(value):
        v = Decimal(str(value))
        if not v.is_finite():
            raise ValueError('Finite prices and costs are required')
        return v
    e, s, q, cv, step, rr, profit, reserve, gst = map(d,
        (entry, stop, quantity, contract_value, tick, net_rr, minimum_profit, slippage, gst_pct))
    if side not in (1, -1) or min(e, s, q, cv, step, rr) <= 0 or q != int(q):
        raise ValueError('Valid side, positive prices and whole contracts required')
    if side*(e-s) <= 0 or min(profit, reserve, gst) < 0 or contract.contract_type not in FUTURES_TYPES:
        raise ValueError('Stop must be on the loss side of a vanilla futures position')
    maker = d(contract.rate('maker')) * (1+gst/100)
    taker = d(contract.rate('taker')) * (1+gst/100)
    if not 0 <= maker < 1 or not 0 <= taker < 1:
        raise ValueError('Invalid product fee rates')
    units=q*cv
    opening=e*units*maker
    stop_fee=s*units*taker
    risk=abs(e-s)*units+opening+stop_fee+reserve
    required=max(profit,rr*risk)
    raw=((e*units+opening+reserve+required)/(units*(1-maker)) if side==1
         else (e*units-opening-reserve-required)/(units*(1+maker)))
    target=(raw/step).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*step
    if target <= 0 or side*(target-e) <= 0:
        raise ValueError('No valid target covers the required net return')
    target_fee=target*units*maker
    net=side*(target-e)*units-opening-target_fee-reserve
    return {key: float(value) for key,value in {
        'entry':e,'stop':s,'target':target,'net_risk':risk,'net_target':net,
        'entry_fee':opening,'stop_fee':stop_fee,'target_fee':target_fee,
        'slippage_reserve':reserve,'net_rr':net/risk,
    }.items()}


@dataclass(frozen=True, slots=True)
class FeeProfile:
    """The operator's side of the schedule: tax and the offers joined."""

    gst_pct: float = 18.0
    scalper_offer: bool = True
    scalper_minutes_major: float = 30.0
    scalper_minutes_other: float = 15.0
    scalper_majors: tuple[str, ...] = ("BTCUSD", "ETHUSD")
    scalper_excluded: tuple[str, ...] = ("PAXGUSD", "SLVONUSD", "XAUTUSD")
    diwali_offer: bool = False
    diwali_symbols: tuple[str, ...] = ("BTCUSD",)
    diwali_window_minutes: float = 30.0
    voucher_monthly_cap: float = 100.0
    premium_cap_pct: float = 3.5


@dataclass(frozen=True, slots=True)
class ContractFees:
    """One product's side: what it is and what it charges."""

    symbol: str
    contract_type: str = "perpetual_futures"
    maker_rate: float | None = None
    taker_rate: float | None = None

    def rate(self, role: str) -> float:
        explicit = self.maker_rate if role == "maker" else self.taker_rate
        if explicit is not None and explicit >= 0:
            return float(explicit)
        if self.contract_type in PREMIUM_TYPES:
            maker, taker = DEFAULT_RATES["premium"]
        elif self.contract_type == "spot":
            maker, taker = DEFAULT_RATES["spot"]
        else:
            maker, taker = DEFAULT_RATES["futures"]
        return maker if role == "maker" else taker


@dataclass(frozen=True, slots=True)
class FillFee:
    """One fill's fee. ``total`` is what the account pays, GST included."""

    fee: float
    gst: float
    total: float
    waived: bool = False
    capped: bool = False


@dataclass(frozen=True, slots=True)
class OpenPositionFees:
    """Fees on an open position, known and still to come.

    ``voucher_now`` is the Fee Voucher that closing now would earn; it is a
    credit, not part of any cash figure here.
    """

    entry_fee: float
    exit_fee_now: float
    exit_fee_after_window: float
    window_minutes: float | None
    window_remaining_minutes: float | None
    voucher_now: float = 0.0
    voucher_window_remaining_minutes: float | None = None


def _is_futures(contract: ContractFees) -> bool:
    return contract.contract_type in FUTURES_TYPES


def scalper_window_minutes(contract: ContractFees, profile: FeeProfile) -> float | None:
    """Minutes within which closing is free, or None when the offer does not apply."""
    if not profile.scalper_offer or not _is_futures(contract):
        return None
    symbol = contract.symbol.upper()
    if symbol in profile.scalper_excluded:
        return None
    if symbol in profile.scalper_majors:
        return profile.scalper_minutes_major
    return profile.scalper_minutes_other


def voucher_window_minutes(contract: ContractFees, profile: FeeProfile) -> float | None:
    """Minutes within which closing earns the opening fee back, or None."""
    if not profile.diwali_offer or scalper_window_minutes(contract, profile) is None:
        return None
    if contract.symbol.upper() not in profile.diwali_symbols:
        return None
    return profile.diwali_window_minutes


def opening_voucher(
    contract: ContractFees,
    profile: FeeProfile,
    *,
    opening_fee: float,
    held_minutes: float | None,
    earned_this_month: float = 0.0,
) -> float:
    """The Fee Voucher one close earns.

    Args:
        opening_fee: the cash-paid opening fee on the contracts being closed,
            before GST. A fee paid with a voucher earns nothing, so leave that
            part out.
        held_minutes: how long the position had been open when it closed.
        earned_this_month: vouchers already credited this calendar month
            (IST), for the monthly cap.
    """
    window = voucher_window_minutes(contract, profile)
    if window is None or held_minutes is None or held_minutes > window:
        return 0.0
    room = max(0.0, profile.voucher_monthly_cap - max(0.0, earned_this_month))
    return min(max(0.0, float(opening_fee)), room)


def fill_fee(
    contract: ContractFees,
    profile: FeeProfile,
    *,
    notional: float,
    role: str = "taker",
    premium: float | None = None,
    closing: bool = False,
    held_minutes: float | None = None,
) -> FillFee:
    """The fee on one fill.

    Args:
        notional: contracts x contract_value x price, in the settling currency.
        role: "taker" or "maker".
        premium: for an option, MOVE or spread, the premium paid on the fill,
            which caps the fee.
        closing: True for the fill that closes (part of) a position.
        held_minutes: how long the position was open, for the Scalper Offer.
    """
    notional = abs(float(notional))
    window = scalper_window_minutes(contract, profile)
    if closing and window is not None and held_minutes is not None and held_minutes <= window:
        return FillFee(fee=0.0, gst=0.0, total=0.0, waived=True)
    fee = notional * contract.rate(role)
    capped = False
    if contract.contract_type in PREMIUM_TYPES and premium is not None and premium > 0:
        cap = abs(float(premium)) * profile.premium_cap_pct / 100
        if fee > cap:
            fee, capped = cap, True
    gst = fee * profile.gst_pct / 100
    return FillFee(fee=fee, gst=gst, total=fee + gst, capped=capped)


def fee_pct(
    contract: ContractFees,
    profile: FeeProfile,
    *,
    role: str = "taker",
    closing: bool = False,
    held_minutes: float | None = None,
) -> float:
    """A fill's fee as a percent of notional, GST included (no premium cap)."""
    return fill_fee(
        contract, profile, notional=100.0, role=role, closing=closing, held_minutes=held_minutes
    ).total


def opening_fee_before_gst(fee_with_gst: float, profile: FeeProfile) -> float:
    """An opening fee with its GST taken back out, which is what a voucher returns."""
    return max(0.0, float(fee_with_gst)) / (1 + profile.gst_pct / 100)


def open_position_fees(
    contract: ContractFees,
    profile: FeeProfile,
    *,
    entry_notional: float,
    exit_notional: float,
    held_minutes: float,
    entry_role: str = "taker",
    exit_role: str = "taker",
    entry_fee_paid: float | None = None,
    entry_premium: float | None = None,
    exit_premium: float | None = None,
    voucher_earned_this_month: float = 0.0,
) -> OpenPositionFees:
    """Fees on an open position: paid to open it, and due if it closed now.

    ``entry_fee_paid`` is the exchange's own figure from the opening fills,
    GST included, which wins over the estimate whenever it is known.
    """
    if entry_fee_paid is None:
        entry_fee = fill_fee(
            contract, profile, notional=entry_notional, role=entry_role, premium=entry_premium
        ).total
    else:
        entry_fee = max(0.0, float(entry_fee_paid))
    window = scalper_window_minutes(contract, profile)
    now = fill_fee(
        contract,
        profile,
        notional=exit_notional,
        role=exit_role,
        premium=exit_premium,
        closing=True,
        held_minutes=held_minutes,
    ).total
    after = fill_fee(
        contract, profile, notional=exit_notional, role=exit_role, premium=exit_premium
    ).total
    remaining = None if window is None else max(0.0, window - held_minutes)
    voucher_window = voucher_window_minutes(contract, profile)
    return OpenPositionFees(
        entry_fee=entry_fee,
        exit_fee_now=now,
        exit_fee_after_window=after,
        window_minutes=window,
        window_remaining_minutes=remaining,
        voucher_now=opening_voucher(
            contract,
            profile,
            opening_fee=opening_fee_before_gst(entry_fee, profile),
            held_minutes=held_minutes,
            earned_this_month=voucher_earned_this_month,
        ),
        voucher_window_remaining_minutes=(
            None if voucher_window is None else max(0.0, voucher_window - held_minutes)
        ),
    )


def net_pnl(
    *,
    gross: float,
    fees_paid: float = 0.0,
    exit_fee_due: float = 0.0,
    funding: float = 0.0,
) -> float:
    """Net cash P&L: gross price P&L, less fees paid and due, plus funding.

    ``funding`` is signed as the exchange reports it: positive is received.
    A Fee Voucher is not cash and is reported beside this figure.
    """
    return gross - fees_paid - exit_fee_due + funding


def fees_from_fills(
    contract: ContractFees,
    profile: FeeProfile,
    fills: list[tuple[float, float, float]],
    *,
    contract_value: float,
    role: str = "taker",
    voucher_earned_before: float = 0.0,
) -> tuple[float, float, float | None]:
    """Fees on a run of fills for one contract, oldest first.

    Each fill is ``(time_seconds, signed_contracts, price)``: positive buys,
    negative sells. The position is followed through the fills so a fill that
    reduces it is charged as a closing fill, with the Scalper Offer judged on
    how long the position had been open. A close inside the Diwali window
    earns its share of the opening fees still held, before GST.

    Returns the fees paid (GST in), the Fee Vouchers those closes earned, and
    when the position still open at the end was opened (None when flat).
    """
    fees = 0.0
    vouchers = 0.0
    position = 0.0
    opening_pool = 0.0
    opened_at: float | None = None

    def open_fee(contracts: float, price: float) -> float:
        nonlocal fees, opening_pool
        charged = fill_fee(contract, profile, notional=contracts * contract_value * price, role=role)
        fees += charged.total
        opening_pool += charged.fee
        return charged.total

    for at, contracts, price in fills:
        if not contracts or not price:
            continue
        reducing = position != 0 and (position > 0) != (contracts > 0)
        if reducing:
            closed = min(abs(contracts), abs(position))
            held = None if opened_at is None else max(0.0, (at - opened_at) / 60)
            fees += fill_fee(
                contract,
                profile,
                notional=closed * contract_value * price,
                role=role,
                closing=True,
                held_minutes=held,
            ).total
            share = opening_pool * closed / abs(position)
            opening_pool -= share
            earned = opening_voucher(
                contract,
                profile,
                opening_fee=share,
                held_minutes=held,
                earned_this_month=voucher_earned_before + vouchers,
            )
            vouchers += earned
            remainder = abs(contracts) - closed
            position += contracts
            if abs(position) < 1e-12:
                position, opened_at, opening_pool = 0.0, None, 0.0
            if remainder > 1e-12:
                open_fee(remainder, price)
                opened_at = at
            continue
        open_fee(abs(contracts), price)
        if position == 0:
            opened_at = at
        position += contracts
    return fees, vouchers, opened_at if position else None


def reported_commission(
    commission: float,
    *,
    notional: float | None = None,
    effective_rate: float | None = None,
    gst_pct: float = 18.0,
) -> float:
    """A fill's commission as Delta reports it, with GST included.

    Delta reports a fill's ``commission`` and its ``effective_commission_rate``
    but does not say whether GST is inside the figure. When the rate and the
    notional are known, whichever reading the figure matches is taken; when it
    matches neither, or they are unknown, the figure is taken as it stands.
    """
    commission = abs(float(commission))
    if not notional or effective_rate is None or effective_rate <= 0:
        return commission
    base = abs(float(notional)) * float(effective_rate)
    if base <= 0:
        return commission
    with_gst = base * (1 + gst_pct / 100)
    tolerance = 0.02
    if abs(commission - base) <= tolerance * base:
        return commission * (1 + gst_pct / 100)
    if abs(commission - with_gst) <= tolerance * with_gst:
        return commission
    return commission
