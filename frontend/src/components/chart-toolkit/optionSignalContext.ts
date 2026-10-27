import { impliedVolatility, matchOptionSnapshot, type Bar } from './model'
import type { IndicatorState } from './nineIndicators'
import { expiryDate } from '@/lib/neoOptionSelection'

export function normalizeFeedExpiry(value: string): string {
  const raw = value.trim().toUpperCase()
  const named = /^(\d{1,2})[-\s]?([A-Z]{3})[-\s]?(\d{2}|\d{4})$/.exec(raw)
  let compact = named ? `${named[1].padStart(2, '0')}${named[2]}${named[3].slice(-2)}` : ''
  if (!compact && /^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const date = new Date(`${raw}T00:00:00Z`)
    if (Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === raw)
      compact = `${String(date.getUTCDate()).padStart(2, '0')}${['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'][date.getUTCMonth()]}${String(date.getUTCFullYear()).slice(-2)}`
  }
  return expiryDate(compact) ? compact : ''
}

export interface IVComparison {
  value: number
  previous: number
  time: number
}
export interface OptionSignalSnapshot {
  identity: string
  observedAt: number
  expiry?: number
  pcr: number | null
  pcrObservedAt?: number
  ceIV: IVComparison | null
  peIV: IVComparison | null
  future: { symbol: string; price: number; oi: number } | null
  futureObservedAt?: number
}
export function volumePCR(
  chain: Array<{ ce: { volume?: number } | null; pe: { volume?: number } | null }>
): number | null {
  let calls = 0,
    puts = 0
  if (!chain.length) return null
  for (const row of chain) {
    for (const leg of [row.ce, row.pe]) {
      if (leg && (!Number.isFinite(leg.volume) || leg.volume! < 0)) return null
    }
    calls += row.ce?.volume ?? 0
    puts += row.pe?.volume ?? 0
  }
  return calls > 0 && puts > 0 ? puts / calls : null
}
// IV is percent, using explicit zero rate/yield assumptions and matched closes.
export function ivComparison(
  option: Bar[],
  spot: Bar[],
  expiry: number,
  strike: number,
  call: boolean,
  asOf: number
): IVComparison | null {
  if (!(expiry > asOf && strike > 0)) return null
  const latest = matchOptionSnapshot(option, spot, asOf)
  if (!latest?.fresh) return null
  const previous = matchOptionSnapshot(
    option.filter((b) => b.time < latest.time),
    spot,
    latest.time
  )
  if (!previous || latest.time - previous.time !== 60) return null
  const calculate = (s: typeof latest) =>
    impliedVolatility(s.premium, s.spot, strike, (expiry - s.time - 60) / 31536000, 0, 0, call)
  const value = calculate(latest),
    priorValue = calculate(previous)
  return value != null && priorValue != null && value > 0 && priorValue > 0
    ? { value, previous: priorValue, time: latest.time + 60 }
    : null
}

export function optionContextStates(
  current: OptionSignalSnapshot | undefined,
  previous: OptionSignalSnapshot | undefined,
  expectedIdentity: string,
  now: number
): IndicatorState[] {
  const states: IndicatorState[] = (['iv', 'pcr', 'oi'] as const).map((key) => ({
    key,
    value: null,
    side: 'WAIT',
    time: null,
    reason: key === 'oi' ? 'Waiting for fresh futures data' : 'Waiting for fresh option data',
  }))
  if (
    !current ||
    current.identity !== expectedIdentity ||
    !Number.isFinite(now) ||
    !Number.isFinite(current.observedAt) ||
    current.observedAt > now ||
    now - current.observedAt > 90
  )
    return states
  const [iv, pcr, oi] = states
  const fresh = (time: number | undefined): time is number =>
    time != null && Number.isFinite(time) && time <= now && now - time <= 90
  const pcrObservedAt = current.pcrObservedAt ?? current.observedAt,
    futureObservedAt = current.futureObservedAt ?? current.observedAt,
    priorFutureObservedAt = previous?.futureObservedAt ?? previous?.observedAt
  if (current.expiry != null && Number.isFinite(current.expiry) && current.expiry > now) {
    const freshIV = (leg: IVComparison | null): leg is IVComparison =>
      leg != null &&
      [leg.value, leg.previous, leg.time].every(Number.isFinite) &&
      leg.value > 0 &&
      leg.previous > 0 &&
      now - leg.time >= 0 &&
      now - leg.time <= 90
    const ce = current.ceIV,
      pe = current.peIV
    if (freshIV(ce) && freshIV(pe) && ce.time === pe.time) {
      const ceFalling = ce.value < ce.previous - 1e-6,
        peFalling = pe.value < pe.previous - 1e-6
      iv.side = ceFalling === peFalling ? 'WAIT' : ceFalling ? 'CALL' : 'PUT'
      const chosenIV = iv.side === 'PUT' ? pe : ce
      iv.value = chosenIV.value
      iv.time = chosenIV.time
      iv.reason = `App-defined standalone falling-IV pricing comparison, not an established direction signal: CE IV ${ceFalling ? 'falling' : 'not falling'}; PE IV ${peFalling ? 'falling' : 'not falling'}; ${ceFalling === peFalling ? 'both or neither qualify: WAIT; ' : ''}BSM rate/yield 0%`
    } else {
      iv.reason =
        'Standalone IV unavailable: needs fresh valid CE IV and PE IV comparisons for the same completed minutes'
    }
    if (
      fresh(pcrObservedAt) &&
      current.pcr != null &&
      Number.isFinite(current.pcr) &&
      current.pcr > 0
    ) {
      pcr.value = current.pcr
      pcr.time = pcrObservedAt
      pcr.side = current.pcr < 1 ? 'CALL' : current.pcr > 1 ? 'PUT' : 'WAIT'
      pcr.reason =
        'Standalone expiry-window put/call volume ratio: below 1 CALL; above 1 PUT; 1 WAIT'
    }
  } else {
    iv.reason = 'Standalone IV unavailable: option expiry is missing or expired'
    pcr.reason = 'Standalone PCR unavailable: option expiry is missing or expired'
  }
  const f = current.future,
    prior = previous?.future
  if (
    fresh(futureObservedAt) &&
    f &&
    Number.isFinite(f.oi) &&
    f.oi > 0 &&
    Number.isFinite(f.price) &&
    f.price > 0
  ) {
    oi.value = f.oi
    oi.time = futureObservedAt
    oi.reason = `${f.symbol}: needs two fresh observations, increasing OI and a futures price move`
    if (
      previous?.identity === current.identity &&
      prior?.symbol === f.symbol &&
      Number.isFinite(prior.oi) &&
      Number.isFinite(prior.price) &&
      prior.oi > 0 &&
      prior.price > 0 &&
      fresh(priorFutureObservedAt) &&
      priorFutureObservedAt < futureObservedAt &&
      futureObservedAt - priorFutureObservedAt <= 90 &&
      f.oi > prior.oi
    ) {
      oi.side = f.price > prior.price ? 'CALL' : f.price < prior.price ? 'PUT' : 'WAIT'
      oi.reason = `${f.symbol}: futures OI increasing with price ${f.price > prior.price ? 'rising' : f.price < prior.price ? 'falling' : 'unchanged'} (observed snapshots)`
    }
  }
  return states
}
