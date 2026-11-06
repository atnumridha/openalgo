import { FRAMES, type Instrument, type ScreenDefinition, type Frame, type RuleNode } from './model'
import { isPatternSelection, type PatternSelection } from '../chart-toolkit/candlePatterns'
export interface ChartTarget extends Instrument {
  interval: Frame
  candlePattern: PatternSelection
  candleStudy: boolean
}
export function parseChartTarget(search: string): ChartTarget | null {
  const p = new URLSearchParams(search),
    symbol = p.get('symbol')?.toUpperCase(),
    exchange = p.get('exchange')?.toUpperCase(),
    interval = p.get('interval') ?? '15m'
  if (
    !symbol ||
    !exchange ||
    !FRAMES.includes(interval as Frame) ||
    !/^([A-Z0-9])[A-Z0-9&_.:+/-]{0,99}$/.test(symbol) ||
    !/^[A-Z][A-Z0-9_]{1,19}$/.test(exchange) ||
    symbol.includes('://')
  )
    return null
  const choice = p.get('pattern')
  return {
    symbol,
    exchange,
    interval: interval as Frame,
    candleStudy: p.get('study') === 'candle-probability',
    candlePattern: isPatternSelection(choice) ? choice : 'all',
  }
}
export function chartTargetUrl(
  item: Instrument,
  definition: ScreenDefinition,
  choice?: PatternSelection
): string {
  let pattern = choice
  const visit = (node: RuleNode) => {
    if (node.enabled === false) return
    if (node.type === 'group') node.children.forEach(visit)
    else if (typeof node.left !== 'number' && node.left.field === 'candle_pattern')
      pattern = pattern ?? node.left.pattern ?? 'all'
  }
  visit(definition.rule)
  const p = new URLSearchParams({
    symbol: item.symbol,
    exchange: item.exchange,
    interval: definition.interval,
  })
  if (pattern) {
    p.set('study', 'candle-probability')
    p.set('pattern', pattern)
  }
  return `/trading?${p.toString()}`
}
