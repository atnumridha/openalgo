/**
 * Delta Exchange India trading fees: the browser copy of services/crypto_fees.py.
 *
 * Both are tested against test/crypto_fees/vectors.json, so a rule changed in
 * one and not the other fails a test rather than showing two different net
 * P&L figures for one position. See the Python module for the schedule.
 */

export const FUTURES_TYPES = new Set(['perpetual_futures', 'futures'])
export const PREMIUM_TYPES = new Set([
  'call_options',
  'put_options',
  'move_options',
  'options_combos',
  'spreads',
  'turbo_call_options',
  'turbo_put_options',
])

const DEFAULT_RATES = {
  futures: { maker: 0.0002, taker: 0.0005 },
  premium: { maker: 0.0001, taker: 0.0001 },
  spot: { maker: 0.001, taker: 0.001 },
}

export type FeeRole = 'maker' | 'taker'

export interface FeeProfile {
  gst_pct: number
  scalper_offer: boolean
  scalper_minutes_major: number
  scalper_minutes_other: number
  scalper_majors: string[]
  scalper_excluded: string[]
  diwali_offer: boolean
  diwali_symbols: string[]
  diwali_window_minutes: number
  voucher_monthly_cap: number
  premium_cap_pct: number
}

export const DEFAULT_FEE_PROFILE: FeeProfile = {
  gst_pct: 18,
  scalper_offer: true,
  scalper_minutes_major: 30,
  scalper_minutes_other: 15,
  scalper_majors: ['BTCUSD', 'ETHUSD'],
  scalper_excluded: ['PAXGUSD', 'SLVONUSD', 'XAUTUSD'],
  diwali_offer: false,
  diwali_symbols: ['BTCUSD'],
  diwali_window_minutes: 30,
  voucher_monthly_cap: 100,
  premium_cap_pct: 3.5,
}

export interface ContractFees {
  symbol: string
  contract_type?: string
  maker_rate?: number | null
  taker_rate?: number | null
}

export interface FillFee {
  fee: number
  gst: number
  total: number
  waived: boolean
  capped: boolean
}

export interface OpenPositionFees {
  entry_fee: number
  exit_fee_now: number
  exit_fee_after_window: number
  window_minutes: number | null
  window_remaining_minutes: number | null
  /** Fee Voucher closing now would earn. A credit, never part of a cash figure. */
  voucher_now: number
  voucher_window_remaining_minutes: number | null
}

export function withProfile(partial?: Partial<FeeProfile> | null): FeeProfile {
  return { ...DEFAULT_FEE_PROFILE, ...(partial ?? {}) }
}

export function contractRate(contract: ContractFees, role: FeeRole): number {
  const explicit = role === 'maker' ? contract.maker_rate : contract.taker_rate
  if (typeof explicit === 'number' && explicit >= 0) return explicit
  const type = contract.contract_type ?? 'perpetual_futures'
  const table = PREMIUM_TYPES.has(type)
    ? DEFAULT_RATES.premium
    : type === 'spot'
      ? DEFAULT_RATES.spot
      : DEFAULT_RATES.futures
  return table[role]
}

export function scalperWindowMinutes(contract: ContractFees, profile: FeeProfile): number | null {
  const type = contract.contract_type ?? 'perpetual_futures'
  if (!profile.scalper_offer || !FUTURES_TYPES.has(type)) return null
  const symbol = contract.symbol.toUpperCase()
  if (profile.scalper_excluded.includes(symbol)) return null
  return profile.scalper_majors.includes(symbol)
    ? profile.scalper_minutes_major
    : profile.scalper_minutes_other
}

export function voucherWindowMinutes(contract: ContractFees, profile: FeeProfile): number | null {
  if (!profile.diwali_offer || scalperWindowMinutes(contract, profile) === null) return null
  if (!profile.diwali_symbols.includes(contract.symbol.toUpperCase())) return null
  return profile.diwali_window_minutes
}

