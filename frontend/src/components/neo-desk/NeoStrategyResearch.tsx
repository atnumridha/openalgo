import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { neoResearchApi } from '@/api/neoResearch'
import { Button } from '@/components/ui/button'

const labels: Record<string, string> = {
  orb_trail: 'ORB · index trail',
  orb_controls: 'ORB · option controls',
  donchian_controls: 'Donchian · trend',
  price_retest: 'Break & Retest',
}
export function NeoStrategyResearch() {
  const [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(''),
    [error, setError] = useState('')
  const datasets = useQuery({ queryKey: ['neo-datasets'], queryFn: neoResearchApi.datasets })
  const recent = useQuery({
    queryKey: ['neo-research-latest'],
    queryFn: neoResearchApi.latest,
    refetchInterval: busy ? 1000 : 10000,
  })
  async function runAll() {
    const dataset = datasets.data?.[0]
    if (!dataset || busy) return
    setBusy(true)
    setError('')
    try {
      const end = new Date(`${dataset.end}T12:00:00Z`),
        start = new Date(end)
      start.setUTCDate(start.getUTCDate() - 29)
      for (const [profile, label] of Object.entries(labels)) {
        setProgress(`Backtesting ${label}…`)
        let job = await neoResearchApi.start({
          request_id: `neo-compare:${Date.now()}:${crypto.randomUUID()}`,
          dataset: dataset.id,
          profile,
          symbol: 'NIFTY',
          expiry: dataset.expiries[0],
          start: start.toISOString().slice(0, 10),
          end: dataset.end,
          compound: true,
        })
        while (['queued', 'running'].includes(job.status)) {
          await new Promise((resolve) => setTimeout(resolve, 1000))
          job = await neoResearchApi.job(job.id)
        }
        if (job.status !== 'complete') throw Error(job.error || 'Backtest did not complete.')
        await recent.refetch()
      }
      setProgress('All four backtests completed.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="rounded-md border bg-card p-3" aria-label="Strategy backtest results">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Backtest results</h2>
        <Link to="/neo-backtests" className="text-xs text-primary underline">
          Details
        </Link>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        ₹10,000 start · 6R · up to 2 lots · reinvestment
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="pb-2 font-normal">Preset</th>
              <th className="pb-2 text-right font-normal">Closed net</th>
              <th className="pb-2 text-right font-normal">Wins</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(labels).map(([profile, label]) => {
              const job = recent.data?.find((j) => j.result?.profile === profile),
                r = job?.result
              return (
                <tr key={profile} className="border-b last:border-0">
                  <td className="py-2">
                    {label}
                    {r && !r.coverage.complete ? (
                      <span className="block text-[10px] text-muted-foreground">
                        Incomplete coverage
                      </span>
                    ) : null}
                    {r?.unresolved_count ? (
                      <span className="block text-[10px] text-amber-500">
                        {r.unresolved_count} unresolved entry
                      </span>
                    ) : null}
                  </td>
                  <td className="text-right tabular-nums">
                    {r
                      ? r.closed_count
                        ? `₹${Number(r.known_realized_net).toFixed(2)}`
                        : r.unresolved_count
                          ? 'Unresolved'
                          : 'No closes'
                      : 'Not run'}
                  </td>
                  <td className="text-right tabular-nums">
                    {r ? `${r.wins}/${r.closed_count}` : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {datasets.data?.[0] ? (
        <p className="mt-2 text-[10px] text-muted-foreground">
          Archive: {datasets.data[0].start} to {datasets.data[0].end}. Missing option observations
          prevent a complete month/year result.
        </p>
      ) : null}
      <Button
        variant="outline"
        size="sm"
        className="mt-3 w-full"
        disabled={busy || !datasets.data?.length}
        onClick={() => void runAll()}
      >
        {busy ? 'Backtesting…' : 'Backtest all 4 · last 30 archive days'}
      </Button>
      {progress ? (
        <output className="mt-2 block text-xs text-muted-foreground">{progress}</output>
      ) : null}
      {error || recent.error || datasets.error ? (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {error || (recent.error as Error)?.message || (datasets.error as Error)?.message}
        </p>
      ) : null}
    </section>
  )
}
