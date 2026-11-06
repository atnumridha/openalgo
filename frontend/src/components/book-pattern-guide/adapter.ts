import type { BookBar, BookContext, BookInstrument } from './engine'
export interface BookSession {
  start: number
  end: number
  offset: number
}
/** Input is already UTC from chartBars(). Never apply the raw API's display shift here. */
export function bookChartBars(
  bars: readonly (Omit<BookBar, 'volume'> & { volume?: number })[],
  seconds: number,
  session?: BookSession | null
): BookBar[] {
  return bars.map((b) => {
    if (!session) return { ...b, volume: b.volume ?? 0 }
    const midnight = Math.floor((b.time + session.offset) / 86400) * 86400 - session.offset
    const closeTime =
      seconds >= 86400
        ? midnight + session.end * 60
        : Math.min(b.time + seconds, midnight + session.end * 60)
    return { ...b, volume: b.volume ?? 0, closeTime }
  })
}
export function validatedBookInstrument(
  input: Partial<BookInstrument>,
  identity?: { symbol: string; exchange: string }
): BookInstrument | undefined {
  if (!input.kind || !input.unitDefinition) return undefined
  const premium =
    identity && ['NFO', 'BFO'].includes(identity.exchange) && /(?:CE|PE)$/.test(identity.symbol)
  return {
    ...input,
    kind: identity?.exchange.endsWith('_INDEX') ? 'index' : input.kind,
    unitDefinition: input.unitDefinition,
    ...(identity
      ? { chartPriceKind: premium ? ('premium' as const) : ('underlying' as const) }
      : {}),
  }
}
/** Session schedule only; the host does not provide an exchange holiday calendar. Unknown stays open. */
export function bookChartContext(
  input: Omit<BookContext, 'marketOpen' | 'chartType'> & {
    session?: BookSession | null
    historical?: boolean
    marketOpen?: boolean
    chartType?: BookContext['chartType']
  }
): BookContext {
  const { session, historical, ...context } = input
  const local = input.now + (session?.offset ?? 0),
    day = new Date(local * 1000).getUTCDay(),
    minute = (((local % 86400) + 86400) % 86400) / 60
  const scheduled = session
    ? day !== 0 && day !== 6 && minute >= session.start && minute < session.end
    : true
  return {
    ...context,
    marketOpen: historical ? false : (input.marketOpen ?? scheduled),
    chartType: input.chartType ?? 'standard',
  }
}
