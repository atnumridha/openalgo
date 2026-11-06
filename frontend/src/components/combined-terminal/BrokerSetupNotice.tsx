export function BrokerSetupNotice({ combinedDisabled = false }: { combinedDisabled?: boolean }) {
  return <section aria-label="Broker connections" className="space-y-3 rounded-lg border bg-card p-4">
    <h2 className="font-semibold">Broker connections</h2>
    <div className="grid grid-cols-2 gap-3 text-sm">
      <div className="rounded-md border p-3"><p className="font-semibold">Kotak Neo</p><p className="mt-1 text-muted-foreground">Sign in on this console</p></div>
      <div className="rounded-md border p-3"><p className="font-semibold">Flattrade</p><p className="mt-1 text-amber-700 dark:text-amber-400">{combinedDisabled ? 'Setup / activation required' : 'Separate broker connection'}</p></div>
    </div>
    {combinedDisabled && <p className="text-sm text-muted-foreground">The combined terminal is not enabled. Your existing Kotak screen remains available below.</p>}
    <details className="text-sm">
      <summary className="min-h-11 cursor-pointer content-center font-medium">How to connect Flattrade</summary>
      <div className="space-y-2 pt-2 text-muted-foreground">
        <p>Configure Flattrade’s client ID, API key and API secret in its own local broker worker, with its registered callback URL and static public IP.</p>
        <p>Complete the daily Flattrade login on that worker, then activate the combined terminal after both accounts pass read-only checks.</p>
        <p>Each broker keeps its own credentials and trades. This Kotak login does not connect a Flattrade account.</p>
      </div>
    </details>
  </section>
}
