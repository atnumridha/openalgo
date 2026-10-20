import { Loader2, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { type MlSettings, mlSignalsApi } from '@/api/mlSignals'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { showToast } from '@/utils/toast'

type NumberKey = {
  [K in keyof MlSettings]: MlSettings[K] extends number ? K : never
}[keyof MlSettings]
type BoolKey = {
  [K in keyof MlSettings]: MlSettings[K] extends boolean ? K : never
}[keyof MlSettings]

const NUMBER_FIELDS: { key: NumberKey; label: string; hint?: string }[] = [
  { key: 'risk_pct', label: 'Risk per trade %', hint: 'Lost at the stop, fees included' },
  { key: 'max_leverage', label: 'Max leverage' },
  { key: 'sandbox_balance_usd', label: 'Sandbox balance (USD)', hint: 'Sizes Sandbox trades' },
  { key: 'max_hold_minutes', label: 'Max hold (minutes)' },
  {
    key: 'smart_exit_confirmations',
    label: 'Smart exit confirmations',
    hint: 'Closed bars in a row',
  },
  { key: 'breakeven_buffer_pct', label: 'Break-even buffer %', hint: 'Above round-trip fees' },
  { key: 'retrain_hour_ist', label: 'Retrain hour (IST)' },
  { key: 'retrain_minute_ist', label: 'Retrain minute' },
  { key: 'fee_gst_pct', label: 'GST on fees %' },
  {
    key: 'fee_voucher_earned_month',
    label: 'Vouchers earned this month ($)',
    hint: 'Counts toward the $100 cap',
  },
]

const BOOL_FIELDS: { key: BoolKey; label: string; hint: string }[] = [
  { key: 'smart_exit_enabled', label: 'Smart exit', hint: 'Close early when the model turns' },
  {
    key: 'retrain_enabled',
    label: 'Nightly save and retrain',
    hint: 'Newest model is used at once',
  },
  {
    key: 'fee_scalper_offer',
    label: 'Scalper Offer joined',
    hint: 'Free close within 30 min (BTC, ETH) or 15 min',
  },
  {
    key: 'fee_diwali_offer',
    label: 'Diwali Scalper Offer',
    hint: 'BTCUSD opening fee back as a Fee Voucher',
  },
]

export function MlSettingsCard({ onSaved }: { onSaved?: () => void }) {
  const [settings, setSettings] = useState<MlSettings | null>(null)
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    mlSignalsApi
      .settings()
      .then(setSettings)
      .catch(() => setSettings(null))
  }, [])

  if (!settings) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Trading settings</CardTitle>
          <CardDescription>Loading.</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  const value = (key: keyof MlSettings) =>
    key in draft ? draft[key as string] : (settings[key] as string | number | boolean)

  const save = async () => {
    setSaving(true)
    const changes: Record<string, unknown> = {}
    for (const [key, raw] of Object.entries(draft)) {
      changes[key] =
        key === 'symbols'
          ? String(raw)
              .split(',')
              .map((s) => s.trim())
          : raw
    }
    try {
      const result = await mlSignalsApi.saveSettings(changes as Partial<MlSettings>)
      setSettings(result.data)
      setDraft({})
      if (result.status === 'success') showToast.success('Settings saved')
      else showToast.error(result.message || 'Some settings were not saved')
      onSaved?.()
    } catch {
      showToast.error('Settings could not be saved')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trading settings</CardTitle>
        <CardDescription>
          {settings.last_retrain_status
            ? `Last retrain: ${settings.last_retrain_status}`
            : 'No retrain has finished yet.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <Label htmlFor="ml-symbols">Symbols</Label>
          <Input
            id="ml-symbols"
            value={String(value('symbols') ?? '')}
            onChange={(e) => setDraft({ ...draft, symbols: e.target.value })}
          />
          <p className="pt-1 text-xs text-muted-foreground">
            Delta perpetuals, comma separated. A new one downloads a year of history and trains.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {NUMBER_FIELDS.map((field) => (
            <div key={field.key}>
              <Label htmlFor={`ml-${field.key}`}>{field.label}</Label>
              <Input
                id={`ml-${field.key}`}
                inputMode="decimal"
                value={String(value(field.key) ?? '')}
                onChange={(e) => setDraft({ ...draft, [field.key]: e.target.value })}
              />
              {field.hint && <p className="pt-1 text-xs text-muted-foreground">{field.hint}</p>}
            </div>
          ))}
        </div>
        <div className="space-y-3">
          {BOOL_FIELDS.map((field) => (
            <div key={field.key} className="flex items-center justify-between gap-3">
              <div>
                <Label htmlFor={`ml-${field.key}`}>{field.label}</Label>
                <p className="text-xs text-muted-foreground">{field.hint}</p>
              </div>
              <Switch
                id={`ml-${field.key}`}
                checked={Boolean(value(field.key))}
                onCheckedChange={(checked) => setDraft({ ...draft, [field.key]: checked })}
              />
            </div>
          ))}
        </div>
        <Button onClick={() => void save()} disabled={saving || Object.keys(draft).length === 0}>
          {saving ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save settings
        </Button>
      </CardContent>
    </Card>
  )
}
