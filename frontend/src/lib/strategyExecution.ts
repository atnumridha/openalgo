// Present execution evidence from the controller's reports, never from proposed plans.
type RecordValue = Record<string, unknown>
const object = (value: unknown): RecordValue | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as RecordValue)
    : null
const text = (value: unknown): string | null => (typeof value === 'string' ? value : null)
const number = (value: unknown): number | null => {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []

export interface ExecutionPosition {
  side: string
  orderId: string | null
  quantity: number | null
  filled: number | null
  open: number | null
  entryOpen: boolean
  entry: number | null
  stop: number | null
  target: number | null
  net: number | null
}
export interface ExecutionReport {
  mode: 'live' | 'paper'
  status: string
  executionEnabled: boolean | null
  reasons: string[]
  warnings: string[]
  positionKnown: boolean
  position: ExecutionPosition | null
  pending: boolean
  signal: string | null
  signalReason: string | null
  dailyNet: number | null
  uncertain: boolean
}

function fresh(mode: ExecutionReport['mode']): ExecutionReport {
  return {
    mode,
    status: '',
    executionEnabled: null,
    reasons: [],
    warnings: [],
    positionKnown: false,
    position: null,
    pending: false,
    signal: null,
    signalReason: null,
    dailyNet: null,
    uncertain: false,
  }
}

export function parseExecutionLog(content: string): ExecutionReport | null {
  let report: ExecutionReport | null = null
  // Only the recent snapshot matters; do not retain growing logs in the parsed result.
  const tail = content.slice(-262144)
  const lines = tail.split('\n')
  if (tail.length < content.length) lines.shift()
  for (const line of lines) {
    if (!line.trim()) continue
    if (line.startsWith('=== Strategy Started')) {
      report = null
      continue
    }
    let row: RecordValue | null
    try {
      row = object(JSON.parse(line))
    } catch {
      if (report) report.uncertain = true
      continue
    }
    if (!row || (row.mode !== 'live' && row.mode !== 'paper')) continue
    if (!report || report.mode !== row.mode) report = fresh(row.mode)
    const state = object(row.state)
    const data = state || row
    report.uncertain = false
    if (text(data.status)) report.status = String(data.status)
    // Every status report must reassert entry permission; activation alone never does.
    report.executionEnabled =
      typeof row.execution_enabled === 'boolean' ? row.execution_enabled : null
    report.reasons = [...strings(row.entry_wait), ...strings(row.blockers)]
    if (text(row.pause_reason)) report.reasons.push(String(row.pause_reason))
    if (text(row.message)) report.reasons.push(String(row.message))
    if (Array.isArray(row.warnings)) report.warnings = strings(row.warnings)
    if ('position' in data) {
      report.positionKnown = true
      const p = object(data.position)
      report.position = p
        ? {
            side:
              p.side === 'buy' || p.side === 1
                ? 'LONG'
                : p.side === 'sell' || p.side === -1
                  ? 'SHORT'
                  : 'Unknown',
            orderId:
              typeof p.entry_id === 'number' || typeof p.entry_id === 'string'
                ? String(p.entry_id)
                : null,
            quantity: number(p.qty ?? p.quantity),
            filled: number(row.mode === 'paper' ? p.quantity : p.filled),
            open: number(row.mode === 'paper' ? p.quantity : p.open_qty),
            entryOpen: p.entry_open === true,
            entry: number(p.entry),
            stop: number(p.ack_stop),
            target: number(p.target),
            net: number(p.net_estimate ?? p.unrealized_net),
          }
        : null
      if (row.mode === 'paper' && p && report.position) report.position.stop = number(p.stop)
    }
    if ('pending' in data) report.pending = Boolean(data.pending)
    const decision = object(row.decision) || object(data.latest_decision)
    if (decision) {
      report.signal = text(decision.action)
      report.signalReason = text(decision.reason)
    }
    const daily = object(row.daily)
    if (daily) report.dailyNet = number(daily.net)
    if (state) report.dailyNet = number(state.day_net)
  }
  return report
}

export function executionStage(r: ExecutionReport): string {
  const status = r.status.toLowerCase()
  const exposed = (r.position?.open ?? 0) > 0
  if (status.includes('unresolved')) return 'Unresolved exposure · check orders'
  if (status.includes('stopped')) return exposed ? 'Stopped · check exposure' : 'Stopped'
  if (r.uncertain) return 'Check latest logs'
  if (status.includes('halt')) return 'Daily halt'
  if (status.includes('paused') || status.includes('suspended'))
    return exposed ? 'Entries paused · check exposure' : 'Entries paused'
  if (r.mode === 'paper')
    return exposed
      ? 'Simulated position open'
      : r.pending
        ? 'Simulated entry pending'
        : 'Paper monitoring'
  if (exposed)
    return (r.position?.filled ?? 0) < (r.position?.quantity ?? 0)
      ? 'Partially filled · position open'
      : 'Trade executed · position open'
  if (r.position?.entryOpen && r.position.filled === 0) return 'Entry pending · no fill'
  if ((r.position?.filled ?? 0) > 0) return 'Position closed · reconciling'
  if (r.position) return 'Order state needs confirmation'
  if (r.executionEnabled === false || r.reasons.length) return 'Monitoring only'
  return r.executionEnabled === true ? 'Scanning · entries enabled' : 'Checking execution readiness'
}
