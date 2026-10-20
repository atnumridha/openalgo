import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import type { Quote } from '@/api/kotakAssistant'
import { scalpingApi } from '@/api/scalping'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { candleKey, useChartCandles } from './chartCandleStore'
import { RsiSpeedometer } from './RsiSpeedometer'
import { indicatorTime, tradeIndicators } from './tradeIndicatorsModel'
import { useChartSession } from './useChartSession'

const volumeText = (value: number | null | undefined) =>
  value != null && Number.isFinite(value) && value >= 0
    ? value.toLocaleString('en-IN', { maximumFractionDigits: 0 })
    : 'Unavailable'

export function TradeIndicators({
  symbol,
  exchange,
  interval,
  quote,
  now,
  fetchHistory = true,
}: {
  symbol: string
  exchange: string
  interval: string
  quote?: Quote
  now: number
  fetchHistory?: boolean
}) {
  const username = useAuthStore((s) => s.user?.username)
  const mode = useThemeStore((s) => s.appMode)
  const session = useChartSession(exchange, now, !!symbol)
  const chartBars = useChartCandles(candleKey(username, mode, symbol, exchange, interval))
  const seconds = { '1m': 60, '5m': 300, '15m': 900 }[interval] || 300
  const chartRecent =
    (chartBars.at(-1)?.time ?? 0) >= Math.floor((now + 19800) / seconds) * seconds - seconds
  const history = useQuery({
    queryKey: ['kotak-trade-indicators', username, mode, symbol, exchange, interval],
    queryFn: async () => {
      const result = await scalpingApi.getHistory(symbol, exchange, interval)
      if (result.status !== 'success') throw new Error(result.message || 'Candles unavailable')
      return result.candles || []
    },
    staleTime: 20000,
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
    retry: false,
    enabled: fetchHistory && !chartRecent,
  })
  const bars =
    chartRecent || (chartBars.at(-1)?.time ?? 0) > (history.data?.at(-1)?.time ?? 0)
      ? chartBars
      : history.data || chartBars
  const readout = useMemo(
    () => tradeIndicators(bars, quote, interval, now, session.window),
    [bars, quote, interval, now, session.window]
  )
  const fresh = readout.priceFresh
  const sessionNote =
    session.state === 'checking'
      ? 'Checking exchange calendar'
      : session.state === 'unavailable'
        ? 'Calendar unavailable'
        : ''
  return (
    <div
      className="trade-indicators grid items-stretch gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"
      aria-live="off"
    >
      <RsiSpeedometer
        value={readout.rsi}
        live={readout.live && (chartBars.length > 0 || !history.isError)}
        interval={interval}
        note={
          history.isError && !chartBars.length
            ? 'Candle refresh unavailable'
            : `${sessionNote || readout.reason}${readout.barTime ? ` · ${indicatorTime(readout.barTime)} IST` : ''}`
        }
      />
      <div className="flex min-w-0 flex-col justify-center gap-4 rounded-lg border bg-background/50 p-4">
        <div>
          <p className="text-sm text-muted-foreground">Current {interval} bar volume</p>
          <output
            aria-label="Current bar volume"
            aria-live="off"
            className="mt-1 block text-2xl font-bold tabular-nums"
          >
            {volumeText(readout.currentVolume)}
          </output>
          <p className="mt-1 text-xs text-muted-foreground">
            Bar opened {indicatorTime(readout.currentTime)} IST ·{' '}
            {fresh ? readout.volumeSource : 'Last update · stale'}
          </p>
        </div>
        <div className="border-t pt-3">
          <dl className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs text-muted-foreground">Buyers · bid qty</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums trade-indicators__buy">
                <output aria-label="Current buyer quantity" aria-live="off">
                  {volumeText(quote?.buy_quantity)}
                </output>
              </dd>
              <dd className="text-xs text-muted-foreground">
                {quote?.buy_levels || '—'} visible levels
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Sellers · ask qty</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums trade-indicators__sell">
                <output aria-label="Current seller quantity" aria-live="off">
                  {volumeText(quote?.sell_quantity)}
                </output>
              </dd>
              <dd className="text-xs text-muted-foreground">
                {quote?.sell_levels || '—'} visible levels
              </dd>
            </div>
          </dl>
          <p className="mt-2 text-xs text-muted-foreground">
            {fresh ? 'Live' : 'Last · stale'} pending order-book quantities; executed buy/sell
            volume per bar is unavailable.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Day total:{' '}
            <output aria-label="Day traded volume" aria-live="off">
              {volumeText(quote?.volume)}
            </output>
          </p>
        </div>
      </div>
    </div>
  )
}
