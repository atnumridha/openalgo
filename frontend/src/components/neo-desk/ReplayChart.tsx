import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  LineSeries,
  LineStyle,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReplayTrade } from '@/api/neoResearch'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { useThemeStore } from '@/stores/themeStore'
import { formatIST, type PriceBar } from './tradingViewStudies'

const number = (value: unknown) =>
  value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value)
export function replayBars(input: PriceBar[]) {
  const unique = new Map<number, PriceBar>()
  for (const b of input)
    if (
      [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
      b.low > 0 &&
      b.low <= Math.min(b.open, b.close) &&
      b.high >= Math.max(b.open, b.close)
    )
      unique.set(b.time, b)
  return [...unique.values()].sort((a, b) => a.time - b.time)
}
export function replayFrame(
  trade: ReplayTrade,
  show: 'option' | 'index',
  bars: PriceBar[],
  position: number
) {
  const spacing = Math.min(
    ...bars
      .slice(1)
      .map((b, i) => b.time - bars[i].time)
      .filter((n) => n > 0),
    show === 'index' && !trade.recorded ? 900 : 60
  )
  const visible = bars.slice(0, position + 1),
    cutoff = visible.length ? visible[visible.length - 1].time + spacing - 1 : 0
  const entry = Date.parse(trade.entry_time) / 1000,
    exit = trade.exit_time ? Date.parse(trade.exit_time) / 1000 : null
  const bucket = (time: number) =>
    visible.find((b) => b.time <= time && time < b.time + spacing)?.time
  const marks = []
  const entryBucket = bucket(entry)
  if (entryBucket != null)
    marks.push({
      time: entryBucket as UTCTimestamp,
      position: 'belowBar' as const,
      shape: 'arrowUp' as const,
      color: '#26a69a',
      text: `${trade.entry_side || 'BUY'} ${trade.direction}`.trim(),
    })
  const exitBucket = exit == null ? undefined : bucket(exit)
  if (exitBucket != null)
    marks.push({
      time: exitBucket as UTCTimestamp,
      position: 'aboveBar' as const,
      shape: 'arrowDown' as const,
      color: '#ef5350',
      text: 'EXIT',
    })
  const points = new Map<number, { time: UTCTimestamp; value: number }>()
  const observed = trade.trail.filter((t) => t.time <= cutoff)
  for (const t of observed) {
    const time = bucket(t.time),
      value = number(show === 'index' ? t.index_stop : t.option_stop)
    if (time != null && value != null) points.set(time, { time: time as UTCTimestamp, value })
  }
  const last = observed.at(-1)
  const levels: Array<{ price: number; title: string; color: string }> = []
  const line = (value: unknown, title: string, color: string) => {
    const price = number(value)
    if (price != null && price > 0) levels.push({ price, title, color })
  }
  if (entry <= cutoff) {
    line(
      show === 'option' ? trade.entry_price : (last?.index_reference ?? trade.index_reference),
      'ENTRY',
      '#2962ff'
    )
    line(
      show === 'option'
        ? (last?.option_stop ?? trade.initial_option_stop)
        : (last?.index_stop ?? trade.initial_index_stop),
      'SL / trail',
      '#ef5350'
    )
    line(
      show === 'option'
        ? (last?.option_target ?? trade.option_target)
        : (last?.index_target ?? trade.index_target),
      'TARGET',
      '#26a69a'
    )
  }
  if (exit != null && exit <= cutoff && show === 'option') line(trade.exit_price, 'EXIT', '#a78bfa')
  return {
    visible,
    cutoff,
    marks,
    trail: [...points.values()].sort((a, b) => a.time - b.time),
    levels,
    netFloor: last?.net_floor,
  }
}
interface Scene {
  chart: IChartApi
  price: ISeriesApi<'Candlestick'>
  trail: ISeriesApi<'Line'>
  markers: ISeriesMarkersPluginApi<Time>
  levels: IPriceLine[]
}
export function ReplayChart({
  trade,
  source = 'Backtest model · saved observations',
  notes = [],
}: {
  trade: ReplayTrade
  source?: string
  notes?: string[]
}) {
  const [show, setShow] = useState<'option' | 'index'>('option'),
    [position, setPosition] = useState(Number.MAX_SAFE_INTEGER),
    [playing, setPlaying] = useState(false),
    [error, setError] = useState(''),
    [ready, setReady] = useState(0)
  const host = useRef<HTMLDivElement>(null),
    scene = useRef<Scene | null>(null),
    theme = useThemeStore((s) => s.mode),
    appMode = useThemeStore((s) => s.appMode)
  const bars = useMemo(() => {
    const all = replayBars(show === 'option' ? trade.option_bars : trade.index_bars)
    if (!trade.recorded || !trade.exit_time) return all
    const from = Date.parse(trade.entry_time) / 1000 - 15 * 60
    const through = Date.parse(trade.exit_time) / 1000 + 15 * 60
    return all.filter((b) => b.time >= from && b.time <= through)
  }, [trade, show])
  const cursor = Math.min(position, Math.max(0, bars.length - 1)),
    frame = useMemo(() => replayFrame(trade, show, bars, cursor), [trade, show, bars, cursor])
  useEffect(() => {
    if (!host.current) return
    const dark = theme === 'dark' || appMode === 'analyzer'
    try {
      const chart = createChart(host.current, {
        autoSize: true,
        layout: {
          background: { color: dark ? '#131722' : '#ffffff' },
          textColor: dark ? '#b2b5be' : '#434651',
          fontFamily: 'Inter,system-ui,sans-serif',
          attributionLogo: true,
        },
        grid: {
          vertLines: { color: dark ? '#1e222d' : '#f0f3fa' },
          horzLines: { color: dark ? '#1e222d' : '#f0f3fa' },
        },
        rightPriceScale: { scaleMargins: { top: 0.18, bottom: 0.15 } },
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 6,
          tickMarkFormatter: (t: Time) => (typeof t === 'number' ? formatIST(t) : String(t)),
        },
        localization: {
          timeFormatter: (t: Time) =>
            typeof t === 'number' ? `${formatIST(t, true)} IST` : String(t),
        },
      })
      const price = chart.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
        borderVisible: false,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      scene.current = {
        chart,
        price,
        trail: chart.addSeries(LineSeries, {
          color: '#ef5350',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
        }),
        markers: createSeriesMarkers(price, []),
        levels: [],
      }
      setReady((v) => v + 1)
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
    return () => {
      scene.current?.chart.remove()
      scene.current = null
    }
  }, [theme, appMode])
  useEffect(() => {
    const s = scene.current
    if (!ready || !s) return
    try {
      s.price.setData(frame.visible.map((b) => ({ ...b, time: b.time as UTCTimestamp })))
      s.trail.setData(frame.trail)
      s.markers.setMarkers(frame.marks)
      for (const p of s.levels) s.price.removePriceLine(p)
      s.levels = frame.levels.map((l) =>
        s.price.createPriceLine({
          ...l,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
        })
      )
      s.chart.timeScale().fitContent()
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [frame, ready])
  useEffect(() => {
    if (!playing) return
    if (cursor >= bars.length - 1) {
      setPlaying(false)
      return
    }
    const timer = window.setTimeout(() => setPosition(cursor + 1), 600)
    return () => window.clearTimeout(timer)
  }, [playing, cursor, bars.length])
  function switchView(view: 'option' | 'index') {
    setPlaying(false)
    setPosition(Number.MAX_SAFE_INTEGER)
    setShow(view)
  }
  return (
    <section
      className="rounded-lg border bg-card p-4 space-y-3"
      aria-label={`Trade replay ${trade.symbol}`}
    >
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h3 className="font-semibold">
            {trade.symbol} · {trade.quantity} units
          </h3>
          <p className="text-xs text-muted-foreground">{source}</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={show === 'option' ? 'default' : 'outline'}
            onClick={() => switchView('option')}
          >
            Option premium
          </Button>
          <Button
            variant={show === 'index' ? 'default' : 'outline'}
            disabled={!trade.index_bars.length}
            onClick={() => switchView('index')}
          >
            {trade.underlying || 'NIFTY'} index
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          disabled={!bars.length}
          onClick={() => {
            setPlaying(false)
            setPosition(0)
          }}
        >
          Replay from start
        </Button>
        <Button
          disabled={!bars.length}
          onClick={() => {
            if (cursor >= bars.length - 1) setPosition(0)
            setPlaying(!playing)
          }}
        >
          {playing ? 'Pause replay' : 'Play replay'}
        </Button>
        <Button
          variant="outline"
          disabled={!bars.length || cursor === 0}
          onClick={() => {
            setPlaying(false)
            setPosition(cursor - 1)
          }}
        >
          Previous candle
        </Button>
        <Button
          variant="outline"
          disabled={!bars.length || cursor >= bars.length - 1}
          onClick={() => {
            setPlaying(false)
            setPosition(cursor + 1)
          }}
        >
          Next candle
        </Button>
        <Button
          variant="outline"
          disabled={!bars.length}
          onClick={() => {
            setPlaying(false)
            setPosition(Number.MAX_SAFE_INTEGER)
          }}
        >
          Show full trade
        </Button>
      </div>
      <Label className="block">
        Replay candle
        <input
          aria-label="Replay candle"
          type="range"
          min={0}
          max={Math.max(0, bars.length - 1)}
          value={cursor}
          disabled={!bars.length}
          onChange={(e) => {
            setPlaying(false)
            setPosition(Number(e.target.value))
          }}
          className="block w-full accent-primary"
        />
      </Label>
      <output className="block font-mono text-xs" aria-label="Replay position">
        {bars.length
          ? `${cursor + 1} / ${bars.length} · ${formatIST(frame.visible.at(-1)!.time, true)} IST · close ₹${frame.visible.at(-1)!.close.toFixed(2)}`
          : 'No saved candles for this instrument.'}
      </output>
      <div
        ref={host}
        className="h-[420px] w-full"
        role="img"
        aria-label={`Historical ${show} candles with recorded entry, exit and available protection`}
      />
      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span className="text-blue-500">ENTRY</span>
        <span className="text-red-500">SL / trailing stop</span>
        <span className="text-emerald-600 dark:text-emerald-400">TARGET</span>
        <span className="text-violet-500">EXIT</span>
      </div>
      {frame.netFloor != null ? (
        <p className="text-xs">
          Recorded cash trailing floor: ₹{frame.netFloor}. This is a net-profit threshold, not an
          option premium price.
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        {trade.status} · {trade.reason}.{' '}
        {show === 'option'
          ? 'Option prices in ₹ per unit. Index 6R targets appear in the index view.'
          : 'Index points. SL and target belong to the underlying index.'}{' '}
        Playback shows saved candles and protection known by that candle; gaps remain empty. Minute
        candles do not reveal the order of ticks inside a candle.
      </p>
      {notes.map((note) => (
        <p key={note} className="text-sm text-muted-foreground">
          {note}
        </p>
      ))}
    </section>
  )
}
