import './RsiSpeedometer.css'

const point = (value: number, radius: number) => {
  const angle = ((135 + value * 2.7) * Math.PI) / 180
  return { x: 120 + radius * Math.cos(angle), y: 110 + radius * Math.sin(angle) }
}
const arc = (from: number, to: number) => {
  const a = point(from, 84),
    b = point(to, 84)
  return `M ${a.x} ${a.y} A 84 84 0 0 1 ${b.x} ${b.y}`
}

export function RsiSpeedometer({
  value,
  live,
  interval,
  note,
}: {
  value: number | null
  live: boolean
  interval: string
  note: string
}) {
  const available = value != null && Number.isFinite(value) && value >= 0 && value <= 100
  const number = available ? value.toFixed(2) : '—'
  const zone = !available
    ? 'Unavailable'
    : value < 30
      ? 'Oversold'
      : value > 70
        ? 'Overbought'
        : 'Mid-range'
  return (
    <figure
      className="rsi-speedometer min-w-0 rounded-lg border bg-background/50 p-3"
      aria-label={`RSI 14 · ${interval}`}
    >
      <figcaption className="flex items-center justify-between gap-2 text-sm font-medium">
        <span>RSI 14 · {interval}</span>
        <span className="text-xs text-muted-foreground">{live ? 'Live' : 'Last reading'}</span>
      </figcaption>
      <svg
        viewBox="0 0 240 205"
        role="img"
        aria-label={`RSI 14 speedometer: ${number}, ${zone}${live ? '' : ', not live'}`}
        className="mx-auto block w-full max-w-60"
      >
        <title>RSI 14 from 0 to 100, with thresholds at 30 and 70</title>
        {[
          [0, 30, 'low'],
          [30, 70, 'middle'],
          [70, 100, 'high'],
        ].map(([from, to, zone]) => (
          <path
            key={zone}
            d={arc(Number(from), Number(to))}
            fill="none"
            strokeWidth="11"
            className={`rsi-speedometer__${zone}`}
          />
        ))}
        {[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map((tick) => {
          const a = point(tick, 70),
            b = point(tick, tick % 10 === 0 && [0, 30, 50, 70, 100].includes(tick) ? 61 : 66),
            label = point(tick, 103)
          return (
            <g key={tick}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="currentColor" strokeWidth="1.5" />
              {[0, 30, 50, 70, 100].includes(tick) && (
                <text
                  x={label.x}
                  y={label.y}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize="12"
                  fill="currentColor"
                >
                  {tick}
                </text>
              )}
            </g>
          )
        })}
        {available && (
          <g
            transform={`rotate(${-135 + value * 2.7} 120 110)`}
            data-testid="rsi-needle"
            className={live ? 'rsi-speedometer__needle' : 'text-muted-foreground'}
          >
            <path d="M 117 120 L 120 46 L 123 120 Z" fill="currentColor" />
            <circle cx="120" cy="110" r="6" fill="currentColor" />
          </g>
        )}
        <text
          x="120"
          y="155"
          textAnchor="middle"
          fontSize="28"
          fontWeight="700"
          fill="currentColor"
          className="tabular-nums"
        >
          {number}
        </text>
        <text x="120" y="177" textAnchor="middle" fontSize="12" fill="currentColor">
          {zone}
        </text>
      </svg>
      <p className="text-center text-xs text-muted-foreground">
        30 · Oversold <span className="px-2">|</span> 70 · Overbought
      </p>
      <p className="mt-1 text-center text-xs text-muted-foreground">{note}</p>
    </figure>
  )
}
