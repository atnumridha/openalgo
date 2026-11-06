import { memo, useState } from 'react'
import type { OptionData } from '@/types/option-chain'
import { useQuery } from '@tanstack/react-query'
import { scalpingApi } from '@/api/scalping'
import { chartBars } from '../neo-desk/tradingViewStudies'
import {
  impliedVolatility,
  matchOptionSnapshot,
  type Decision,
  type Reference,
  type Result,
} from './model'

export interface OptionReference {
  underlying: string
  exchange: string
  optionExchange: string
  expiry: string
  ce?: { symbol: string; strike: number; contract?: OptionData }
  pe?: { symbol: string; strike: number; contract?: OptionData }
}
export interface DisplaySettings {
  slow: 15 | 21
  bands: boolean
  markerLimit: number
  liquidity?: boolean
  trends?: boolean
  references?: boolean
  events?: boolean
}
const number = (v?: number | null) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(2))
const tone = (v: number | null, lower: number, upper: number) =>
  v == null
    ? 'text-muted-foreground'
    : v > upper
      ? 'text-emerald-600 dark:text-emerald-400'
      : v < lower
        ? 'text-red-600 dark:text-red-400'
        : 'text-amber-600 dark:text-amber-400'
const statusTone = (s?: string) =>
  s === 'BULL'
    ? 'text-emerald-600 dark:text-emerald-400'
    : s === 'BEAR'
      ? 'text-red-600 dark:text-red-400'
      : 'text-amber-600 dark:text-amber-400'
function expirySeconds(expiry: string) {
  const match = /^(\d{2})([A-Z]{3})(\d{2}|\d{4})$/.exec(expiry.toUpperCase())
  if (!match) return NaN
  const month = [
    'JAN',
    'FEB',
    'MAR',
    'APR',
    'MAY',
    'JUN',
    'JUL',
    'AUG',
    'SEP',
    'OCT',
    'NOV',
    'DEC',
  ].indexOf(match[2])
  const year = Number(match[3]) + (match[3].length === 2 ? 2000 : 0)
  return month < 0 ? NaN : Date.UTC(year, month, Number(match[1]), 10, 0) / 1000 // 15:30 IST assumption
}

