import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { neoResearchApi } from '@/api/neoResearch'
import { amount } from '@/components/neo-desk/FeeBreakdown'
import { ReplayChart } from '@/components/neo-desk/ReplayChart'
import { SavedCharts } from '@/components/neo-desk/SavedCharts'
import { TodayTradeReplays } from '@/components/neo-desk/TodayTradeReplays'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'

const profiles = [
  ['orb_trail', 'ORB · index trail'],
  ['orb_controls', 'ORB · option controls'],
  ['donchian_controls', 'Donchian · trend / option controls'],
  ['price_retest', 'Price Retest · research'],
]
export default function NeoBacktests() {
  const datasets = useQuery({ queryKey: ['neo-datasets'], queryFn: neoResearchApi.datasets }),
    [dataset, setDataset] = useState(''),
    [profile, setProfile] = useState('orb_trail'),
    [expiry, setExpiry] = useState(''),
    [start, setStart] = useState(''),
    [end, setEnd] = useState(''),
    [compound, setCompound] = useState(false),
    [jobId, setJobId] = useState(() => {
      try {
        return localStorage.getItem('neo.replay.savedJob.v1') || ''
      } catch {
        return ''
      }
    }),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [selectedIndex, setSelectedIndex] = useState(() => {
      try {
        return Math.max(0, Number(localStorage.getItem('neo.replay.selectedTrade.v1')) || 0)
      } catch {
        return 0
      }
    })
  const saved = useQuery({
    queryKey: ['neo-saved-research'],
    queryFn: neoResearchApi.saved,
    refetchInterval: 10000,
  })
  useEffect(() => {
    if (!jobId && saved.data?.length) {
      const recent = saved.data.find((r) => r.status === 'complete')
      if (recent) setJobId(recent.id)
    }
  }, [jobId, saved.data])
  useEffect(() => {
    try {
      localStorage.setItem('neo.replay.savedJob.v1', jobId)
      localStorage.setItem('neo.replay.selectedTrade.v1', String(selectedIndex))
    } catch {
      /* Keep this screen’s choice. */
    }
  }, [jobId, selectedIndex])
  const chosen = datasets.data?.find((d) => d.id === dataset)
  useEffect(() => {
    if (datasets.data?.length && !datasets.data.some((d) => d.id === dataset))
      setDataset(datasets.data[0].id)
  }, [dataset, datasets.data])
  useEffect(() => {
    if (chosen) {
      setStart(chosen.start)
      setEnd(chosen.end)
      setExpiry(chosen.expiries[0])
    }
  }, [chosen])
  const job = useQuery({
      queryKey: ['neo-job', jobId],
      queryFn: () => neoResearchApi.job(jobId),
      enabled: Boolean(jobId),
      refetchInterval: (q) =>
        ['queued', 'running'].includes(q.state.data?.status || '') ? 1000 : false,
    }),
    report = job.data?.result
  const selected = report?.trades[selectedIndex] ?? null
  async function run() {
    if (busy) return
    setBusy(true)
    setError('')
    setSelectedIndex(0)
    try {
      const result = await neoResearchApi.start({
        request_id: `neo-compare:${Date.now()}:${crypto.randomUUID()}`,
        dataset,
        profile,
        symbol: 'NIFTY',
        expiry,
        start,
        end,
        compound,
      })
      setJobId(result.id)
    } catch (e) {
      const x = e as { response?: { data?: { message?: string } }; message?: string }
      setError(x.response?.data?.message || x.message || 'Research request failed.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Neo strategy backtests</h1>
      <p className="text-sm text-muted-foreground">
        Select up to one year. Results use preserved real observations only; selecting dates cannot
        create unavailable expired-option data. Execution remains 15-minute confirmed NIFTY signals
        with 6R index targets.
      </p>
      <TodayTradeReplays />
      <Card>
        <CardHeader>
          <CardTitle>Saved preset backtests</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="saved-backtest">Backtested preset / date range</Label>
          <select
            id="saved-backtest"
            value={jobId}
            className="h-10 w-full rounded border bg-background px-3"
            onChange={(e) => {
              setJobId(e.target.value)
              setSelectedIndex(0)
            }}
          >
            <option value="">Choose a saved result</option>
            {(saved.data || []).map((r) => (
              <option key={r.id} value={r.id}>
                {profiles.find((p) => p[0] === r.request?.profile)?.[1] ||
                  r.request?.profile ||
                  'Preset'}{' '}
                · {r.request?.start} → {r.request?.end} · expiry {r.request?.expiry} · {r.status} ·{' '}
                {r.id.slice(0, 6)}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            Reopen preserved results and each trade’s chart without rerunning the backtest. Today’s
            actual fills are shown separately above.
          </p>
          {saved.error ? (
            <p role="alert" className="text-destructive">
              {saved.error.message}
            </p>
          ) : null}
        </CardContent>
      </Card>
      <SavedCharts />
      <Card>
        <CardHeader>
          <CardTitle>Research controls</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[
              [
                'research-dataset',
                'Actual dataset',
                dataset,
                setDataset,
                (datasets.data || []).map((d) => [d.id, d.id]),
              ],
              ['research-profile', 'Preset', profile, setProfile, profiles],
              [
                'research-expiry',
                'Expiry',
                expiry,
                setExpiry,
                (chosen?.expiries || []).map((e) => [e, e]),
              ],
            ].map(([id, label, value, set, options]) => (
              <div key={id as string}>
                <Label htmlFor={id as string}>{label as string}</Label>
                <select
                  id={id as string}
                  value={value as string}
                  onChange={(e) => (set as (v: string) => void)(e.target.value)}
                  className="h-10 w-full rounded border bg-background px-3"
                >
                  {(options as string[][]).map(([key, text]) => (
                    <option key={key} value={key}>
                      {text}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <div>
              <Label htmlFor="research-start">From</Label>
              <input
                id="research-start"
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="h-10 rounded border bg-background px-3"
              />
            </div>
            <div>
              <Label htmlFor="research-end">Through</Label>
              <input
                id="research-end"
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="h-10 rounded border bg-background px-3"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={!chosen}
              onClick={() => {
                if (!chosen) return
                const end = new Date(`${chosen.end}T12:00:00Z`)
                end.setUTCDate(end.getUTCDate() - 29)
                setStart(end.toISOString().slice(0, 10))
                setEnd(chosen.end)
              }}
            >
              Last 30 archive days
            </Button>
            <Button
              variant="outline"
              disabled={!chosen}
              onClick={() => {
                if (!chosen) return
                const end = new Date(`${chosen.end}T12:00:00Z`)
                end.setUTCFullYear(end.getUTCFullYear() - 1)
                end.setUTCDate(end.getUTCDate() + 1)
                setStart(end.toISOString().slice(0, 10))
                setEnd(chosen.end)
              }}
            >
              Last year ending at archive date
            </Button>
          </div>
          {chosen && (start < chosen.start || end > chosen.end) ? (
            <output className="block text-sm">
              The selected range extends beyond the archive. Only recorded dates can replay; this
              will be an incomplete result.
            </output>
          ) : null}
          <p>Initial research capital ₹10,000 · up to two whole lots per entry</p>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={compound}
              onChange={(e) => setCompound(e.target.checked)}
            />
            Reinvest profits within the two-lot maximum
          </label>
          {chosen ? (
            <div className="text-sm">
              <p>{chosen.source.name}</p>
              {chosen.storage === 'SQL' ? (
                <p>Replay source and its charts are preserved in SQL.</p>
              ) : null}
              <p>
                Observed calendar: {chosen.start} → {chosen.end}
              </p>
              {chosen.gaps.map((g) => (
                <p key={g} className="text-muted-foreground">
                  {g}
                </p>
              ))}
            </div>
          ) : (
            <p>No eligible real dataset available.</p>
          )}
          <Button
            disabled={busy || !chosen || ['queued', 'running'].includes(job.data?.status || '')}
            onClick={run}
          >
            Run backtest
          </Button>
          {job.data ? <output>Job {job.data.status}</output> : null}
          {error || datasets.error || job.error || job.data?.error ? (
            <p role="alert" className="text-destructive">
              {error ||
                (datasets.error as Error)?.message ||
                (job.error as Error)?.message ||
                job.data?.error}
            </p>
          ) : null}
        </CardContent>
      </Card>
      {report ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {profiles.find((p) => p[0] === report.profile)?.[1] || report.profile} ·{' '}
              {report.coverage.complete ? 'Covered replay' : 'Incomplete historical replay'}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm">
              Backtested preset: {report.profile} · {job.data?.request?.start} →{' '}
              {job.data?.request?.end} · expiry {job.data?.request?.expiry}
            </p>
            <div className="grid gap-4 sm:grid-cols-4">
              {[
                ['Observed closed-trade net estimate', report.known_realized_net],
                ['Complete-period net', report.net_complete],
                ['Estimated model charges', report.fees_estimate],
                ['Closed-trade drawdown', report.drawdown],
              ].map(([label, value]) => (
                <div key={label!}>
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <strong>{amount(value)}</strong>
                </div>
              ))}
            </div>
            <p className="text-sm">
              {report.wins} winners / {report.closed_count} resolved closes ·{' '}
              {report.unresolved_count} unresolved trades. Incomplete P&L cannot establish a winning
              strategy.
            </p>
            {report.coverage.gaps.length ? (
              <details>
                <summary>Data gaps ({report.coverage.gaps.length})</summary>
                <ul className="list-disc pl-5 text-xs">
                  {report.coverage.gaps.slice(0, 20).map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
                {report.coverage.gaps.length > 20 ? (
                  <p>Showing the first 20 gaps. Complete-period P&amp;L remains unavailable.</p>
                ) : null}
              </details>
            ) : null}
            <ul className="list-disc pl-5 text-xs text-muted-foreground">
              {report.assumptions.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    {[
                      'Instrument',
                      'Entry IST',
                      'Qty',
                      'Prices',
                      'Net estimate',
                      'Status',
                      'Chart',
                    ].map((h) => (
                      <th key={h} className="text-left p-2">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.trades.map((t, i) => (
                    <tr key={`${t.entry_time}-${i}`} className="border-t">
                      <td className="p-2">{t.symbol}</td>
                      <td>
                        {new Date(t.entry_time).toLocaleString('en-IN', {
                          timeZone: 'Asia/Kolkata',
                        })}
                      </td>
                      <td>{t.quantity}</td>
                      <td>
                        {t.entry_price} → {t.exit_price || 'Unresolved'}
                      </td>
                      <td>{amount(t.net)}</td>
                      <td>
                        {t.status}
                        <br />
                        {t.reason}
                      </td>
                      <td>
                        <Button
                          variant={selectedIndex === i ? 'default' : 'outline'}
                          onClick={() => setSelectedIndex(i)}
                        >
                          Replay trade
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {selected ? (
              <ReplayChart
                key={`${jobId}:${selectedIndex}`}
                trade={selected}
                source={`Backtested ${report.profile} · modelled fills · preserved observations`}
              />
            ) : (
              <p className="text-sm">
                This preset produced no trades for the saved request. No entry or exit markers are
                invented.
              </p>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
