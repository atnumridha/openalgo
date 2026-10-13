import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { activeExpiries, nearestExpiry } from '@/lib/neoOptionSelection'
import type { TradingTerminal } from '@/lib/trading/terminal'

const studies = ['neo-donchian', 'neo-structure', 'rsi']
export function NeoTradingTools({
  target,
  revision,
}: {
  target: () => TradingTerminal | null
  revision: number
}) {
  const [expiry, setExpiry] = useState(''),
    [ce, setCe] = useState(''),
    [pe, setPe] = useState('')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [shown, setShown] = useState('')
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
  async function applyStudies(pane: TradingTerminal) {
    for (const id of studies) {
      if (!pane.listIndicators().some((s) => s.indicatorId === id)) await pane.addIndicatorById(id)
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
    if (initial.current) return
    const tryDefault = () => {
      const pane = target()
      if (!initial.current && pane && !pane.dataUnavailable() && !pane.replayActive() && !pane.replayPickingBar()) {
        initial.current = true
        void chart('INDEX')
      }
    }
    tryDefault()
    if (initial.current) return
    const timer = setInterval(() => {tryDefault(); if (initial.current) clearInterval(timer)}, 250)
    return () => clearInterval(timer)
  }, [revision, target])
  const problem =
    error ||
    (expiriesQuery.error || chainQuery.error
      ? 'Could not load NIFTY expiries or strikes. Refresh broker data.'
      : '')
  return (
    <section aria-label="NIFTY chart selection" className="shrink-0 border-b bg-card px-3 py-2">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <Label htmlFor="neo-chart-expiry">NIFTY expiry</Label>
          <select
            id="neo-chart-expiry"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            disabled={busy || !dates.length}
            className="block h-9 rounded border bg-background px-2 text-sm"
          >
            {dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        {(['CE', 'PE'] as const).map((side) => (
          <div key={side}>
            <Label htmlFor={'neo-chart-' + side}>{side} strike</Label>
            <select
              id={'neo-chart-' + side}
              value={side === 'CE' ? ce : pe}
              onChange={(e) => (side === 'CE' ? setCe(e.target.value) : setPe(e.target.value))}
              disabled={busy || !rows.length}
              className="block h-9 rounded border bg-background px-2 text-sm"
            >
              {rows
                .filter((r) => (side === 'CE' ? r.ce : r.pe)?.symbol)
                .map((r) => (
                  <option key={r.strike} value={String(r.strike)}>
                    {r.strike}
                    {r.strike === chainQuery.data?.atm_strike ? ' · ATM' : ''}
                  </option>
                ))}
            </select>
          </div>
        ))}
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void chart('INDEX')}>
          Chart NIFTY
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !ce || chainQuery.isFetching}
          onClick={() => void chart('CE')}
        >
          Chart CE
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !pe || chainQuery.isFetching}
          onClick={() => void chart('PE')}
        >
          Chart PE
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => {
            void expiriesQuery.refetch()
            void chainQuery.refetch()
          }}
        >
          Refresh broker data
        </Button>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {busy ? 'Loading selected prices and indicators…' : shown || 'NIFTY charts'} · nearest
        active expiry by default; expiry list newest first. Donchian 20 / EMA 200, FVG / structure
        and RSI 14. These buttons select charts; strategy execution uses confirmed NIFTY 15m
        signals.
      </p>
      {problem ? (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      ) : null}
    </section>
  )
}
