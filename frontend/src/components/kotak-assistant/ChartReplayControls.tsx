import { useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, RotateCcw, SkipBack, SkipForward } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useChartCandles } from './chartCandleStore'
import {
  freezeReplay,
  istSessionDate,
  sessionBounds,
  chartRangeBounds,
  type ChartDateRange,
  parseReplayInput,
  replayIndex,
  replayInput,
  replayStamp,
  type ReplayFrame,
  type ReplayCandle,
  type ReplaySnapshot,
} from './chartReplay'

/** Key this component by scope, so switching instruments also disposes its timer. */
export function ChartReplayControls({
  scope,
  keys,
  interval,
  onChange,
  sessionDate,
  onSessionDateChange,
  sessionEndDate = sessionDate,
  onSessionRangeChange,
  loading = false,
  unavailable = false,
  sources: suppliedSources,
}: {
  scope: string
  keys: string[]
  interval: string
  sessionDate?: string
  sessionEndDate?: string
  onSessionRangeChange?: (range: ChartDateRange) => void
  loading?: boolean
  unavailable?: boolean
  sources?: readonly (readonly ReplayCandle[])[]
  onSessionDateChange?: (date: string) => void
  onChange: (frame: ReplayFrame | null) => void
}) {
  const a = useChartCandles(keys[0] || '')
  const b = useChartCandles(keys[1] || '')
  const c = useChartCandles(keys[2] || '')
  const [snapshot, setSnapshot] = useState<ReplaySnapshot | null>(null)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [date, setDate] = useState('')
  const dateInput = useRef<HTMLInputElement>(null)
  const fromInput = useRef<HTMLInputElement>(null),
    toInput = useRef<HTMLInputElement>(null)
  const [from, setFrom] = useState(sessionDate ?? '')
  const [to, setTo] = useState(sessionEndDate ?? '')
  const dateLabel =
    sessionEndDate && sessionEndDate !== sessionDate
      ? `${sessionDate} → ${sessionEndDate}`
      : sessionDate
  const rangeEdited = !!onSessionRangeChange && (from !== sessionDate || to !== sessionEndDate)
  const [error, setError] = useState('')
  const until = snapshot?.timeline[index]
  const frame = useMemo(
    () => (snapshot && until != null ? { ...snapshot, scope, until } : null),
    [snapshot, scope, until]
  )
  useEffect(() => onChange(frame), [frame, onChange])
  useEffect(() => {
    if (until != null) setDate(replayInput(until))
  }, [until])
  const atEnd = !!snapshot && index >= snapshot.timeline.length - 1
  useEffect(() => {
    if (!playing || !snapshot || atEnd) return
    const timer = setTimeout(() => {
      setIndex((value) => Math.min(value + 1, snapshot.timeline.length - 1))
      if (index + 1 >= snapshot.timeline.length - 1) setPlaying(false)
    }, 1000 / speed)
    return () => clearTimeout(timer)
  }, [playing, snapshot, speed, atEnd, index])
  const start = () => {
    const sources = suppliedSources ?? [a, b, c]
    const next = freezeReplay(
      keys.map((key, i) => ({ key, bars: sources[i] ?? [] })),
      interval,
      Date.now() / 1000,
      sessionDate,
      sessionEndDate
    )
    if (!next) {
      setError(
        sessionDate
          ? `No replay available for ${dateLabel}. At least two completed candles are needed in this period.`
          : 'Load at least two shared completed candles in every visible chart, then try Replay.'
      )
      return
    }
    setError('')
    setIndex(sessionDate ? 0 : Math.floor((next.timeline.length - 1) / 4))
    setSnapshot(next)
    setPlaying(false)
  }
  const move = (value: number) => {
    setPlaying(false)
    setError('')
    setIndex(value)
  }
  const jump = () => {
    const requested = parseReplayInput(dateInput.current?.value ?? date)
    const next = requested == null || !snapshot ? -1 : replayIndex(snapshot.timeline, requested)
    if (!snapshot || next < 0 || requested! > snapshot.timeline.at(-1)!) {
      setError(
        sessionDate
          ? `Choose a time within ${dateLabel} and its loaded candles (IST).`
          : 'Choose a time within the loaded history.'
      )
      return
    }
    move(next)
  }
  const changeSession = (value: string) => {
    if (!sessionBounds(value) || value > istSessionDate()) {
      setError('Choose a valid date up to today in IST.')
      return
    }
    setPlaying(false)
    setSnapshot(null)
    setError('')
    onSessionDateChange?.(value)
  }
  const applyRange = (range: ChartDateRange) => {
    if (!sessionBounds(range.start) || !sessionBounds(range.end) || range.end > istSessionDate()) {
      setError('Choose valid dates up to today in IST.')
      return
    }
    if (!chartRangeBounds(range.start, range.end)) {
      setError('From date must be on or before To date.')
      return
    }
    setPlaying(false)
    setSnapshot(null)
    setError('')
    onSessionRangeChange?.(range)
  }
  return (
    <div className={`border-b px-3 py-2 ${snapshot ? 'bg-amber-500/10' : 'bg-muted/10'}`}>
      {sessionDate && onSessionRangeChange && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs">
            From · IST
            <input
              ref={fromInput}
              aria-label="From date IST"
              type="date"
              value={from}
              max={istSessionDate()}
              onChange={(e) => setFrom(e.target.value)}
              onInput={(e) => setFrom(e.currentTarget.value)}
              className="h-8 rounded border bg-background px-2"
            />
          </label>
          <label className="flex items-center gap-2 text-xs">
            To · IST
            <input
              ref={toInput}
              aria-label="To date IST"
              type="date"
              value={to}
              max={istSessionDate()}
              onChange={(e) => setTo(e.target.value)}
              onInput={(e) => setTo(e.currentTarget.value)}
              className="h-8 rounded border bg-background px-2"
            />
          </label>
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              applyRange({
                start: fromInput.current?.value ?? from,
                end: toInput.current?.value ?? to,
              })
            }
          >
            Apply dates
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const today = istSessionDate()
              setFrom(today)
              setTo(today)
              applyRange({ start: today, end: today })
            }}
          >
            Today
          </Button>
          <span className="text-xs text-muted-foreground">Both dates included</span>
        </div>
      )}
      {sessionDate && !onSessionRangeChange && onSessionDateChange && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs">
            Date · IST
            <input
              aria-label="Chart date IST"
              type="date"
              value={sessionDate}
              max={istSessionDate()}
              onChange={(e) => changeSession(e.target.value)}
              onInput={(e) => changeSession(e.currentTarget.value)}
              className="h-8 rounded border bg-background px-2"
            />
          </label>
          <Button size="sm" variant="outline" onClick={() => changeSession(istSessionDate())}>
            Today
          </Button>
          <span className="text-xs text-muted-foreground">Chart & Replay use this date</span>
        </div>
      )}
      {!snapshot ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            onClick={start}
            disabled={loading || unavailable || rangeEdited}
            aria-label="Replay charts"
          >
            <RotateCcw className="mr-1.5 size-4" aria-hidden="true" />
            Replay
          </Button>
          <span className="text-xs text-muted-foreground">
            {loading
              ? 'Loading selected dates…'
              : unavailable
                ? 'Range history unavailable · retry history below'
                : rangeEdited
                  ? 'Apply dates to update the chart'
                  : keys.length === 1
                    ? 'Review candles · choose a time, play or step forward'
                    : 'Review loaded candles · CE, index & PE stay in sync'}
          </span>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-1 text-xs text-amber-700 dark:text-amber-300">REPLAY</strong>
            <Button
              size="sm"
              variant="outline"
              aria-label="Previous replay candle"
              disabled={index === 0}
              onClick={() => move(index - 1)}
            >
              <SkipBack className="size-4" aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="secondary"
              aria-label={playing ? 'Pause replay' : 'Play replay'}
              disabled={atEnd}
              onClick={() => setPlaying(!playing)}
            >
              {playing ? (
                <Pause className="mr-1 size-4" aria-hidden="true" />
              ) : (
                <Play className="mr-1 size-4" aria-hidden="true" />
              )}
              {playing ? 'Pause' : 'Play'}
            </Button>
            <Button
              size="sm"
              variant="outline"
              aria-label="Next replay candle"
              disabled={atEnd}
              onClick={() => move(index + 1)}
            >
              <SkipForward className="size-4" aria-hidden="true" />
            </Button>
            <label className="flex items-center gap-1.5 text-xs">
              Speed
              <select
                aria-label="Replay speed"
                className="h-8 rounded border bg-background px-2"
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
              >
                {[0.5, 1, 2, 4, 10].map((v) => (
                  <option key={v} value={v}>
                    {v}×
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-xs">
              Time · IST
              <input
                ref={dateInput}
                aria-label="Replay start time IST"
                type="datetime-local"
                min={replayInput(snapshot.timeline[0])}
                max={replayInput(snapshot.timeline.at(-1)!)}
                value={date}
                onChange={(e) => setDate(e.target.value)}
                onInput={(e) => setDate(e.currentTarget.value)}
                className="h-8 rounded border bg-background px-2"
              />
            </label>
            <Button size="sm" variant="outline" onClick={jump}>
              Jump
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              onClick={() => {
                setPlaying(false)
                setSnapshot(null)
                setError('')
              }}
            >
              Return to live
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
            <input
              className="min-w-40 flex-1 accent-amber-600"
              aria-label="Replay candle"
              type="range"
              min={0}
              max={snapshot.timeline.length - 1}
              value={index}
              onChange={(e) => move(Number(e.target.value))}
            />
            <output className="tabular-nums" aria-label="Replay time">
              {replayStamp(until!)} · {index + 1}/{snapshot.timeline.length}
            </output>
            {atEnd && <span>End of loaded history</span>}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Charts replay history. Order tickets, current prices and trade monitoring remain live.
          </p>
        </>
      )}
      {error && (
        <output
          aria-label="Replay message"
          className="mt-2 block text-xs text-amber-700 dark:text-amber-300"
        >
          {error}
        </output>
      )}
    </div>
  )
}
