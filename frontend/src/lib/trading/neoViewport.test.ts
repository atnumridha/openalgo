import { afterEach, expect, it, vi } from 'vitest'
import { TradingTerminal } from './terminal'
afterEach(() => vi.unstubAllEnvs())
it.each([
  ['true', 90],
  ['false', 120],
])('uses the readable Neo window only for the Neo desk (%s)', (enabled, count) => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED', enabled)
  const terminal = Object.create(TradingTerminal.prototype)
  const ranges: Array<{ from: number; to: number }> = []
  terminal.shownCount = 300
  terminal.chart = {
    resetScale: () => {},
    timeScale: {
      setVisibleLogicalRange: (range: { from: number; to: number }) => ranges.push(range),
    },
  }
  terminal.resetScale()
  expect(ranges).toHaveLength(1)
  expect(ranges[0].to - ranges[0].from).toBe(count)
})
