import { INDICATORS } from '../chart-toolkit/nineIndicators'

export const CHART_STUDIES = [
  ['strategies-51-guide', '51 strategies · live guide'],
  ['book-pattern-risk-guide', 'Book patterns & risk · single plan'],
  ['neo-toolkit', 'Option buying · RSI + MACD'],
  ['bb-chikou', 'BB + Chikou · BULL / BEAR'],
  ['video-strategy-guide', 'Video strategies · guidance'],
  ['candle-patterns', 'Candle patterns · BULL / BEAR'],
  ['candle-probability', 'Candlestick probability · 2R / 10 candles'],
  ['neo-donchian', 'Donchian / EMA'],
  ['neo-structure', 'Fair Value Gaps / levels'],
  ['ema-9-15', 'EMA 9 + EMA 15 + EMA 21'],
  ['fibonacci-pivots', 'Fibonacci pivots · previous day'],
  ['volume', 'Volume'],
  ['rsi', 'RSI 14'],
  ...INDICATORS.map((item) => [item.id, `${item.short} · CALL / PUT`] as const),
] as const

export function chartStudyLabel(id: string, label: string, crypto: boolean) {
  if (!crypto) return label
  if (id === 'neo-toolkit') return 'Trend setup · RSI + MACD'
  return label.replace('CALL / PUT', 'LONG / SHORT').replace('BULL / BEAR', 'LONG / SHORT')
}

const DELTA_STUDIES_KEY = 'neo.delta.chart.indicators'
const DELTA_DEFAULTS_VERSION = 'neo.delta.chart.volume-rsi.version'
/** Fresh Delta charts show the unified pattern study. Saved choices, including
 * a manual off, remain separate from non-crypto chart preferences. */
export function readDeltaStudyPreferences(fallback: string[]): string[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(DELTA_STUDIES_KEY) || 'null')
    const selected = Array.isArray(saved)
      ? saved.filter(
          (id): id is string =>
            typeof id === 'string' && CHART_STUDIES.some((choice) => choice[0] === id)
        )
      : [...new Set([...fallback, 'candle-patterns'])]
    const base =
      localStorage.getItem(DELTA_DEFAULTS_VERSION) === '1'
        ? selected
        : [...new Set([...selected, 'volume', 'rsi'])]
    const withEma = localStorage.getItem('neo.delta.chart.ema-fib.version') === '1'
      ? base
      : [...new Set([...base, 'ema-9-15', 'fibonacci-pivots'])]
    return localStorage.getItem('neo.delta.chart.video-guide.version') === '1'
      ? withEma : [...new Set([...withEma, 'video-strategy-guide'])]
  } catch {
    return [
      ...new Set([...fallback, 'candle-patterns', 'video-strategy-guide', 'volume', 'rsi', 'ema-9-15', 'fibonacci-pivots']),
    ]
  }
}
export function saveDeltaStudyPreferences(studies: string[]): void {
  try {
    localStorage.setItem(DELTA_STUDIES_KEY, JSON.stringify(studies))
    localStorage.setItem(DELTA_DEFAULTS_VERSION, '1')
    localStorage.setItem('neo.delta.chart.ema-fib.version', '1')
    localStorage.setItem('neo.delta.chart.video-guide.version', '1')
  } catch {
    /* Keep this chart's current choices when preferences cannot be saved. */
  }
}

const STANDARD_EMA_VERSION = 'neo.native.chart.ema-9-15-21.version'
/** Add the requested shared EMA study once; subsequent manual off choices win. */
export function withStandardEmaDefault(studies: string[]): string[] {
  try {
    const withEma = localStorage.getItem(STANDARD_EMA_VERSION) === '1' ? studies : [...new Set([...studies, 'ema-9-15'])]
    return localStorage.getItem('neo.native.chart.video-guide.version') === '1' ? withEma : [...new Set([...withEma, 'video-strategy-guide'])]
  } catch { /* Render the requested default when storage is unavailable. */ }
  return [...new Set([...studies, 'ema-9-15', 'video-strategy-guide'])]
}
export function saveStandardStudyPreferences(studies: string[]): void {
  try {
    localStorage.setItem('neo.native.chart.indicators', JSON.stringify(studies))
    localStorage.setItem(STANDARD_EMA_VERSION, '1')
    localStorage.setItem('neo.native.chart.video-guide.version', '1')
  } catch { /* Retain current in-memory choices. */ }
}
