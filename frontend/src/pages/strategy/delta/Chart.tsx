import { useBrokerPriceFormatter } from '@/hooks/useBrokerCurrencyFormatter'
import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  ColorType,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useThemeStore } from '@/stores/themeStore'
import type { Candle, Amount } from './types'
export default function Chart({
  candles = [],
  levels = {},
  lines = [],
}: {
  candles?: Candle[]
  levels?: Record<string, Amount>
  lines?: { name: string; color: string; data: { time: number; value: number }[] }[]
}) {
  const display = useBrokerPriceFormatter('deltaexchange')
  const displayRef = useRef(display)
  displayRef.current = display
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<ReturnType<typeof createChart> | null>(null)
  const candle = useRef<ReturnType<ReturnType<typeof createChart>['addSeries']> | null>(null)
  const extras = useRef<ReturnType<ReturnType<typeof createChart>['addSeries']>[]>([])
  const fitted = useRef(false)
  const { mode } = useThemeStore()
  useEffect(() => { chart.current?.applyOptions({localization:{priceFormatter:display}}) }, [display])
  useEffect(() => {
    if (!host.current) return
    const dark = mode === 'dark'
    chart.current = createChart(host.current, {
      autoSize: true,
      height: 370,
      layout: {
        background: { type: ColorType.Solid, color: dark ? '#111827' : '#ffffff' },
        textColor: dark ? '#b5c0d1' : '#39465b',
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: dark ? '#1f2937' : '#f1f5f9' },
        horzLines: { color: dark ? '#1f2937' : '#f1f5f9' },
      },
      timeScale: { timeVisible: true },
      localization: {
        priceFormatter: (value: number) => displayRef.current(value),
        timeFormatter: (t: number) =>
          new Date(t * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }),
      },
    })
    fitted.current = false
    return () => {
      chart.current?.remove()
      chart.current = null
      candle.current = null
      extras.current = []
    }
  }, [mode])
  useEffect(() => {
    const c = chart.current
    if (!c) return
    if (candle.current) {
      c.removeSeries(candle.current)
      candle.current = null
    }
    for (const s of extras.current) c.removeSeries(s)
    extras.current = []
    if (candles.length) {
      const s = c.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
      })
      s.setData(
        candles.map((b) => ({
          time: b.time as UTCTimestamp,
          open: Number(b.open),
          high: Number(b.high),
          low: Number(b.low),
          close: Number(b.close),
        }))
      )
      for (const [name, price] of Object.entries(levels))
        if (price != null && Number(price) > 0)
          s.createPriceLine({
            price: Number(price),
            title: name,
            color: name.includes('SL') ? '#ef5350' : '#2962ff',
            lineWidth: 1,
            axisLabelVisible: true,
          })
      candle.current = s
      for (const [key, color] of [
        ['ema9', '#e5a51a'],
        ['ema20', '#2962ff'],
        ['ema50', '#9c6ade'],
      ] as const) {
        const points = candles
          .filter((b) => b[key] != null)
          .map((b) => ({ time: b.time as UTCTimestamp, value: Number(b[key]) }))
        if (points.length) {
          const line = c.addSeries(LineSeries, { color, lineWidth: 1, title: key.toUpperCase() })
          line.setData(points)
          extras.current.push(line)
        }
      }
    }
    for (const value of lines) {
      const unique = new Map(value.data.map((p) => [p.time, p]))
      const line = c.addSeries(LineSeries, { color: value.color, title: value.name, lineWidth: 2 })
      line.setData(
        [...unique.values()]
          .sort((a, b) => a.time - b.time)
          .map((p) => ({ ...p, time: p.time as UTCTimestamp }))
      )
      extras.current.push(line)
    }
    if (!fitted.current && (candles.length || lines.some((l) => l.data.length))) {
      c.timeScale().fitContent()
      fitted.current = true
    }
  }, [candles, levels, lines, mode])
  return (
    <div>
      <div ref={host} className="h-[370px] w-full" aria-label="TradingView price chart" />
      <a
        className="text-xs text-muted-foreground underline"
        href="https://www.tradingview.com/"
        target="_blank"
        rel="noreferrer"
      >
        Charts by TradingView Lightweight Charts
      </a>
    </div>
  )
}
