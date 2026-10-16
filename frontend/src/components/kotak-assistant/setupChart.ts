import type { SetupDirection, SetupResult } from '@/api/kotakAssistant'

/** Follow the selected option side without changing the underlying strategy rules. */
export function setupForSelectedSide(setup: SetupResult | null | undefined, side?: SetupDirection) {
  const branch = side && setup?.directions?.[side]
  if (
    !setup ||
    !branch ||
    setup.strategy === 'trend' ||
    ![
      'waiting_reference',
      'waiting_break',
      'waiting_signal',
      'waiting_trigger',
      'triggered',
      'expired',
    ].includes(setup.stage)
  )
    return setup
  return {
    ...setup,
    ...branch,
    directions: { [side]: branch },
    source: setup.source,
    read_only: setup.read_only,
    eligible: branch.eligible === true && setup.chart_fresh !== false,
    reason: setup.chart_fresh === false ? setup.reason : branch.reason,
  }
}

type Marker = {
  time: number
  action: string
  price: number
  label?: string
  side?: 'above' | 'below'
  color?: string
}
type Level = { price: number; title: string; color: string }
const color = (side?: string | null) => (side === 'PE' ? '#f87171' : '#34d399')
const price = (value: number) => value.toFixed(2)

/** Bound annotations to the decision's causal evidence, independent of fills. */
export function setupChartAnnotations(setup?: SetupResult | null, now = Date.now() / 1000) {
  const levels: Level[] = [],
    markers: Marker[] = []
  if (!setup) return { levels, markers }
  for (const swing of setup.numbered_swings || []) {
    if (swing.ordinal > 2 || swing.time == null || (swing.known_at ?? 0) > now) continue
    markers.push({
      time: swing.time,
      action: 'SETUP',
      price: swing.price,
      label: `${swing.kind === 'high' ? 'H' : 'L'}${swing.ordinal} · ${price(swing.price)}`,
      side: swing.kind === 'high' ? 'above' : 'below',
      color: '#a5b4fc',
    })
  }
  const choices = setup.directions ? Object.values(setup.directions).filter(Boolean) : [setup]
  for (const item of choices) {
    if (!item) continue
    const side = item.direction || setup.direction,
      c = color(side)
    if (item.reference && (item.reference.known_at ?? 0) <= now)
      levels.push({
        price: item.reference.price,
        title: `${side || ''} reference ${item.reference.kind === 'high' ? 'H2' : item.reference.kind === 'low' ? 'L2' : ''}`,
        color: '#a5b4fc',
      })
    if (item.signal_candle && (item.signal_candle.closed_at ?? item.signal_candle.time + 60) <= now)
      markers.push({
        time: item.signal_candle.time,
        action: 'SETUP',
        price: item.signal_candle.close,
        label: `${side} ${side === 'PE' ? 'red' : 'green'} signal`,
        side: side === 'PE' ? 'above' : 'below',
        color: c,
      })
    if (item.trigger && item.stage === 'waiting_trigger') {
      const remaining = Math.max(0, Math.ceil((item.expires ?? now) - now))
      levels.push({
        price: item.trigger,
        title: `Watching ${side} ${side === 'PE' ? 'below' : 'above'} · ${remaining}s`,
        color: c,
      })
    }
    if (item.trigger && item.triggered_at && item.triggered_at <= now)
      markers.push({
        time: item.triggered_at,
        action: 'SETUP',
        price: item.trigger,
        label: `${side} TRIGGERED`,
        side: side === 'PE' ? 'above' : 'below',
        color: c,
      })
  }
  if (setup.strategy === 'trend' && setup.entry_zone) {
    for (const [value, title, c] of [
      [setup.index_entry, 'Frozen index entry', '#60a5fa'],
      [setup.entry_zone.lower, 'Entry zone low', '#60a5fa'],
      [setup.entry_zone.upper, 'Entry zone high', '#60a5fa'],
      [setup.invalidation, 'Index invalidation', '#f87171'],
      [setup.index_target, setup.projected ? 'Projected 2R' : 'Index 2R', '#34d399'],
    ] as const)
      if (value != null && value > 0) levels.push({ price: value, title, color: c })
  }
  return { levels, markers }
}
