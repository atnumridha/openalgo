import { ArrowDown, ArrowUp, Minus } from 'lucide-react'
import type { Quote } from '@/api/kotakAssistant'
import './IndexMovement.css'

const positive = (value: number | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0
const number = (value: number, signed = false) =>
  value.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: signed && value !== 0 ? 'always' : 'auto',
  })

export function IndexMovement({
  index,
  quote,
  now,
}: {
  index: string
  quote?: Quote
  now: number
}) {
  const previous = [quote?.prev_close, quote?.close].find(positive)
  const points =
    positive(quote?.ltp) && previous != null ? Math.round((quote.ltp - previous) * 100) / 100 : null
  const percent = points != null && previous != null ? (points / previous) * 100 : null
  const age = now - (quote?.time ?? NaN)
  const fresh = Number.isFinite(age) && age >= 0 && age <= 5
  const direction = points == null ? null : points > 0 ? 'UP' : points < 0 ? 'DOWN' : 'FLAT'
  const Icon = direction === 'UP' ? ArrowUp : direction === 'DOWN' ? ArrowDown : Minus
  return (
    <div
      role="group"
      aria-label={`${index} day movement`}
      className="index-movement flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 text-sm tabular-nums"
    >
      <span
        data-direction={fresh ? direction : undefined}
        className="index-movement__direction inline-flex items-center gap-1 whitespace-nowrap rounded-md border bg-muted px-2 py-1 font-semibold text-muted-foreground"
      >
        <Icon className="size-4 shrink-0" strokeWidth={2.5} aria-hidden="true" />
        {index} {direction ? `${fresh ? '' : 'Last '}${direction}` : 'Change unavailable'}
      </span>
      {points != null && percent != null && (
        <strong>
          {number(points, true)} pts ({number(percent, true)}%)
        </strong>
      )}
      <span className="text-xs text-muted-foreground">
        {previous != null ? `vs previous close ${number(previous)}` : 'Waiting for previous close'}
        {points != null && !fresh ? ' · Last quote · stale' : ''}
      </span>
    </div>
  )
}
