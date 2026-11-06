/** Screenshot-derived descriptions, not executable strategy definitions. */
export interface SourceStrategy {
  id: string
  name: string
  underlying: 'NIFTY' | 'BANKNIFTY'
  instrument: 'options' | 'future'
  sourceParameters: string
  unconfigured: readonly string[]
  sourceClaim: { minimumCapitalInr: number; maximumDrawdownPercent: number }
}
const optionMissing = [
  'Option side and direction',
  'Listed expiry',
  'Exact contracts and ratios',
  'Entry and exit rules',
]
const futureMissing = [
  'Direction',
  'Listed futures contract and expiry',
  'Entry and exit rules',
  'Session eligibility verification',
]
export const SOURCE_STRATEGIES: readonly SourceStrategy[] = [
  {
    id: 'A-01',
    name: 'Nifty Alpha Edge',
    underlying: 'NIFTY',
    instrument: 'options',
    sourceParameters:
      'Weekly ATM credit spread; 200-point protective wing. Source illustration: bullish payoff with capped loss.',
    unconfigured: optionMissing,
    sourceClaim: { minimumCapitalInr: 60000, maximumDrawdownPercent: 20 },
  },
  {
    id: 'A-02',
    name: 'Nifty Alpha Wing',
    underlying: 'NIFTY',
    instrument: 'options',
    sourceParameters:
      'Weekly unequal-wing butterfly; small entry cost; directional lean toward sold strikes; capped loss.',
    unconfigured: [...optionMissing, 'Wing distances and entry cost'],
    sourceClaim: { minimumCapitalInr: 120000, maximumDrawdownPercent: 20 },
  },
  {
    id: 'A-03',
    name: 'Nifty Alpha Ladder',
    underlying: 'NIFTY',
    instrument: 'options',
    sourceParameters:
      'Buy ATM; sell a larger block 200 points out; cap with a far wing. Illustrated payoff peaks at the sold strike and drops to a flat right tail.',
    unconfigured: [...optionMissing, 'Far-wing distance'],
    sourceClaim: { minimumCapitalInr: 250000, maximumDrawdownPercent: 20 },
  },
  {
    id: 'A-04',
    name: 'Nifty Alpha Ladder Plus',
    underlying: 'NIFTY',
    instrument: 'options',
    sourceParameters:
      'Ladder plus extra far-wing buying; net-long favorable tail. Source describes defined downside and open favorable upside.',
    unconfigured: [...optionMissing, 'Far-wing distance and extra buying quantity'],
    sourceClaim: { minimumCapitalInr: 250000, maximumDrawdownPercent: 20 },
  },
  {
    id: 'A-05',
    name: 'Nifty Thunderbolt',
    underlying: 'NIFTY',
    instrument: 'options',
    sourceParameters:
      'Intraday 1×2 directional ratio; bounded loss and convex favorable tail. Illustration suggests short 1 / buy 2 backspread; exact orientation is unverified.',
    unconfigured: [...optionMissing, 'Ratio orientation verification'],
    sourceClaim: { minimumCapitalInr: 60000, maximumDrawdownPercent: 25 },
  },
  {
    id: 'A-06',
    name: 'Titan Naked Strike',
    underlying: 'NIFTY',
    instrument: 'future',
    sourceParameters:
      'Directional NIFTY FUT on the Tuesday-expiry session; automated 200-point intraday stop trigger described by source. Verify the actual listed expiry and session.',
    unconfigured: futureMissing,
    sourceClaim: { minimumCapitalInr: 250000, maximumDrawdownPercent: 30 },
  },
  {
    id: 'A-07',
    name: 'Titan Naked Blitz · BankNifty',
    underlying: 'BANKNIFTY',
    instrument: 'future',
    sourceParameters:
      'Directional BANKNIFTY FUT Monday and Tuesday; 200-point stop per session described by source. Verify current session eligibility.',
    unconfigured: futureMissing,
    sourceClaim: { minimumCapitalInr: 250000, maximumDrawdownPercent: 30 },
  },
]
export function strategyCompatibility(strategy: SourceStrategy, symbol: string, exchange: string) {
  const normalized = symbol.trim().toUpperCase()
  const venue = exchange.trim().toUpperCase()
  if (venue === 'NSE_INDEX' && normalized === strategy.underlying) {
    return {
      compatible: true,
      kind: 'index-context' as const,
      reason: `${strategy.underlying} index context only; select the actual listed contracts separately.`,
    }
  }
  // Match the app's explicit dated futures symbol, never an option premium or loose prefix.
  if (
    venue === 'NFO' &&
    new RegExp(`^${strategy.underlying}\\d{2}[A-Z]{3}\\d{2}FUT$`).test(normalized)
  ) {
    return {
      compatible: true,
      kind: 'future' as const,
      reason:
        strategy.instrument === 'future'
          ? 'Matching futures price units; contract/session eligibility still needs verification.'
          : 'Underlying futures context only; option contracts and premium risk remain unconfigured.',
    }
  }
  return {
    compatible: false,
    kind: 'incompatible' as const,
    reason: `Requires ${strategy.underlying} index or matching NFO futures context. This chart has different instrument or price units.`,
  }
}
export function proposedFutureTrigger({
  strategy,
  symbol,
  exchange,
  entry,
  direction,
  tickSize,
}: {
  strategy: SourceStrategy
  symbol: string
  exchange: string
  entry: number
  direction: '' | 'long' | 'short'
  tickSize?: number
}): number | null {
  if (
    strategy.instrument !== 'future' ||
    strategyCompatibility(strategy, symbol, exchange).kind !== 'future' ||
    !['long', 'short'].includes(direction) ||
    !Number.isFinite(entry) ||
    entry <= 0 ||
    !tickSize ||
    !Number.isFinite(tickSize) ||
    tickSize <= 0
  )
    return null
  const trigger = entry + (direction === 'long' ? -200 : 200)
  const aligned = (price: number) =>
    Math.abs(price / tickSize - Math.round(price / tickSize)) < 1e-6
  if (trigger <= 0 || !aligned(entry) || !aligned(trigger)) return null
  return Number(trigger.toFixed(10))
}
export interface StrategyConfiguration {
  selectedId: string
  entry: string
  direction: '' | 'long' | 'short'
  notes: string
  anchor?: string
  expiry?: string
  legs?: StrategyLeg[]
}
const emptyConfiguration = (): StrategyConfiguration => ({
  selectedId: '',
  entry: '',
  direction: '',
  notes: '',
})
export function strategyStorageKey(scope: {
  owner?: string
  broker?: string | null
  appMode: string
  symbol: string
  exchange: string
  interval: string
}): string | null {
  if (!scope.owner?.trim()) return null
  return `neo-source-strategy:v1:${JSON.stringify([scope.owner, scope.broker ?? '', scope.appMode, scope.exchange, scope.symbol, scope.interval])}`
}
export function readStrategyConfiguration(
  storage: Pick<Storage, 'getItem'>,
  key: string | null
): StrategyConfiguration {
  if (!key) return emptyConfiguration()
  try {
    const value: unknown = JSON.parse(storage.getItem(key) ?? 'null')
    if (!value || typeof value !== 'object') return emptyConfiguration()
    const data = value as Partial<StrategyConfiguration>
    if (
      !SOURCE_STRATEGIES.some((s) => s.id === data.selectedId) ||
      typeof data.entry !== 'string' ||
      typeof data.notes !== 'string' ||
      !['', 'long', 'short'].includes(data.direction ?? 'invalid')
    )
      return emptyConfiguration()
    return {
      selectedId: data.selectedId!,
      entry: data.entry.slice(0, 40),
      direction: data.direction!,
      notes: data.notes.slice(0, 4000),
      ...(boundedDraftText(data.anchor, 40) ? { anchor: data.anchor } : {}),
      ...(boundedDraftText(data.expiry, 80) ? { expiry: data.expiry } : {}),
      ...(Array.isArray(data.legs) && data.legs.length <= 6 && data.legs.every(isStrategyLeg)
        ? {
            legs: data.legs.map((leg) => ({
              optionType: leg.optionType,
              offset: leg.offset,
              quantity: leg.quantity,
              premium: leg.premium,
            })),
          }
        : {}),
    }
  } catch {
    return emptyConfiguration()
  }
}
export function saveStrategyConfiguration(
  storage: Pick<Storage, 'setItem'>,
  key: string | null,
  configuration: StrategyConfiguration
): boolean {
  if (!key) return false
  try {
    storage.setItem(key, JSON.stringify(configuration))
    return true
  } catch {
    return false
  }
}

