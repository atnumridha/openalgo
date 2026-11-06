import { useEffect, useState } from 'react'
import { chooseVideoSetup, activeVideoSetups } from '../chart-toolkit/videoStrategyGuide.js'
import type { VideoGuideResult, VideoStrategyId } from '../chart-toolkit/videoStrategyTypes'
const price = (n: number | null) =>
  n == null ? '—' : n.toLocaleString('en-IN', { maximumFractionDigits: 4 })
const stamp = (n: number | null) =>
  n
    ? new Date(n * 1000).toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      }) + ' IST'
    : 'Unavailable'
const stateName: Record<string, string> = {
  watching: 'Wait for confirmation',
  waiting: 'Wait for retest',
  entry: 'Entry condition observed',
  invalidated: 'Invalidated',
  target: 'Target touched',
  expired: 'Expired',
  ambiguous: 'Ambiguous — wait',
  unpriced: 'Target unavailable',
  none: 'No matching setup',
  incomplete: 'Rules incomplete',
  unavailable: 'Data unavailable',
}
export function VideoStrategyGuide({
  result,
  selectedId,
  onSelect,
  symbol,
  exchange,
  interval,
  live,
}: {
  result: VideoGuideResult
  selectedId: VideoStrategyId | ''
  onSelect: (id: VideoStrategyId | '') => void
  symbol: string
  exchange: string
  interval: string
  live: boolean
}) {
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [])
  const selection = chooseVideoSetup(result, selectedId),
    event = selection.event,
    matches = activeVideoSetups(result),
    supportedCount = result.readings.filter((r) => r.supported).length
  const stale =
    live &&
    (!result.closedTime ||
      now - result.closedTime > result.seconds * 2 + 15 ||
      now - result.asOf > Math.max(90, result.seconds + 15))
  const option = ['NFO', 'BFO'].includes(exchange) && /(CE|PE)$/.test(symbol)
  const action = !live
    ? 'History · chart observations'
    : stale
      ? 'Check live data'
      : option && selection.action === 'Review Short'
        ? 'Premium bearish · avoid new buy'
        : selection.action
  const reason = stale
    ? 'Verified candles are old. Wait for the feed to reconcile before reviewing an entry.'
    : selection.reason
  const selected = result.readings.find((r) => r.id === (selectedId || event?.strategy))
  return (
    <details
      open
      aria-label="Video strategy guide"
      className="mb-2 rounded border border-border bg-card text-xs"
    >
      <summary className="cursor-pointer px-2 py-2 focus-visible:outline focus-visible:outline-2">
        <strong>Strategy guide · video</strong>
        <span
          className={`mt-1 block font-medium ${action === 'Review Long' ? 'text-emerald-600 dark:text-emerald-400' : action === 'Review Short' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}`}
        >
          {action}
        </span>
        <span className="mt-1 block text-muted-foreground">
          {selected?.name ?? 'All video strategies'} · {interval}
        </span>
      </summary>
      <div className="space-y-2 border-t px-2 py-2">
        <p className="font-medium">
          Automatic scan · {supportedCount} detectors · {matches.length} confirmed matches
        </p>
        <p className="text-muted-foreground">6 recipes use local rules · KRM unavailable</p>
        <p>{reason}</p>
        {matches.length > 0 && (
          <ul aria-label="Detected strategy matches" className="space-y-1">
            {matches.slice(0, 3).map((e) => (
              <li key={e.id} className="rounded border px-2 py-1">
                <strong>{result.readings.find((r) => r.id === e.strategy)?.name}</strong>
                <span className="block text-muted-foreground">
                  {e.side > 0 ? 'Bullish' : option ? 'Premium bearish' : 'Bearish'} ·{' '}
                  {stateName[e.status]}
                  {!live || stale ? ' · verify live data' : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
        <label className="block space-y-1">
          <span>Strategy from video</span>
          <select
            aria-label="Strategy from video"
            className="w-full rounded border bg-background px-2 py-2 text-xs"
            value={selectedId}
            onChange={(e) => onSelect(e.target.value as VideoStrategyId | '')}
          >
            <option value="">Auto · current evidence</option>
            {result.readings.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
                {r.supported ? '' : ' · rules incomplete'}
              </option>
            ))}
          </select>
        </label>
        {selected && <p className="text-muted-foreground">{selected.rule || selected.missing}</p>}
        {event && (
          <>
            <p className="font-medium">
              {event.side > 0 ? 'Bullish' : 'Bearish'} · {stateName[event.status]}
              {!live ? ' · history' : ''}
            </p>
            <dl
              aria-label="Video setup price levels"
              className="grid grid-cols-2 gap-x-2 gap-y-1 tabular-nums"
            >
              <dt>Watched pullback</dt>
              <dd className="text-right">{price(event.watch)}</dd>
              <dt>Close reference</dt>
              <dd className="text-right">{price(event.entry)}</dd>
              <dt>SL reference</dt>
              <dd className="text-right">{price(event.stop)}</dd>
              <dt>Target reference</dt>
              <dd className="text-right">{price(event.target)}</dd>
            </dl>
            <p className="text-muted-foreground">
              Known {stamp(event.confirmedAt ?? event.createdAt)}
              {event.entryAt ? ` · condition ${stamp(event.entryAt)}` : ''}
            </p>
          </>
        )}
        <p className="text-muted-foreground">
          Closed-candle guidance. A watched limit price is not an assumed fill. Levels use this
          chart’s {option ? 'option premium' : 'price'} units.
        </p>
        <details>
          <summary className="cursor-pointer font-medium">
            All 15 strategies &amp; conditions
          </summary>
          <ul
            className="mt-2 max-h-72 space-y-2 overflow-y-auto"
            aria-label="Video strategy catalogue"
          >
            {result.readings.map((r) => (
              <li key={r.id} className="rounded border px-2 py-2">
                <strong>{r.name}</strong>
                <span className="mt-1 block">{stateName[r.status]}</span>
                <p className="mt-1 text-muted-foreground">{r.reason}</p>
                <span className="text-muted-foreground">
                  Source: {r.source}
                  {r.variant ? ' · local rules' : ''}
                </span>
              </li>
            ))}
          </ul>
        </details>
        <details>
          <summary className="cursor-pointer text-muted-foreground">
            Detection settings &amp; source coverage
          </summary>
          <p className="mt-1 text-muted-foreground">
            Implementation settings: strict 2-left/2-right pivots, prior ATR14 displacement, 20-bar
            pending expiry. These numerical choices are not specified by the clip. OTE uses its
            shown 62–79% zone and 70.5% reference.
          </p>
          <p className="mt-1 text-muted-foreground">
            Fourteen methods scan automatically. Six added recipes use explicit local rules informed
            by the creator’s full video. KRM’s exact trigger is not public and stays unavailable.
            Related concepts can describe one event; they are not independent confidence votes.
          </p>
        </details>
      </div>
    </details>
  )
}
