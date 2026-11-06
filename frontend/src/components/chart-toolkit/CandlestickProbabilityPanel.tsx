import type { CandleStudy } from './candleProbabilityTypes'
import { closeTime } from './model'
import { resolveIndicatorChart } from './indicatorChartContext'

const percent = (value: number | null) => (value == null ? '—' : `${(100 * value).toFixed(1)}%`)
const price = (value: number | null | undefined) => (value == null ? '—' : value.toFixed(2))
const stamp = (time: number) =>
  new Date(time * 1000).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })

export function CandlestickProbabilityPanel({
  study,
  symbol,
  exchange,
  seconds,
  ready,
  now,
  replay = false,
  compact = false,
}: {
  study: CandleStudy | null
  symbol: string
  exchange: string
  seconds: number
  ready: boolean
  now: number
  replay?: boolean
  compact?: boolean
}) {
  const scoped =
    study?.model.symbol === symbol &&
    study.model.exchange === exchange &&
    study.model.seconds === seconds
      ? study
      : null
  const latest = scoped?.latest
  const active = scoped?.active
  const reference = active ?? latest ?? scoped?.lastSetup
  const estimate = reference?.estimate
  const closed =
    scoped?.closedTime == null
      ? null
      : closeTime(
          {
            time: scoped.closedTime,
            open: 0,
            high: 0,
            low: 0,
            close: 0,
            volume: 0,
          },
          seconds,
          scoped.model.indian,
          scoped.model.session
        )
  const fresh = closed != null && closed <= now && (replay || now - closed <= seconds + 90)
  const allowed = ready && fresh
  const newSignal =
    latest?.qualified &&
    latest.time === scoped?.closedTime &&
    (!active || active.time === latest.time)
  const decision = allowed ? (newSignal ? latest : active?.qualified ? active : null) : null
  const index = ['NSE_INDEX', 'BSE_INDEX'].includes(exchange)
  const optionSide = resolveIndicatorChart(symbol, exchange).optionSide
  const riskReference = optionSide && reference?.side === 'PUT' ? null : reference
  const tracking = decision != null && !newSignal
  const direction =
    exchange === 'DELTA'
      ? decision?.side === 'CALL'
        ? 'LONG'
        : 'SHORT'
      : decision?.side === 'CALL'
        ? 'BULL'
        : 'BEAR'
  const label = !decision
    ? 'WAIT'
    : optionSide
      ? `${decision.side === 'PUT' ? 'AVOID' : tracking ? 'HOLD' : 'BUY'} ${optionSide}`
      : tracking
        ? `HOLD ${index ? decision.side : direction}`
        : index
          ? `BUY ${decision.side}`
          : direction
  const tone = !decision
    ? 'text-yellow-700 dark:text-yellow-300'
    : decision.side === 'CALL'
      ? 'text-emerald-700 dark:text-emerald-400'
      : 'text-red-700 dark:text-red-400'
  const reason =
    !ready || !scoped
      ? 'Waiting for verified candle history'
      : !fresh
        ? 'Latest completed candle is stale; waiting for fresh history'
        : optionSide && decision?.side === 'PUT'
          ? `Premium is bearish; avoid a new ${optionSide} buy.`
          : tracking
            ? 'Tracking the qualified setup; entry is the original closing price'
            : !latest
              ? 'No setup on the latest completed candle'
              : latest.reason
  const timeframe =
    seconds >= 86400
      ? `${seconds / 86400}d`
      : seconds >= 3600
        ? `${seconds / 3600}h`
        : `${seconds / 60}m`
  const outcome = scoped?.lastOutcome
  const levels = [
    ['Entry', riskReference?.entry],
    ['SL', riskReference?.stop],
    ['2R target', riskReference?.target],
    ['Support · prior 10', reference?.support ?? scoped?.support],
    ['Resistance · prior 10', reference?.resistance ?? scoped?.resistance],
  ] as const
  return (
    <section
      aria-label="Candlestick probability"
      className={`min-w-0 space-y-3 text-foreground ${compact ? 'text-xs' : 'text-sm'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold">Candlestick probability</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {symbol} · {exchange} · {timeframe}
            {replay ? ' · REPLAY' : ''}
          </p>
        </div>
        <output
          aria-label="Candlestick decision"
          className={`rounded-md bg-muted px-2.5 py-1 font-semibold ${tone}`}
        >
          {label}
        </output>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">{reason}</p>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-y py-2">
        <span className="font-medium">{reference?.name ?? 'Awaiting pattern'}</span>
        <strong className="text-lg tabular-nums">{percent(estimate?.probability ?? null)}</strong>
        {reference ? (
          <span className="w-full text-xs text-muted-foreground">
            Prior price context · {reference.context}
          </span>
        ) : null}
        <span className="w-full text-xs text-muted-foreground">
          {estimate
            ? `${estimate.targets} / ${estimate.samples} resolved matches reached 2R`
            : 'No resolved matching observations'}
          {' · '}95% interval {percent(estimate?.lower ?? null)}–{percent(estimate?.upper ?? null)}
        </span>
      </div>
      <div>
        <p className="mb-1.5 text-xs text-muted-foreground">
          {reference
            ? reference.qualified
              ? `Original signal references · ${stamp(reference.time)} IST`
              : `Unqualified reference · ${stamp(reference.time)} IST`
            : 'Price references'}
        </p>
        <dl aria-label="Price references" className="grid grid-cols-3 gap-x-3 gap-y-2 tabular-nums">
          {levels.map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-0.5 font-medium">{price(value)}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="text-xs text-muted-foreground">
        Last signal exit:{' '}
        {outcome
          ? `${outcome.result} · ${stamp(outcome.time)} IST`
          : 'No qualified signal resolved'}
        {outcome?.result === 'TIMEOUT' ? ' · did not reach 2R within 10 candles' : ''}
        {outcome?.ambiguous ? ' · both touched; stop counted first' : ''}
        {outcome?.result === 'UNKNOWN' ? ' · missing candles; excluded from evidence' : ''}
      </p>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Source:{' '}
        {scoped ? scoped.model.source : 'Awaiting evidence for this exact market and timeframe'}
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer py-1 focus-visible:outline focus-visible:outline-ring">
          Evidence and rules
        </summary>
        <div className="mt-1 space-y-1.5 leading-relaxed">
          <p>
            {scoped?.seedUsed
              ? 'Scope-matched historical seed + loaded candles'
              : 'Loaded chart candles only'}
          </p>
          {scoped?.seedUsed ? (
            <p>Evidence observed through: {stamp(scoped.model.trainedThrough)} IST</p>
          ) : null}
          <p>
            Matching observations use the same pattern, direction and prior price context. Rule
            version {scoped?.model.version ?? 1}.
          </p>
          <p>
            Qualifies at ≥80% with ≥50 resolved matches. Estimate is fixed at setup creation;
            Laplace smoothing and Wilson 95% interval.
          </p>
        </div>
      </details>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Historical chance of reaching 2R before SL within 10 completed candles; not option profit or
        a guarantee.
        {index
          ? ' CALL / PUT denotes underlying direction.'
          : ['NFO', 'BFO'].includes(exchange)
            ? ' On option charts, BULL / BEAR describes premium direction.'
            : exchange === 'DELTA'
              ? ' LONG / SHORT describes this perpetual contract’s price direction.'
              : ' BULL / BEAR describes this chart’s price direction.'}
      </p>
    </section>
  )
}
