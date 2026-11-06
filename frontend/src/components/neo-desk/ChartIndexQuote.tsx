import { useEffect, useState } from 'react'
import { useLiveQuote } from '@/hooks/useLiveQuote'

const number = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const positive = (value: number | undefined): value is number =>
  value != null && Number.isFinite(value) && value > 0
const signed = (value: number) =>
  `${value > 0 ? '+' : value < 0 ? '−' : ''}${number.format(Math.abs(value))}`

export function ChartIndexQuote({ symbol }: { symbol: string }) {
  // Reset fallback quote state on an index switch, including while viewing CE/PE.
  return <IndexQuote key={symbol} symbol={symbol} />
}

function IndexQuote({ symbol }: { symbol: string }) {
  const [, refresh] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => refresh(value => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const quote = useLiveQuote(symbol, symbol === 'SENSEX' ? 'BSE_INDEX' : 'NSE_INDEX', {
    mode: 'Quote',
    useDepthFallback: false,
    refreshInterval: 1000,
    staleThreshold: 5000,
  })
  const price = positive(quote.data.ltp) ? quote.data.ltp : null
  const close = positive(quote.data.close) ? quote.data.close : null
  const change = price != null && close != null ? price - close : null
  const percent = change != null && close != null ? 100 * change / close : null
  const known = change != null && percent != null && Number.isFinite(percent)
  const live = quote.isLive && quote.dataSource === 'websocket' && price != null
  const tone = !live || !known || change === 0
    ? 'text-muted-foreground'
    : change > 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400'
  return (
    <div aria-label="Selected index quote" className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded px-1 text-xs tabular-nums">
      <span className="font-semibold">{symbol}</span>
      <strong aria-label="Index price" className="text-sm">{price == null ? '—' : number.format(price)}</strong>
      <span aria-label="Index day change" title="Day change versus previous close" className={`font-semibold ${tone}`}>
        {known ? `${signed(change)} (${signed(percent)}%)` : '—'}
      </span>
      <span className="text-xs text-muted-foreground">{live ? 'Live' : price == null ? 'Waiting for quote' : 'Last quote'}</span>
    </div>
  )
}
