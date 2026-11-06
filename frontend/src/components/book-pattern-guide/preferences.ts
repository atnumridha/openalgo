import {
  DEFAULT_BOOK_SETTINGS,
  resolveBookSettings,
  type BookInstrument,
  type BookSettings,
} from './engine'
export const BOOK_PREFERENCES_KEY = 'neo.book-pattern-risk-guide.v1'
export interface BookPreferences {
  settings: BookSettings
  instrument: Partial<BookInstrument>
  instrumentScope?: string
}
export function normalizeBookPreferences(value?: Partial<BookPreferences>): BookPreferences {
  const input: Partial<BookSettings> = {}
  const source = value?.settings
  for (const key of Object.keys(DEFAULT_BOOK_SETTINGS) as (keyof BookSettings)[]) {
    const v = source?.[key],
      d = DEFAULT_BOOK_SETTINGS[key]
    if (typeof v === typeof d && (typeof v !== 'number' || Number.isFinite(v)))
      (input as Record<string, unknown>)[key] = v
  }
  if (Array.isArray(source?.disabledPatterns))
    input.disabledPatterns = source.disabledPatterns.filter((v) => typeof v === 'string')
  else input.disabledPatterns = []
  const settings = resolveBookSettings(input)
  settings.maxDrawings = Math.min(40, settings.maxDrawings)
  settings.maxPolylines = Math.min(80, settings.maxPolylines)
  settings.maxLabels = Math.min(160, settings.maxLabels)
  settings.maxLines = Math.min(120, settings.maxLines)
  const instrument: Partial<BookInstrument> = {},
    raw = value?.instrument
  if (raw && ['linear', 'inverse', 'nonlinear', 'index'].includes(raw.kind ?? '')) {
    instrument.kind = raw.kind
    if (['underlying', 'contract', 'option-premium'].includes(raw.unitDefinition ?? ''))
      instrument.unitDefinition = raw.unitDefinition
    for (const k of ['valuePerPriceUnit', 'quantityStep', 'lotSize', 'conversionRate'] as const)
      if (typeof raw[k] === 'number' && Number.isFinite(raw[k]) && raw[k]! > 0)
        instrument[k] = raw[k]
    for (const k of ['accountCurrency', 'quoteCurrency'] as const)
      if (typeof raw[k] === 'string') instrument[k] = raw[k]!.trim().toUpperCase().slice(0, 12)
    if (raw.chartPriceKind === 'premium' || raw.chartPriceKind === 'underlying')
      instrument.chartPriceKind = raw.chartPriceKind
  }
  return {
    settings,
    instrument,
    instrumentScope: typeof value?.instrumentScope === 'string' ? value.instrumentScope : undefined,
  }
}
export function readBookPreferences(): BookPreferences {
  try {
    return normalizeBookPreferences(
      JSON.parse(localStorage.getItem(BOOK_PREFERENCES_KEY) || 'null') ?? undefined
    )
  } catch {
    return normalizeBookPreferences()
  }
}
export function saveBookPreferences(p: BookPreferences): void {
  try {
    localStorage.setItem(BOOK_PREFERENCES_KEY, JSON.stringify(normalizeBookPreferences(p)))
  } catch {
    /* Keep the current chart settings when storage is unavailable. */
  }
}

/** Manually verified units apply only to their original instrument identity. */
export function bookInstrumentForScope(p: BookPreferences, scope: string): Partial<BookInstrument> {
  return p.instrumentScope === scope ? p.instrument : {}
}
