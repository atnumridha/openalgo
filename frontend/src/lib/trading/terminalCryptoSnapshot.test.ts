import { afterEach, describe, expect, it, vi } from 'vitest'
import { TradingTerminal } from './terminal'
const b = Array.from({ length: 10 }, (_, i) => ({
  time: i * 180,
  open: 100,
  high: 101,
  low: 99,
  close: 100,
}))
function fixture() {
  const terminal = Object.create(TradingTerminal.prototype) as TradingTerminal
  const state = {
    destroyed: false,
    sym: { symbol: 'BTCUSDFUT', exchange: 'CRYPTO', contractValue: 0.001, tick: 0.5 },
    interval: '3m',
    rawBars: b,
    dataUnavailable: () => false,
    replayOwnsDisplay: () => false,
    replayState: () => ({ bar: { time: 720 } }),
  }
  Object.assign(terminal, state)
  return { terminal, state: terminal as unknown as typeof state }
}
afterEach(() => vi.restoreAllMocks())
describe('BTC futures research snapshots', () => {
  it('excludes the forming bar and follows the current selected BTC contract', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1750 * 1000)
    const { terminal } = fixture(),
      s = terminal.cryptoResearchSnapshot()!
    expect(s.symbol).toBe('BTCUSDFUT')
    expect(s.contractValue).toBe(0.001)
    expect(s.bars.at(-1)?.time).toBe(1440)
    expect(s.fresh).toBe(true)
  })
  it('never includes a replay current partial bar or any future bar', () => {
    const { terminal, state } = fixture()
    state.replayOwnsDisplay = () => true
    const s = terminal.cryptoResearchSnapshot()!
    expect(s.replay).toBe(true)
    expect(s.fresh).toBe(false)
    expect(s.bars.map((x) => x.time)).toEqual([0, 180, 360, 540])
  })
  it('rejects ETH, BTC options, synthetic charts and unavailable data', () => {
    for (const symbol of ['ETHUSDFUT', 'C-BTC-90000-171026', 'BTCUSDT']) {
      const { terminal, state } = fixture()
      state.sym.symbol = symbol
      expect(terminal.cryptoResearchSnapshot()).toBeNull()
    }
    const { terminal, state } = fixture()
    state.dataUnavailable = () => true
    expect(terminal.cryptoResearchSnapshot()).toBeNull()
  })
  it('does not expose live bars during replay selection or workspace transition', () => {
    for (const flag of [
      'replayPicking',
      'replayLoading',
      'workspaceTransitionLocked',
      'preparingWorkspace',
    ]) {
      const { terminal } = fixture()
      Object.assign(terminal, { [flag]: true })
      expect(terminal.cryptoResearchSnapshot()).toBeNull()
    }
  })

  it('caps historical data and never calls old candles fresh', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1e10)
    const { terminal, state } = fixture()
    state.rawBars = Array.from({ length: 3000 }, (_, i) => ({ ...b[0], time: i * 180 }))
    const s = terminal.cryptoResearchSnapshot()!
    expect(s.bars).toHaveLength(2000)
    expect(s.fresh).toBe(false)
  })
})
