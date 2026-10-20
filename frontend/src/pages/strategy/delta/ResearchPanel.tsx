import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { num, when, type Research, type Models } from './types'
export default function ResearchPanel({ data, models }: { data?: Research; models?: Models }) {
  const c = data?.comparison,
    t = data?.training
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Local DeepSeek · training & evaluation</CardTitle>
          <CardDescription>BTCUSD, DOGEUSD and AKEUSD research · BTCUSD execution</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p>
            Ollama: {models?.local.online ? 'Available on this Mac' : 'Unavailable'} · Model
            artifact: {data?.model?.tag || 'No completed training report'}
          </p>
          {t && (
            <p>
              {t.iterations.toLocaleString()} training updates · {num(t.seconds / 60)} minutes ·{' '}
              {num(t.peak_gpu_bytes / 1e9)} GB peak MLX allocation
            </p>
          )}
          {c && (
            <>
              <Alert variant={c.eligible_for_paper ? 'default' : 'destructive'}>
                <AlertTitle>
                  {c.eligible_for_paper
                    ? 'Offline paper selection passed'
                    : 'Research model not activated'}
                </AlertTitle>
                <AlertDescription>
                  {c.eligible_for_paper
                    ? 'Passing offline selection does not prove profitability. The active run identifies the serving model.'
                    : c.failures.join(' · ').replaceAll('_', ' ')}
                </AlertDescription>
              </Alert>
              <Table>
                <TableHeader>
                  <TableRow>
                    {['Serving evaluation', 'Base DeepSeek', 'Trained DeepSeek'].map((h) => (
                      <TableHead key={h}>{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[
                    ['Cases', c.baseline.samples, c.trained.samples],
                    ['Valid responses', c.baseline.valid, c.trained.valid],
                    [
                      'Reference agreement',
                      num(c.baseline.accuracy * 100, '%'),
                      num(c.trained.accuracy * 100, '%'),
                    ],
                    [
                      'Median latency',
                      num(c.baseline.latency?.median, ' s'),
                      num(c.trained.latency?.median, ' s'),
                    ],
                    [
                      'p95 latency',
                      num(c.baseline.latency?.p95, ' s'),
                      num(c.trained.latency?.p95, ' s'),
                    ],
                    [
                      'Unnecessary exits',
                      c.baseline.unnecessary_exits,
                      c.trained.unnecessary_exits,
                    ],
                  ].map(([name, a, b]) => (
                    <TableRow key={name}>
                      <TableCell>{name}</TableCell>
                      <TableCell>{a}</TableCell>
                      <TableCell>{b}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="grid gap-4 md:grid-cols-2">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Symbol</TableHead>
                      <TableHead>Cases</TableHead>
                      <TableHead>Agreement</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.entries(c.by_symbol).map(([k, v]) => (
                      <TableRow key={k}>
                        <TableCell>{k}</TableCell>
                        <TableCell>{v.samples}</TableCell>
                        <TableCell>{num(v.trained_accuracy * 100, '%')}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Action</TableHead>
                      <TableHead>Cases</TableHead>
                      <TableHead>Recall</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.entries(c.action_recall).map(([k, v]) => (
                      <TableRow key={k}>
                        <TableCell>{k.replaceAll('_', ' ')}</TableCell>
                        <TableCell>{v.cases}</TableCell>
                        <TableCell>{num(v.recall * 100, '%')}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
          <p className="text-sm text-muted-foreground">
            {data?.note || 'Loading research evidence…'} Evaluation {when(data?.at)}. Latency
            measurements were taken under different resource loads.
          </p>
          <p className="text-sm text-muted-foreground">
            Training runs offline through the installed Python training workflow. All controllers
            must be stopped, flat and free of unresolved intents. This page reads completed reports
            and never starts training alongside a trading run.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
