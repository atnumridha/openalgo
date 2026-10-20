type Gap = { direction: 'bullish' | 'bearish'; lower: number; upper: number; touched: boolean }
export function FairValueGapLegend({ gaps }: { gaps: Gap[] }) {
  return (
    <details className="relative ml-auto shrink-0 text-xs">
      <summary
        className="cursor-pointer whitespace-nowrap rounded border bg-background px-2 py-1 tabular-nums focus-visible:outline focus-visible:outline-ring"
        title="Nearby unfilled Fair Value Gaps · click for price ranges"
      >
        FVG ↑{gaps.filter((g) => g.direction === 'bullish').length} ↓
        {gaps.filter((g) => g.direction === 'bearish').length}
      </summary>
      <div className="absolute right-0 top-full z-30 mt-1 w-64 max-w-[80vw] rounded-md border bg-popover p-3 text-popover-foreground shadow-md">
        <strong className="block text-xs">Nearby Fair Value Gaps</strong>
        <p className="mb-2 mt-1 text-[11px] text-muted-foreground">
          Up to 3 nearest zones · filled zones disappear
        </p>
        {gaps.length ? (
          gaps.map((gap) => (
            <div
              key={`${gap.direction}:${gap.lower}:${gap.upper}`}
              className="flex items-center justify-between gap-2 border-t py-2 tabular-nums"
            >
              <span
                className={
                  gap.direction === 'bullish'
                    ? 'text-emerald-700 dark:text-emerald-300'
                    : 'text-rose-700 dark:text-rose-300'
                }
              >
                {gap.direction === 'bullish' ? '↑ Bullish' : '↓ Bearish'}
              </span>
              <span>
                {gap.lower.toFixed(2)}–{gap.upper.toFixed(2)}
                <small className="block text-right text-muted-foreground">
                  {gap.touched ? 'Partly filled' : 'Unfilled'}
                </small>
              </span>
            </div>
          ))
        ) : (
          <p className="text-muted-foreground">No active gaps in the displayed candles.</p>
        )}
      </div>
    </details>
  )
}