export function openingVoucher(
  contract: ContractFees,
  profile: FeeProfile,
  args: { opening_fee: number; held_minutes: number | null; earned_this_month?: number }
): number {
  const window = voucherWindowMinutes(contract, profile)
  if (window === null || args.held_minutes == null || args.held_minutes > window) return 0
  const room = Math.max(0, profile.voucher_monthly_cap - Math.max(0, args.earned_this_month ?? 0))
  return Math.min(Math.max(0, args.opening_fee), room)
}

export function openingFeeBeforeGst(feeWithGst: number, profile: FeeProfile): number {
  return Math.max(0, feeWithGst) / (1 + profile.gst_pct / 100)
}

export function fillFee(
  contract: ContractFees,
  profile: FeeProfile,
  args: {
    notional: number
    role?: FeeRole
    premium?: number | null
    closing?: boolean
    held_minutes?: number | null
  }
): FillFee {
  const notional = Math.abs(args.notional)
  const window = scalperWindowMinutes(contract, profile)
  if (args.closing && window !== null && args.held_minutes != null && args.held_minutes <= window) {
    return { fee: 0, gst: 0, total: 0, waived: true, capped: false }
  }
  let fee = notional * contractRate(contract, args.role ?? 'taker')
  let capped = false
  const type = contract.contract_type ?? 'perpetual_futures'
  if (PREMIUM_TYPES.has(type) && args.premium != null && args.premium > 0) {
    const cap = (Math.abs(args.premium) * profile.premium_cap_pct) / 100
    if (fee > cap) {
      fee = cap
      capped = true
    }
  }
  const gst = (fee * profile.gst_pct) / 100
  return { fee, gst, total: fee + gst, waived: false, capped }
}

export function openPositionFees(
  contract: ContractFees,
  profile: FeeProfile,
  args: {
    entry_notional: number
    exit_notional: number
    held_minutes: number
    entry_role?: FeeRole
    exit_role?: FeeRole
    entry_fee_paid?: number | null
    entry_premium?: number | null
    exit_premium?: number | null
    voucher_earned_this_month?: number
  }
): OpenPositionFees {
  const entryFee =
    args.entry_fee_paid == null
      ? fillFee(contract, profile, {
          notional: args.entry_notional,
          role: args.entry_role,
          premium: args.entry_premium,
        }).total
      : Math.max(0, args.entry_fee_paid)
  const window = scalperWindowMinutes(contract, profile)
  const now = fillFee(contract, profile, {
    notional: args.exit_notional,
    role: args.exit_role,
    premium: args.exit_premium,
    closing: true,
    held_minutes: args.held_minutes,
  }).total
  const after = fillFee(contract, profile, {
    notional: args.exit_notional,
    role: args.exit_role,
    premium: args.exit_premium,
  }).total
  const voucherWindow = voucherWindowMinutes(contract, profile)
  return {
    entry_fee: entryFee,
    exit_fee_now: now,
    exit_fee_after_window: after,
    window_minutes: window,
    window_remaining_minutes: window === null ? null : Math.max(0, window - args.held_minutes),
    voucher_now: openingVoucher(contract, profile, {
      opening_fee: openingFeeBeforeGst(entryFee, profile),
      held_minutes: args.held_minutes,
      earned_this_month: args.voucher_earned_this_month,
    }),
    voucher_window_remaining_minutes:
      voucherWindow === null ? null : Math.max(0, voucherWindow - args.held_minutes),
  }
}

export function netPnl(args: {
  gross: number
  fees_paid?: number
  exit_fee_due?: number
  funding?: number
}): number {
  return args.gross - (args.fees_paid ?? 0) - (args.exit_fee_due ?? 0) + (args.funding ?? 0)
}

