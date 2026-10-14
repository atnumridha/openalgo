import { useQuery } from '@tanstack/react-query'
import { neoReportsApi } from '@/api/neoReports'
import { Button } from '@/components/ui/button'
import { ReplayChart } from './ReplayChart'

export function RecordedTradeReplay({ tradeId, mode }: { tradeId: string; mode: string }) {
  const q = useQuery({
    queryKey: ['neo-recorded-replay', mode, tradeId],
    queryFn: () => neoReportsApi.replay(tradeId, mode),
    staleTime: 60000,
    retry: false,
  })
  if (q.error)
    return (
      <div role="alert" className="text-destructive">
        {(q.error as { response?: { data?: { message?: string } } }).response?.data?.message ||
          q.error.message}
        <Button variant="outline" onClick={() => q.refetch()}>
          Retry trade replay
        </Button>
      </div>
    )
  if (!q.data) return <output>Loading this trade’s saved chart…</output>
  return (
    <ReplayChart
      key={`${mode}:${tradeId}`}
      trade={q.data.trade}
      source={q.data.source}
      notes={q.data.coverage.gaps}
    />
  )
}