function IVCalculator({ reference, replay }: { reference?: OptionReference; replay: boolean }) {
  const [side, setSide] = useState<'CE' | 'PE'>('CE'),
    [enabled, setEnabled] = useState(false),
    [rate, setRate] = useState(0),
    [yieldRate, setYieldRate] = useState(0),
    [ceiling, setCeiling] = useState(0)
  const leg = side === 'CE' ? reference?.ce : reference?.pe
  const source = useQuery({
    queryKey: [
      'toolkit-iv',
      reference?.underlying,
      reference?.exchange,
      reference?.optionExchange,
      leg?.symbol,
    ],
    enabled: enabled && !replay && !!reference && !!leg,
    queryFn: async () => {
      const [option, spot] = await Promise.all([
        scalpingApi.getHistory(leg!.symbol, reference!.optionExchange, '1m'),
        scalpingApi.getHistory(reference!.underlying, reference!.exchange, '1m'),
      ])
      if (option.status !== 'success' || spot.status !== 'success')
        throw Error('Option or underlying candles unavailable')
      return { option: chartBars(option.candles), spot: chartBars(spot.candles) }
    },
    staleTime: 30000,
    refetchInterval: enabled && !replay ? 30000 : false,
    retry: false,
  })
  const asOf = Date.now() / 1000
  const snapshot =
    source.data && !replay ? matchOptionSnapshot(source.data.option, source.data.spot, asOf) : null
  const expiry = reference ? expirySeconds(reference.expiry) : NaN
  const expiredNow = expiry <= asOf
  const iv =
    snapshot && leg && !expiredNow
      ? impliedVolatility(
          snapshot.premium,
          snapshot.spot,
          leg.strike,
          (expiry - snapshot.time - 60) / 31536000,
          rate / 100,
          yieldRate / 100,
          side === 'CE'
        )
      : null
  const check =
    iv == null
      ? null
      : !snapshot?.fresh
        ? 'STALE · context only'
        : ceiling > 0
          ? iv <= ceiling
            ? `Within your ${ceiling}% ceiling`
            : `Above your ${ceiling}% ceiling`
          : 'Context only · no IV ceiling set'
  return (
    <details
      className="border-t px-3 py-1.5 text-xs"
      onToggle={(e) => setEnabled(e.currentTarget.open)}
    >
      <summary className="cursor-pointer text-muted-foreground focus-visible:outline focus-visible:outline-ring">
        Option IV calculator · separate from price signal
      </summary>
      <div className="space-y-2 py-2">
        {!reference ? (
          <p>Select an index and a listed option in the chart toolbar to calculate IV.</p>
        ) : replay ? (
          <p>IV is hidden during replay / saved-history viewing.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <label className="space-y-1">
                <span className="block">Reference option</span>
                <select
                  aria-label="IV reference option"
                  value={side}
                  onChange={(e) => setSide(e.target.value as 'CE' | 'PE')}
                  className="h-8 rounded border bg-background px-2"
                >
                  <option value="CE">Selected CE</option>
                  <option value="PE">Selected PE</option>
                </select>
              </label>
              {[
                ['Rate %', rate, setRate],
                ['Yield %', yieldRate, setYieldRate],
                ['Your IV ceiling % (0 = context)', ceiling, setCeiling],
              ].map(([label, value, setter]) => (
                <label key={String(label)} className="space-y-1">
                  <span className="block">{String(label)}</span>
                  <input
                    aria-label={String(label)}
                    type="number"
                    step="0.5"
                    value={value as number}
                    onChange={(e) => (setter as (n: number) => void)(Number(e.target.value))}
                    className="h-8 w-24 rounded border bg-background px-2"
                  />
                </label>
              ))}
            </div>
            <p className="text-muted-foreground">
              {leg?.symbol || 'No listed strike selected'} · {reference.expiry} · expiry time
              assumed 15:30 IST · European BSM model
            </p>
            {iv != null ? (
              <p className="flex flex-wrap gap-x-3 tabular-nums">
                <strong
                  className={
                    snapshot?.fresh
                      ? 'text-sky-600 dark:text-sky-400'
                      : 'text-amber-600 dark:text-amber-400'
                  }
                >
                  Calculated IV {iv.toFixed(2)}%
                </strong>
                <span>{check}</span>
                <span>
                  Premium {number(snapshot?.premium)} · Spot {number(snapshot?.spot)} · Strike{' '}
                  {number(leg?.strike)}
                </span>
              </p>
            ) : (
              <p className="text-amber-600 dark:text-amber-400">
                {source.isFetching
                  ? 'Loading matched one-minute option / index candles…'
                  : expiredNow
                    ? 'Reference option expired · choose a current expiry'
                    : source.isError
                      ? 'Broker option / index candles unavailable'
                      : !snapshot
                        ? 'No matching closed one-minute candles'
                        : 'Premium is outside model bounds · IV unavailable'}
              </p>
            )}
            {snapshot ? (
              <p className="text-muted-foreground">
                Matched candle close{' '}
                {new Date((snapshot.time + 60) * 1000).toLocaleTimeString('en-IN', {
                  timeZone: 'Asia/Kolkata',
                })}{' '}
                IST · age {Math.max(0, Math.floor(asOf - snapshot.time - 60))}s. No IV Rank /
                history is inferred. Check the intended contract, expiry, premium and event risk
                separately.
              </p>
            ) : null}
          </>
        )}
      </div>
    </details>
  )
}