export interface StrategyLeg {
  optionType: 'CE' | 'PE'
  /** Proposed strike offset from the explicit underlying anchor, in price points. */
  offset: string
  /** Signed ratio quantity: positive buys, negative sells. Not a lot count or sizing advice. */
  quantity: string
  premium: string
}
export interface StrategyReference {
  price: number
  title: string
  color: string
}
export interface OptionStructurePreview {
  points: { price: number; value: number }[]
  includesPremiums: boolean
  reason: string
  strikes: { price: number; quantity: number; optionType: 'CE' | 'PE' }[]
}
function boundedDraftText(value: unknown, limit: number): value is string {
  return typeof value === 'string' && value.length <= limit
}
function isStrategyLeg(value: unknown): value is StrategyLeg {
  if (!value || typeof value !== 'object') return false
  const leg = value as Partial<StrategyLeg>
  return (
    (leg.optionType === 'CE' || leg.optionType === 'PE') &&
    boundedDraftText(leg.offset, 40) &&
    boundedDraftText(leg.quantity, 40) &&
    boundedDraftText(leg.premium, 40)
  )
}
/** Editable illustrative proposals only. Missing source details are not reconstructed or verified. */
export function proposedOptionLegs(id: string): StrategyLeg[] {
  const leg = (optionType: 'CE' | 'PE', offset: number, quantity: number): StrategyLeg => ({
    optionType,
    offset: String(offset),
    quantity: String(quantity),
    premium: '',
  })
  switch (id) {
    case 'A-01':
      return [leg('PE', 0, -1), leg('PE', -200, 1)]
    case 'A-02':
      return [leg('CE', -200, 1), leg('CE', 0, -2), leg('CE', 300, 1)]
    case 'A-03':
      return [leg('CE', 0, 1), leg('CE', 200, -2), leg('CE', 400, 1)]
    case 'A-04':
      return [leg('CE', 0, 1), leg('CE', 200, -2), leg('CE', 400, 2)]
    case 'A-05':
      return [leg('CE', 0, -1), leg('CE', 200, 2)]
    default:
      return []
  }
}
/** Blank is never silently treated as a supplied zero price or premium. */
function explicitNumber(value: unknown): number | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
export function optionStructurePreview(
  strategy: SourceStrategy,
  config: StrategyConfiguration
): OptionStructurePreview {
  const invalid = (reason: string): OptionStructurePreview => ({
    points: [],
    includesPremiums: false,
    reason,
    strikes: [],
  })
  if (strategy.instrument !== 'options')
    return invalid('Select an option template to preview proposed option exposure.')
  const anchor = explicitNumber(config.anchor)
  if (anchor === null || anchor <= 0)
    return invalid(
      'Supply an explicit positive underlying anchor in index or matching futures price points.'
    )
  if (
    !Array.isArray(config.legs) ||
    config.legs.length < 1 ||
    config.legs.length > 6 ||
    !config.legs.every(isStrategyLeg)
  )
    return invalid('Supply 1–6 editable proposed CE or PE legs with bounded text fields.')
  const strikes: OptionStructurePreview['strikes'] = []
  const premiums: (number | null)[] = []
  for (const leg of config.legs) {
    const offset = explicitNumber(leg.offset),
      quantity = explicitNumber(leg.quantity)
    if (
      offset === null ||
      quantity === null ||
      !Number.isInteger(quantity) ||
      quantity === 0 ||
      Math.abs(quantity) > 10
    )
      return invalid(
        'Every leg needs a finite explicit offset and a nonzero integer signed quantity between −10 and 10.'
      )
    const price = anchor + offset
    if (!Number.isFinite(price) || price <= 0)
      return invalid(
        'Every proposed strike must be finite and positive after adding its offset to the anchor.'
      )
    strikes.push({ price, quantity, optionType: leg.optionType })
    premiums.push(explicitNumber(leg.premium))
  }
  const includesPremiums = premiums.every((premium) => premium !== null && premium >= 0)
  const prices = strikes.map((strike) => strike.price)
  const minimum = Math.min(...prices),
    maximum = Math.max(...prices)
  const padding = Math.max(200, maximum - minimum)
  const lower = Math.max(minimum / 2, minimum - padding),
    upper = maximum + padding
  if (!Number.isFinite(upper) || upper <= lower)
    return invalid('The proposed strike range is too large to preview safely.')
  // At most 73 regular samples + six exact strikes + the explicit anchor = 80 points.
  const samples = [
    ...Array.from({ length: 73 }, (_, index) => lower + (upper - lower) * (index / 72)),
    ...prices,
    anchor,
  ]
  const points = [...new Set(samples)]
    .sort((a, b) => a - b)
    .map((price) => ({
      price,
      value: strikes.reduce((total, strike, index) => {
        const intrinsic = Math.max(
          strike.optionType === 'CE' ? price - strike.price : strike.price - price,
          0
        )
        return total + strike.quantity * (intrinsic - (includesPremiums ? premiums[index]! : 0))
      }, 0),
    }))
  if (points.some((point) => !Number.isFinite(point.price) || !Number.isFinite(point.value)))
    return invalid('The proposed exposure exceeds the finite numeric preview range.')
  return {
    points,
    includesPremiums,
    strikes,
    reason: includesPremiums
      ? 'Proposed expiry payoff in ratio-weighted price points using every supplied premium; excludes fees, lot sizing and rupee P&L. Contracts and expiry remain unverified.'
      : 'Intrinsic exposure only in ratio-weighted price points: premiums are incomplete or invalid, so no premiums are included. This is not net profit; proposed contracts and expiry remain unverified.',
  }
}
export function strategyReferenceLevels({
  strategy,
  configuration,
  symbol,
  exchange,
  tickSize,
}: {
  strategy: SourceStrategy
  configuration: StrategyConfiguration
  symbol: string
  exchange: string
  tickSize?: number
}): StrategyReference[] {
  const compatibility = strategyCompatibility(strategy, symbol, exchange)
  if (!compatibility.compatible) return []
  if (strategy.instrument === 'future') {
    const entry = explicitNumber(configuration.entry)
    if (entry === null) return []
    const stop = proposedFutureTrigger({
      strategy,
      symbol,
      exchange,
      tickSize,
      entry,
      direction: configuration.direction,
    })
    if (stop === null) return []
    return [
      { price: entry, title: 'Entry reference', color: '#3b82f6' },
      { price: stop, title: '200-point stop reference', color: '#ef4444' },
    ]
  }
  return optionStructurePreview(strategy, configuration).strikes.map((strike) => ({
    price: strike.price,
    title: `Proposed ${strike.optionType} strike · ${strike.quantity > 0 ? '+' : ''}${strike.quantity} ratio`,
    color: strike.quantity > 0 ? '#8b5cf6' : '#f59e0b',
  }))
}

/** An option chart can configure its underlying structure, but its premium axis cannot carry strike guides. */
export function optionChartReference(
  strategy: SourceStrategy,
  symbol: string,
  exchange: string
): { strike: number; expiry: string } | null {
  if (strategy.instrument !== 'options' || exchange.trim().toUpperCase() !== 'NFO') return null
  const match = new RegExp(
    `^${strategy.underlying}(\\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\\d{2})(\\d+(?:\\.\\d+)?)(CE|PE)$`
  ).exec(symbol.trim().toUpperCase())
  if (!match) return null
  const month = [
    'JAN',
    'FEB',
    'MAR',
    'APR',
    'MAY',
    'JUN',
    'JUL',
    'AUG',
    'SEP',
    'OCT',
    'NOV',
    'DEC',
  ].indexOf(match[2])
  const day = Number(match[1]),
    year = 2000 + Number(match[3]),
    date = new Date(Date.UTC(year, month, day)),
    strike = Number(match[4])
  if (
    date.getUTCDate() !== day ||
    date.getUTCMonth() !== month ||
    !Number.isFinite(strike) ||
    strike <= 0
  )
    return null
  return { strike, expiry: `${match[1]}${match[2]}${match[3]}` }
}
