import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { FairValueGapOverlay } from './FairValueGapOverlay'
import type { FairValueGap } from './fairValueGaps'

describe('Fair Value Gap chart zones', () => {
  it('labels direction, bounds and touches, clipped above the RSI pane', () => {
    const container = document.createElement('div')
    Object.defineProperty(container, 'clientWidth', { value: 600 })
    const chartRef = {
      current: {
        panes: () => [{ getHeight: () => 300 }],
        timeScale: () => ({ timeToCoordinate: () => 50, width: () => 500 }),
      } as unknown as IChartApi,
    }
    const candleRef = {
      current: {
        priceToCoordinate: (price: number) => (price === 110 ? 290 : 330),
      } as unknown as ISeriesApi<'Candlestick'>,
    }
    const gap: FairValueGap = {
      id: 'bull',
      direction: 'bullish',
      lower: 100,
      upper: 110,
      startTime: 100,
      confirmedAt: 300,
      touched: true,
    }
    const view = render(
      <FairValueGapOverlay
        chartRef={chartRef}
        candleRef={candleRef}
        containerRef={{ current: container }}
        gaps={[gap]}
        isDark={true}
      />
    )
    const label = screen.getByText('↑ FVG')
    expect(label).toHaveAttribute('title', 'Bullish Fair Value Gap 100.00–110.00, partially filled')
    expect(label.parentElement).toHaveStyle({ top: '290px', height: '10px', width: '450px' })
    expect(label).toHaveStyle({ top: '-12px' })
    view.rerender(
      <FairValueGapOverlay
        chartRef={chartRef}
        candleRef={candleRef}
        containerRef={{ current: container }}
        gaps={[]}
        isDark={true}
      />
    )
    expect(screen.queryByText(/↑ FVG/)).not.toBeInTheDocument()
  })
  it('keeps nearby labels apart on narrow plots', () => {
    const container = document.createElement('div')
    const chartRef = {
      current: {
        panes: () => [{ getHeight: () => 200 }],
        timeScale: () => ({ timeToCoordinate: () => 250, width: () => 270 }),
      } as unknown as IChartApi,
    }
    const candleRef = {
      current: {
        priceToCoordinate: (price: number) => 150 - price / 10,
      } as unknown as ISeriesApi<'Candlestick'>,
    }
    const gaps: FairValueGap[] = [100, 101, 102].map((lower) => ({
      id: String(lower),
      direction: 'bullish',
      lower,
      upper: lower + 0.5,
      startTime: 1,
      confirmedAt: 3,
      touched: false,
    }))
    render(
      <FairValueGapOverlay
        chartRef={chartRef}
        candleRef={candleRef}
        containerRef={{ current: container }}
        gaps={gaps}
        isDark={false}
      />
    )
    const labels = screen.getAllByText(/↑ FVG/)
    const tops = labels
      .map((label) => parseFloat(label.style.top) + parseFloat(label.parentElement!.style.top))
      .sort((a, b) => a - b)
    expect(tops[1] - tops[0]).toBeGreaterThanOrEqual(24)
    expect(tops[2] - tops[1]).toBeGreaterThanOrEqual(24)
    for (const label of labels) expect(label).toHaveClass('right-1')
  })
})
