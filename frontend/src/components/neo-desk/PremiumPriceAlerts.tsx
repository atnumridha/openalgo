import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { readySound, playAlertSound } from '@/lib/trading/alertDelivery'
import { PremiumAlertMonitor, type PremiumPriceAlert, type PremiumQuote } from './premiumAlerts'
import { ChartToolPanel } from './ChartToolDock'
type Source = 'support' | 'resistance' | 'entry' | 'custom'
const premiumSound = { volume: 0.7, repeats: 3 }
const names: Record<Source, string> = {
  support: 'Support',
  resistance: 'Resistance',
  entry: 'Entry',
  custom: 'Custom level',
}
export function PremiumPriceAlerts({
  scope,
  symbol,
  quote,
  live,
  levels,
  docked = false,
}: {
  scope: string
  symbol: string
  quote: PremiumQuote | null
  live: boolean
  levels: { support: number | null; resistance: number | null; entry: number | null }
  docked?: boolean
}) {
  const key = `chart.premium-alerts.v1:${scope}`
  const [alerts, setAlerts] = useState<PremiumPriceAlert[]>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(key) || '[]')
      return Array.isArray(v)
        ? v
            .filter(
              (a) =>
                a &&
                typeof a.id === 'string' &&
                typeof a.label === 'string' &&
                a.label.length < 50 &&
                Number.isFinite(a.price) &&
                a.price > 0 &&
                typeof a.enabled === 'boolean' &&
                typeof a.fired === 'boolean'
            )
            .slice(0, 20)
        : []
    } catch {
      return []
    }
  })
  const [source, setSource] = useState<Source>('support'),
    [price, setPrice] = useState(levels.support?.toFixed(2) ?? '')
  const [soundOn, setSoundOn] = useState(false),
    [message, setMessage] = useState('')
  const monitor = useRef(new PremiumAlertMonitor())
  const manualPrice = useRef(false)
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(alerts))
    } catch {
      /* Alerts remain active for this view. */
    }
  }, [key, alerts])
  useEffect(() => {
    if (source !== 'custom' && !price && !manualPrice.current && levels[source] != null)
      setPrice(levels[source]!.toFixed(2))
  }, [source, price, levels.support, levels.resistance, levels.entry])
  useEffect(() => {
    const hits = monitor.current.update(alerts, quote, Date.now(), live && soundOn)
    if (!hits.length) return
    const fired = alerts.filter((a) => hits.includes(a.id))
    const heard = playAlertSound(premiumSound)
    setMessage(
      `${fired.map((a) => `${a.label} ₹${a.price.toFixed(2)}`).join(', ')} reached on ${symbol}.${heard ? '' : ' Sound unavailable; use Test sound.'}`
    )
    setAlerts((old) => old.map((a) => (hits.includes(a.id) ? { ...a, fired: true } : a)))
  }, [alerts, quote?.price, quote?.time, live, soundOn, symbol])
  const armed = alerts.filter((a) => a.enabled).length
  return (
    <ChartToolPanel
      floating={docked}
      label="Price alerts"
      title={
        <>
          Price alerts{armed ? ` · ${armed} armed` : ''}
          {soundOn ? ' · sound on' : ''}
        </>
      }
    >
      <div className="space-y-3 p-3 text-xs">
        <p>
          {symbol} premium · live quotes only · sounds on every new touch or crossing. Price must
          move away before another touch. Saved prices stay fixed.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="space-y-1">
            <span className="block text-muted-foreground">Level</span>
            <select
              aria-label="Alert level source"
              value={source}
              onChange={(e) => {
                manualPrice.current = false
                const s = e.target.value as Source
                setSource(s)
                setPrice(s === 'custom' ? '' : (levels[s]?.toFixed(2) ?? ''))
              }}
              className="h-8 rounded-md border bg-background px-2 focus-visible:outline focus-visible:outline-ring"
            >
              {Object.entries(names).map(([v, n]) => (
                <option key={v} value={v}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-muted-foreground">Price ₹</span>
            <Input
              aria-label="Alert premium price"
              type="number"
              min="0.05"
              step="0.05"
              value={price}
              onChange={(e) => {
                manualPrice.current = true
                setPrice(e.target.value)
              }}
              className="h-8 w-28 bg-background px-2 text-xs tabular-nums md:text-xs"
            />
          </label>
          <Button
            type="button"
            size="sm"
            className="text-xs"
            disabled={!Number.isFinite(Number(price)) || Number(price) <= 0 || alerts.length >= 20}
            onClick={() => {
              setAlerts((old) => [
                ...old,
                {
                  id: crypto.randomUUID(),
                  label: names[source],
                  price: Number(price),
                  enabled: true,
                  fired: false,
                },
              ])
              setMessage(
                soundOn ? 'Alert added and armed.' : 'Alert added. Enable sound alerts to listen.'
              )
            }}
          >
            Add alert
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="text-xs"
            onClick={() => {
              if (!soundOn) readySound()
              setSoundOn((v) => !v)
            }}
          >
            {soundOn ? 'Mute alerts' : 'Enable sound alerts'}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-xs"
            onClick={() => {
              readySound()
              setMessage(
                playAlertSound(premiumSound)
                  ? 'Test sound played.'
                  : 'Sound unavailable in this browser.'
              )
            }}
          >
            Test sound
          </Button>
        </div>
        {!live ? (
          <p className="text-amber-600 dark:text-amber-400">
            Alerts paused: use today's live option chart with a connected quote feed.
          </p>
        ) : null}
        {source !== 'custom' && levels[source] == null ? (
          <p>
            No chart {names[source].toLowerCase()} is available; enter the premium price manually.
          </p>
        ) : null}
        {!soundOn && alerts.length ? (
          <p>Sound is muted. Click Enable sound alerts after opening this page.</p>
        ) : null}
        <ul className="space-y-1">
          {alerts.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 rounded border px-2 py-1">
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  aria-label={`Enable ${a.label} alert`}
                  checked={a.enabled}
                  onChange={(e) => {
                    monitor.current.reset(a.id)
                    setAlerts((old) =>
                      old.map((r) => (r.id === a.id ? { ...r, enabled: e.target.checked } : r))
                    )
                  }}
                />
                {a.label} ₹{a.price.toFixed(2)}
              </label>
              <span>
                {a.enabled
                  ? a.fired
                    ? 'Armed · repeats · reached before'
                    : 'Armed · repeats'
                  : 'Disabled'}
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="text-xs"
                aria-label={`Reset ${a.label} alert`}
                onClick={() => {
                  monitor.current.reset(a.id)
                  setAlerts((old) =>
                    old.map((r) => (r.id === a.id ? { ...r, fired: false, enabled: true } : r))
                  )
                }}
              >
                Reset
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="text-xs"
                aria-label={`Delete ${a.label} alert`}
                onClick={() => {
                  monitor.current.reset(a.id)
                  setAlerts((old) => old.filter((r) => r.id !== a.id))
                }}
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
        <output role="status" className="block font-medium" aria-live="polite">
          {message}
        </output>
        <p className="text-muted-foreground">
          Keep this page open. Alerts use observed price crossings; a jump across a level also
          counts. Browser sleep or disconnection can miss prices.
        </p>
      </div>
    </ChartToolPanel>
  )
}
