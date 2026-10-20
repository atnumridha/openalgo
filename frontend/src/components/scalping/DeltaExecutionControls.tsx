interface Props {
  leverage?: number
  onLeverageChange: (value: number) => void
  netTarget?: boolean
}

export function DeltaExecutionControls({ leverage = 25, onLeverageChange, netTarget = false }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="delta-leverage" className="text-sm text-muted-foreground">
        Delta leverage
      </label>
      <select
        onKeyDown={(event) => {
          if (event.key.startsWith('Arrow')) event.stopPropagation()
        }}
        id="delta-leverage"
        value={leverage}
        onChange={(e) => onLeverageChange(Number(e.target.value))}
        className="h-9 rounded-md border border-input bg-background px-2 text-sm"
      >
        {Array.from({ length: 200 }, (_, i) => i + 1).map((value) => (
          <option key={value} value={value}>
            {value}×
          </option>
        ))}
      </select>
      <span className="text-xs text-muted-foreground">
        Applied and verified on the next live entry. Contract limits may be lower.
      </span>
      <p className="w-full text-xs text-muted-foreground">
        Maker entries and targets (post-only). SL and emergency exits use market orders. Unfilled
        limits remain pending. {netTarget ? 'ML targets include fees, GST and slippage.' : 'Manual 1:3 targets are before fees.'}
      </p>
    </div>
  )
}