export const ToolkitPanel = memo(function ToolkitPanel({
  result,
  references,
  settings,
  onSettings,
  reference,
  replay,
  referenceError,
  referenceLoading = false,
  showIV = true,
  feedFresh = true,
  compact = false,
  historyReady = true,
  signalMarket = 'index',
}: {
  result: Result | null
  references: Reference[]
  settings: DisplaySettings
  onSettings: (next: DisplaySettings) => void
  reference?: OptionReference
  replay: boolean
  referenceError?: boolean
  referenceLoading?: boolean
  showIV?: boolean
  feedFresh?: boolean
  compact?: boolean
  historyReady?: boolean
  signalMarket?: 'index' | 'perpetual' | 'option' | 'price'
}) {
  // The visible checks must use the same closed candle as the entry decision.
  // Live EMA values remain in the chart legend.
  const m = result?.points.find((point) => point.time === result.closedTime)?.metrics
  const decision: Decision | undefined = !historyReady
    ? { status: 'WAIT', reason: 'Waiting for candle history', rsiAge: null, crossAge: null }
    : !replay && !feedFresh
      ? { status: 'WAIT', reason: 'Waiting for fresh prices', rsiAge: null, crossAge: null }
      : result?.confirmed
  const latest = result?.allSignals.at(-1)
  const reason =
    decision?.status === 'BULL'
      ? signalMarket === 'index'
        ? 'BULL · bullish price setup'
        : signalMarket === 'perpetual'
          ? 'LONG · bullish price setup'
          : signalMarket === 'price'
            ? 'BULL · bullish price setup'
            : 'BULL · option premium only'
      : decision?.status === 'BEAR'
        ? signalMarket === 'index'
          ? 'BEAR · bearish price setup'
          : signalMarket === 'perpetual'
            ? 'SHORT · bearish price setup'
            : signalMarket === 'price'
              ? 'BEAR · bearish price setup'
              : 'BEAR · option premium only'
        : decision?.reason.includes('fresh RSI')
          ? m?.rsi != null && m.rsi <= 30
            ? 'Wait for RSI to cross above 30'
            : m?.rsi != null && m.rsi >= 70
              ? 'Wait for RSI to cross below 70'
              : 'No recent RSI 30 / 70 exit'
          : decision?.reason.includes('exit used')
            ? 'Waiting for a new setup'
            : decision?.reason.includes('MACD cross')
              ? 'Waiting for MACD confirmation'
              : (decision?.reason ?? 'Loading indicators')
  return (
    <section
      aria-label="Price decision toolkit"
      className={
        compact
          ? 'relative z-20 w-full rounded-md border bg-background/95'
          : 'relative z-20 shrink-0 border-b bg-card'
      }
    >
      <div
        className={
          compact
            ? 'flex flex-col gap-2 px-3 py-2.5'
            : 'flex flex-wrap items-center justify-between gap-3 px-3 py-2'
        }
      >
        <section aria-label="Confirmed price signal" className="flex items-center gap-2.5">
          <strong
            className={`${compact ? 'text-sm' : 'rounded px-3 py-1 text-lg'} ${statusTone(decision?.status)} ${compact ? '' : decision?.status === 'BULL' ? 'bg-emerald-500/10' : decision?.status === 'BEAR' ? 'bg-red-500/10' : 'bg-amber-500/10'}`}
          >
            {decision?.status === 'BULL'
              ? signalMarket === 'index'
                ? 'BUY CALL'
                : signalMarket === 'perpetual'
                  ? 'LONG'
                  : 'BULL'
              : decision?.status === 'BEAR'
                ? signalMarket === 'index'
                  ? 'BUY PUT'
                  : signalMarket === 'perpetual'
                    ? 'SHORT'
                    : 'BEAR'
                : 'WAIT'}
          </strong>
          <div className={compact ? 'min-w-0 text-[11px] leading-4' : 'text-xs'}>
            <p>{reason}</p>
            <p className="text-[11px] text-muted-foreground">
              {replay
                ? 'Historical candle'
                : signalMarket === 'index'
                  ? 'RSI + MACD · closed candle'
                  : 'Closed candle signal'}
            </p>
          </div>
        </section>
        <div
          className={
            compact
              ? 'flex items-center justify-between gap-2 border-t pt-2'
              : 'flex items-center gap-5'
          }
        >
          <section
            aria-label="Momentum values"
            className={
              compact
                ? 'flex gap-3 text-[11px] tabular-nums text-muted-foreground'
                : 'flex gap-4 text-xs tabular-nums text-muted-foreground'
            }
          >
            <span>
              RSI 14 <b className={tone(m?.rsi ?? null, 30, 70)}>{number(m?.rsi)}</b>
            </span>
            <span>
              MACD hist <b className={tone(m?.histogram ?? null, 0, 0)}>{number(m?.histogram)}</b>
            </span>
          </section>
          <details className="relative text-xs">
            <summary
              className={
                compact
                  ? 'cursor-pointer text-[11px] text-muted-foreground focus-visible:outline focus-visible:outline-ring'
                  : 'cursor-pointer rounded border px-3 py-2 text-muted-foreground focus-visible:outline focus-visible:outline-ring'
              }
            >
              Details
            </summary>
            <div className="absolute right-0 top-full z-30 mt-2 max-h-[65vh] w-[min(560px,calc(100vw-2rem))] overflow-auto rounded-md border bg-card p-4 shadow-xl">
              <p className="font-medium">Setup: Directional option buying</p>
              <p className="mb-3 text-muted-foreground">
                Confirmed RSI + MACD price entries. IV remains a separate premium check.
              </p>
              <p className="mb-3 text-muted-foreground">
                <a
                  href="https://algotest.in/blog/best-indicator-for-option-trading/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2"
                >
                  Article: RSI timing + MACD confirmation + IV
                </a>
                . Our implementation uses RSI 14, MACD 12/26/9 and a five-candle event window; these
                settings are not specified by the article. EMA 9/15 and levels are context.
              </p>
              <p className="mb-3 font-medium">Chart layers</p>
              <div className="grid gap-3 border-b pb-3 sm:grid-cols-2">
                {(
                  [
                    ['liquidity', 'Liquidity zones'],
                    ['trends', 'Diagonal trendlines'],
                    ['references', '1D / 4H / 1H high & low'],
                    ['events', 'Breakout & sweep markers'],
                    ['bands', 'Bollinger bands'],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!settings[key]}
                      onChange={(e) => onSettings({ ...settings, [key]: e.target.checked })}
                    />
                    {label}
                  </label>
                ))}
                <label className="flex items-center gap-2">
                  Historical {signalMarket === 'perpetual' ? 'LONG / SHORT' : 'BULL / BEAR'}
                  <select
                    aria-label="Historical BULL BEAR labels"
                    value={settings.markerLimit}
                    onChange={(e) =>
                      onSettings({ ...settings, markerLimit: Number(e.target.value) })
                    }
                    className="h-8 rounded border bg-background px-2"
                  >
                    {[4, 8, 12].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="space-y-2 py-3 leading-relaxed">
                <p>
                  <b>Current check:</b> {decision?.reason ?? 'Loading indicators'}
                </p>
                <p className="tabular-nums">
                  RSI zone exit:{' '}
                  {decision?.rsiAge == null ? 'none detected' : `${decision.rsiAge} candles ago`}
                  {' · '}Matching MACD cross:{' '}
                  {decision?.crossAge == null
                    ? 'none detected'
                    : `${decision.crossAge} candles ago`}
                  . Each must be within 5 candles.
                </p>
                <p>
                  <b>{signalMarket === 'perpetual' ? 'LONG' : 'BULL'}:</b> RSI exits above 30 +
                  recent MACD cross up + positive, rising histogram.
                </p>
                <p>
                  <b>{signalMarket === 'perpetual' ? 'SHORT' : 'BEAR'}:</b> RSI exits below 70 +
                  recent MACD cross down + negative, falling histogram.
                </p>
                <p className="text-muted-foreground">
                  Both events must be within 5 candles and RSI between 30–70. One confirmed signal
                  per RSI exit. WAIT means no new confirmed setup. CALL / PUT identifies the index
                  price direction; option IV is a separate check. EMA and levels provide context.
                </p>
                <p className="tabular-nums">
                  <span className="text-blue-500">EMA 9 {number(m?.ema9)}</span> ·{' '}
                  <span className="text-amber-500">
                    EMA {settings.slow} {number(m?.emaSlow)}
                  </span>
                  {m?.imi != null ? (
                    <span>
                      {' '}
                      · IMI <b className={tone(m.imi, 30, 70)}>{number(m.imi)}</b>
                    </span>
                  ) : null}
                  {m?.mfi != null ? (
                    <span>
                      {' '}
                      · MFI <b className={tone(m.mfi, 20, 80)}>{number(m.mfi)}</b>
                    </span>
                  ) : null}
                  {m?.bbWidth != null ? <span> · BB width {number(m.bbWidth)}%</span> : null}
                </p>
                {latest ? (
                  <p className="text-muted-foreground">
                    Last historical signal: {latest.side} ·{' '}
                    {new Date(latest.time * 1000).toLocaleString('en-IN', {
                      timeZone: 'Asia/Kolkata',
                      day: '2-digit',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}{' '}
                    IST
                  </p>
                ) : null}
                <p className="text-muted-foreground">
                  Liquidity zones estimate repeated highs/lows. ▲ / ▼ = strong closed breakout; ◇ =
                  wick sweep. Swing levels confirm after 5 closed candles.
                </p>
              </div>
              {settings.references ? (
                <div className="grid gap-1 border-t py-3 tabular-nums sm:grid-cols-2">
                  {references.map((r) => (
                    <p key={r.name}>
                      <b>{r.name}</b> {number(r.price)}{' '}
                      <span className="text-muted-foreground">· completed</span>
                    </p>
                  ))}
                  {!references.length ? (
                    <p className="text-muted-foreground">
                      {referenceError
                        ? 'Reference history unavailable'
                        : referenceLoading
                          ? 'Loading completed reference candles…'
                          : 'No complete reference candles in this history range.'}
                    </p>
                  ) : null}
                </div>
              ) : null}
              {showIV ? <IVCalculator reference={reference} replay={replay} /> : null}
            </div>
          </details>
        </div>
      </div>
    </section>
  )
})
