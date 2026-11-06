import type { BookInstrument } from '../book-pattern-guide/types'
import { STRATEGIES_51 } from './catalog'
import { DEFAULT_STRATEGY51_SETTINGS } from './settings'
import type { Strategy51Settings, SuppliedContext } from './types'
export const STRATEGY51_KEY = 'neo.strategy51-guide.v1'
const object = (v: unknown): Record<string, unknown> =>
  v != null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
const number = (v: unknown, base: number, min = 0, max = 1e12) =>
  typeof v === 'number' && Number.isFinite(v) && v >= min && v <= max ? v : base
export function normalizeStrategy51Settings(value: unknown): Strategy51Settings {
  const x = object(value),
    d = DEFAULT_STRATEGY51_SETTINGS,
    s = { ...d, supplied: [] } as Strategy51Settings
  s.selected =
    x.selected === 'auto' || STRATEGIES_51.some((z) => z.id === x.selected)
      ? (x.selected as string)
      : 'auto'
  for (const k of [
    'showPending',
    'showOtherSetups',
    'cleanChart',
    'fullHistory',
    'showTrendLines',
    'localTargets',
    'localStructures',
  ] as const)
    if (typeof x[k] === 'boolean') s[k] = x[k]
  for (const k of ['equity', 'fixedCost', 'perUnitCost', 'slippagePrice'] as const)
    s[k] = number(x[k], d[k])
  s.riskPercent = number(x.riskPercent, d.riskPercent, 0.001, 5)
  s.targetR = number(x.targetR, d.targetR, 0.25, 20)
  s.minRR = number(x.minRR, d.minRR, 0, 20)
  s.labelLookback = Math.floor(number(x.labelLookback, d.labelLookback, 1, 100))
  s.planExpiryBars = Math.floor(number(x.planExpiryBars, d.planExpiryBars, 1, 500))
  for (const k of ['voFast', 'voSlow', 'donchianPeriod', 'rangeBars'] as const)
    s[k] = Math.floor(number(x[k], d[k], 2, 200))
  s.supertrendMultiplier = number(x.supertrendMultiplier, d.supertrendMultiplier, 0.5, 10)
  s.squeezePercent = number(x.squeezePercent, d.squeezePercent, 0.01, 30)
  s.volumeFactor = number(x.volumeFactor, d.volumeFactor, 1, 10)
  s.touchATR = number(x.touchATR, d.touchATR, 0, 2)
  if (s.voSlow <= s.voFast) s.voSlow = Math.min(250, s.voFast + 5)
  const u = object(x.instrument)
  if (
    ['linear', 'inverse', 'nonlinear', 'index'].includes(String(u.kind)) &&
    ['underlying', 'contract', 'option-premium'].includes(String(u.unitDefinition))
  ) {
    s.instrument = {
      kind: u.kind as BookInstrument['kind'],
      unitDefinition: u.unitDefinition as BookInstrument['unitDefinition'],
    }
    for (const k of ['valuePerPriceUnit', 'conversionRate', 'quantityStep', 'lotSize'] as const)
      if (typeof u[k] === 'number' && Number.isFinite(u[k]) && u[k] > 0) s.instrument[k] = u[k]
    for (const k of ['accountCurrency', 'quoteCurrency'] as const)
      if (typeof u[k] === 'string' && /^[A-Z]{3,8}$/.test(u[k])) s.instrument[k] = u[k]
    if (u.chartPriceKind === 'underlying' || u.chartPriceKind === 'premium')
      s.instrument.chartPriceKind = u.chartPriceKind
    if (typeof x.instrumentScope === 'string' && x.instrumentScope.length < 120)
      s.instrumentScope = x.instrumentScope
  }
  if (Array.isArray(x.supplied))
    s.supplied = x.supplied.slice(-51).flatMap((raw) => {
      const z = object(raw)
      if (
        !STRATEGIES_51.some((d) => d.id === z.strategyId) ||
        !['elliott', 'gann', 'renko', 'sector', 'repo', 'gap-zone', 'risk'].includes(
          String(z.kind)
        ) ||
        typeof z.symbol !== 'string' ||
        z.symbol.length > 80 ||
        typeof z.description !== 'string' ||
        z.description.trim().length < 3 ||
        !['long', 'short'].includes(String(z.side)) ||
        !(number(z.asOf, 0) > 0) ||
        !(number(z.intervalSeconds, 0) > 0)
      )
        return []
      const item: SuppliedContext = {
        strategyId: String(z.strategyId),
        kind: z.kind as SuppliedContext['kind'],
        symbol: z.symbol,
        exchange: typeof z.exchange === 'string' ? z.exchange.slice(0, 20) : undefined,
        intervalSeconds: Number(z.intervalSeconds),
        asOf: Number(z.asOf),
        side: z.side as SuppliedContext['side'],
        description: z.description.slice(0, 1000),
      }
      for (const k of [
        'entry',
        'stop',
        'target',
        'zoneLow',
        'zoneHigh',
        'newRate',
        'previousRate',
        'touchCount',
        'nextSessionExitAt',
      ] as const)
        if (typeof z[k] === 'number' && Number.isFinite(z[k]) && z[k] >= 0) item[k] = z[k]
      item.liquidityConfirmed = z.liquidityConfirmed === true
      return [item]
    })
  return s
}
export function readStrategy51Preferences(): Strategy51Settings {
  try {
    const x = object(JSON.parse(localStorage.getItem(STRATEGY51_KEY) || 'null'))
    return normalizeStrategy51Settings(x.version === 1 ? x.settings : x)
  } catch {
    return normalizeStrategy51Settings({})
  }
}
export function saveStrategy51Preferences(s: Strategy51Settings) {
  try {
    localStorage.setItem(
      STRATEGY51_KEY,
      JSON.stringify({ version: 1, settings: normalizeStrategy51Settings(s) })
    )
  } catch {
    /* In-memory chart settings still work when storage is unavailable. */
  }
}
