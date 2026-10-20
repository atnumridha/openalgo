import { useLayoutEffect, useState, type RefObject } from 'react'
import type { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts'
import type { FairValueGap } from './fairValueGaps'
import { layoutChartLabels } from './chartLabels'

type Zone = FairValueGap & {
  left: number
  top: number
  width: number
  height: number
  labelTop: number | null
}
/** Screen geometry only. Gaps are computed from the same candles as the chart. */
export function FairValueGapOverlay({
  chartRef,
  candleRef,
  containerRef,
  gaps,
  isDark,
}: {
  chartRef: RefObject<IChartApi | null>
  candleRef: RefObject<ISeriesApi<'Candlestick'> | null>
  containerRef: RefObject<HTMLDivElement | null>
  gaps: FairValueGap[]
  isDark: boolean
}) {
  const [zones, setZones] = useState<Zone[]>([])
  useLayoutEffect(() => {
    const update = () => {
      const chart = chartRef.current,
        candle = candleRef.current,
        container = containerRef.current
      const mainHeight = chart?.panes()[0]?.getHeight?.() || 0
      const width = Math.max(0, chart?.timeScale().width?.() ?? (container?.clientWidth || 0) - 64)
      const next: Zone[] = []
      if (chart && candle && container && mainHeight > 0 && width > 0) {
        for (const gap of gaps) {
          const top = candle.priceToCoordinate(gap.upper),
            bottom = candle.priceToCoordinate(gap.lower)
          const start = chart.timeScale().timeToCoordinate?.(gap.startTime as UTCTimestamp)
          if (top == null || bottom == null || start == null) continue
          const left = Math.max(0, Number(start)),
            y = Math.max(0, Number(top))
          const height = Math.min(mainHeight, Number(bottom)) - y
          if (left >= width || height <= 0) continue
          next.push({
            ...gap,
            left,
            top: y,
            width: width - left,
            height: Math.max(2, Math.min(height, mainHeight - y)),
            labelTop: null,
          })
        }
      }
      const labels = layoutChartLabels(
        next.map((zone) => ({
          title: zone.id,
          price: zone.lower,
          color: '',
          y: zone.top + zone.height / 2,
        })),
        mainHeight
      )
      for (const zone of next) {
        const label = labels.find((item) => item.title === zone.id)
        if (label) zone.labelTop = label.top - zone.top
      }
      setZones((old) => (JSON.stringify(old) === JSON.stringify(next) ? old : next))
    }
    update()
    if (!gaps.length) return
    const timer = setInterval(update, 200)
    return () => clearInterval(timer)
  }, [gaps, chartRef, candleRef, containerRef])
  return (
    <figure
      className="pointer-events-none absolute inset-0 z-[5] overflow-hidden"
      aria-label="Fair Value Gap zones"
    >
      <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
        {zones
          .filter((zone) => zone.labelTop != null)
          .map((zone) => (
            <path
              key={zone.id}
              d={`M ${zone.left + zone.width} ${zone.top + zone.height / 2} L ${zone.left + zone.width - 8} ${zone.top + zone.labelTop! + 11}`}
              fill="none"
              stroke={zone.direction === 'bullish' ? '#10b981' : '#f43f5e'}
              strokeWidth="1"
            />
          ))}
      </svg>
      {zones.map((zone) => {
        const bullish = zone.direction === 'bullish'
        const color = bullish ? (isDark ? '#6ee7b7' : '#047857') : isDark ? '#fda4af' : '#be123c'
        return (
          <div
            key={zone.id}
            className="absolute border-y border-dashed"
            style={{
              left: zone.left,
              top: zone.top,
              width: zone.width,
              height: zone.height,
              borderColor: color,
              backgroundColor: bullish ? 'rgba(16,185,129,0.06)' : 'rgba(244,63,94,0.06)',
            }}
          >
            {zone.labelTop != null && (
              <span
                className="absolute right-1 truncate rounded px-1 py-0.5 text-[11px] font-semibold tabular-nums"
                title={`${bullish ? 'Bullish' : 'Bearish'} Fair Value Gap ${zone.lower.toFixed(2)}–${zone.upper.toFixed(2)}${zone.touched ? ', partially filled' : ''}`}
                style={{
                  top: zone.labelTop,
                  maxWidth: Math.max(0, zone.left + zone.width - 8),
                  color,
                  backgroundColor: isDark ? '#111827' : '#ffffff',
                }}
              >
                {bullish ? '↑ FVG' : '↓ FVG'}
              </span>
            )}
          </div>
        )
      })}
    </figure>
  )
}
