import type { MoneyFormatter } from '@/lib/deltaCurrency'
import { Activity, Gauge, Receipt, ShieldAlert, Target } from 'lucide-react'
import type { RiskOverview, StrategyRiskState } from '@/api/risk'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { Position } from '@/types/trading'

/** The running strategies with an open trade on this row's contract. */
export function strategiesForPosition(
  overview: RiskOverview | null,
  position: Pick<Position, 'symbol' | 'exchange' | 'product'>
): StrategyRiskState[] {
  return (overview?.strategies ?? []).filter(
    (s) =>
      s.running &&
      s.position &&
      s.symbol === position.symbol &&
      s.exchange === position.exchange &&
      (!s.product || !position.product || s.product === position.product)
  )
}

/** "Delta BTC EMA 20/50 1h" -> "EMA 20/50 1h", to label a row that two strategies share. */
export function shortStrategyName(name: string) {
  return name.replace(/^Delta\s+BTC\s+/i, '')
}

/**
 * Exit price at which this trade breaks even after the round-trip fee.
 * Long: entry x (1 + fee). Short: entry x (1 - fee).
 */
export function breakEvenPrice(entry: number, side: 'LONG' | 'SHORT', roundTripPct: number) {
  return entry * (1 + (side === 'LONG' ? 1 : -1) * (roundTripPct / 100))
}

export function liquidationPrice(entry: number, side: 'LONG' | 'SHORT', movePct: number | null) {
  if (movePct == null) return null
  return entry * (1 - (side === 'LONG' ? 1 : -1) * (movePct / 100))
}

