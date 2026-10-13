import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { neoDeskApi } from '@/api/neoDesk'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { amount } from './FeeBreakdown'
export function OwnedTradeControls() {
  return import.meta.env.VITE_NEO_DESK_ENABLED === 'true' ? <EnabledControls /> : null
}
function EnabledControls() {
  const client = useQueryClient(),
    q = useQuery({ queryKey: ['neo-desk'], queryFn: neoDeskApi.state, refetchInterval: 2000 }),
    d = q.data,
    p = d?.protection || {},
    leg = d?.owned?.legs[0],
    rid = d?.run_id
  const [sl, setSL] = useState(''),
    [target, setTarget] = useState(''),
    [activation, setActivation] = useState('1000'),
    [distance, setDistance] = useState('250'),
    [trail, setTrail] = useState(false),
    [confirm, setConfirm] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  // Populate only on trade identity changes so quotes never overwrite edits.
  // biome-ignore lint/correctness/useExhaustiveDependencies: protection is snapshotted when the exact run changes
  useEffect(() => {
    setSL(String(p.option_stop ?? ''))
    setTarget(String(p.option_target ?? ''))
    setActivation(String(p.cash_activation ?? 1000))
    setDistance(String(p.cash_distance ?? 250))
    setTrail(Boolean(p.cash_trail_enabled))
    setConfirm(false)
  }, [rid])
  const locked = busy || !rid || !leg?.qty || Boolean(leg.exit_order_id || leg.exit_claim_token)
  async function perform(close = false) {
    if (busy || !rid) return
    setBusy(true)
    setError('')
    try {
      if (close) {
        if (!confirm) return
        await neoDeskApi.close(rid)
      } else {
        const changes: Record<string, unknown> = {
          cash_trail_enabled: trail,
          cash_activation: activation,
          cash_distance: distance,
        }
        if (sl) changes.option_stop = sl
        if (target) changes.option_target = target
        await neoDeskApi.protection(rid, changes)
      }
      await client.invalidateQueries({ queryKey: ['neo-desk'] })
    } catch (e) {
      const x = e as { response?: { data?: { message?: string } }; message?: string }
      setError(x.response?.data?.message || x.message || 'Owned trade request failed.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Owned trade and protection</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {rid && leg ? (
          <>
            <p className="text-sm">
              {String(p.symbol || leg.symbol)} · {d.mode} · {String(leg.qty || 0)} confirmed units ·
              run {rid}
            </p>
            <div className="flex flex-wrap gap-6">
              <p>
                Gross running P&L <strong>{amount(p.gross_open as string)}</strong>
              </p>
              <p>
                Net running estimate <strong>{amount(p.net_open_estimate as string)}</strong>
              </p>
              <p>
                Locked net floor <strong>{amount(p.net_floor as string)}</strong>
              </p>
            </div>
            <p className="text-xs text-muted-foreground">
              Effective option SL {String(p.option_stop ?? 'Unset')} · target{' '}
              {String(p.option_target ?? 'Unset')}. Index target {String(p.target ?? 'Unavailable')}{' '}
              uses index points. A stop threshold does not guarantee the eventual fill price.
            </p>
            <div className="grid gap-3 md:grid-cols-4">
              {[
                ['owned-sl', 'Option SL ₹', sl, setSL],
                ['owned-target', 'Option target ₹', target, setTarget],
                ['owned-activation', 'Trail activation · net ₹', activation, setActivation],
                ['owned-distance', 'Trail distance · net ₹', distance, setDistance],
              ].map(([id, label, value, set]) => (
                <div key={id as string}>
                  <Label htmlFor={id as string}>{label as string}</Label>
                  <input
                    id={id as string}
                    type="number"
                    min="0"
                    step="0.05"
                    value={value as string}
                    disabled={locked}
                    onChange={(e) => (set as (v: string) => void)(e.target.value)}
                    className="w-full h-10 rounded border bg-background px-3"
                  />
                </div>
              ))}
            </div>
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={trail}
                disabled={locked}
                onChange={(e) => setTrail(e.target.checked)}
              />
              Enable cash-profit trailing SL
            </label>
            <Button disabled={locked} onClick={() => perform()}>
              Save protection
            </Button>
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={confirm}
                disabled={locked}
                onChange={(e) => setConfirm(e.target.checked)}
              />
              Confirm square-off of this owned trade
            </label>
            <Button
              variant="destructive"
              disabled={locked || !confirm}
              onClick={() => perform(true)}
            >
              Square off owned trade
            </Button>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            No current terminal-owned trade. Manual broker positions are shown in native Positions.
          </p>
        )}
        {error || q.error ? (
          <p role="alert" className="text-destructive">
            {error || (q.error as Error).message}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
