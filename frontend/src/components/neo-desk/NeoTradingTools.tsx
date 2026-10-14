import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { activeExpiries, nearestExpiry } from '@/lib/neoOptionSelection'
import type { OptionChainRow, OptionType } from '@/types/scalping'
export interface NeoChartTarget {
  loadSymbol: (instrument: { symbol: string; exchange: string }) => Promise<unknown>
  replayActive: () => boolean
  replayPickingBar: () => boolean
  dataUnavailable: () => boolean
  listIndicators: () => Array<{ id: string; indicatorId: string; name: string }>
  addIndicatorById: (id: string) => Promise<unknown>
  removeIndicatorById: (id: string) => unknown
}

const studies = ['neo-donchian', 'neo-structure', 'rsi']
const studyLabels: Record<string, string> = {
  'neo-donchian': 'Donchian / EMA',
  'neo-structure': 'FVG / levels',
  rsi: 'RSI 14',
}
export function NeoTradingTools({
  target,
  revision,
  initialize = true,
  shownSymbol,
}: {
  target: () => NeoChartTarget | null
  revision: number
  initialize?: boolean
  shownSymbol?: string
}) {
  const [expiry, setExpiry] = useState(''),
    [ce, setCe] = useState(''),
    [pe, setPe] = useState('')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [shown, setShown] = useState('')
  const [enabledStudies, setEnabledStudies] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('neo.native.chart.indicators') || 'null')
      return Array.isArray(saved) ? saved.filter((id) => studies.includes(id)) : studies
    } catch {
      return studies
    }
  })
  useEffect(() => {
    if (shownSymbol) setShown(shownSymbol)
  }, [shownSymbol])
  const initial = useRef(false),
    loading = useRef(false)
  const expiriesQuery = useQuery({
    queryKey: ['scalping', 'expiry', 'NFO', 'NIFTY'],
    queryFn: () => scalpingApi.getExpiry('NIFTY', 'NFO', 'options'),
    staleTime: 60000,
  })
  const dates = useMemo(() => activeExpiries(expiriesQuery.data?.data || []), [expiriesQuery.data])
  useEffect(() => {
    if (dates.length && !dates.includes(expiry)) setExpiry(nearestExpiry(dates))
  }, [dates, expiry])
  const chainQuery = useQuery({
    queryKey: ['scalping', 'strikes', 'NFO', 'NIFTY', expiry],
    queryFn: () => scalpingApi.getStrikes('NIFTY', 'NFO', expiry, 20),
    enabled: Boolean(expiry),
    staleTime: 30000,
  })
  const rows = useMemo(
    () => [...(chainQuery.data?.chain || [])].sort((a, b) => a.strike - b.strike),
    [chainQuery.data]
  )
  useEffect(() => {
    if (!rows.length) return
    const atm = String(chainQuery.data?.atm_strike ?? rows[0].strike)
    setCe((old) => (rows.some((r) => String(r.strike) === old && r.ce?.symbol) ? old : atm))
    setPe((old) => (rows.some((r) => String(r.strike) === old && r.pe?.symbol) ? old : atm))
  }, [rows, chainQuery.data])
  // Match the broker chain's nearest-ATM convention, not the option premium.
  function strikeLabel(row: OptionChainRow, side: OptionType): string {
    const atm = chainQuery.data?.atm_strike
    if (atm == null || !Number.isFinite(atm) || atm <= 0) return 'Unclassified'
    const reported = (side === 'CE' ? row.ce : row.pe)?.label
    if (reported && /^(ATM|ITM[0-9]*|OTM[0-9]*)$/.test(reported)) return reported
    if (row.strike === atm) return 'ATM'
    return (side === 'CE' ? row.strike < atm : row.strike > atm) ? 'ITM' : 'OTM'
  }
  async function applyStudies(pane: NeoChartTarget) {
    for (const id of studies) {
      const existing = pane.listIndicators().filter((s) => s.indicatorId === id)
      if (enabledStudies.includes(id)) {
        if (!existing.length) await pane.addIndicatorById(id)
      } else {
        for (const item of existing) pane.removeIndicatorById(item.id)
      }
    }
  }
  async function toggleStudy(id: string, on: boolean) {
    if (loading.current) return
    const pane = target()
    if (!pane || pane.dataUnavailable()) {
      setError('Wait for chart prices before changing overlays.')
      return
    }
    loading.current = true
    setBusy(true)
    setError('')
    try {
      if (on && !pane.listIndicators().some((s) => s.indicatorId === id))
        await pane.addIndicatorById(id)
      if (!on)
        for (const item of pane.listIndicators().filter((s) => s.indicatorId === id))
          pane.removeIndicatorById(item.id)
      const next = on
        ? [...new Set([...enabledStudies, id])]
        : enabledStudies.filter((item) => item !== id)
      setEnabledStudies(next)
      try {
        localStorage.setItem('neo.native.chart.indicators', JSON.stringify(next))
      } catch {
        /* This browser still keeps the choice for the current view. */
      }
    } catch {
      setError('This overlay could not be changed. Open Indicators or retry after reconnecting.')
    } finally {
      loading.current = false
      setBusy(false)
    }
  }
  async function chart(which: 'INDEX' | 'CE' | 'PE') {
    if (loading.current) return
    const pane = target()
    if (!pane || pane.replayActive() || pane.replayPickingBar()) {
      setError('Finish loading or stop chart replay before changing the contract.')
      return
    }
    const leg =
      which === 'INDEX'
        ? { symbol: 'NIFTY', exchange: 'NSE_INDEX' }
        : (() => {
            const row = rows.find((r) => String(r.strike) === (which === 'CE' ? ce : pe))
            const symbol = which === 'CE' ? row?.ce?.symbol : row?.pe?.symbol
            return symbol ? { symbol, exchange: 'NFO' } : null
          })()
    if (!leg) {
      setError('Choose a listed strike for this expiry.')
      return
    }
    // An explicit valid selection owns initialization, even after restored history failed.
    initial.current = true
    loading.current = true
    setBusy(true)
    setError('')
    try {
      await pane.loadSymbol(leg)
      await applyStudies(pane)
      if (pane.dataUnavailable())
        throw Error(
          'Prices are unavailable for this contract. Choose another listed strike or refresh broker data.'
        )
      setShown(leg.symbol)
    } catch {
      setError(
        'The chart could not load this contract and studies. Refresh the connection or choose another listed strike.'
      )
    } finally {
      loading.current = false
      setBusy(false)
    }
  }
  // Initial native chart readiness is delivered by the workspace revision.
  // biome-ignore lint/correctness/useExhaustiveDependencies: revision follows native pane readiness; initialize once
  useEffect(() => {
    if (!initialize || initial.current) return
    const tryDefault = () => {
      const pane = target()
      if (
        !initial.current &&
        pane &&
        !pane.dataUnavailable() &&
        !pane.replayActive() &&
        !pane.replayPickingBar()
      ) {
        initial.current = true
        void chart('INDEX')
      }
    }
    tryDefault()
    if (!initialize || initial.current) return
    const timer = setInterval(() => {
      tryDefault()
      if (initial.current) clearInterval(timer)
    }, 250)
    return () => clearInterval(timer)
  }, [revision, target, initialize])
  const problem =
    error ||
    (expiriesQuery.error || chainQuery.error
      ? 'Could not load NIFTY expiries or strikes. Refresh broker data.'
      : '')
  return (
    <section aria-label="NIFTY chart selection" className="shrink-0 border-b bg-card px-3 py-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="neo-chart-expiry" className="text-xs text-muted-foreground">
            NIFTY expiry
          </Label>
          <select
            id="neo-chart-expiry"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            disabled={busy || !dates.length}
            className="block h-9 min-w-28 rounded-md border bg-background px-2 text-sm"
          >
            {dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        {(['CE', 'PE'] as const).map((side) => (
          <div key={side} className="space-y-1">
            <Label htmlFor={`neo-chart-${side}`} className="text-xs text-muted-foreground">
              {side} strike
            </Label>
            <select
              id={`neo-chart-${side}`}
              value={side === 'CE' ? ce : pe}
              onChange={(e) => (side === 'CE' ? setCe(e.target.value) : setPe(e.target.value))}
              disabled={busy || !rows.length}
              className="block h-9 min-w-36 rounded-md border bg-background px-2 text-sm"
            >
              {rows
                .filter((r) => (side === 'CE' ? r.ce : r.pe)?.symbol)
                .map((r) => (
                  <option key={r.strike} value={String(r.strike)}>
                    {r.strike} · {strikeLabel(r, side)}
                  </option>
                ))}
            </select>
          </div>
        ))}
        <div
          className="flex items-center gap-1 rounded-md border bg-background p-0.5"
          role="toolbar"
          aria-label="Chart instrument"
        >
          {(['INDEX', 'CE', 'PE'] as const).map((which) => {
            const active = which === 'INDEX' ? shown === 'NIFTY' : shown.endsWith(which)
            return (
              <Button
                key={which}
                size="sm"
                variant={active ? 'secondary' : 'ghost'}
                className="h-8"
                aria-label={which === 'INDEX' ? 'Chart NIFTY' : `Chart ${which}`}
                aria-pressed={active}
                disabled={
                  busy ||
                  (which !== 'INDEX' && (!(which === 'CE' ? ce : pe) || chainQuery.isFetching))
                }
                onClick={() => void chart(which)}
              >
                {which === 'INDEX' ? 'NIFTY' : which}
              </Button>
            )
          })}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-9"
          aria-label="Refresh broker data"
          disabled={busy}
          onClick={() => {
            void expiriesQuery.refetch()
            void chainQuery.refetch()
          }}
        >
          Refresh
        </Button>
        <details className="relative text-xs text-muted-foreground">
          <summary className="flex h-9 cursor-pointer items-center rounded-md px-2 focus-visible:outline focus-visible:outline-ring">
            Chart guide
          </summary>
          <div className="absolute right-0 top-10 z-50 w-72 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-md">
            <p>
              ATM is the nearest strike. ITM and OTM numbers count listed strikes from ATM; call and
              put directions differ.
            </p>
            <p>
              Faint green / red zones show unfilled bullish / bearish FVGs. Dashed support and
              resistance lines mark confirmed pivots, which may attract liquidity.
            </p>
            <p>
              {shown || 'NIFTY charts'} · nearest active expiry by default; expiry list newest
              first. Donchian 20 / EMA 200, FVG / structure and RSI 14. These buttons select charts;
              strategy execution uses confirmed NIFTY 15m signals.
            </p>
          </div>
        </details>
        {busy ? <output className="text-xs text-muted-foreground">Loading chart…</output> : null}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
        {rows.length ? (
          <fieldset
            aria-label="Selected option moneyness"
            className="flex flex-wrap items-center gap-2 text-xs"
          >
            <span className="text-muted-foreground">
              ATM {chainQuery.data?.atm_strike ?? 'unavailable'}
            </span>
            {(['CE', 'PE'] as const).map((side) => {
              const row = rows.find((r) => String(r.strike) === (side === 'CE' ? ce : pe))
              return row ? (
                <Badge key={side} variant="outline" className="font-normal">
                  {side} {row.strike} · {strikeLabel(row, side)}
                </Badge>
              ) : null
            })}
          </fieldset>
        ) : null}
        <fieldset aria-label="Chart overlays" className="flex flex-wrap items-center gap-3">
          {studies.map((id) => (
            <Label
              key={id}
              htmlFor={`neo-study-${id}`}
              className="flex min-h-8 cursor-pointer items-center gap-2 text-xs font-normal text-muted-foreground"
            >
              <Checkbox
                id={`neo-study-${id}`}
                checked={enabledStudies.includes(id)}
                disabled={busy || !shown || target()?.dataUnavailable()}
                onCheckedChange={(on) => void toggleStudy(id, on === true)}
              />
              {studyLabels[id]}
            </Label>
          ))}
        </fieldset>
      </div>
      {problem ? (
        <p role="alert" className="mt-1 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
    </section>
  )
}
