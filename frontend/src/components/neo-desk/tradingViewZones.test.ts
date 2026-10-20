import { describe, expect, it, vi } from 'vitest'
import type { SeriesAttachedParameter, Time } from 'lightweight-charts'
import { TradingViewZones } from './tradingViewZones'

describe('Trading page FVG chart labels', () => {
  it('prints direction, prices and touches without overlapping nearby labels', () => {
    const primitive = new TradingViewZones(true)
    const requestUpdate = vi.fn()
    primitive.attached({
      chart: { timeScale: () => ({ timeToCoordinate: (t: number) => t }) },
      series: { priceToCoordinate: (price: number) => 250 - price },
      requestUpdate,
    } as unknown as SeriesAttachedParameter<Time>)
    primitive.setZones([
      { time: 10, end: 350, low: 100, high: 105, bullish: true, touched: false },
      { time: 20, end: 350, low: 106, high: 110, bullish: false, touched: true },
    ])
    const context = {
      fillRect: vi.fn(),
      strokeRect: vi.fn(),
      fillText: vi.fn(),
      measureText: (text: string) => ({ width: text.length * 6 }),
      save: vi.fn(),
      restore: vi.fn(),
      beginPath: vi.fn(),
      rect: vi.fn(),
      clip: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
    }
    const target = {
      useMediaCoordinateSpace: (fn: (data: unknown) => void) =>
        fn({ context, mediaSize: { width: 400, height: 300 } }),
    }
    for (const view of primitive.paneViews()) view.renderer()!.draw(target as never)
    expect(context.fillText).toHaveBeenCalledWith('↑ FVG', expect.any(Number), expect.any(Number))
    expect(context.fillText).toHaveBeenCalledWith('↓ FVG', expect.any(Number), expect.any(Number))
    const rows = context.fillText.mock.calls.map((call) => Number(call[2])).sort((a, b) => a - b)
    expect(rows[1] - rows[0]).toBeGreaterThanOrEqual(24)
    expect(requestUpdate).toHaveBeenCalledOnce()
    primitive.setZones([])
    context.fillText.mockClear()
    for (const view of primitive.paneViews()) view.renderer()!.draw(target as never)
    expect(context.fillText).not.toHaveBeenCalled()
    primitive.detached()
  })
})
