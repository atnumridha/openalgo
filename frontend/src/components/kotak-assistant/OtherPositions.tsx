import { useRef, useState } from 'react'
import { kotakAssistantApi, type Snapshot } from '@/api/kotakAssistant'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { errorMessage, money } from './model'

export function OtherPositions({ desk, refresh }: { desk: Snapshot; refresh: () => void }) {
  const [stops, setStops] = useState<Record<string, string>>({}),
    [targets, setTargets] = useState<Record<string, string>>({}),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState('')
  const lock = useRef(false)
  const positions = (desk.positions || []).filter(
    (p) =>
      p.quantity > 0 &&
      !desk.trades.some(
        (t) =>
          t.symbol === p.symbol &&
          t.product === p.product &&
          !['closed', 'rejected'].includes(t.status)
      )
  )
  if (!positions.length) return null
  const act = async (p: (typeof positions)[number], close: boolean) => {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    const orders = (desk.orders || []).filter(
      (o) =>
        o.symbol === p.symbol &&
        o.exchange === p.exchange &&
        o.product === p.product &&
        !['complete', 'completed', 'cancelled', 'canceled', 'rejected'].includes(
          o.order_status.toLowerCase()
        )
    )
    try {
      await kotakAssistantApi.adopt(desk.mode, {
        symbol: p.symbol,
        exchange: p.exchange,
        product: p.product,
        quantity: p.quantity,
        ...(!close ? { sl: Number(stops[p.symbol]), target: Number(targets[p.symbol]) } : {}),
        order_ids: orders.map((o) => o.orderid),
        request_id: crypto.randomUUID(),
        close,
      })
      setMessage(
        close ? 'Exit recorded; monitoring fills' : 'Position adopted; monitoring protection'
      )
      refresh()
    } catch (e) {
      setMessage(errorMessage(e))
      refresh()
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  return (
    <Card>
      <CardContent className="pt-5 space-y-3">
        <h3 className="font-semibold">Other broker positions</h3>
        <p className="text-xs text-muted-foreground">
          Take control with an SL and target, or exit directly. Exit cancels the displayed pending
          orders before selling the confirmed remaining quantity. Managed positions square off by{' '}
          {desk.settings.cutoff} IST.
        </p>
        {positions.map((p) => {
          const orders = (desk.orders || []).filter(
            (o) =>
              o.symbol === p.symbol &&
              o.exchange === p.exchange &&
              o.product === p.product &&
              !['complete', 'completed', 'cancelled', 'canceled', 'rejected'].includes(
                o.order_status.toLowerCase()
              )
          )
          return (
            <div key={`${p.symbol}:${p.product}`} className="rounded border p-3 space-y-2">
              <strong>{p.symbol}</strong>
              <p className="text-sm">
                {p.quantity} units · Average {money(p.average_price)} ·{' '}
                {desk.mode === 'live' ? 'LIVE' : 'PAPER'}
              </p>
              <p className="text-xs">
                Pending order IDs: {orders.map((o) => o.orderid).join(', ') || 'None'}
              </p>
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs">
                  SL
                  <Input
                    className="w-28"
                    type="number"
                    value={stops[p.symbol] || ''}
                    onChange={(e) => setStops({ ...stops, [p.symbol]: e.target.value })}
                  />
                </label>
                <label className="text-xs">
                  Target
                  <Input
                    className="w-28"
                    type="number"
                    value={targets[p.symbol] || ''}
                    onChange={(e) => setTargets({ ...targets, [p.symbol]: e.target.value })}
                  />
                </label>
                <Button
                  variant="outline"
                  disabled={busy || !stops[p.symbol] || !targets[p.symbol]}
                  onClick={() => act(p, false)}
                >
                  Manage position
                </Button>
                <Button variant="destructive" disabled={busy} onClick={() => act(p, true)}>
                  Exit full
                </Button>
              </div>
            </div>
          )
        })}
        <p role="status">{message}</p>
      </CardContent>
    </Card>
  )
}
