import { useEffect, useMemo, useRef, useState } from 'react'
import { adminApi } from '@/api/admin'
import { scalpingApi } from '@/api/scalping'
import { useChartCandles } from './chartCandleStore'
import {
  chartRangeBars,
  istSessionDate,
  type ChartDateRange,
  type ReplayCandle,
} from './chartReplay'
import { loadChartRangeHistory } from './chartRangeHistory'
import { loadReplayCalendar, replayDefaultDate, type ReplayCalendar } from './replayMarketDay'

export function useDashboardReplay(
  keys: string[],
  instruments: Array<{ symbol: string; exchange: string }>,
  interval: string,
  exchange: string
) {
  const [minute, setMinute] = useState(() => Math.floor(Date.now() / 60000))
  const today = istSessionDate(minute * 60)
  const calendarScope = `${today}:${exchange}`
  const [calendar, setCalendar] = useState<{
    scope: string
    value?: ReplayCalendar
    error?: string
  }>({ scope: '' })
  const [selectedRange, setSelectedRange] = useState<ChartDateRange | null>(null)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setMinute(Math.floor(Date.now() / 60000)), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    loadReplayCalendar(today, exchange, adminApi.checkTimings, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setCalendar({ scope: calendarScope, value })
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setCalendar({
            scope: calendarScope,
            error: 'Market calendar unavailable; choose replay dates manually.',
          })
      })
    return () => controller.abort()
  }, [today, exchange, calendarScope, revision])
  const current = calendar.scope === calendarScope ? calendar : null
  const automaticDate = current?.value ? replayDefaultDate(current.value, minute * 60000) : today
  const range = selectedRange ?? { start: automaticDate, end: automaticDate }
  const a = useChartCandles(keys[0] || ''),
    b = useChartCandles(keys[1] || ''),
    c = useChartCandles(keys[2] || '')
  const liveSources = [a, b, c].slice(0, keys.length)
  const autoHistoryMissing =
    !selectedRange &&
    !!current?.value &&
    automaticDate !== today &&
    liveSources.every((bars) => bars.length > 0) &&
    liveSources.some((bars) => !chartRangeBars(bars, range.start, range.end, 19800).length)
  const needsHistory = !!selectedRange || autoHistoryMissing
  const seed = useRef([a, b, c])
  seed.current = [a, b, c]
  const instrumentScope = JSON.stringify(instruments)
  const historyScope = JSON.stringify([keys, range.start, range.end])
  const [loaded, setLoaded] = useState<{
    scope: string
    series?: ReplayCandle[][]
    error?: string
    emptyDates?: string[]
  }>({ scope: '' })
  // Primitive scopes prevent live ticks/account refreshes from reloading historical days.
  // biome-ignore lint/correctness/useExhaustiveDependencies: inputs are represented by these stable value scopes
  useEffect(() => {
    if (!needsHistory) return
    const controller = new AbortController()
    const sources = seed.current
    const dayCalendars = new Map<string, ReturnType<typeof adminApi.checkTimings>>()
    const load = async () => {
      const series: ReplayCandle[][] = [],
        emptyDates = new Set<string>()
      // Load panes sequentially; the shared loader limits daily reads to two at once.
      for (let i = 0; i < instruments.length; i++) {
        const instrument = instruments[i],
          cached = sources[i] || []
        if (!instrument.symbol)
          throw Error('Choose expiry and strikes before replaying this range.')
        const result = await loadChartRangeHistory(
          range,
          async (date) => {
            const known = chartRangeBars(cached, date, date, 19800)
            if (known.length) return { status: 'success', candles: known }
            if ([0, 6].includes(new Date(`${date}T00:00:00Z`).getUTCDay())) {
              if (!dayCalendars.has(date)) dayCalendars.set(date, adminApi.checkTimings(date))
              const day = await dayCalendars.get(date)!
              const calendarExchange = instrument.exchange.replace(/_INDEX$/, '')
              if (!day.timings.some((t) => t.exchange === calendarExchange))
                return { status: 'success', candles: [] }
            }
            return scalpingApi.getHistory(instrument.symbol, instrument.exchange, interval, date)
          },
          cached,
          controller.signal,
          true
        )
        series.push(result.candles)
        result.emptyDates.forEach((date) => emptyDates.add(date))
      }
      if (!controller.signal.aborted)
        setLoaded({ scope: historyScope, series, emptyDates: [...emptyDates] })
    }
    void load().catch((error) => {
      if (!controller.signal.aborted)
        setLoaded({ scope: historyScope, error: (error as Error).message })
    })
    return () => controller.abort()
  }, [selectedRange, needsHistory, historyScope, instrumentScope, interval, revision])
  const history = loaded.scope === historyScope ? loaded : null
  const sources = useMemo(
    () =>
      needsHistory && history?.series
        ? history.series.map((saved, i) =>
            [
              ...new Map(
                [...saved, ...([a, b, c][i] || [])].map((bar) => [bar.time, bar])
              ).values(),
            ].sort((x, y) => x.time - y.time)
          )
        : undefined,
    [needsHistory, history?.series, a, b, c]
  )
  const loading = needsHistory ? !history : !current
  const error = needsHistory ? history?.error : current?.error
  const coverage =
    needsHistory && history?.emptyDates?.length
      ? `No candles on ${history.emptyDates.join(', ')} in one or more charts.`
      : ''
  const policy = !current
    ? 'Checking exchange calendar…'
    : automaticDate === today
      ? 'Market open · replay defaults to today'
      : 'Market closed · replay defaults to the previous trading day'
  return {
    range,
    selectedRange,
    setSelectedRange,
    retry: () => {
      setCalendar({ scope: '' })
      setLoaded({ scope: '' })
      setRevision((value) => value + 1)
    },
    sources,
    loading: !!loading,
    unavailable: !!error,
    canRetry: !!error || !!coverage,
    message: error ?? [selectedRange ? '' : policy, coverage].filter(Boolean).join(' · '),
  }
}
