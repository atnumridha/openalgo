import { useEffect, useState } from 'react'
import type { TimedArchiveMatch } from '../chart-toolkit/archiveConfirmations'
import type { Bar } from '../chart-toolkit/model'
import type { TrendSession } from '../chart-toolkit/trendAnalysis'
import { liveCandleProgress, makePatternGuidance } from './livePatternGuidance'
const price = (n: number | null) =>
  n == null ? '—' : n.toLocaleString('en-IN', { maximumFractionDigits: 4 })
const statusName = {
  none: 'Wait · no confirmed pattern',
  neutral: 'Indecision · wait',
  mixed: 'Mixed evidence · wait',
  confirmed: 'Confirmed on latest closed candle',
  active: 'Recent reference · watch follow-through',
  invalidated: 'Reference invalidated',
  target: 'Projection touched',
  ambiguous: 'Barrier order unknown · wait',
}
const references = [
  [
    'Fidelity',
    'https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Idenitfying-Chart-Patterns.pdf',
  ],
  [
    'IG',
    'https://www.ig.com/en/trading-strategies/10-chart-patterns-every-trader-needs-to-know-190514',
  ],
  ['Groww', 'https://groww.in/blog/candlestick-patterns'],
  ['TrendSpider', 'https://trendspider.com/blog/the-ultimate-guide-to-chart-patterns/'],
  [
    'Kotak Neo',
    'https://www.kotakneo.com/stockshaala/introduction-to-technical-analysis/introduction-to-chart-patterns/',
  ],
  ['TradingView ideas', 'https://in.tradingview.com/ideas/chartpattern/'],
  ['Dhan', 'https://dhan.co/blog/technical-analysis/top-trading-patterns-in-charts/'],
  ['ChartPatterns', 'https://www.chartpatterns.com/'],
]
export function LivePatternGuide({
  events,
  bars,
  seconds,
  asOf,
  live,
  candle,
  observedAt,
  symbol,
  exchange,
  session,
}: {
  events: TimedArchiveMatch[]
  bars: Bar[]
  seconds: number
  asOf: number
  live: boolean
  candle: Bar | null
  observedAt: number | null
  symbol: string
  exchange: string
  session?: TrendSession | null
}) {
  const [, setClockTick] = useState(0)
  const now = Date.now() / 1000
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => setClockTick((tick) => tick + 1), 1000)
    return () => clearInterval(timer)
  }, [live])
  const progress = liveCandleProgress(candle, seconds, observedAt, now, live)
  const lastClosed = bars.at(-1)
  const old =
    live &&
    (!lastClosed ||
      now - (lastClosed.time + seconds) > seconds * 2 + 15 ||
      now - asOf > Math.max(90, seconds + 15))
  const guide = makePatternGuidance(
    events,
    bars,
    seconds,
    asOf,
    progress.state === 'forming' && !old ? candle!.close : null,
    session,
    ['NSE', 'NFO', 'NSE_INDEX', 'BSE', 'BFO', 'BSE_INDEX'].includes(exchange),
    progress.state === 'forming' && !old ? candle!.time : null
  )
  const option = ['NFO', 'BFO'].includes(exchange) && /(CE|PE)$/.test(symbol)
  return (
    <details
      open
      aria-label="Live pattern guide"
      className="mb-2 rounded border border-border bg-card text-xs leading-relaxed"
    >
      <summary className="cursor-pointer px-2 py-2 font-semibold focus-visible:outline focus-visible:outline-2">
        Live pattern guide
        <span className="mt-1 block font-medium text-muted-foreground">
          {!live
            ? 'History · chart observations'
            : old
              ? 'Check completed-candle data'
              : statusName[guide.status]}
        </span>
      </summary>
      <div className="space-y-2 border-t px-2 py-2">
        <p aria-label="Live candle progress" className="rounded bg-muted px-2 py-1 tabular-nums">
          {progress.state === 'forming'
            ? `Forming candle · ${progress.direction} · ${progress.remaining}s to close`
            : progress.state === 'history'
              ? 'Historical view · live candle updates paused'
              : progress.state === 'stale'
                ? 'Waiting for a fresh live quote'
                : 'Waiting for the current candle receipt'}
        </p>
        {guide.event && (
          <>
            <strong className="block text-sm">{guide.event.name}</strong>
            <p className="text-muted-foreground">
              {new Date((guide.event.time + seconds) * 1000).toLocaleString('en-IN', {
                timeZone: 'Asia/Kolkata',
                day: '2-digit',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit',
              })}{' '}
              IST ·{' '}
              {guide.side === 'NEUTRAL'
                ? 'Neutral'
                : guide.side === 'CALL'
                  ? 'Bullish'
                  : option
                    ? 'Premium bearish'
                    : 'Bearish'}
            </p>
          </>
        )}
        <p>{guide.explanation}</p>
        <p>
          <strong>Expected: </strong>
          {guide.expectation}
        </p>
        <p className="font-medium">
          <strong>Next: </strong>
          {guide.next}
        </p>
        {guide.event && guide.side !== 'NEUTRAL' && (
          <dl
            aria-label="Pattern reference levels"
            className="grid grid-cols-2 gap-x-2 tabular-nums"
          >
            <dt>Breakout boundary</dt>
            <dd className="text-right">{price(guide.boundary)}</dd>
            <dt>Invalidation reference</dt>
            <dd className="text-right">{price(guide.stop)}</dd>
            <dt>Projected target</dt>
            <dd className="text-right">{price(guide.target)}</dd>
          </dl>
        )}
        {guide.liveNote && (
          <p className="font-medium text-amber-700 dark:text-amber-400">{guide.liveNote}</p>
        )}
        {guide.others.length > 0 && (
          <details>
            <summary className="cursor-pointer">
              Other patterns on this candle ({guide.otherCount})
            </summary>
            <ul>
              {guide.others.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            {guide.otherCount > guide.others.length && (
              <p className="text-muted-foreground">{guide.otherCount - guide.others.length} more patterns</p>
            )}
          </details>
        )}
        <p className="text-muted-foreground">
          Updates with received candles and quotes. Confirmation waits for verified candle close.
          References are chart {option ? 'premium' : 'price'} levels; no order is placed.
        </p>
        <details>
          <summary className="cursor-pointer font-medium">Pattern references &amp; rules</summary>
          <p className="mt-2 text-muted-foreground">
            Classical shapes and candle families use local numerical rules: confirmed 2-left/2-right
            pivots; fitted boundaries and completed breakouts. A pattern name does not guarantee a
            move. Forming drawings use the unconfirmed-pattern option; older labels use the history
            option.
          </p>
          <p className="mt-2 flex flex-wrap gap-x-2 gap-y-1">
            {references.map(([name, url]) => (
              <a key={url} href={url} target="_blank" rel="noreferrer" className="underline">
                {name}
              </a>
            ))}
          </p>
          <p className="mt-2 text-muted-foreground">
            TradingView is an ideas feed, not a rule specification. Dhan's article body was
            unavailable during this review. No success rate is inferred from these references.
          </p>
        </details>
      </div>
    </details>
  )
}
