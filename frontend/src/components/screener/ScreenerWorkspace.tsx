import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { screenerApi } from '@/api/screener'
import { watchlistApi } from '@/api/watchlist'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { useAlertStore } from '@/stores/alertStore'
import { readySound, playAlertSound } from '@/lib/trading/alertDelivery'
import { RuleBuilder } from './RuleBuilder'
import { ResultsTable } from './ResultsTable'
import { useScreener } from './useScreener'
import { MatchMonitor } from './alerts'
import { makePresets } from './presets'
import { FRAMES, type Frame, type SavedScreen, type ScreenDefinition, type Universe } from './model'
const control = 'rounded-md border border-input bg-background px-3 py-2 text-sm'
const stamp = (seconds: number) =>
  seconds > 0 ? new Date(seconds * 1000).toLocaleString() : 'Unavailable'
export function ScreenerWorkspace() {
  const owner = useAuthStore((s) => s.user?.username),
    mode = useThemeStore((s) => s.appMode),
    soundEnabled = useAlertStore((s) => s.soundEnabled),
    client = useQueryClient()
  const presets = useMemo(makePresets, []),
    [definition, setDefinition] = useState<ScreenDefinition>(presets[0]),
    [selectedId, setSelectedId] = useState<number>(),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false),
    [deleting, setDeleting] = useState(false),
    [visible, setVisible] = useState(!document.hidden),
    [armedScope, setArmedScope] = useState<string | null>(null),
    [pauseReason, setPauseReason] = useState('Not armed'),
    [nextRefresh, setNextRefresh] = useState<number | null>(null),
    [clock, setClock] = useState(Date.now() / 1000)
  const monitor = useRef(new MatchMonitor()),
    awaitLoading = useRef(false)
  const screensKey = ['screener-screens', owner, mode],
    universesKey = ['screener-universes', owner, mode]
  const savedQuery = useQuery({
    queryKey: screensKey,
    queryFn: ({ signal }) => screenerApi.screens(signal),
    refetchOnWindowFocus: false,
  })
  const universesQuery = useQuery({
    queryKey: universesKey,
    queryFn: ({ signal }) => screenerApi.universes(signal),
    refetchOnWindowFocus: false,
  })
  const watchlistsQuery = useQuery({
    queryKey: ['screener-watchlists', owner, mode],
    queryFn: () => watchlistApi.list(),
    refetchOnWindowFocus: false,
  })
  const screens = savedQuery.data ?? [],
    universes = universesQuery.data ?? [],
    selected = screens.find((s) => s.id === selectedId)
  const universeId =
    definition.universe.kind === 'watchlist'
      ? `watchlist:${definition.universe.id}`
      : definition.universe.kind === 'custom'
        ? 'crypto'
        : definition.universe.kind
  const items =
    definition.universe.kind === 'custom'
      ? (definition.universe.items ?? [])
      : (universes.find((u) => u.id === universeId)?.items ?? [])
  const scan = useScreener({ definition, items, owner, mode, visible })
  const dirty = !selected || JSON.stringify(selected.definition) !== JSON.stringify(definition)
  const scope = JSON.stringify([owner, mode, selected?.id, selected?.revision, definition]),
    armed = armedScope === scope && visible && !dirty
  const currentScope = useRef(scope)
  currentScope.current = scope
  const history = useQuery({
    queryKey: ['screener-events', owner, mode, selected?.id, selected?.revision],
    enabled: !!selected,
    queryFn: ({ signal }) => screenerApi.events(selected!.id, signal),
    refetchOnWindowFocus: false,
  })
  // biome-ignore lint/correctness/useExhaustiveDependencies: Changing owner or mode must reset the editable draft.
  useEffect(() => {
    setDefinition(presets[0])
    setSelectedId(undefined)
    setArmedScope(null)
    setPauseReason('Account or app mode changed')
    setMessage('')
    setBusy(false)
    setDeleting(false)
  }, [owner, mode, presets])
  useEffect(() => {
    const change = () => {
      setVisible(!document.hidden)
      if (document.hidden) {
        setArmedScope(null)
        setPauseReason('Paused: page hidden')
        monitor.current.reset()
      }
    }
    document.addEventListener('visibilitychange', change)
    const timer = setInterval(() => setClock(Date.now() / 1000), 1000)
    return () => {
      document.removeEventListener('visibilitychange', change)
      clearInterval(timer)
    }
  }, [])
  // biome-ignore lint/correctness/useExhaustiveDependencies: A definition identity change must disarm monitoring.
  useEffect(() => {
    setArmedScope(null)
    setNextRefresh(null)
    monitor.current.reset()
    setPauseReason('Paused: screen or rules changed')
  }, [scope])
  useEffect(() => {
    if (!armed) return
    if (scan.status === 'loading' || scan.status === 'evaluating') {
      awaitLoading.current = false
      return
    }
    if (scan.status === 'error' || scan.status === 'cancelled') {
      setArmedScope(null)
      setPauseReason(`Paused: ${scan.status}`)
      return
    }
    if (scan.status !== 'complete' || awaitLoading.current) return
    if (!scan.rows.length || scan.rows.some((r) => !r.fresh || r.state === 'unavailable')) {
      setArmedScope(null)
      setPauseReason('Paused: missing or stale source coverage')
      monitor.current.reset()
      return
    }
    const events = monitor.current.update(scan.rows)
    if (!events.length || !selected) return
    const controller = new AbortController()
    void screenerApi
      .record(
        selected.id,
        selected.revision,
        mode,
        events.map((r) => ({
          symbol: r.symbol,
          exchange: r.exchange,
          time: r.time!,
          direction: r.direction,
          source: r.source,
          observedAt: r.observedAt,
        })),
        controller.signal
      )
      .then((accepted) => {
        if (controller.signal.aborted || document.hidden) return
        if (accepted.length) {
          if (useAlertStore.getState().soundEnabled) playAlertSound()
          setMessage(
            `${accepted.length} fresh matching ${accepted.length === 1 ? 'instrument' : 'instruments'}`
          )
          void client.invalidateQueries({ queryKey: ['screener-events', owner, mode, selected.id] })
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setMessage(error instanceof Error ? error.message : 'Could not save alert history')
          setArmedScope(null)
          setPauseReason('Paused: alert history could not be saved')
        }
      })
    return () => controller.abort()
  }, [armed, scan.status, scan.rows, selected, mode, client, owner])
  // biome-ignore lint/correctness/useExhaustiveDependencies: Finishing a scan schedules the next real observation.
  useEffect(() => {
    if (!armed) {
      setNextRefresh(null)
      return
    }
    // Poll confirmed history at minute boundaries, including session-aligned hourly bars.
    // Longer timeframes still need a real source observation within the 90-second freshness window.
    const next = (Math.floor(Date.now() / 1000 / 60) + 1) * 60 + 2
    setNextRefresh(next)
    const timer = setTimeout(() => scan.run(true), Math.max(0, next * 1000 - Date.now()))
    return () => clearTimeout(timer)
  }, [armed, scan.run, scan.status === 'complete'])
  useEffect(() => {
    if (armed && scan.status === 'complete' && scan.rows.some((r) => clock - r.observedAt > 90)) {
      setArmedScope(null)
      setPauseReason('Paused: source observation is no longer fresh')
      monitor.current.reset()
    }
  }, [clock, armed, scan.status, scan.rows])
  function edit(next: ScreenDefinition) {
    setArmedScope(null)
    setPauseReason('Paused: screen or rules changed')
    setDefinition(next)
    setMessage('')
  }
  async function persist(copy = false) {
    setBusy(true)
    setMessage('')
    try {
      const next = await screenerApi.save(
        copy ? { ...definition, name: `${definition.name} copy` } : definition,
        copy ? undefined : selected
      )
      if (currentScope.current !== scope) return
      client.setQueryData<SavedScreen[]>(screensKey, (old) => [
        ...(old ?? []).filter((s) => s.id !== next.id),
        next,
      ])
      setSelectedId(next.id)
      setDefinition(next.definition)
      setMessage(copy ? 'Screen duplicated' : 'Screen saved')
    } catch (e) {
      if (currentScope.current === scope)
        setMessage(e instanceof Error ? e.message : 'Could not save screen')
    } finally {
      setBusy(false)
    }
  }
  async function remove() {
    if (!selected) return
    setBusy(true)
    try {
      await screenerApi.remove(selected.id)
      if (currentScope.current !== scope) return
      client.setQueryData<SavedScreen[]>(screensKey, (old) =>
        (old ?? []).filter((s) => s.id !== selected.id)
      )
      setSelectedId(undefined)
      setDeleting(false)
      setArmedScope(null)
      setMessage('Screen deleted')
    } catch (e) {
      if (currentScope.current === scope)
        setMessage(e instanceof Error ? e.message : 'Could not delete screen')
    } finally {
      setBusy(false)
    }
  }
  function chooseUniverse(id: string) {
    const found = universes.find((u) => u.id === id)
    let universe: Universe = { kind: 'stored' }
    if (id.startsWith('watchlist:')) universe = { kind: 'watchlist', id: Number(id.slice(10)) }
    else if (id === 'nifty50') universe = { kind: 'nifty50' }
    else if (id === 'crypto') universe = { kind: 'custom', items: found?.items ?? [] }
    edit({ ...definition, universe })
  }
  const error = savedQuery.error || universesQuery.error || watchlistsQuery.error
  return (
    <main className="mx-auto w-full max-w-[1800px] space-y-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Market Screener</h1>
          <p className="text-sm text-muted-foreground">
            Closed-candle snapshots from available history. Setup intent is analytical.
          </p>
        </div>
        <span className="rounded-md border px-3 py-1 text-xs">
          {mode === 'analyzer' ? 'Analyzer' : 'Live'} data view
        </span>
      </header>
      <section
        className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-4"
        aria-label="Screen settings"
      >
        <label className="grid gap-1 text-xs">
          Saved screen
          <select
            className={control}
            aria-label="Saved screen"
            value={selectedId ?? ''}
            onChange={(e) => {
              const screen = screens.find((s) => s.id === Number(e.target.value))
              setSelectedId(screen?.id)
              edit(screen?.definition ?? presets[0])
            }}
          >
            <option value="">Unsaved screen</option>
            {screens.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          Screen name
          <input
            className={control}
            aria-label="Screen name"
            maxLength={64}
            value={definition.name}
            onChange={(e) => edit({ ...definition, name: e.target.value })}
          />
        </label>
        <label className="grid gap-1 text-xs">
          Universe
          <select
            className={control}
            aria-label="Universe"
            value={universeId}
            onChange={(e) => chooseUniverse(e.target.value)}
          >
            {!universes.length && <option value="stored">Downloaded data</option>}
            {universes.map((u) => (
              <option key={u.id} value={u.id}>
                {u.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          Timeframe
          <select
            className={control}
            aria-label="Timeframe"
            value={definition.interval}
            onChange={(e) => edit({ ...definition, interval: e.target.value as Frame })}
          >
            {FRAMES.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          Setup intent
          <select
            className={control}
            aria-label="Setup intent"
            value={definition.intent}
            onChange={(e) =>
              edit({ ...definition, intent: e.target.value as ScreenDefinition['intent'] })
            }
          >
            <option value="observe">Neutral · MATCH</option>
            <option value="bullish">Bullish</option>
            <option value="bearish">Bearish</option>
          </select>
        </label>
        <Button disabled={busy || !definition.name.trim()} onClick={() => persist()}>
          Save screen
        </Button>
        <Button variant="outline" disabled={busy || !selected} onClick={() => persist(true)}>
          Duplicate
        </Button>
        <Button variant="outline" disabled={busy || !selected} onClick={() => setDeleting(true)}>
          Delete
        </Button>
      </section>
      {deleting && (
        <div role="alertdialog" aria-label="Delete saved screen" className="rounded-lg border p-4">
          <p>Delete “{selected?.name}” and its saved trigger history?</p>
          <div className="mt-3 flex gap-2">
            <Button variant="destructive" disabled={busy} onClick={remove}>
              Confirm delete
            </Button>
            <Button variant="outline" onClick={() => setDeleting(false)}>
              Keep screen
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error instanceof Error ? error.message : 'Could not load screener data'}
        </p>
      )}
      {message && (
        <output className="block text-sm">
          {message}
        </output>
      )}
      <details className="rounded-lg border bg-card p-4">
        <summary className="cursor-pointer font-medium">
          Preset gallery · {presets.length} editable screens
        </summary>
        <div className="mt-3 flex flex-wrap gap-2">
          {presets.map((p, index) => (
            <Button
              key={index}
              size="sm"
              variant="outline"
              onClick={() => {
                setSelectedId(undefined)
                edit({ ...p, universe: definition.universe, interval: definition.interval })
              }}
            >
              {p.name}
            </Button>
          ))}
        </div>
      </details>
      <details open className="rounded-lg border bg-card p-4">
        <summary className="mb-3 cursor-pointer font-medium">
          Rule builder{dirty ? ' · unsaved changes' : ''}
        </summary>
        <p className="mb-3 text-xs text-muted-foreground">
          One timeframe per screen. RSI, ATR and Bollinger use the shared chart periods;
          previous-session fields require Daily history. Rename with Screen name, then Save screen.
        </p>
        <RuleBuilder rule={definition.rule} onChange={(rule) => edit({ ...definition, rule })} />
      </details>
      <section className="space-y-3 rounded-lg border bg-card p-4" aria-label="Data coverage">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-medium">Data coverage</h2>
          <Button
            size="sm"
            variant="outline"
            disabled={!visible || items.length > 500}
            onClick={() => scan.run(false)}
          >
            Scan available data
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!visible || !items.length || items.length > 25}
            onClick={() => scan.run(true)}
          >
            Load / refresh history
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!['loading', 'evaluating'].includes(scan.status)}
            onClick={scan.cancel}
          >
            Cancel scan
          </Button>
        </div>
        <output className="block text-sm">
          {scan.status} · {items.length} instruments ·{' '}
          {scan.datasets.filter((d) => d.candles.length && !d.error).length} covered ·{' '}
          {scan.pending} pending · {scan.failed} failed · {scan.missing} missing or unavailable
        </output>
        {scan.error && (
          <p role="alert" className="text-sm text-destructive">
            {scan.error}
          </p>
        )}
        {!items.length && (
          <p className="text-sm text-muted-foreground">
            No instruments in this universe. Choose a watchlist, or download history in Historify to
            populate stored data.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Stored snapshots: up to 500 instruments. Explicit history refresh and automatic
          monitoring: up to 25. Public Delta history is fetched for supported crypto symbols. No
          data is forward-filled.
        </p>
        <details>
          <summary className="cursor-pointer text-sm">
            Source observations and coverage ({scan.datasets.length})
          </summary>
          <div className="mt-2 max-h-64 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>Source</th>
                  <th>Observed</th>
                  <th>Bars / Daily</th>
                  <th>Data state</th>
                </tr>
              </thead>
              <tbody>
                {scan.datasets.map((d) => (
                  <tr key={`${d.exchange}:${d.symbol}`} className="border-t">
                    <td className="py-2">
                      {d.symbol} · {d.exchange}
                    </td>
                    <td>{d.source}</td>
                    <td>{stamp(d.observedAt)}</td>
                    <td>
                      {d.candles.length} / {d.daily.length}
                    </td>
                    <td>
                      {d.error ??
                        scan.rows
                          .filter((r) => r.symbol === d.symbol && r.exchange === d.exchange)
                          .map(
                            (r) => `${r.fresh ? 'Fresh' : 'Stale'} · ${r.state} · ${r.reason}`
                          )[0] ??
                        'Pending evaluation'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>
      <ResultsTable
        key={`${scope}`}
        rows={scan.rows}
        definition={definition}
        watchlists={watchlistsQuery.data ?? []}
        onAdd={async (id, rows) => {
          try {
            for (const row of rows) await watchlistApi.addItem(id, row.symbol, row.exchange)
            setMessage(`Added ${rows.length} instruments to watchlist`)
            void client.invalidateQueries({ queryKey: ['screener-watchlists', owner, mode] })
            void client.invalidateQueries({ queryKey: universesKey })
          } catch (e) {
            setMessage(e instanceof Error ? e.message : 'Could not add selected instruments')
          }
        }}
      />
      <section className="space-y-3 rounded-lg border bg-card p-4" aria-label="Screen alerts">
        <h2 className="font-medium">Visible-page sound alerts</h2>
        <p className="text-sm text-muted-foreground">
          Monitors only this selected saved screen while this page is visible. Initial and resumed
          matches are silent. New confirmed entries can sound after a verified non-match. Hiding
          this page, editing rules or losing source freshness pauses monitoring. Up to 25
          instruments; history refreshes once per minute, and only completed candles can trigger.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              readySound()
              setMessage(
                playAlertSound() ? 'Test sound played' : 'Sound unavailable in this browser'
              )
            }}
          >
            Test sound
          </Button>
          <Button
            size="sm"
            disabled={
              dirty ||
              !selected ||
              !items.length ||
              items.length > 25 ||
              !visible ||
              !soundEnabled ||
              scan.status === 'error'
            }
            onClick={() => {
              if (armed) {
                setArmedScope(null)
                setPauseReason('Paused by you')
              } else {
                readySound()
                monitor.current.reset()
                awaitLoading.current = true
                setArmedScope(scope)
                setPauseReason('')
                scan.run(true)
              }
            }}
          >
            {armed ? 'Pause alerts' : 'Arm alerts'}
          </Button>
          <span className="text-sm">
            {armed
              ? `Armed · next refresh ${nextRefresh ? stamp(nextRefresh) : 'pending'}`
              : pauseReason}
          </span>
        </div>
        {!soundEnabled && (
          <p className="text-xs text-muted-foreground">
            Sound is disabled in your alert preferences.
          </p>
        )}
        <details>
          <summary className="cursor-pointer text-sm">
            Saved trigger history ({history.data?.length ?? 0})
          </summary>
          {history.error && <p role="alert">Could not load trigger history.</p>}
          <ul className="mt-2 max-h-52 overflow-auto text-xs">
            {(history.data ?? []).map((event, index) => (
              <li key={event.id ?? index} className="border-t py-2">
                {event.symbol} · {event.exchange} · {event.direction} · candle {stamp(event.time)} ·{' '}
                {event.source}, observed {stamp(event.observedAt)}
              </li>
            ))}
          </ul>
        </details>
      </section>
    </main>
  )
}
