import { useEffect, useState } from 'react'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { useMarketDataContextOptional } from '@/contexts/MarketDataContext'

const number = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const positive = (value: number | undefined): value is number =>
  value != null && Number.isFinite(value) && value > 0
const signed = (value: number) => `${value > 0 ? '+' : ''}${number.format(value)}`

export function DashboardMarketStrip({ symbol = 'NIFTY' }: { symbol?: string }) {
  // Remount quote state on an index switch so an old REST snapshot cannot flash
  // beneath the new index name while the hook resets its fallback state.
  return <MarketStrip key={symbol} symbol={symbol} />
}

function MarketStrip({ symbol }: { symbol: string }) {
  const retainBackgroundUpdates = useMarketDataContextOptional()?.retainBackgroundUpdates
  useEffect(() => retainBackgroundUpdates?.(), [retainBackgroundUpdates])
  const [, tick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => tick((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const quote = useLiveQuote(symbol, symbol === 'SENSEX' ? 'BSE_INDEX' : 'NSE_INDEX', {
    mode: 'Quote',
    useDepthFallback: false,
    refreshInterval: 1000,
    staleThreshold: 5000,
  })
  const price = positive(quote.data.ltp) ? quote.data.ltp : null
  const prior = positive(quote.data.close) ? quote.data.close : null
  const change = price != null && prior != null ? price - prior : null
  const percent = change != null && prior != null ? (change / prior) * 100 : null
  const movementKnown = change != null && percent != null && Number.isFinite(percent)
  const fresh = quote.isLive && quote.dataSource === 'websocket' && price != null
  useEffect(() => {
    const previous = document.title
    const title =
      price == null
        ? `${symbol} —`
        : `${fresh ? '' : 'Last '}${number.format(price)}${change == null ? '' : ` ${signed(change).replace('-', '−')}`} | ${symbol}`
    document.title = title
    return () => {
      if (document.title === title) document.title = previous
    }
  }, [symbol, price, change, fresh])
  const direction =
    fresh && movementKnown ? (change > 0 ? 'up' : change < 0 ? 'down' : 'neutral') : 'neutral'
  useEffect(() => {
    const previousIcon = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
    const icon = previousIcon ?? document.createElement('link')
    const previousHref = icon.getAttribute('href')
    const previousType = icon.getAttribute('type')
    const color = direction === 'up' ? '#15803d' : direction === 'down' ? '#b91c1c' : '#64748b'
    const arrow =
      direction === 'up'
        ? 'M16 6 5 22h22z'
        : direction === 'down'
          ? 'M16 26 5 10h22z'
          : 'M6 13h20v6H6z'
    const href = `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="${color}"/><path d="${arrow}" fill="white"/></svg>`)}`
    icon.rel = 'icon'
    icon.type = 'image/svg+xml'
    icon.href = href
    if (!previousIcon) document.head.append(icon)
    return () => {
      if (icon.getAttribute('href') !== href) return
      if (!previousIcon) {
        icon.remove()
        return
      }
      if (previousHref == null) icon.removeAttribute('href')
      else icon.setAttribute('href', previousHref)
      if (previousType == null) icon.removeAttribute('type')
      else icon.setAttribute('type', previousType)
    }
  }, [direction])
  const tone =
    direction === 'up'
      ? 'border-emerald-600 bg-emerald-950 text-emerald-100'
      : direction === 'down'
        ? 'border-red-600 bg-red-950 text-red-100'
        : 'border-slate-600 bg-slate-900 text-slate-100'
  const Icon =
    movementKnown && change > 0
      ? ArrowUpRight
      : movementKnown && change < 0
        ? ArrowDownRight
        : Minus
  const movement = movementKnown
    ? change > 0
      ? 'UP'
      : change < 0
        ? 'DOWN'
        : 'UNCHANGED'
    : 'WAITING'
  const source = fresh
    ? 'Live feed · panels refresh 1s'
    : quote.dataSource === 'rest'
      ? 'Broker snapshot · freshness unverified'
      : price != null
        ? 'Feed unavailable or stale · last reported price'
        : 'Waiting for broker quote'
  return (
    <section
      aria-label={`${symbol} market summary`}
      data-direction={direction}
      className={`sticky top-14 z-30 rounded-xl border px-4 py-3 shadow-lg md:px-6 ${tone}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="text-lg font-bold tracking-wide md:text-xl">{symbol}</h2>
          <strong aria-label="Index price" className="text-3xl font-bold tabular-nums md:text-4xl">
            {price == null ? '—' : `₹${number.format(price)}`}
          </strong>
        </div>
        <div className="flex items-center gap-3">
          <Icon aria-hidden="true" className="h-7 w-7 shrink-0" />
          <div>
            <p className="text-lg font-bold">
              {!fresh && movementKnown ? `Last ${movement}` : movement}
            </p>
            <p aria-label="Day movement" className="text-xl font-semibold tabular-nums md:text-2xl">
              {movementKnown
                ? `${signed(change)} pts (${signed(percent)}%)`
                : 'Waiting for previous close'}
            </p>
          </div>
        </div>
      </div>
      <p className="mt-1 text-xs opacity-85">{source} · Day movement versus previous close</p>
    </section>
  )
}
