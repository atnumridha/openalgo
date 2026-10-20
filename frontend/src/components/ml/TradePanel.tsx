import { useBrokerCurrencyFormatter, useBrokerPriceFormatter } from '@/hooks/useBrokerCurrencyFormatter'
import { Loader2, Lock } from 'lucide-react'
import { useState } from 'react'
import { type MlMode, type MlSuggestion, mlSignalsApi } from '@/api/mlSignals'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

export function usd(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return '-'
  const sign = value < 0 ? '-' : ''
  return `${sign}$${Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

export function price(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '-'
  const digits = value >= 1000 ? 1 : value >= 10 ? 2 : 4
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function pct(value: number | null | undefined, digits = 3) {
  return value == null || !Number.isFinite(value) ? '-' : `${value.toFixed(digits)}%`
}

function Row({
  label,
  value,
  className,
}: {
  label: string
  value: React.ReactNode
  className?: string
}) {
  return (
    <div className="flex justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn('font-mono text-right', className)}>{value}</span>
    </div>
  )
}

/** Why Live cannot be used for this suggestion, or null when it can. */
export function liveLockReason(suggestion: MlSuggestion | undefined): string | null {
  if (!suggestion) return 'No suggestion yet.'
  if (!suggestion.model_promoted) {
    return (
      suggestion.promotion_reason ||
      'The model has not beaten random entries after fees on unseen data yet.'
    )
  }
  return null
}

export function SuggestionCard({
  suggestion,
  mode,
  onTraded,
  nowSeconds,
}: {
  suggestion: MlSuggestion
  mode: MlMode
  onTraded: () => void
  nowSeconds: number
}) {
  const display = useBrokerCurrencyFormatter('deltaexchange')
  const usd = (value: number | null | undefined) => value == null ? '-' : display(value)
  const quote = useBrokerPriceFormatter('deltaexchange')
  const price = (v: number | null | undefined) => v == null ? '-' : quote(v)
  const [confirming, setConfirming] = useState(false)
  const [sending, setSending] = useState(false)
  const sizing = suggestion.sizing
  const side = suggestion.action
  const locked = mode === 'live' ? liveLockReason(suggestion) : null
  const canTrade = side !== 'WAIT' && suggestion.tradable && !locked
  const expiresIn = suggestion.expires_at != null ? suggestion.expires_at - nowSeconds : null

  const send = async () => {
    if (!sizing) return
    setSending(true)
    try {
      const result = await mlSignalsApi.trade({
        symbol: suggestion.symbol,
        interval: suggestion.interval,
        mode,
        action: side,
        contracts: sizing.contracts,
      })
      if (result.status === 'success') showToast.success(result.message)
      else showToast.error(result.message)
      onTraded()
    } catch {
      showToast.error('The trade could not be sent. Details are in the error log.')
    } finally {
      setSending(false)
      setConfirming(false)
    }
  }

  return (
    <Card data-testid={`suggestion-${suggestion.symbol}`}>
      <CardHeader className="pb-2">
        <CardDescription className="flex items-center justify-between">
          <span>
            {suggestion.symbol} · {suggestion.interval}
          </span>
          <span className="font-mono text-foreground">{price(suggestion.price)}</span>
        </CardDescription>
        <div className="flex items-baseline justify-between">
          <CardTitle
            className={cn(
              'text-2xl',
              side === 'LONG'
                ? 'text-green-600'
                : side === 'SHORT'
                  ? 'text-red-600'
                  : 'text-muted-foreground'
            )}
          >
            {side}
          </CardTitle>
          <Badge variant={suggestion.model_promoted ? 'default' : 'secondary'}>
            {suggestion.model_promoted ? 'Live allowed' : 'Sandbox only'}
          </Badge>
        </div>
        {suggestion.ev_pct != null && (
          <p className="text-xs text-muted-foreground">
            Expected {pct(suggestion.ev_pct)} after fees per trade · needs more than{' '}
            {pct(suggestion.min_edge_pct)}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-1">
        {side !== 'WAIT' && suggestion.entry_price != null && (
          <>
            <Row label="Entry (market)" value={price(suggestion.entry_price)} />
            <Row
              label={`Stop (${pct(suggestion.stop_pct, 2)})`}
              value={price(suggestion.stop_price)}
              className="text-red-600"
            />
            <Row
              label={`Target (${pct(suggestion.target_pct, 2)})`}
              value={price(suggestion.target_price)}
              className="text-green-600"
            />
          </>
        )}
        {sizing?.ok && (
          <>
            <Row label="Contracts" value={sizing.contracts} />
            <Row label="Margin" value={`${usd(sizing.margin)} at ${sizing.leverage}x`} />
            <Row
              label="Loss at stop, fees in"
              value={usd(-sizing.loss_at_stop)}
              className="text-red-600"
            />
            <Row
              label="Profit at target, fees in"
              value={usd(sizing.profit_at_target)}
              className="text-green-600"
            />
            <Row
              label="Fees"
              value={`${usd(sizing.entry_fee)} open · ${
                sizing.exit_fee_in_window === 0
                  ? 'close free in window'
                  : usd(sizing.exit_fee_in_window)
              }`}
            />
            {sizing.voucher_if_in_window > 0 && (
              <Row
                label="Diwali voucher if closed in 30m"
                value={usd(sizing.voucher_if_in_window)}
                className="text-emerald-600"
              />
            )}
            <Row
              label="Reward to risk after fees"
              value={
                sizing.reward_risk_after_fees != null
                  ? sizing.reward_risk_after_fees.toFixed(2)
                  : '-'
              }
            />
          </>
        )}
        {suggestion.message && <p className="pt-1 text-xs text-amber-600">{suggestion.message}</p>}
        {expiresIn != null && side !== 'WAIT' && (
          <p className="text-xs text-muted-foreground">
            {expiresIn > 0
              ? `Valid for ${Math.ceil(expiresIn / 60)} more min`
              : 'Expired; waiting for the next candle'}
          </p>
        )}
        <div className="pt-2">
          <Button
            className="w-full"
            disabled={!canTrade || sending || (expiresIn != null && expiresIn <= 0)}
            variant={side === 'SHORT' ? 'destructive' : 'default'}
            onClick={() => setConfirming(true)}
            data-testid={`trade-${suggestion.symbol}`}
          >
            {locked ? (
              <>
                <Lock className="mr-2 h-4 w-4" />
                Live locked
              </>
            ) : side === 'WAIT' ? (
              'No trade'
            ) : (
              `${side === 'LONG' ? 'Buy' : 'Sell'} ${sizing?.contracts ?? ''} in ${mode === 'live' ? 'Live' : 'Sandbox'}`
            )}
          </Button>
          {locked && <p className="pt-1 text-xs text-muted-foreground">{locked}</p>}
        </div>
      </CardContent>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {side} {sizing?.contracts} {suggestion.symbol} in{' '}
              {mode === 'live' ? 'Live' : 'Sandbox'}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {mode === 'live'
                ? 'A real market order is sent to Delta Exchange now, with a protective stop held on Delta.'
                : 'A Sandbox order is placed now. No real money is used.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {sizing && (
            <div className="space-y-1 rounded border p-3">
              <Row label="Entry (market, about)" value={price(suggestion.entry_price)} />
              <Row label="Stop" value={price(suggestion.stop_price)} />
              <Row label="Target" value={price(suggestion.target_price)} />
              <Row label="Notional" value={usd(sizing.notional)} />
              <Row label="Margin" value={usd(sizing.margin)} />
              <Row label="Loss at stop, fees in" value={usd(-sizing.loss_at_stop)} />
              <Row label="Profit at target, fees in" value={usd(sizing.profit_at_target)} />
              <Row
                label="Balance used for sizing"
                value={`${usd(suggestion.balance)} (${suggestion.balance_source})`}
              />
              <p className="pt-2 text-xs text-muted-foreground">
                After it opens, the stop, target and break-even trail are managed for you, and the
                smart exit closes it early if the model turns or holding stops being worth the fee.
              </p>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={sending}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void send()} disabled={sending}>
              {sending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Start trade
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

export function ModeSelect({ mode, onChange }: { mode: MlMode; onChange: (mode: MlMode) => void }) {
  return (
    <Select value={mode} onValueChange={(value) => onChange(value as MlMode)}>
      <SelectTrigger className="w-32" aria-label="Trading mode">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="sandbox">Sandbox</SelectItem>
        <SelectItem value="live">Live</SelectItem>
      </SelectContent>
    </Select>
  )
}
