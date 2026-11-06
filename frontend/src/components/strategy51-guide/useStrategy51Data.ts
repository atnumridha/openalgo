import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { scalpingApi } from '@/api/scalping'
import type { OptionChainResponse } from '@/types/scalping'
import { resolveIndicatorChart } from '../chart-toolkit/indicatorChartContext'
import { bookChartBars } from '../book-pattern-guide/adapter'
import { chartBars } from '../neo-desk/tradingViewStudies'
import type { OptionEvidence, StrategyBar, StrategyExtras, SuppliedContext } from './types'
type HistoryReader = (
  symbol: string,
  exchange: string,
  interval: string,
  date?: string,
  signal?: AbortSignal
) => Promise<{
  status: string
  symbol: string
  exchange: string
  interval: string
  observedAt: number
  candles: StrategyBar[]
}>
const slot = (t: number) => ((((t + 19800) % 86400) + 86400) % 86400) / 60
const day = (t: number) => Math.floor((t + 19800) / 86400)
/** Candle-open snapshots are labelled local approximations to source tick snapshots. */
export function deriveOptionEvidence(
  symbol: string,
  exchange: string,
  premium: readonly StrategyBar[],
  underlying: readonly StrategyBar[],
  chain: OptionChainResponse | undefined,
  supplied: SuppliedContext[] = [],
  intervalSeconds?: number
): OptionEvidence | undefined {
  const m = /^([A-Z][A-Z0-9&-]*?)(\d{2}[A-Z]{3}\d{2})(\d+(?:\.\d+)?)(CE|PE)$/.exec(symbol)
  if (
    !m ||
    !chain ||
    chain.status !== 'success' ||
    chain.fo_exchange !== exchange ||
    chain.expiry_date !== m[2] ||
    chain.underlying !== m[1]
  )
    return
  const strike = Number(m[3]),
    type = m[4] as 'CE' | 'PE',
    contract = chain.chain.find((r) => r.strike === strike)?.[type === 'CE' ? 'ce' : 'pe']
  if (!contract || contract.symbol !== symbol || contract.exists === false) return
  const selections: NonNullable<OptionEvidence['selection']>[] = []
  const days = [...new Set(premium.slice(-1500).map((b) => day(b.time)))],
    strikes = chain.chain
      .map((r) => r.strike)
      .filter(Number.isFinite)
      .sort((a, b) => a - b)
  for (const sourceDay of days)
    for (const n of [556, 560, 570, 600, 616, 660, 676, 736, 900]) {
      const p = premium.find((b) => day(b.time) === sourceDay && Math.abs(slot(b.time) - n) < 0.01),
        u = underlying.find((b) => day(b.time) === sourceDay && Math.abs(slot(b.time) - n) < 0.01)
      if (!p) continue
      for (const z of supplied.filter(
        (x) =>
          x.symbol === symbol &&
          x.exchange === exchange &&
          (intervalSeconds == null || x.intervalSeconds === intervalSeconds) &&
          day(x.asOf) === sourceDay &&
          Math.abs(slot(x.asOf) - n) < 0.01 &&
          x.description.trim()
      )) {
        if (z.strategyId === '6.3' && n === 560)
          selections.push({
            time: p.time,
            kind: 'highest-oi',
            source: 'supplied',
            description: z.description,
          })
        if (z.strategyId === '6.10' && n === 660 && type === 'CE')
          selections.push({
            time: p.time,
            kind: 'chosen-call',
            source: 'supplied',
            description: z.description,
            exitAt: z.nextSessionExitAt,
          })
      }
      if (!u) continue
      // Never declare the edge of a truncated chain to be ATM.
      if (!(strikes[0] < u.open && strikes.at(-1)! > u.open)) continue
      const atm = strikes.reduce(
        (best, z) => (Math.abs(z - u.open) < Math.abs(best - u.open) ? z : best),
        strikes[0]
      )
      const describe = `Exact${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')} underlying candle-open${u.open}; listed strike metadata and the same option's baseline candle. Local nearest-strike tie chooses lower.`
      if (strike === atm)
        selections.push({
          time: p.time,
          kind: 'atm',
          source: 'verified-history',
          description: describe,
        })
      const otm = type === 'CE' ? strike > u.open : strike < u.open
      if (otm && Math.abs(p.open - 40) <= 2)
        selections.push({
          time: p.time,
          kind: 'near40',
          source: 'verified-history',
          description: `${describe} Local near₹40 tolerance±₹2.`,
        })
      if (Math.abs(p.open - 150) <= 7.5)
        selections.push({
          time: p.time,
          kind: 'near150',
          source: 'verified-history',
          description: `${describe} Local near₹150 tolerance±5%.`,
        })
    }
  const date = /^(\d{2})([A-Z]{3})(\d{2})$/.exec(m[2]),
    months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'],
    month = date ? months.indexOf(date[2]) : -1,
    year = date ? 2000 + Number(date[3]) : 0,
    dom = date ? Number(date[1]) : 0,
    midnight = Date.UTC(year, month, dom) / 1000,
    parsed = new Date(midnight * 1000)
  const expiryTime =
    month >= 0 &&
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month &&
    parsed.getUTCDate() === dom
      ? midnight - 19800 + 930 * 60
      : undefined
  return {
    symbol,
    exchange,
    underlying: m[1],
    expiry: m[2],
    expiryTime,
    strike,
    optionType: type,
    selections,
  }
}
export function useStrategy51Data({
  enabled,
  symbol,
  exchange,
  seconds,
  owner,
  mode,
  historical,
  readHistory,
}: {
  enabled: boolean
  symbol: string
  exchange: string
  seconds: number
  owner?: string
  mode: string
  historical: boolean
  readHistory: HistoryReader
}) {
  const chart = resolveIndicatorChart(symbol, exchange),
    root = chart.underlying,
    option =
      chart.kind === 'option' && ['NFO', 'BFO'].includes(exchange) && !!root && !!chart.expiry
  const hourly = useQuery({
    queryKey: ['strategy51-hourly', owner, mode, symbol, exchange],
    enabled: enabled && !historical && seconds === 300,
    queryFn: async ({ signal }) => {
      const h = await readHistory(symbol, exchange, '1h', undefined, signal)
      if (
        h.status !== 'success' ||
        h.symbol !== symbol ||
        h.exchange !== exchange ||
        h.interval !== '1h'
      )
        throw Error('Matching hourly source unavailable')
      const bars = bookChartBars(
        chartBars(h.candles),
        3600,
        ['DELTA', 'CRYPTO'].includes(exchange) ? undefined : { start: 555, end: 930, offset: 19800 }
      ).filter(
        (b) =>
          b.closeTime! <= h.observedAt || (b.closeTime == null && b.time + 3600 <= h.observedAt)
      )
      return { bars, intervalSeconds: 3600, observedAt: h.observedAt, symbol, exchange }
    },
    staleTime: 45000,
    refetchInterval: enabled && !historical && seconds === 300 ? 60000 : false,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const underlying = useQuery({
    queryKey: ['strategy51-underlying-baselines', owner, mode, root?.symbol, root?.exchange],
    enabled: enabled && !historical && option,
    queryFn: async ({ signal }) => {
      const h = await readHistory(root!.symbol, root!.exchange, '1m', undefined, signal)
      if (
        h.status !== 'success' ||
        h.symbol !== root!.symbol ||
        h.exchange !== root!.exchange ||
        h.interval !== '1m'
      )
        throw Error('Underlying baseline source mismatched')
      return {
        bars: bookChartBars(chartBars(h.candles), 60, {
          start: 555,
          end: 930,
          offset: 19800,
        }).filter((b) => (b.closeTime ?? b.time + 60) <= h.observedAt),
        intervalSeconds: 60,
        observedAt: h.observedAt,
        symbol: root!.symbol,
        exchange: root!.exchange,
      }
    },
    staleTime: 45000,
    refetchInterval: enabled && !historical && option ? 60000 : false,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const chain = useQuery({
    queryKey: ['strategy51-contracts', owner, mode, root?.symbol, exchange, chart.expiry],
    enabled: enabled && !historical && option,
    queryFn: async () => {
      const data = await scalpingApi.getStrikes(root!.symbol, exchange, chart.expiry!, 20, {
        quotes: false,
      })
      if (
        data.status !== 'success' ||
        data.underlying !== root!.symbol ||
        data.fo_exchange !== exchange ||
        data.expiry_date !== chart.expiry
      )
        throw Error('Matching option contract metadata unavailable')
      return data
    },
    staleTime: 60000,
    refetchInterval: enabled && !historical && option ? 120000 : false,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const extras = useMemo<StrategyExtras>(
    () => ({
      higher: enabled && !historical && !hourly.isError ? hourly.data : undefined,
      underlying: enabled && !historical && !underlying.isError ? underlying.data : undefined,
      dataReasons: [
        ...(historical
          ? ['Auxiliary live data is excluded from historical/replay decisions.']
          : []),
        ...(hourly.isError ? ['Hourly source delayed; Double RSI waits.'] : []),
        ...(underlying.isError
          ? ['Underlying baseline history unavailable; ATM selection waits.']
          : []),
        ...(chain.isError ? ['Option contract metadata unavailable.'] : []),
      ],
    }),
    [
      enabled,
      historical,
      hourly.data,
      hourly.isError,
      underlying.data,
      underlying.isError,
      chain.isError,
    ]
  )
  return { extras, chain: enabled && !historical && !chain.isError ? chain.data : undefined }
}
