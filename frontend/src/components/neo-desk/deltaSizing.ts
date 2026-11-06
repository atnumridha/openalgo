import type { DeltaChartState } from '@/api/deltaChart'
export type BalanceFraction = 0.1 | 0.25 | 0.5 | 0.75 | 1
export function calculateDeltaContracts(
  sizing: DeltaChartState['sizing'],
  fraction: BalanceFraction,
  price: number,
  contractValue: number,
  leverage: number
): number | null {
  if (
    !sizing ||
    sizing.currency !== 'USD' ||
    typeof sizing.version !== 'string' ||
    !sizing.version ||
    !Number.isFinite(sizing.available_balance) ||
    sizing.available_balance < 0 ||
    !Number.isFinite(sizing.maker_fee_rate) ||
    sizing.maker_fee_rate < 0 ||
    sizing.maker_fee_rate > 1 ||
    !Number.isFinite(sizing.fee_tax_rate) ||
    sizing.fee_tax_rate < 0 ||
    sizing.fee_tax_rate > 1 ||
    ![0.1, 0.25, 0.5, 0.75, 1].includes(fraction) ||
    !Number.isFinite(price) ||
    price <= 0 ||
    !Number.isFinite(contractValue) ||
    contractValue <= 0 ||
    !Number.isInteger(leverage) ||
    leverage < 1 ||
    leverage > 200
  )
    return null
  const costPerContract =
    price * contractValue * (1 / leverage + sizing.maker_fee_rate * (1 + sizing.fee_tax_rate))
  const contracts = Math.floor((fraction * sizing.available_balance * 0.99) / costPerContract)
  return Number.isSafeInteger(contracts) && contracts >= 0 ? contracts : null
}

/** Uses standard fees even when a temporary fee waiver is available. */
export function scalpRiskLimitedContracts(lots: number | null, entry: number, stop: number,
  contractValue: number, sizing: DeltaChartState['sizing']): number | null {
  if (lots === null || !sizing || ![entry, stop, contractValue].every(n => Number.isFinite(n) && n > 0)
      || !Number.isFinite(sizing.taker_fee_rate) || sizing.taker_fee_rate! < 0) return null
  const perLot = (Math.abs(entry-stop) + (entry*sizing.maker_fee_rate + stop*sizing.taker_fee_rate!)*(1+sizing.fee_tax_rate))*contractValue*85
  return perLot > 0 ? Math.min(lots, Math.floor(20/perLot)) : null
}
