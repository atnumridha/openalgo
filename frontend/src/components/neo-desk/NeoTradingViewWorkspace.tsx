import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { scalpingApi } from '@/api/scalping'
import { Navbar } from '@/components/layout/Navbar'
import { NeoStrategyControls } from '@/components/scalping/NeoStrategyControls'
import { Button } from '@/components/ui/button'
import { NeoMarketChart } from './NeoMarketChart'
import { NeoStrategyResearch } from './NeoStrategyResearch'
import { type NeoChartTarget, NeoTradingTools } from './NeoTradingTools'

type Instrument = { symbol: string; exchange: string }
type History = Awaited<ReturnType<typeof scalpingApi.getHistory>>
const defaults = ['neo-donchian', 'neo-structure', 'rsi']
export function NeoTradingViewWorkspace() {
  const [instrument, setInstrument] = useState<Instrument>({
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
    }),
    [interval, setInterval] = useState('15m'),
    [history, setHistory] = useState<History>(),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(''),
    [revision, setRevision] = useState(0)
  const [studies, setStudies] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem('neo.native.chart.indicators') || 'null')
      return Array.isArray(stored) ? stored.filter((id) => defaults.includes(id)) : defaults
    } catch {
      return defaults
    }
  })
  const state = useRef({ instrument, interval, history, studies }),
    sequence = useRef(0)
  state.current = { instrument, interval, history, studies }
  const load = useCallback(async (selected: Instrument) => {
    const version = ++sequence.current
    setLoading(true)
    setError('')
    try {
      const result = await scalpingApi.getHistory(
        selected.symbol,
        selected.exchange,
        state.current.interval
      )
      if (version !== sequence.current) return
      if (result.status !== 'success' || !result.candles?.length)
        throw Error(
          result.message ||
            'No candles for this instrument. Choose another strike or refresh history.'
        )
      setInstrument(selected)
      setHistory(result)
      state.current = { ...state.current, instrument: selected, history: result }
      setRevision((n) => n + 1)
    } catch (e) {
      if (version === sequence.current) setError((e as Error).message)
      throw e
    } finally {
      if (version === sequence.current) setLoading(false)
    }
  }, [])
  // biome-ignore lint/correctness/useExhaustiveDependencies: a timeframe change must request the current contract again
  useEffect(() => {
    void load(state.current.instrument).catch(() => {})
  }, [interval, load])
  useEffect(
    () => () => {
      sequence.current++
    },
    []
  )
  const adapter = useMemo<NeoChartTarget>(
    () => ({
      loadSymbol: load,
      replayActive: () => false,
      replayPickingBar: () => false,
      dataUnavailable: () => !state.current.history?.candles.length,
      listIndicators: () => state.current.studies.map((id) => ({ id, indicatorId: id, name: id })),
      addIndicatorById: async (id) => {
        const next = [...new Set([...state.current.studies, id])]
        state.current.studies = next
        setStudies(next)
      },
      removeIndicatorById: (id) => {
        const next = state.current.studies.filter((x) => x !== id)
        state.current.studies = next
        setStudies(next)
      },
    }),
    [load]
  )
  const target = useCallback(() => adapter, [adapter])
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Navbar fluid />
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2">
        <div>
          <h1 className="text-base font-semibold">NIFTY trading workspace</h1>
          <p className="text-xs text-muted-foreground">
            TradingView chart · Kotak Neo data · our strategy presets
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="neo-tv-timeframe" className="text-xs text-muted-foreground">
            Timeframe
          </label>
          <select
            id="neo-tv-timeframe"
            value={interval}
            disabled={loading}
            onChange={(e) => setInterval(e.target.value)}
            className="h-9 rounded-md border bg-card px-2 text-sm"
          >
            {['1m', '3m', '5m', '15m', '30m', '1h', '1d'].map((value) => (
              <option key={value} value={value}>
                {value === '1d' ? 'Daily' : value}
              </option>
            ))}
          </select>
          <Button size="sm" variant="outline" asChild>
            <Link to="/scalping">Positions & controls</Link>
          </Button>
        </div>
      </div>
      <NeoTradingTools
        target={target}
        revision={revision}
        initialize={false}
        shownSymbol={instrument.symbol}
      />
      {error ? (
        <p
          role="alert"
          className="flex items-center justify-between gap-2 border-b px-4 py-2 text-sm text-destructive"
        >
          {error}
          <Button
            size="sm"
            variant="outline"
            onClick={() => void load(state.current.instrument).catch(() => {})}
          >
            Retry chart
          </Button>
        </p>
      ) : null}
      <div className="grid flex-1 gap-3 p-3 md:grid-cols-[minmax(0,1fr)_300px]">
        <div className="h-[65vh] min-h-[480px] md:h-[calc(100vh-255px)] md:min-h-[550px]">
          <NeoMarketChart
            symbol={instrument.symbol}
            exchange={instrument.exchange}
            interval={interval}
            studies={studies}
            initialHistory={history}
            compact
          />
        </div>
        <aside aria-label="Strategy workspace" className="space-y-3">
          <NeoStrategyControls compact />
          <NeoStrategyResearch />
        </aside>
      </div>
      <p className="px-4 pb-3 text-xs text-muted-foreground">
        Chart timeframe and CE / PE selection are for viewing. Automated entries use confirmed NIFTY
        15-minute setups. BUY, SL and target lines appear for the terminal-owned filled position on
        its matching chart.
      </p>
    </div>
  )
}
