import type { PivotOverlay } from '@/api/kotakAssistant'

/** Never project today's daily levels onto a different session or replay cursor. */
export function pivotChartLevels(pivots: PivotOverlay | null | undefined, underlying: string, from: string, to: string, replay: boolean, lastBarTime?: number) {
  const actualDate = lastBarTime != null && Number.isFinite(lastBarTime) ? new Date(lastBarTime * 1000).toISOString().slice(0,10) : null
  if (!pivots || actualDate !== pivots.session_date || replay || pivots.underlying !== underlying || from !== to || from !== pivots.session_date) return []
  return [
    { price: pivots.levels.P, title: 'P · Daily Pivot', color: '#2563eb' },
    { price: pivots.levels.S1, title: 'S1 · Pivot support', color: '#0891b2' },
    { price: pivots.levels.R1, title: 'R1 · Pivot resistance', color: '#d97706' },
  ]
}
