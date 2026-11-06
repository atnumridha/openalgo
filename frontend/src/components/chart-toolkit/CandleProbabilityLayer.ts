import {
  LineStyle,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesPrimitive,
  type IPrimitivePaneRenderer,
  type SeriesAttachedParameter,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { PatternLabelTooltip } from './PatternLabelTooltip'
import type { Bar } from './model'
import type { CandleStudy } from './candleProbabilityTypes'

export interface Marker {
  time: number
  price: number
  text: string
  above: boolean
  color: string
  textColor?: string
  background?: string
  pointer?: boolean
  labelPrice?: number
  tooltip?: string
}
export class CandleMarkers implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private markers: Marker[] = []
  private bars: Bar[] = []
  private tooltip: PatternLabelTooltip | null = null
  private readonly fontSize: number
  constructor(fontSize = 6) { this.fontSize = fontSize }
  attached(value: SeriesAttachedParameter<Time>) {
    this.tooltip?.dispose()
    this.attachment = value
    const root = value.chart.chartElement?.()
    this.tooltip = root ? new PatternLabelTooltip(root) : null
  }
  detached() {
    this.tooltip?.dispose()
    this.tooltip = null
    this.attachment = null
  }
  set(markers: Marker[], bars: Bar[] = []) {
    this.bars = bars
    this.markers = markers
    if (!markers.length) this.tooltip?.setRegions([])
    this.attachment?.requestUpdate()
  }
  paneViews() {
    return [
      {
        zOrder: () => 'top' as const,
        renderer: () => ({
          draw: (target: Parameters<IPrimitivePaneRenderer['draw']>[0]) => {
            const attachment = this.attachment
            if (!attachment || !this.markers.length) return
            // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate API
            target.useMediaCoordinateSpace(({ context, mediaSize }) => {
              context.save()
              context.beginPath()
              context.rect(0, 0, mediaSize.width, mediaSize.height)
              context.clip()
              context.font = `600 ${this.fontSize}px Inter, system-ui, sans-serif`
              context.textAlign = 'center'
              context.textBaseline = 'middle'
              const candles = this.bars.flatMap((bar) => {
                const x = attachment.chart.timeScale().timeToCoordinate(bar.time as UTCTimestamp)
                const high = attachment.series.priceToCoordinate(bar.high)
                const low = attachment.series.priceToCoordinate(bar.low)
                return x == null || high == null || low == null
                  ? []
                  : [{ x, top: Math.min(high, low), bottom: Math.max(high, low) }]
              })
              const lanes = new Map<string, number>()
              const layouts: {
                marker: Marker
                x: number
                anchor: number
                labelX: number
                y: number
                width: number
              }[] = []
              const occupied: { left: number; right: number; top: number; bottom: number }[] = []
              for (const marker of this.markers) {
                const x = attachment.chart.timeScale().timeToCoordinate(marker.time as UTCTimestamp)
                const anchor = attachment.series.priceToCoordinate(marker.price)
                if (x == null || anchor == null || x < -100 || x > mediaSize.width + 100) continue
                const key = `${marker.time}:${marker.above}`
                const lane = lanes.get(key) ?? 0
                lanes.set(key, lane + 1)
                const labelAnchor =
                  marker.labelPrice == null
                    ? anchor
                    : (attachment.series.priceToCoordinate(marker.labelPrice) ?? anchor)
                let y = labelAnchor + (marker.above ? -1 : 1) * (24 + lane * 18)
                const width = context.measureText(marker.text).width + 10
                const labelX = Math.max(width / 2 + 2, Math.min(mediaSize.width - width / 2 - 2, x))
                // Keep neighboring candle names readable while preserving their side.
                const left = labelX - width / 2,
                  right = labelX + width / 2
                // Clear every candle under the full text width, including zoom changes.
                for (const candle of candles) {
                  if (candle.x < left - 5 || candle.x > right + 5) continue
                  y = marker.above ? Math.min(y, candle.top - 18) : Math.max(y, candle.bottom + 18)
                }
                for (let attempt = 0; attempt < 24; attempt++) {
                  if (
                    !occupied.some(
                      (box) =>
                        left < box.right + 3 &&
                        right > box.left - 3 &&
                        y - 8 < box.bottom + 2 &&
                        y + 8 > box.top - 2
                    )
                  )
                    break
                  y += marker.above ? -18 : 18
                }
                occupied.push({ left, right, top: y - 8, bottom: y + 8 })
                layouts.push({ marker, x, anchor, labelX, y, width })
              }
              this.tooltip?.setRegions(
                layouts
                  .filter(({ marker, y }) => marker.tooltip && y >= 0 && y <= mediaSize.height)
                  .map(({ marker, labelX, y, width }) => ({
                    left: labelX - width / 2,
                    right: labelX + width / 2,
                    top: y - 8,
                    bottom: y + 8,
                    text: marker.tooltip!,
                  }))
              )
              // Draw stems behind all label boxes, ending exactly at the candle wick.
              for (const { marker, x, anchor, labelX, y } of layouts) {
                if (!marker.pointer) continue
                context.strokeStyle = marker.textColor ?? marker.color
                context.fillStyle = marker.textColor ?? marker.color
                context.lineWidth = 1
                context.setLineDash([2, 3])
                context.beginPath()
                context.moveTo(labelX, y + (marker.above ? 8 : -8))
                context.lineTo(x, anchor)
                context.stroke()
                context.setLineDash([])
                // Arrowhead points at the exact wick; text stays outside nearby candles.
                const angle = Math.atan2(anchor - (y + (marker.above ? 8 : -8)), x - labelX)
                context.beginPath()
                context.moveTo(
                  x - 5 * Math.cos(angle - Math.PI / 6),
                  anchor - 5 * Math.sin(angle - Math.PI / 6)
                )
                context.lineTo(x, anchor)
                context.lineTo(
                  x - 5 * Math.cos(angle + Math.PI / 6),
                  anchor - 5 * Math.sin(angle + Math.PI / 6)
                )
                context.stroke()
                context.beginPath()
                context.arc(x, anchor, 2.5, 0, Math.PI * 2)
                context.fill()
              }
              for (const { marker, labelX, y, width } of layouts) {
                context.fillStyle = marker.background ?? marker.color
                context.fillRect(labelX - width / 2, y - 8, width, 16)
                context.fillStyle = marker.textColor ?? '#ffffff'
                context.fillText(marker.text, labelX, y)
              }
              context.restore()
            })
          },
        }),
      },
    ]
  }
}

