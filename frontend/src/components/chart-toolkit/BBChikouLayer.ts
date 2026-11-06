import {
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesPrimitive,
  type IPrimitivePaneRenderer,
  type SeriesAttachedParameter,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { BBChikouResult } from './bbChikou'

class BBSignals implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private result: BBChikouResult | null = null
  private first = 0
  private last = 0
  private directional = false
  private reward = 1
  private optionSide?: 'CE' | 'PE'
  attached(attachment: SeriesAttachedParameter<Time>) {
    this.attachment = attachment
  }
  detached() {
    this.attachment = null
  }
  set(
    result: BBChikouResult | null,
    first: number,
    last: number,
    directional = false,
    reward = 1,
    optionSide?: 'CE' | 'PE'
  ) {
    this.result = result
    this.directional = directional
    this.reward = reward
    this.optionSide = optionSide
    this.first = first
    this.last = last
    this.attachment?.requestUpdate()
  }
  paneViews() {
    return [
      {
        zOrder: () => 'top' as const,
        renderer: () => ({
          draw: (target: Parameters<IPrimitivePaneRenderer['draw']>[0]) => {
            const a = this.attachment,
              r = this.result
            if (!a || !r) return
            // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate API
            target.useMediaCoordinateSpace(({ context: c, mediaSize: size }) => {
              const x = (time: number) => a.chart.timeScale().timeToCoordinate(time as UTCTimestamp)
              const y = (price: number) => a.series.priceToCoordinate(price)
              c.save()
              c.beginPath()
              c.rect(0, 0, size.width, size.height)
              c.clip()
              c.font = '600 11px Inter, system-ui, sans-serif'
              c.textAlign = 'center'
              for (const signal of r.signals.filter(
                (s) => s.time >= this.first && s.time <= this.last
              )) {
                const left = x(signal.time),
                  price = y(signal.price),
                  bull = signal.side === 'BULL'
                if (left == null || price == null || left < -22 || left > size.width + 22) continue
                const top = price + (bull ? 16 : -16),
                  color = bull ? '#26a69a' : '#ef5350'
                c.fillStyle = color
                c.beginPath()
                c.moveTo(left, price + (bull ? 5 : -5))
                c.lineTo(left - 4, price + (bull ? 11 : -11))
                c.lineTo(left + 4, price + (bull ? 11 : -11))
                c.closePath()
                c.fill()
                c.fillStyle = '#131722'
                c.fillRect(left - 22, top - 8, 44, 16)
                c.fillStyle = color
                c.textBaseline = 'middle'
                c.fillText(
                  this.optionSide
                    ? `${bull ? 'BUY' : 'AVOID'} ${this.optionSide}`
                    : this.directional
                      ? bull
                        ? 'LONG'
                        : 'SHORT'
                      : signal.side,
                  left,
                  top
                )
              }
              if (r.latest) {
                const left = Math.max(0, x(Math.max(r.latest.time, this.first)) ?? 0)
                const right = Math.min(size.width, (x(this.last) ?? size.width) + 8)
                c.font = '500 10px Inter, system-ui, sans-serif'
                c.textAlign = 'left'
                for (const [name, value, color] of [
                  ['BB entry', r.latest.entry, '#3988ff'],
                  ['BB initial SL', r.latest.stop, '#ef5350'],
                  [this.reward === 2 ? 'BB target 1:2' : 'BB 1R', r.latest.target, '#26a69a'],
                ] as const) {
                  const top = y(value)
                  if (top == null) continue
                  c.strokeStyle = color
                  c.setLineDash([4, 4])
                  c.lineWidth = 1
                  c.beginPath()
                  c.moveTo(left, top)
                  c.lineTo(right, top)
                  c.stroke()
                  const text = `${name} ${value.toFixed(2)}`,
                    width = c.measureText(text).width + 8
                  const labelX = Math.max(left, Math.min(right - width, size.width - width))
                  c.fillStyle = '#131722'
                  c.fillRect(labelX, top - 14, width, 13)
                  c.fillStyle = color
                  c.fillText(text, labelX + 4, top - 7)
                }
              }
              c.restore()
            })
          },
        }),
      },
    ]
  }
}

// Lazy series creation keeps disabled studies off the live redraw path.
export class BBChikouLayer {
  private lines: ISeriesApi<'Line'>[] = []
  private signals = new BBSignals()
  private chart: IChartApi
  private price: ISeriesApi<'Candlestick'>
  constructor(chart: IChartApi, price: ISeriesApi<'Candlestick'>) {
    this.chart = chart
    this.price = price
  }
  update(
    result: BBChikouResult | null,
    first: number,
    last: number,
    directional = false,
    reward = 1,
    optionSide?: 'CE' | 'PE'
  ) {
    if (result && !this.lines.length) {
      this.lines = ['#5b8def', '#f5a623', '#5b8def', '#b596ff'].map((color, i) =>
        this.chart.addSeries(LineSeries, {
          color,
          lineWidth: i === 1 || i === 3 ? 2 : 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
      )
      this.price.attachPrimitive(this.signals)
    }
    this.signals.set(result, first, last, directional, reward, optionSide)
    if (!this.lines.length) return
    for (let i = 0; i < this.lines.length; i++) {
      const field = (['upper', 'middle', 'lower'] as const)[i]
      const points =
        i === 3
          ? (result?.chikou ?? [])
          : (result?.points ?? []).map((p) => ({ time: p.time, value: p[field] }))
      this.lines[i].setData(
        points
          .filter((p) => p.time >= first && p.time <= last)
          .map((p) =>
            p.value == null
              ? { time: p.time as UTCTimestamp }
              : { time: p.time as UTCTimestamp, value: p.value }
          )
      )
      this.lines[i].applyOptions({ visible: result != null })
    }
  }
}
