import { INDICATORS } from '../chart-toolkit/nineIndicators'

export const CHART_STUDIES = [
  ['neo-toolkit', 'Option buying · RSI + MACD'],
  ['bb-chikou', 'BB + Chikou · BULL / BEAR'],
  ['candle-probability', 'Candlestick probability · 2R / 10 candles'],
  ['neo-donchian', 'Donchian / EMA'],
  ['neo-structure', 'Fair Value Gaps / levels'],
  ['rsi', 'RSI 14'],
  ...INDICATORS.map((item) => [item.id, `${item.short} · CALL / PUT`] as const),
] as const

export function chartStudyLabel(id: string, label: string, crypto: boolean) {
  if (!crypto) return label
  if (id === 'neo-toolkit') return 'Trend setup · RSI + MACD'
  return label.replace('CALL / PUT', 'LONG / SHORT').replace('BULL / BEAR', 'LONG / SHORT')
}