function usd(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(v)) return '-'
  return v.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function signedPct(v: number, digits = 2) {
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`
}

function Row({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'up' | 'down'
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-right">
        <span
          className={cn(
            'font-mono text-sm',
            tone === 'up' && 'text-green-600',
            tone === 'down' && 'text-red-600'
          )}
        >
          {value}
        </span>
        {sub && <span className="ml-1.5 text-xs text-muted-foreground">{sub}</span>}
      </span>
    </div>
  )
}

function TradeCard({
  s,
  ltp,
  overview,
  money = usd,
}: {
  money?: MoneyFormatter
  s: StrategyRiskState
  ltp?: number
  overview: RiskOverview
}) {
  const p = s.position
  if (!p) return null
  const fixedTarget = p.target_type === 'fixed' && p.target_price != null
  const sign = p.side === 'LONG' ? 1 : -1
  const live = ltp && ltp > 0 ? ltp : (p.live ?? p.entry)
  const move = ((sign * (live - p.entry)) / p.entry) * 100
  const roundTrip = s.fees.round_trip_pct
  const net = move - roundTrip
  const netUsd = (p.notional_usd * net) / 100
  const lev = s.leverage ?? overview.leverage
  const liqMove = s.liquidation_move_pct ?? overview.liquidation_move_pct
  const liq = liquidationPrice(p.entry, p.side, liqMove)
  const be = breakEvenPrice(p.entry, p.side, roundTrip)
  const distToStop = ((sign * (live - p.stop_price)) / live) * 100
  const stopMovePct = ((sign * (p.stop_price - p.entry)) / p.entry) * 100
  const stopUsd = (p.notional_usd * (stopMovePct - roundTrip)) / 100

  return (
    <Card
      className="border-l-4"
      style={{ borderLeftColor: p.side === 'LONG' ? '#16a34a' : '#dc2626' }}
    >
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">
            <span className={p.side === 'LONG' ? 'text-green-600' : 'text-red-600'}>{p.side}</span>{' '}
            {s.symbol} @ {usd(p.entry)}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline">{lev ? `${lev}x leverage` : 'Default leverage'}</Badge>
            <Badge
              variant="outline"
              className={
                s.mode === 'live'
                  ? 'border-red-500/40 bg-red-500/10 text-red-600'
                  : 'border-violet-500/40 bg-violet-500/10 text-violet-600'
              }
            >
              {s.mode === 'live' ? 'LIVE' : 'Analyze'}
            </Badge>
          </div>
        </div>
        <CardDescription>
          {s.strategy} · notional {money(p.notional_usd)} · margin {money(p.margin_usd)}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-x-8 gap-y-1 sm:grid-cols-3">
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-red-600">
            <ShieldAlert className="h-3.5 w-3.5" />
            {p.trailing ? 'Trailing stop (locks profit)' : 'Stop loss'}
          </div>
          <Row
            label="Price"
            value={usd(p.stop_price)}
            sub={signedPct(stopMovePct)}
            tone={stopMovePct >= 0 ? 'up' : 'down'}
          />
          <Row
            label="If hit, after fees"
            value={money(stopUsd)}
            sub={lev ? `${signedPct((stopMovePct - roundTrip) * lev, 1)} of margin` : undefined}
            tone={stopUsd >= 0 ? 'up' : 'down'}
          />
          <Row label="Distance from live" value={`${distToStop.toFixed(2)}%`} />
          {liq != null && (
            <Row label="Liquidation" value={usd(liq)} sub={`${liqMove?.toFixed(2)}% away`} />
          )}
        </div>

        <div>
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-green-600">
            <Target className="h-3.5 w-3.5" />
            {fixedTarget ? 'Take profit (fixed)' : 'Take profit (trailing)'}
          </div>
          {fixedTarget ? (
            <Row
              label="Target"
              value={usd(p.target_price as number)}
              sub={signedPct(((sign * ((p.target_price as number) - p.entry)) / p.entry) * 100)}
              tone="up"
            />
          ) : (
            <>
              <Row
                label={p.trailing ? 'Trail armed at' : 'Trail arms at'}
                value={usd(p.trail_arm_price)}
                sub={signedPct(sign * ((p.trail_arm_price - p.entry) / p.entry) * 100)}
                tone="up"
              />
              <Row label="Trails behind best by" value={`${p.trail_gap_pct.toFixed(2)}%`} />
            </>
          )}
          <Row
            label="Best move so far"
            value={signedPct(p.best_move_pct, 3)}
            tone={p.best_move_pct > 0 ? 'up' : undefined}
          />
          {p.time_exit_at && !p.trailing && (
            <Row
              label={fixedTarget ? 'Closed at' : 'Closed if flat at'}
              value={new Date(p.time_exit_at).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })}
              sub={
                s.rules.max_hold_hours < 1
                  ? `${Math.round(s.rules.max_hold_hours * 60)} min max`
                  : `${s.rules.max_hold_hours}h max`
              }
            />
          )}
        </div>

        <div>
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <Receipt className="h-3.5 w-3.5" />
            Fees and net P&L
          </div>
          <Row
            label="Round-trip fees"
            value={money(p.fees_usd_round_trip, 3)}
            sub={`${roundTrip.toFixed(3)}%`}
          />
          <Row label="Break-even exit" value={usd(be)} />
          <Row
            label="Live"
            value={usd(live)}
            sub={signedPct(move, 3)}
            tone={move >= 0 ? 'up' : 'down'}
          />
          <Row
            label="Net P&L after fees"
            value={money(netUsd)}
            sub={lev ? `${signedPct(net * lev, 1)} of margin` : signedPct(net, 3)}
            tone={netUsd >= 0 ? 'up' : 'down'}
          />
        </div>
      </CardContent>
    </Card>
  )
}

export function PositionRiskPanel({
  overview,
  positions,
  money = usd,
}: {
  money?: MoneyFormatter
  overview: RiskOverview | null
  positions: Position[]
}) {
  if (!overview) return null
  const lev = overview.leverage
  const running = overview.strategies.filter((s) => s.running)
  const withTrade = running.filter((s) => s.position)
  const ltpFor = (s: StrategyRiskState) =>
    positions.find((p) => p.symbol === s.symbol && p.exchange === s.exchange)?.ltp

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Gauge className="h-3.5 w-3.5" /> Configured leverage
            </CardDescription>
            <CardTitle className="text-2xl">{lev ? `${lev}x` : 'Delta default'}</CardTitle>
            <p className="text-xs text-muted-foreground">
              {lev
                ? 'App order setting; actual Delta position leverage may differ'
                : 'Using broker default; actual leverage is not verified here'}
            </p>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <ShieldAlert className="h-3.5 w-3.5" /> Estimated liquidation distance
            </CardDescription>
            <CardTitle className="text-2xl">
              {overview.liquidation_move_pct != null
                ? `${overview.liquidation_move_pct.toFixed(2)}%`
                : '-'}
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Estimate from configured leverage, not a broker liquidation price (
              {overview.maintenance_margin_pct}% maintenance)
            </p>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Receipt className="h-3.5 w-3.5" /> Fees per round trip
            </CardDescription>
            <CardTitle className="text-2xl">
              {overview.fees.round_trip_taker_pct.toFixed(3)}%
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Taker {overview.fees.taker_pct}% per side + {overview.fees.gst_pct}% GST (maker{' '}
              {overview.fees.maker_pct}%), plus funding every 8h
            </p>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5" /> Strategies managing risk
            </CardDescription>
            <CardTitle className="text-2xl">{running.length}</CardTitle>
            <p className="text-xs text-muted-foreground">
              {running.length === 0
                ? 'No Python strategy is reporting stops'
                : running.map((s) => `${s.strategy} (${s.mode})`).join(', ')}
            </p>
          </CardHeader>
        </Card>
      </div>

      {withTrade.map((s) => (
        <TradeCard
          key={s.strategy_id || s.strategy}
          s={s}
          ltp={ltpFor(s)}
          overview={overview}
          money={money}
        />
      ))}

      {running
        .filter((s) => !s.position)
        .map((s) => (
          <Card key={`flat-${s.strategy_id || s.strategy}`} className="border-dashed">
            <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm">
              <span>
                <span className="font-medium">{s.strategy}</span>
                <span className="text-muted-foreground"> is flat on {s.symbol}. </span>
                <span className="text-muted-foreground">{s.rules.entry}.</span>
              </span>
              <span className="flex flex-wrap items-center gap-3 text-muted-foreground">
                {s.indicator ? (
                  <span>Now: {s.indicator}</span>
                ) : (
                  s.rsi != null && <span>RSI now {s.rsi.toFixed(1)}</span>
                )}
                {s.next_stop_pct != null && (
                  <span>Next stop loss {s.next_stop_pct.toFixed(2)}%</span>
                )}
                <span>
                  Today {s.day.trades} trades, {signedPct(s.day.net_pct, 2)}, fees{' '}
                  {money(s.day.fees_usd, 3)}
                </span>
                {s.day.halted && <Badge variant="destructive">Daily loss cap hit</Badge>}
              </span>
            </CardContent>
          </Card>
        ))}
    </div>
  )
}
