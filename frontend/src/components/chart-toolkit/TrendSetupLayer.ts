import type { IPriceLine, ISeriesApi } from 'lightweight-charts'
import type { TrendSetup } from './trendSetup'

/** Owns only the current shape's three plan lines on the underlying series. */
export class TrendSetupLayer {
  private readonly series: ISeriesApi<'Candlestick'>
  private lines: IPriceLine[] = []
  private key: string | null = null

  constructor(series: ISeriesApi<'Candlestick'>) {
    this.series = series
  }

  update(setup: TrendSetup | null): void {
    const active = setup?.status === 'active' ? setup : null
    const key = active
      ? JSON.stringify([active.time, active.side, active.name, active.entry, active.stop, active.target])
      : null
    if (key === this.key) return
    this.destroy()
    if (!active) return
    this.key = key
    for (const [price, color, title] of [
      [active.entry, '#3b82f6', 'Shape entry'],
      [active.stop, '#ef4444', 'Shape stop'],
      [active.target, '#22c55e', 'Shape target'],
    ] as const) {
      this.lines.push(this.series.createPriceLine({
        price, color, title, lineWidth: 2, lineStyle: 2, axisLabelVisible: true,
      }))
    }
  }

  destroy(): void {
    for (const line of this.lines) this.series.removePriceLine(line)
    this.lines = []
    this.key = null
  }
}
