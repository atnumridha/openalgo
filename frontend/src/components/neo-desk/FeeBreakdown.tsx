export function amount(value: string | null | undefined) {
  return value == null
    ? 'Unavailable'
    : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(Number(value))
}
export function FeeBreakdown({
  breakdown,
  source,
  assumption,
}: {
  breakdown: Record<string, string>
  source: string
  assumption?: string
}) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer">Estimated charge breakdown</summary>
      <dl className="grid grid-cols-2 gap-2 py-3">
        {Object.entries(breakdown).map(([key, value]) => (
          <div key={key}>
            <dt className="capitalize text-muted-foreground">{key}</dt>
            <dd>{amount(value)}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted-foreground">
        {source}. {assumption}. Actual fees require broker-reported charges.
      </p>
    </details>
  )
}
