import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { neoDeskApi } from '@/api/neoDesk'
import { useSocketContext } from '@/components/socket/SocketProvider'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { useThemeStore } from '@/stores/themeStore'

function message(error: unknown) {
  const e = error as { response?: { data?: { message?: string } }; message?: string }
  return (
    e.response?.data?.message ||
    e.message ||
    'Request did not complete. Refresh the connection and retry.'
  )
}
export function NeoStrategyControls({ compact = false }: { compact?: boolean } = {}) {
  return import.meta.env.VITE_NEO_DESK_ENABLED === 'true' ? (
    <EnabledNeoControls compact={compact} />
  ) : null
}
function EnabledNeoControls({ compact }: { compact: boolean }) {
  const client = useQueryClient()
  const { socket } = useSocketContext()
  useEffect(() => {
    if (!socket) return
    const subscribe = () => socket.emit('neo_desk_subscribe')
    const update = (data: Awaited<ReturnType<typeof neoDeskApi.state>>) =>
      client.setQueryData(['neo-desk'], data)
    subscribe()
    socket.on('connect', subscribe)
    socket.on('neo_desk_update', update)
    return () => {
      socket.off('connect', subscribe)
      socket.off('neo_desk_update', update)
      socket.emit('neo_desk_unsubscribe')
    }
  }, [socket, client])

  const toggleMode = useThemeStore((s) => s.toggleAppMode)
  const modeBusy = useThemeStore((s) => s.isTogglingMode)
  const busy = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const query = useQuery({
    queryKey: ['neo-desk'],
    queryFn: neoDeskApi.state,
    refetchInterval: 2000,
  })
  const change = useMutation({
    mutationFn: ({ action, profile }: { action?: string; profile?: string }) =>
      profile
        ? neoDeskApi.settings(profile)
        : neoDeskApi.command(action || 'stop', query.data?.mode === 'live' && action === 'start'),
    onSuccess: (data) => {
      client.setQueryData(['neo-desk'], data)
      setError(null)
    },
    onError: (e) => setError(message(e)),
    onSettled: () => {
      busy.current = false
    },
  })
  function command(action: string) {
    if (busy.current) return
    busy.current = true
    change.mutate({ action })
  }
  const d = query.data
  return (
    <Card aria-busy={query.isPending || change.isPending}>
      <CardHeader>
        <CardTitle>Strategy automation</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {error || query.error ? (
          <div
            role="alert"
            className="rounded border border-destructive p-3 text-sm text-destructive"
          >
            {error || message(query.error)}{' '}
            <Button variant="outline" onClick={() => query.refetch()}>
              Refresh status
            </Button>
          </div>
        ) : null}
        {d?.management && !d.management.ready ? (
          <p role="alert" className="text-destructive">
            {d.management.message}
          </p>
        ) : null}
        {d ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{d.mode === 'sandbox' ? 'Sandbox' : 'Live'}</Badge>
              <Badge variant={d.activation === 'Active' ? 'default' : 'secondary'}>
                {d.activation}
              </Badge>
              <span className="text-sm text-muted-foreground">
                Runner {d.runner.running ? 'running' : 'stopped'}
              </span>
            </div>
            <fieldset className="flex gap-1 rounded-md border p-1" aria-label="Execution mode">
              {(['sandbox', 'live'] as const).map((mode) => (
                <Button
                  key={mode}
                  size="sm"
                  className="flex-1"
                  variant={d.mode === mode ? 'secondary' : 'ghost'}
                  aria-pressed={d.mode === mode}
                  disabled={modeBusy || change.isPending}
                  onClick={async () => {
                    if (d.mode === mode) return
                    const result = await toggleMode()
                    if (!result.success)
                      setError(result.message || 'Execution mode did not change.')
                    await query.refetch()
                  }}
                >
                  {mode === 'sandbox' ? 'Sandbox' : 'Live'}
                </Button>
              ))}
            </fieldset>
            <div className={compact ? 'grid gap-3' : 'grid gap-4 md:grid-cols-2'}>
              <div className="space-y-2">
                <Label htmlFor="neo-preset">Active preset</Label>
                <select
                  id="neo-preset"
                  value={d.profile}
                  disabled={!d.can_edit || change.isPending}
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                  onChange={(e) => change.mutate({ profile: e.target.value })}
                >
                  {d.presets.map((p) => (
                    <option key={p.profile} value={p.profile}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  One preset at a time. Stop entries and wait until flat to switch.
                </p>
              </div>
              <details
                open={!compact}
                className={
                  compact ? 'space-y-1 text-xs text-muted-foreground' : 'space-y-1 text-sm'
                }
              >
                <summary className="cursor-pointer">Entry & exit rules</summary>
                <p>Confirmed 15-minute signals · CE or PE buys</p>
                <p>Entries 09:45–15:15 IST · square-off 15:29 IST</p>
                <p>6R index target · up to two verified lots near ₹50</p>
                <p>₹500 trade guard · ₹1,000 daily guard · 3 entries</p>
              </details>
            </div>
            <output className="block rounded-md bg-muted p-3 text-xs">{d.status}</output>
            <div className="flex flex-wrap gap-3 text-xs">
              <span>
                Entries today <strong>{d.entries_today} / 3</strong>
              </span>
              <span>
                Strategy net estimate <strong>₹{Number(d.day_net_estimate).toFixed(2)}</strong>
              </span>
              <span>
                Owned run <strong>{d.run_id ?? 'Flat'}</strong>
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={change.isPending || d.activation === 'Active'}
                variant={d.mode === 'live' ? 'destructive' : 'default'}
                onClick={() => command('start')}
              >
                Start {d.mode === 'sandbox' ? 'Sandbox' : 'Live'}
              </Button>
              <Button
                variant="outline"
                disabled={change.isPending || d.activation !== 'Active'}
                onClick={() => command('stop')}
              >
                Stop entries
              </Button>
              <Button variant="ghost" onClick={() => query.refetch()}>
                Refresh status
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {d.mode === 'live'
                ? 'Start Live authorizes new real option orders under the displayed controls. '
                : ''}
              Stopping entries keeps owned stops and scheduled exits managed. Trading allowance
              comes from the broker; chart choices do not change the 15-minute execution rules.
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Loading native strategy status…</p>
        )}
      </CardContent>
    </Card>
  )
}