export class CandleProbabilityLayer {
  private markers = new CandleMarkers()
  private attached = false
  private lines: IPriceLine[] = []
  private levelsKey = ''
  private price: ISeriesApi<'Candlestick'>
  constructor(price: ISeriesApi<'Candlestick'>) {
    this.price = price
  }
  update(
    study: CandleStudy | null,
    first: number,
    last: number,
    index: boolean,
    directional = false,
    optionSide?: 'CE' | 'PE',
    patternLabels = false,
    probabilityEnabled = true,
    showUnconfirmed = false
  ) {
    if (study && !this.attached) {
      this.price.attachPrimitive(this.markers)
      this.attached = true
    }
    const anchors = new Map(study?.bars.map((bar) => [bar.time, bar]) ?? [])
    const markers: Marker[] = (study?.setups ?? [])
      .filter((setup) => patternLabels || (probabilityEnabled && setup.qualified))
      .map((setup) => {
        const bull = setup.side === 'CALL'
        const anchor = anchors.get(setup.time)
        return {
          time: setup.time,
          price: (bull ? anchor?.low : anchor?.high) ?? setup.entry,
          above: !bull,
          color: bull ? '#075a43' : '#8c2430',
          textColor: patternLabels ? (bull ? '#34d399' : '#f87171') : undefined,
          pointer: patternLabels,
          background: patternLabels ? '#111827' : undefined,
          text: patternLabels
            ? `${setup.name.replace(/^(Bullish|Bearish|Bull|Bear) /i, '').replace(/^./, (letter) => letter.toUpperCase())}${setup.estimate.samples >= 50 && setup.estimate.probability != null ? ` · ${(100 * setup.estimate.probability).toFixed(1)}%` : ''}`
            : `Candle ${optionSide ? `${bull ? 'BUY' : 'AVOID'} ${optionSide}` : index ? `BUY ${setup.side}` : directional ? (bull ? 'LONG' : 'SHORT') : bull ? 'BULL' : 'BEAR'} · ${setup.estimate.probability == null ? '—' : `${(100 * setup.estimate.probability).toFixed(1)}%`}`,
        }
      })
    for (const outcome of probabilityEnabled ? (study?.signalOutcomes ?? []) : []) {
      const anchor = anchors.get(outcome.time)
      markers.push({
        time: outcome.time,
        price: outcome.price ?? anchor?.close ?? outcome.setup.entry,
        above: outcome.setup.side === 'CALL',
        color:
          outcome.result === 'TARGET'
            ? '#075a43'
            : outcome.result === 'STOP'
              ? '#8c2430'
              : '#785800',
        text: `Candle ${outcome.result}${outcome.result === 'TARGET' ? ' · 2R' : outcome.ambiguous ? ' · both touched' : ''}`,
      })
    }
    this.markers.set(
      markers
        .filter((marker) => marker.time >= first && marker.time <= last)
        .sort((a, b) => a.time - b.time)
    )
    const candidate = study?.active ?? study?.latest
    const reference =
      (optionSide && candidate?.side === 'PUT') || (!showUnconfirmed && !candidate?.qualified)
        ? null
        : candidate
    const prefix = reference?.qualified ? 'Candle' : 'Candidate'
    const suffix = reference?.qualified ? '' : ' · unqualified'
    const levels =
      study && probabilityEnabled
        ? [
            {
              title: 'Candle support · prior 10',
              price: reference?.support ?? study.support,
              color: '#26a69a',
            },
            {
              title: 'Candle resistance · prior 10',
              price: reference?.resistance ?? study.resistance,
              color: '#ef5350',
            },
            ...(reference
              ? [
                  { title: `${prefix} entry${suffix}`, price: reference.entry, color: '#78909c' },
                  { title: `${prefix} SL${suffix}`, price: reference.stop, color: '#ef5350' },
                  {
                    title: `${prefix} 2R target${suffix}`,
                    price: reference.target,
                    color: '#26a69a',
                  },
                ]
              : []),
          ]
        : []
    const key = JSON.stringify(levels)
    if (key !== this.levelsKey) {
      for (const line of this.lines) this.price.removePriceLine(line)
      this.lines = levels.flatMap((level) =>
        level.price != null && Number.isFinite(level.price)
          ? [
              this.price.createPriceLine({
                ...level,
                price: level.price,
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: true,
              }),
            ]
          : []
      )
      this.levelsKey = key
    }
  }
}
