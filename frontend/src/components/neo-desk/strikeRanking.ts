export interface StrikeChoiceLeg {
  symbol?: string | null
  label?: string
  ltp?: number | null
  oi?: number | null
  volume?: number | null
  bid?: number | null
  ask?: number | null
  prev_close?: number | null
}
export interface StrikeChoiceRow {
  strike: number
  ce?: StrikeChoiceLeg | null
  pe?: StrikeChoiceLeg | null
}
const validActivity = (value: number | null | undefined): value is number =>
  value != null && Number.isFinite(value) && value >= 0

/** Only reported observations count; missing activity is not a zero-volume quote. */
export function totalStrikeActivity(row: StrikeChoiceRow, field: 'volume' | 'oi'): number | undefined {
  const values = [row.ce?.[field], row.pe?.[field]].filter(validActivity)
  return values.length ? values.reduce((sum, value) => sum + value, 0) : undefined
}

/** Same overall liquidity order in both menus; only absent contracts are excluded. */
export function rankOptionStrikes<T extends StrikeChoiceRow>(rows: T[], atm: number | undefined, side?: 'CE' | 'PE'): T[] {
  const metric = (row: T, field: 'volume' | 'oi') => totalStrikeActivity(row, field) ?? -1
  const distance = (row: T) => atm != null && Number.isFinite(atm) ? Math.abs(row.strike - atm) : 0
  return rows.filter(row => Number.isFinite(row.strike) && row.strike > 0 && (side ? (side === 'CE' ? row.ce : row.pe)?.symbol : row.ce?.symbol || row.pe?.symbol))
    .sort((a, b) => metric(b, 'volume') - metric(a, 'volume') || metric(b, 'oi') - metric(a, 'oi') || distance(a) - distance(b) || a.strike - b.strike)
}
const compact = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 2 })
export const strikeActivity = (value: number | null | undefined) => validActivity(value) ? compact.format(value) : '—'

const premium = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const strikePremium = (value: number | null | undefined) =>
  value != null && Number.isFinite(value) && value > 0 ? `₹${premium.format(value)}` : '—'

export const strikeSpread = (leg:StrikeChoiceLeg|null|undefined) => {
  const bid=leg?.bid,ask=leg?.ask
  return bid!=null && ask!=null && Number.isFinite(bid) && Number.isFinite(ask) && bid>0 && ask>=bid
    ? `${(100*(ask-bid)/((ask+bid)/2)).toFixed(2)}%` : '—'
}
