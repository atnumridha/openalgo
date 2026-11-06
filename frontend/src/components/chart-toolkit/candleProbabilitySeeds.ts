import rawSeeds from './candleProbabilitySeeds.json'
import type { CandleModel, CandleOptions } from './candleProbabilityTypes'

/** Evidence is never shared across instruments, venues, timeframes or session rules. */
export function getCandleSeed(
  scope: Pick<CandleOptions, 'symbol' | 'exchange' | 'seconds' | 'indian'>
): CandleModel | undefined {
  return (rawSeeds as CandleModel[]).find(
    (seed) =>
      seed.symbol === scope.symbol &&
      seed.exchange === scope.exchange &&
      seed.seconds === scope.seconds &&
      seed.indian === scope.indian
  )
}
