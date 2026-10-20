import { useEffect, useMemo, useState } from 'react'
import { useBrokerCurrencyFormatter, useBrokerPriceFormatter } from '@/hooks/useBrokerCurrencyFormatter'
import type { TradingTerminal } from '@/lib/trading/terminal'
import {
  analyseCrypto,
  backtestCrypto,
  CRYPTO_STRATEGIES,
  DEFAULT_CRYPTO_SETTINGS,
  type CryptoStrategy,
  type CryptoSettings,
  type CryptoBacktest,
} from '@/lib/trading/cryptoStrategies'

type Snapshot = NonNullable<ReturnType<TradingTerminal['cryptoResearchSnapshot']>>
const HUM =
  'https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/controllers/generic/'
const other = [
  {
    name: 'Delta BTC futures · market maker',
    url: 'https://github.com/delta-exchange/trading-bots/blob/9676a2686b2c463c3c66cb001544ec417963ef96/market_maker/unhedged.py',
    reason:
      'Official legacy bitcoin-futures example. Its risk-limit method returns orders unchanged and it can add margin automatically; not adopted as a safe modern Delta India strategy.',
  },
  {
    name: 'Delta BTCUSD · multi-timeframe',
    url: 'https://github.com/kasyap1234/delta-exchange/blob/99ac6b7ab5e8166135ab94e0b29d20aee01cc747/src/strategies/multi_timeframe.py',
    reason:
      'Community Delta implementation: higher-timeframe trend and lower-timeframe entries with ATR stops. Source reviewed; no verified performance or installed executor.',
  },
  {
    name: 'Grid Strike',
    url: HUM + 'grid_strike.py',
    reason:
      'Requires price boundaries, a position budget, order spacing and a grid executor. Not installed in this chart.',
  },
  {
    name: 'Cross-exchange arbitrage',
    url: HUM + 'arbitrage_controller.py',
    reason:
      'Requires two exchange connections, comparable executable quotes and costs for both legs. Only Delta is connected here.',
  },
  {
    name: 'FreqAI example',
    url: 'https://github.com/freqtrade/freqtrade/blob/3ebac56eba525c991462c0714c65a6e2f4e36896/freqtrade/templates/FreqaiExampleStrategy.py',
    reason:
      'Requires Freqtrade/FreqAI, training data and a validated trained model. The existing Delta ML model is a different strategy.',
  },
]
export function CryptoStrategyLab({ target }: { target: () => TradingTerminal | null }) {
  const [open, setOpen] = useState(false),
    [id, setId] = useState<CryptoStrategy>('bollinger')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [config, setConfig] = useState<CryptoSettings>(DEFAULT_CRYPTO_SETTINGS)
  const [result, setResult] = useState<{ key: string; data: CryptoBacktest } | null>(null)
  const money = useBrokerCurrencyFormatter('deltaexchange')
  const quote = useBrokerPriceFormatter('deltaexchange')
  useEffect(() => {
    if (!open) return
    const read = () => {
      if (document.hidden) return
      setSnapshot(target()?.cryptoResearchSnapshot() ?? null)
    }
    read()
    const timer = window.setInterval(read, 1000)
    return () => window.clearInterval(timer)
  }, [open, target])
  // Costs and exits are editable research assumptions; no account or order state is changed.
  const settings = useMemo(
    () => ({
      ...config,
      tick: snapshot?.tick ?? config.tick,
      contractValue: snapshot?.contractValue ?? config.contractValue,
    }),
    [config, snapshot?.tick, snapshot?.contractValue]
  )
  const key = JSON.stringify([
    snapshot?.symbol,
    snapshot?.interval,
    id,
    settings,
    snapshot?.replay,
    snapshot?.replay ? snapshot?.bars.at(-1)?.time : null,
  ])
  const evaluation = useMemo(() => {
    if (!snapshot) return null
    try {
      return { plan: analyseCrypto(id, snapshot.bars, settings), error: null }
    } catch (e) {
      return { plan: null, error: e instanceof Error ? e.message : 'Invalid research settings' }
    }
  }, [snapshot, id, settings])
  const field = (
    label: string,
    name: keyof CryptoSettings,
    step: number,
    min: number,
    max: number
  ) => (
    <label className="flex flex-col gap-1 text-xs" key={name}>
      {label}
      <input
        className="h-8 w-28 rounded border bg-background px-2 tabular-nums"
        type="number"
        step={step}
        min={min}
        max={max}
        value={Number.isFinite(config[name]) ? config[name] : ''}
        onChange={(e) => {
          setConfig((c) => ({ ...c, [name]: e.target.value === '' ? NaN : Number(e.target.value) }))
          setResult(null)
        }}
      />
    </label>
  )
  const p = evaluation?.plan
  const eligible = !!snapshot?.contractValue && snapshot.contractValue > 0
  const currentResult = result?.key === key ? result.data : null
  return (
    <section
      className="shrink-0 border-t bg-background"
      aria-label="BTCUSD futures strategy research"
    >
      <button
        type="button"
        className="flex min-h-10 w-full items-center justify-between px-4 text-sm font-medium hover:bg-accent"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span>BTCUSD futures · source-backed setups</span>
        <span>{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto border-t px-4 py-3 text-sm">
          <div className="sticky top-0 z-10 flex flex-wrap items-end gap-3 border-b bg-background pb-2">
            <label className="flex flex-col gap-1 text-xs">
              Strategy
              <select
                aria-label="Crypto strategy"
                className="h-8 rounded border bg-background px-2"
                value={id}
                onChange={(e) => {
                  setId(e.target.value as CryptoStrategy)
                  setResult(null)
                }}
              >
                {Object.entries(CRYPTO_STRATEGIES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
            <span className="text-xs text-muted-foreground">
              {snapshot
                ? `${snapshot.symbol} · ${snapshot.interval} · ${snapshot.bars.length} completed bars · ${snapshot.replay ? 'REPLAY' : snapshot.fresh ? 'Recent bars' : 'Historical / stale bars'}`
                : 'Select the Delta BTCUSDFUT perpetual chart with loaded history.'}
            </span>
            <a
              className="text-xs underline"
              href={CRYPTO_STRATEGIES[id].source}
              target="_blank"
              rel="noreferrer"
            >
              Pinned GitHub source
            </a>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            General-market source, evaluated on Delta BTCUSD futures. {CRYPTO_STRATEGIES[id].rules}{' '}
            Source timeframe: 3m. Prices are per BTC;{' '}
            {snapshot?.contractValue ? `1 contract = ${snapshot.contractValue} BTC. ` : ''}{' '}
            {snapshot?.interval !== '3m' ? 'Current chart uses an adapted timeframe.' : ''}
          </p>
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            <div className="rounded border p-3">
              <p
                className={`font-semibold ${p?.side === 'LONG' ? 'text-emerald-600 dark:text-emerald-400' : p?.side === 'SHORT' ? 'text-red-600 dark:text-red-400' : ''}`}
              >
                {p?.side === 'LONG'
                  ? '↑ LONG setup'
                  : p?.side === 'SHORT'
                    ? '↓ SHORT setup'
                    : 'Waiting for setup'}
                {snapshot?.replay
                  ? ' · replay only'
                  : snapshot && !snapshot.fresh
                    ? ' · historical only'
                    : ''}
              </p>
              <p className="mt-1 text-xs">
                {evaluation?.error ?? p?.reason ?? 'Waiting for chart candles.'}
              </p>
              {p?.evidence.map((x) => (
                <p key={x} className="mt-1 text-xs text-muted-foreground">
                  {x}
                </p>
              ))}
              {p?.entry && (
                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <dt>Reference entry</dt>
                    <dd className="font-semibold">{quote(p.entry)}</dd>
                  </div>
                  <div>
                    <dt>App SL</dt>
                    <dd className="font-semibold">{quote(p.stop!)}</dd>
                  </div>
                  <div>
                    <dt>App target</dt>
                    <dd className="font-semibold">{quote(p.target!)}</dd>
                  </div>
                </dl>
              )}
            </div>
            <div>
              <p className="text-xs font-medium">
                Research exit and cost template · separate from source entry rules
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {field('Contracts', 'quantity', 1, 1, 100000)}
                {field('Stop distance %', 'stopPct', 0.1, 0.1, 49)}
                {field('Reward multiple', 'reward', 0.5, 1, 10)}
                {field('Max holding bars', 'maxBars', 1, 1, 1000)}
                {field('Fee % per side, incl. GST', 'feePct', 0.001, 0, 5)}
                {field('Slippage % per side', 'slippagePct', 0.001, 0, 5)}
              </div>
              <button
                type="button"
                className="mt-3 rounded border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50"
                disabled={
                  !snapshot ||
                  !eligible ||
                  !!evaluation?.error ||
                  snapshot.bars.length <= CRYPTO_STRATEGIES[id].warmup
                }
                onClick={() => {
                  if (snapshot) {
                    try {
                      setResult({ key, data: backtestCrypto(id, snapshot.bars, settings) })
                    } catch {
                      setResult(null)
                    }
                  }
                }}
              >
                Run loaded-history backtest
              </button>
              {!eligible && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Contract size is unavailable. Cash simulation waits for broker metadata.
                </p>
              )}
            </div>
          </div>
          {currentResult && (
            <div className="mt-3 rounded border p-3 text-xs">
              <p className="font-medium">
                {currentResult.trades.length} simulated trades · Net {money(currentResult.net)} ·
                Costs {money(currentResult.fees)} · Win rate{' '}
                {(currentResult.winRate * 100).toFixed(1)}% · Profit factor{' '}
                {currentResult.profitFactor?.toFixed(2) ?? '—'} · Expectancy{' '}
                {money(currentResult.expectancy)} · Closed-trade drawdown{' '}
                {money(currentResult.drawdown)}
              </p>
              <p className="mt-1">
                Coverage: {currentResult.bars} completed bars,{' '}
                {currentResult.from != null
                  ? new Date(currentResult.from * 1000).toLocaleString()
                  : ''}{' '}
                –{' '}
                {currentResult.to != null ? new Date(currentResult.to * 1000).toLocaleString() : ''}
                . Frozen at click time. Next-bar market assumptions; stop first if both levels
                touch. Includes entered fees and slippage; excludes funding. Loaded history is not a
                one-month validation or a live execution result.
              </p>
            </div>
          )}
          <p className="mt-3 text-xs text-muted-foreground">
            Signals only; no strategy starts or orders are submitted. Stops and targets above use
            your app template, not the full Hummingbot execution engine. Backtest fees default to
            0.05% taker + 18% GST per side; verify the selected contract’s fees.
          </p>
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer font-medium">
              More BTC futures sources · grid, multi-timeframe, arbitrage and ML
            </summary>
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              {other.map((x) => (
                <div className="rounded border p-3" key={x.name}>
                  <a
                    href={x.url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium underline"
                  >
                    {x.name}
                  </a>
                  <p className="mt-1">{x.reason}</p>
                </div>
              ))}
            </div>
          </details>
        </div>
      )}
    </section>
  )
}
