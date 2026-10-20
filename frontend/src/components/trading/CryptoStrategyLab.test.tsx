import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CryptoStrategyLab } from './CryptoStrategyLab'
import type { TradingTerminal } from '@/lib/trading/terminal'
vi.mock('@/hooks/useBrokerCurrencyFormatter', () => ({
  useBrokerCurrencyFormatter: () => (x: number) => `$${x.toFixed(2)}`,
  useBrokerPriceFormatter: () => (x: number) => `$${x.toFixed(2)}`,
}))
const candles = Array.from({ length: 140 }, (_, i) => ({
  time: i * 180,
  open: 100,
  high: 101,
  low: 99,
  close: 100,
}))
afterEach(() => vi.useRealTimers())
describe('Crypto strategy research panel', () => {
  it('does not poll until opened and clears its one-second timer on unmount', () => {
    vi.useFakeTimers()
    const cryptoResearchSnapshot = vi.fn(() => ({
      symbol: 'BTCUSDFUT',
      interval: '3m',
      tick: 0.5,
      contractValue: 0.001,
      replay: false,
      fresh: true,
      bars: candles,
    }))
    const target = () => ({ cryptoResearchSnapshot }) as unknown as TradingTerminal
    const view = render(<CryptoStrategyLab target={target} />)
    expect(cryptoResearchSnapshot).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /BTCUSD futures/ }))
    expect(cryptoResearchSnapshot).toHaveBeenCalledTimes(1)
    act(() => vi.advanceTimersByTime(1000))
    expect(cryptoResearchSnapshot).toHaveBeenCalledTimes(2)
    view.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('does not reveal a cached live backtest when replay begins or moves', () => {
    vi.useFakeTimers()
    let snapshot = {
      symbol: 'BTCUSDFUT',
      interval: '3m',
      tick: 0.5,
      contractValue: 0.001,
      replay: false,
      fresh: true,
      bars: candles,
    }
    const target = () => ({ cryptoResearchSnapshot: () => snapshot }) as unknown as TradingTerminal
    render(<CryptoStrategyLab target={target} />)
    fireEvent.click(screen.getByRole('button', { name: /BTCUSD futures/ }))
    fireEvent.click(screen.getByRole('button', { name: /Run loaded-history/ }))
    expect(screen.getByText(/simulated trades/)).toBeInTheDocument()
    snapshot = { ...snapshot, replay: true, bars: candles.slice(0, 125) }
    act(() => vi.advanceTimersByTime(1000))
    expect(screen.queryByText(/simulated trades/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Run loaded-history/ }))
    expect(screen.getByText(/simulated trades/)).toBeInTheDocument()
    snapshot = { ...snapshot, bars: candles.slice(0, 120) }
    act(() => vi.advanceTimersByTime(1000))
    expect(screen.queryByText(/simulated trades/)).not.toBeInTheDocument()
  })
  it('blocks cash simulation without metadata and offers source links rather than order buttons', () => {
    const target = () =>
      ({
        cryptoResearchSnapshot: () => ({
          symbol: 'X',
          interval: '3m',
          tick: 0.1,
          contractValue: null,
          replay: false,
          fresh: false,
          bars: candles,
        }),
      }) as unknown as TradingTerminal
    render(<CryptoStrategyLab target={target} />)
    fireEvent.click(screen.getByRole('button', { name: /BTCUSD futures/ }))
    expect(screen.getByRole('button', { name: /Run loaded-history/ })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Pinned GitHub source' })).toHaveAttribute(
      'href',
      expect.stringContaining('9af100d')
    )
    expect(screen.queryByRole('button', { name: /buy|sell|enable live/i })).not.toBeInTheDocument()
  })
})
