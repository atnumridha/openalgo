import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { DeskMode, Leg, Trade, PivotOverlay } from '@/api/kotakAssistant'
import { Button } from '@/components/ui/button'
import { KotakAssistantChart } from './KotakAssistantChart'
import { LEVEL_COLORS } from './PriceLevels'
import { money } from './model'
import type { ChartPosition } from './chartPosition'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { candleKey, useChartCandles } from './chartCandleStore'
import { ChartReplayControls } from './ChartReplayControls'
import type { ChartReplay, ReplayFrame } from './chartReplay'
import { useDashboardReplay } from './useDashboardReplay'
import { pivotChartLevels } from './pivotChart'

type Level = { price: number; title: string; color: string }
type Fill = { symbol: string; epoch: number; action: string; average_price: number }

function positionFor(trade?: Trade): ChartPosition | undefined {
  if (!trade || trade.remaining <= 0) return undefined
  return {
    status: trade.average_entry_verified === false ? 'unavailable' : 'open',
    currency: 'INR',
    entry: trade.average_entry,
    quantity: trade.remaining,
    gross: trade.gross_open ?? null,
    sl: trade.status === 'protected' ? (trade.current_sl ?? null) : null,
    target: trade.target,
    slGross:
      trade.average_entry && trade.current_sl
        ? (trade.current_sl - trade.average_entry) * trade.remaining
        : null,
    targetGross: trade.average_entry
      ? (trade.target - trade.average_entry) * trade.remaining
      : null,
    protectionAvailable: trade.status === 'protected',
  }
}

function OptionChart({
  symbol,
  trade,
  fills,
  ...chart
}: {
  symbol: string
  trade?: Trade
  fills: Fill[]
  exchange: string
  interval: string
  title: string
  levels?: Level[]
  replay?: ChartReplay
  showFvg?: boolean
}) {
  const position = useMemo(() => positionFor(trade), [trade])
  const markers = useMemo(
    () =>
      fills
        .filter((f) => f.symbol === symbol)
        .map((f) => ({ time: f.epoch, action: f.action, price: f.average_price })),
    [fills, symbol]
  )
  return (
    <KotakAssistantChart
      {...chart}
      symbol={symbol}
      position={position}
      markers={markers}
      protectionLabel="broker-accepted stop"
    />
  )
}

