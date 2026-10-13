import { afterEach, expect, it, vi } from 'vitest'
import { TradingTerminal } from './terminal'
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs() })
function terminal() {
  const chart = Object.create(TradingTerminal.prototype)
  chart.sym = {symbol: 'NIFTY', exchange:'NSE_INDEX'}
  chart.cb = {onLtp: vi.fn()}
  chart.builder = {onTick: vi.fn(() => null)}
  chart.refreshLegend = vi.fn()
  chart.replayOwnsDisplay = () => false
  return chart
}
it('keeps last-reported LTP but does not fabricate candles from after-hours snapshots', () => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED','true')
  vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-13T23:00:00+05:30'))
  const chart = terminal()
  chart.onTick({ltp:22721.95,timeSec:Date.now()/1000})
  expect(chart.cb.onLtp).toHaveBeenCalledWith(22721.95)
  expect(chart.builder.onTick).not.toHaveBeenCalled()
})
it('accepts fresh in-session candles and refuses old timestamped snapshots', () => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED','true')
  vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-13T15:29:30+05:30'))
  const chart = terminal()
  chart.onTick({ltp:22721.95,timeSec:Date.now()/1000})
  expect(chart.builder.onTick).toHaveBeenCalledTimes(1)
  chart.onTick({ltp:22720,timeSec:Date.now()/1000-120})
  expect(chart.builder.onTick).toHaveBeenCalledTimes(1)
})
