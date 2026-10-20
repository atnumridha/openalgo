import { barCountdown } from './barCountdown'

export function ChartReadouts({
  rsi,
  hovered = false,
  barTime,
  interval,
  now,
  replay = false,
}: {
  rsi: number | null
  hovered?: boolean
  barTime: number | null
  interval: string
  now: number
  replay?: boolean
}) {
  const timer = barCountdown(barTime, interval, now)
  const rsiAvailable = rsi != null && Number.isFinite(rsi) && rsi >= 0 && rsi <= 100
  const closeTime =
    timer.closesAt == null
      ? ''
      : new Date(timer.closesAt * 1000).toLocaleTimeString('en-GB', {
          timeZone: 'Asia/Kolkata',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        })
  return (
    <div
      className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b bg-muted/20 px-2.5 py-1.5 text-xs"
      aria-live="off"
    >
      <div className="flex items-baseline gap-1.5">
        <span className="font-medium">RSI 14</span>
        <strong
          aria-label="RSI 14 value"
          className="text-base tabular-nums text-violet-700 dark:text-violet-300"
        >
          {rsiAvailable ? rsi.toFixed(2) : '—'}
        </strong>
        <span className="text-[10px] text-muted-foreground">
          {replay
            ? hovered
              ? 'Hovered replay bar'
              : 'Replay bar'
            : hovered
              ? 'Hovered bar'
              : timer.state === 'closed'
                ? 'Last bar'
                : 'Latest'}
        </span>
      </div>
      <div
        aria-label="Bar close countdown"
        title={
          closeTime
            ? `${replay ? 'Replay' : 'Latest'} ${interval} candle scheduled close: ${closeTime} IST. Independent of the hovered candle.`
            : 'Waiting for candle data'
        }
        className="flex items-baseline gap-1.5"
      >
        <span className="text-muted-foreground">
          {replay ? 'Closed at' : timer.state === 'forming' ? 'Closes in' : 'Bar'}
        </span>
        <strong className="text-sm tabular-nums">{replay ? closeTime || '—' : timer.text}</strong>
      </div>
    </div>
  )
}
