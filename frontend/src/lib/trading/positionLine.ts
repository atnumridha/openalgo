/**
 * The open position's line on the chart: what it is valued at and what its
 * label says.
 *
 * **A crypto contract is not one coin.** Delta Exchange quotes BTCUSD per BTC
 * and trades it in contracts of 0.001 BTC (ETHUSD 0.01, SOLUSD 1), and the
 * position book carries that as `lot_size`. Multiplying the price move by the
 * contract count alone reports a thousand times the real P&L on BTCUSD.
 * Indian exchanges report quantity in units already, so the multiplier is
 * applied to CRYPTO only.
 *
 * **It is the Positions page's figure, not a second opinion.** Crypto is
 * valued at the exchange's mark price, the price Delta marks unrealised P&L
 * to, and the net figure comes from the same `positionFees` the Positions page
 * and the navbar badge use.
 */
import { DEFAULT_FEE_PROFILE, type FeeProfile, positionFees } from '@/lib/cryptoFees'
import { money } from './format'

/** One position book row, reduced to what the line needs. */
export interface PositionMark {
  symbol: string
  exchange: string
  /** Signed contract count: positive is long. */
  net: number
  avg: number
  product: string
  /** Underlying per contract on CRYPTO; 1 everywhere else. */
  contractValue: number
  /** The exchange's mark price at the last poll, when it sent one. */
  markPrice: number | null
  feesPaid?: number
  funding?: number
  openedAt?: string
}

export function isCryptoExchange(exchange: string): boolean {
  return exchange === 'CRYPTO'
}

function num(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/** The row as a position, or null when it is missing or flat. */
export function positionFromRow(row: Record<string, unknown> | undefined): PositionMark | null {
  if (!row) return null
  const net = num(row.quantity)
  if (net === 0) return null
  const exchange = String(row.exchange ?? '')
  const lot = num(row.lot_size)
  const mark = num(row.mark_price)
  return {
    symbol: String(row.symbol ?? ''),
    exchange,
    net,
    avg: num(row.average_price),
    product: String(row.product ?? ''),
    contractValue: isCryptoExchange(exchange) && lot > 0 ? lot : 1,
    markPrice: mark > 0 ? mark : null,
    feesPaid: typeof row.fees_paid === 'number' ? row.fees_paid : undefined,
    funding: typeof row.funding === 'number' ? row.funding : undefined,
    openedAt: typeof row.opened_at === 'string' ? row.opened_at : undefined,
  }
}

/** The price the position is valued at: the mark price on CRYPTO, else the last trade. */
export function valuationPrice(position: PositionMark, lastLtp: number | null): number {
  if (isCryptoExchange(position.exchange) && position.markPrice != null) return position.markPrice
  return lastLtp ?? position.avg
}

/** Price P&L before any fee, signed: positive is in the trader's favour. */
export function grossPnl(position: PositionMark, price: number): number {
  return (price - position.avg) * position.net * position.contractValue
}

/** P&L after every fee paid and still due, and funding, as the Positions page states it. */
export function netPnl(
  position: PositionMark,
  price: number,
  profile: FeeProfile = DEFAULT_FEE_PROFILE,
  now: number = Date.now()
): number {
  return positionFees(
    {
      symbol: position.symbol,
      quantity: position.net,
      average_price: position.avg,
      mark_price: price,
      ltp: price,
      pnl: grossPnl(position, price),
      lot_size: position.contractValue,
      fees_paid: position.feesPaid,
      funding: position.funding,
      opened_at: position.openedAt,
    },
    profile,
    {},
    now
  ).net
}

function usd(n: number): string {
  const [ip, fp] = Math.abs(n).toFixed(2).split('.')
  return `${ip.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fp}`
}

const signed = (n: number, symbol: string, amount: (v: number) => string) =>
  `${n >= 0 ? '+' : '-'}${symbol}${amount(n)}`

/**
 * The text beside the LONG or SHORT badge.
 *
 * Crypto shows both figures, each named, because the gap between them is the
 * round trip of fees and on a small move it is the whole of the answer.
 */
export function positionLabel(
  position: PositionMark,
  lastLtp: number | null,
  fmt: (n: number) => string,
  profile: FeeProfile | null = DEFAULT_FEE_PROFILE,
  now: number = Date.now(),
  displayMoney?: (value: number) => string
): string {
  const price = valuationPrice(position, lastLtp)
  const gross = grossPnl(position, price)
  if (!isCryptoExchange(position.exchange)) {
    return `@ ${fmt(position.avg)}  ${signed(gross, '₹', money)}`
  }
  const net = profile ? netPnl(position, price, profile, now) : null
  const show = displayMoney
    ? (n: number) => `${n >= 0 ? '+' : ''}${displayMoney(n)}`
    : (n: number) => signed(n, '$', usd)
  return `@ ${fmt(position.avg)}  Net ${net == null ? 'unavailable' : show(net)}  Gross ${show(gross)}`
}