/** What the Positions page needs about one crypto position's fees. */
export interface PositionFeeView {
  /** Fees on the fills so far, GST in: the exchange's figure when it sent one. */
  feesPaid: number
  /** Whether feesPaid is the exchange's own figure rather than an estimate. */
  feesReported: boolean
  /** Fee to close at the current price now (0 inside the Scalper Offer window). */
  exitFeeNow: number
  /** Fee to close once the window has passed. */
  exitFeeAfterWindow: number
  windowRemainingMinutes: number | null
  funding: number
  /** Fee Voucher closing now would earn (Diwali Scalper Offer). Not cash. */
  voucherNow: number
  voucherWindowRemainingMinutes: number | null
  /** Cash P&L after every fee paid and due, and funding. Vouchers are not in it. */
  net: number
  /** Price the position has to reach to break even after every fee, now. */
  breakEven: number | null
}

/**
 * A crypto position's fees and net P&L.
 *
 * ``pnl`` is the gross price P&L (realised plus unrealised). Fees paid come from
 * the exchange when it reported them, else they are estimated as one taker
 * opening fill. An open position also owes its closing fee, which is zero
 * while the Scalper Offer window is open.
 */
export function positionFees(
  position: {
    symbol: string
    quantity: number
    average_price: number
    ltp?: number
    mark_price?: number
    pnl: number
    lot_size?: number
    fees_paid?: number
    funding?: number
    opened_at?: string
  },
  profile: FeeProfile,
  contract: Omit<ContractFees, 'symbol'> = {},
  now: number = Date.now()
): PositionFeeView {
  const quantity = Number(position.quantity) || 0
  const open = quantity !== 0
  const contractValue = Number(position.lot_size) || 1
  const entry = Number(position.average_price) || 0
  const price =
    Number(position.mark_price) > 0 ? Number(position.mark_price) : Number(position.ltp) || entry
  const brSymbol = position.symbol.replace(/FUT$/, '')
  const terms: ContractFees = { symbol: brSymbol, ...contract }
  const openedMs = position.opened_at ? Date.parse(position.opened_at) : Number.NaN
  const timingKnown = Number.isFinite(openedMs) && openedMs <= now
  const heldMinutes = timingKnown ? (now - openedMs) / 60000 : Number.POSITIVE_INFINITY
  const reported = typeof position.fees_paid === 'number' && position.fees_paid > 0
  const entryNotional = Math.abs(quantity) * contractValue * entry
  const exitNotional = Math.abs(quantity) * contractValue * price
  const view = openPositionFees(terms, profile, {
    entry_notional: entryNotional,
    exit_notional: exitNotional,
    held_minutes: heldMinutes,
    entry_fee_paid: reported ? position.fees_paid : open ? null : 0,
  })
  const exitFeeNow = open ? view.exit_fee_now : 0
  const funding = Number(position.funding) || 0
  const net = netPnl({
    gross: Number(position.pnl) || 0,
    fees_paid: view.entry_fee,
    exit_fee_due: exitFeeNow,
    funding,
  })
  let breakEven: number | null = null
  if (open && entry > 0 && contractValue > 0) {
    const costs = view.entry_fee + exitFeeNow - funding
    const perUnit = costs / (Math.abs(quantity) * contractValue)
    breakEven = quantity > 0 ? entry + perUnit : entry - perUnit
  }
  return {
    feesPaid: view.entry_fee,
    feesReported: reported,
    exitFeeNow,
    exitFeeAfterWindow: open ? view.exit_fee_after_window : 0,
    windowRemainingMinutes: open && timingKnown ? view.window_remaining_minutes : null,
    funding,
    voucherNow: open ? view.voucher_now : 0,
    voucherWindowRemainingMinutes:
      open && timingKnown ? view.voucher_window_remaining_minutes : null,
    net,
    breakEven,
  }
}

/** The Positions page's Net P&L total: each row's cash after fees and funding, summed. */
export function totalNetAfterFees(
  positions: readonly Parameters<typeof positionFees>[0][],
  profile: FeeProfile,
  now: number = Date.now()
): number {
  return positions.reduce((sum, p) => sum + positionFees(p, profile, {}, now).net, 0)
}