export function ScalpingCharts({
  ce,
  pe,
  underlying,
  expiry,
  strike,
  exchange,
  indexExchange,
  interval,
  onIntervalChange,
  selected,
  select,
  mode,
  trades,
  indexLevels,
  pivotOverlay,
  indexMarkers,
  onReplayTimeChange,
  activeLevels,
  ceLevels,
  peLevels,
  ceOrderControls,
  peOrderControls,
  fills,
  children,
}: {
  ce?: Leg | null
  pe?: Leg | null
  underlying: string
  expiry: string
  strike?: number
  exchange: string
  indexExchange: string
  interval: string
  onIntervalChange: (value: string) => void
  selected: string
  select: (symbol: string) => void
  mode: DeskMode
  trades: Trade[]
  pivotOverlay?: PivotOverlay | null
  indexLevels: Level[]
  indexMarkers?: Array<{
    time: number
    action: string
    price: number
    label?: string
    side?: 'above' | 'below'
    color?: string
  }>
  onReplayTimeChange?: (time: number | null) => void
  activeLevels?: Level[]
  ceLevels?: Level[]
  peLevels?: Level[]
  ceOrderControls?: ReactNode
  peOrderControls?: ReactNode
  fills: Fill[]
  children?: ReactNode
}) {
  const [layout, setLayout] = useState<'three' | 'two'>('three')
  const [showFvg, setShowFvg] = useState(true)
  const username = useAuthStore((s) => s.user?.username)
  const appMode = useThemeStore((s) => s.appMode)
  const [frame, setFrame] = useState<ReplayFrame | null>(null)
  const ceKey = candleKey(username, appMode, ce?.symbol || '', exchange, interval)
  const peKey = candleKey(username, appMode, pe?.symbol || '', exchange, interval)
  const indexKey = candleKey(username, appMode, underlying, indexExchange, interval)
  const actualIndexBars = useChartCandles(indexKey)
  const keys = useMemo(
    () => (layout === 'three' ? [ceKey, indexKey, peKey] : [ceKey, peKey]),
    [layout, ceKey, peKey, indexKey]
  )
  const replayDates = useDashboardReplay(
    keys,
    layout === 'three'
      ? [
          { symbol: ce?.symbol || '', exchange },
          { symbol: underlying, exchange: indexExchange },
          { symbol: pe?.symbol || '', exchange },
        ]
      : [
          { symbol: ce?.symbol || '', exchange },
          { symbol: pe?.symbol || '', exchange },
        ],
    interval,
    exchange
  )
  const { start: fromDate, end: toDate } = replayDates.range
  const scope = JSON.stringify([keys, mode, layout, fromDate, toDate])
  const activeFrame = frame?.scope === scope ? frame : null
  useEffect(() => {
    onReplayTimeChange?.(activeFrame ? activeFrame.until - 19800 : null)
  }, [activeFrame?.until, scope, onReplayTimeChange])
  const replayByKey = useMemo(
    () =>
      Object.fromEntries(
        keys.map((key) => [
          key,
          activeFrame
            ? {
                bars: activeFrame.series[key],
                until: activeFrame.until,
                seconds: activeFrame.seconds,
              }
            : undefined,
        ])
      ),
    [keys, activeFrame]
  ) as Record<string, ChartReplay | undefined>
  const optionPane = (side: 'CE' | 'PE', leg?: Leg | null) => {
    const active = !!leg && leg.symbol === selected
    const trade = trades.find((t) => t.symbol === leg?.symbol && t.mode === mode)
    return (
      <div
        role="group"
        aria-label={`${side} chart panel`}
        onMouseEnter={() => leg && !active && select(leg.symbol)}
        className={`min-w-0 overflow-hidden border-r last:border-r-0 ${active ? 'ring-1 ring-inset ring-primary/70' : ''}`}
        key={side}
      >
        <div className="h-[560px] min-[1000px]:h-[min(74vh,860px)] min-[1000px]:min-h-[600px]">
          {leg ? (
            <OptionChart
              symbol={leg.symbol}
              exchange={exchange}
              interval={interval}
              title={`${underlying} ${strike} ${side} · ${expiry}`}
              trade={trade}
              levels={(side === 'CE' ? ceLevels : peLevels) ?? (active ? activeLevels : undefined)}
              fills={fills}
              replay={replayByKey[side === 'CE' ? ceKey : peKey]}
              showFvg={showFvg}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              Choose expiry and strike for {side}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t bg-muted/20 p-3">
          <div className="text-sm">
            <strong>{side === 'CE' ? 'Call · CE' : 'Put · PE'}</strong>
            <span className="ml-2 tabular-nums">{money(leg?.ltp ?? leg?.ask)}</span>
            {activeFrame && (
              <span className="ml-2 text-xs text-muted-foreground">Live ticket price</span>
            )}
          </div>
          <Button
            size="sm"
            variant={active ? 'secondary' : 'outline'}
            disabled={!leg}
            aria-label={`Select ${side} for order`}
            aria-pressed={active}
            onClick={() => leg && select(leg.symbol)}
          >
            {active ? 'Active ticket' : `Select ${side}`}
          </Button>
        </div>
        {side === 'CE' ? ceOrderControls : peOrderControls}
      </div>
    )
  }
  return (
    <section
      aria-label="Scalping chart terminal"
      className="overflow-hidden rounded-xl border bg-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-3 py-2">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-sm font-semibold">Scalping terminal</h3>
          <div className="flex gap-1" role="group" aria-label="Chart instrument">
            <Button
              size="sm"
              variant={layout === 'three' ? 'secondary' : 'ghost'}
              aria-label="CE index and PE charts"
              aria-pressed={layout === 'three'}
              onClick={() => setLayout('three')}
            >
              CE · Index · PE
            </Button>
            <Button
              size="sm"
              variant={layout === 'two' ? 'secondary' : 'ghost'}
              aria-label="CE and PE charts"
              aria-pressed={layout === 'two'}
              onClick={() => setLayout('two')}
            >
              CE · PE
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">Candles · EMA · Volume · RSI 14</span>
          <label
            className="flex items-center gap-1.5 text-xs"
            title="Three-candle Fair Value Gaps. Zones appear after confirmation and disappear when fully filled."
          >
            <input
              type="checkbox"
              checked={showFvg}
              onChange={(e) => setShowFvg(e.target.checked)}
              className="accent-primary"
            />
            Fair Value Gaps
          </label>
          <select
            aria-label="Chart timeframe"
            className="h-9 rounded border bg-background px-2 text-sm"
            value={interval}
            onChange={(e) => onIntervalChange(e.target.value)}
          >
            {['1m', '5m', '15m'].map((v) => (
              <option key={v} value={v}>
                {v === '5m' ? '5m · Recommended' : v}
              </option>
            ))}
          </select>
        </div>
      </div>
      <ChartReplayControls
        key={scope}
        scope={scope}
        keys={keys}
        interval={interval}
        onChange={setFrame}
        sessionDate={fromDate}
        sessionEndDate={toDate}
        onSessionRangeChange={replayDates.setSelectedRange}
        sources={replayDates.sources}
        loading={replayDates.loading}
        unavailable={replayDates.unavailable}
      />
      {(replayDates.message || replayDates.selectedRange) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-1 text-xs text-muted-foreground">
          <span role="status">{replayDates.message}</span>
          {replayDates.canRetry && (
            <Button size="sm" variant="outline" onClick={replayDates.retry}>
              Retry replay history
            </Button>
          )}
          {replayDates.selectedRange && (
            <Button size="sm" variant="ghost" onClick={() => replayDates.setSelectedRange(null)}>
              Use market default
            </Button>
          )}
        </div>
      )}
      {children}
      <div
        className={`grid grid-cols-1 ${layout === 'three' ? 'min-[760px]:grid-cols-3' : 'min-[760px]:grid-cols-2'}`}
      >
        {optionPane('CE', ce)}
        {layout === 'three' && (
          <div
            role="group"
            aria-label="Index chart panel"
            className="min-w-0 overflow-hidden border-r"
          >
            <div className="h-[560px] min-[1000px]:h-[min(74vh,860px)] min-[1000px]:min-h-[600px]">
              <KotakAssistantChart
                symbol={underlying}
                exchange={indexExchange}
                interval={interval}
                title={`${underlying} · spot index`}
                levels={[...indexLevels, ...pivotChartLevels(pivotOverlay, underlying, fromDate, toDate, !!activeFrame, actualIndexBars[actualIndexBars.length - 1]?.time)]}
                markers={indexMarkers}
                replay={replayByKey[indexKey]}
                showFvg={showFvg}
              />
            </div>
            <div className="flex min-h-[61px] items-center border-t bg-muted/20 p-3 text-sm font-medium">
              {underlying} support & resistance
            </div>
          </div>
        )}
        {optionPane('PE', pe)}
      </div>
      <div
        aria-label="Chart level legend"
        className="flex flex-wrap gap-x-4 gap-y-1 border-t px-3 py-2 text-xs"
      >
        {[
          ['Entry', LEVEL_COLORS.entry],
          ['Stop loss', LEVEL_COLORS.stop],
          ['Target', LEVEL_COLORS.target],
          ['Support', LEVEL_COLORS.support],
          ['Resistance', LEVEL_COLORS.resistance],
        ].map(([label, color]) => (
          <span key={label} className="inline-flex items-center gap-1.5">
            <span className="w-4 border-t-2" style={{ borderColor: color }} aria-hidden="true" />
            {label}
          </span>
        ))}
        {showFvg && (
          <span className="text-muted-foreground">
            FVG: ↑ bullish · ↓ bearish · touched = partly filled · fully filled zones removed
          </span>
        )}
      </div>
    </section>
  )
}
