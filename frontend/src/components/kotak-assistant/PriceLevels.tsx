import type { Snapshot } from '@/api/kotakAssistant'
import { money } from './model'

export const LEVEL_COLORS = {
  entry: '#2563eb',
  stop: '#dc2626',
  target: '#16a34a',
  support: '#0891b2',
  resistance: '#d97706',
}
export interface DraftLevels {
  symbol: string
  mode: string
  entry: number
  sl: number
  target: number
}

export function OptionLevels({
  entry,
  sl,
  target,
  actual = false,
  protectedStop = false,
  autoTarget = false,
}: {
  entry?: number | null
  sl?: number | null
  target?: number | null
  actual?: boolean
  protectedStop?: boolean
  autoTarget?: boolean
}) {
  const positive = (v: number | null | undefined) => (v != null && v > 0 ? money(v) : 'Not set')
  return (
    <div className="space-y-3 rounded-lg border p-3" aria-label="Option entry and exit levels">
      <p className="text-sm font-semibold">
        {actual ? 'Open trade · option premium in ₹' : 'Trade plan · option premium in ₹'}
      </p>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {[
          {
            label: actual ? 'Filled entry' : 'Buy entry limit',
            value: positive(entry),
            color: LEVEL_COLORS.entry,
            help: actual ? 'Average price of your fills' : 'Maximum premium to pay per unit',
          },
          {
            label: 'Stop loss (SL)',
            value: actual && !protectedStop ? 'Unconfirmed' : positive(sl),
            color: LEVEL_COLORS.stop,
            help:
              actual && protectedStop
                ? 'Broker-confirmed stop loss'
                : 'Exit if the option falls to this trigger',
          },
          {
            label: 'Profit target',
            value: positive(target),
            color: LEVEL_COLORS.target,
            help: autoTarget ? 'Automatic target exit enabled' : 'Manual exit at this level',
          },
        ].map((l) => (
          <div key={l.label} className="min-w-0 border-l-4 pl-3" style={{ borderColor: l.color }}>
            <dt className="text-xs text-muted-foreground">{l.label}</dt>
            <dd className="mt-1 text-xl font-semibold tabular-nums">{l.value}</dd>
            <dd className="text-xs text-muted-foreground">{l.help}</dd>
          </div>
        ))}
      </dl>
      <p className="text-sm text-muted-foreground">
        {actual
          ? 'Exit full sells the remaining position now. An exit is complete only after broker fills are confirmed.'
          : 'Buy places a limit order; entry is confirmed only when it fills. The protective SELL stop attaches to the filled quantity.'}
      </p>
      {actual && !protectedStop && (
        <p className="text-sm font-medium text-destructive">
          Stop protection is not confirmed. Check the trade status and broker response below.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        {autoTarget
          ? 'The server monitors the target and sends an exit when triggered; execution price can differ.'
          : 'Target is a guide. Use Exit full when reached, or enable Automatic target before entry.'}
      </p>
    </div>
  )
}

export function MarketStructure({
  index,
  price,
  zones,
  fresh,
}: {
  index: string
  price?: number
  zones: Snapshot['analysis']['zones']
  fresh: boolean
}) {
  const valid = zones.filter((z) => Number.isFinite(z.price) && z.price > 0)
  const support =
    price && price > 0
      ? valid
          .filter((z) => z.kind === 'low' && z.price <= price)
          .sort((a, b) => b.price - a.price)[0]
      : undefined
  const resistance =
    price && price > 0
      ? valid
          .filter((z) => z.kind === 'high' && z.price >= price)
          .sort((a, b) => a.price - b.price)[0]
      : undefined
  return (
    <div
      className="rounded-lg border bg-card px-4 py-3 space-y-2"
      aria-label="Index support and resistance"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">{index} support & resistance</h3>
        <span className="text-xs text-muted-foreground">Index points · not option prices</span>
      </div>
      <dl className="grid grid-cols-2 gap-3">
        {[
          {
            label: 'Support below price',
            zone: support,
            color: LEVEL_COLORS.support,
            help: 'Area where buyers previously defended the index.',
          },
          {
            label: 'Resistance above price',
            zone: resistance,
            color: LEVEL_COLORS.resistance,
            help: 'Area where sellers previously held back the index.',
          },
        ].map((l) => (
          <div
            key={l.label}
            className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5 border-l-2 pl-3"
            style={{ borderColor: l.color }}
          >
            <dt className="text-xs text-muted-foreground">{l.label}</dt>
            <dd className="text-lg font-semibold tabular-nums">
              {l.zone
                ? l.zone.price.toLocaleString('en-IN', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })
                : 'Not available'}
            </dd>
            <dd className="basis-full text-xs text-muted-foreground">
              {l.zone?.source || 'No confirmed level'}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted-foreground">
        {fresh
          ? 'Completed-candle levels · liquidity observations, not confirmed institutional activity.'
          : 'Last calculated levels · index quote stale. Wait for fresh data.'}
      </p>
    </div>
  )
}
