/**
 * SetSLDialog — configure a leg's stop-loss and optional auto-trailing.
 * Configure a leg's stop-loss: initial stop-loss + trailing step + enable toggle + target.
 */
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { SLState } from '@/hooks/useTrailingSL'
import { initialTarget } from '@/lib/scalpingRisk'
import { priceDecimals } from '@/lib/scalpingPrice'
import type { ScalpingAction, ScalpingProduct, SelectedLeg } from '@/types/scalping'

interface SetSLDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  leg: SelectedLeg | null
  product: ScalpingProduct
  side: ScalpingAction
  entryPrice: number
  quantity: number
  ltp?: number
  existing?: SLState
  suggestedDistance?: number | null
  onSave: (sl: SLState) => void | boolean | Promise<boolean>
  onClear?: () => void | boolean | Promise<boolean>
}

export function SetSLDialog({
  open,
  onOpenChange,
  leg,
  product,
  side,
  entryPrice,
  quantity,
  ltp,
  existing,
  suggestedDistance,
  onSave,
  onClear,
}: SetSLDialogProps) {
  const [stoploss, setStoploss] = useState('')
  const [trailingEnabled, setTrailingEnabled] = useState(false)
  const [trailingStep, setTrailingStep] = useState('')
  const [targetPrice, setTargetPrice] = useState('')
  const [autoTarget, setAutoTarget] = useState(true)
  const [pending, setPending] = useState(false)
  const [saveError, setSaveError] = useState('')
  const seededRef = useRef<string | null>(null)

  // Seed fields when the dialog opens.
  useEffect(() => {
    if (!open) { seededRef.current = null; return }
    const key = `${leg?.exchange}:${leg?.symbol}:${product}:${side}:${entryPrice}`
    if (seededRef.current === key) return
    seededRef.current = key
    setSaveError('')
    setAutoTarget(!(existing?.target && existing.target > 0))
    if (existing) {
      setStoploss(String(existing.currentSl))
      setTrailingEnabled(existing.trailingEnabled)
      setTrailingStep(existing.trailingStep ? String(existing.trailingStep) : '')
      setTargetPrice(existing.target ? String(existing.target) : '')
    } else {
      const suggested = suggestedDistance && entryPrice > 0
        ? entryPrice + (side === 'BUY' ? -suggestedDistance : suggestedDistance) : 0
      setStoploss(suggested > 0 ? String(Number(suggested.toFixed(10))) : '')
      setTrailingEnabled(false)
      setTrailingStep('')
      setTargetPrice('')
    }
  }, [open, existing, leg?.symbol, leg?.exchange, product, side, entryPrice, suggestedDistance])

  // Currency derivatives (CDS/BCD) display to 4 decimals; everything else to 2.
  const decimals = priceDecimals(leg?.exchange)

  // Reference price for validating stop direction: prefer live LTP, else entry.
  const slNum = Number(stoploss)
  const refPrice = ltp != null && ltp > 0 ? ltp : entryPrice
  let directionError = ''
  if (Number.isFinite(slNum) && slNum > 0 && refPrice > 0) {
    if (side === 'BUY' && slNum >= refPrice) {
      directionError = `Long (BUY): stop-loss must be below ${refPrice.toFixed(decimals)}`
    } else if (side === 'SELL' && slNum <= refPrice) {
      directionError = `Short (SELL): stop-loss must be above ${refPrice.toFixed(decimals)}`
    }
  }

  // Target must be on the PROFIT side, or it would trigger an immediate exit.
  let tgtNum = Number(targetPrice)
  let targetError = ''
  if (autoTarget && slNum > 0) {
    try {
      tgtNum = initialTarget(side, entryPrice, existing?.initialSl || slNum, leg?.tickSize)
    } catch (e) {
      targetError = (e as Error).message
    }
  }
  if (Number.isFinite(tgtNum) && tgtNum > 0 && refPrice > 0) {
    if (side === 'BUY' && tgtNum <= refPrice) {
      targetError = `Long (BUY): target must be above ${refPrice.toFixed(decimals)}`
    } else if (side === 'SELL' && tgtNum >= refPrice) {
      targetError = `Short (SELL): target must be below ${refPrice.toFixed(decimals)}`
    }
  }

  // Trailing enabled with a non-positive step would appear active but never move.
  const stepNum = Number(trailingStep)
  const trailingError =
    trailingEnabled && !(Number.isFinite(stepNum) && stepNum > 0)
      ? 'Trailing step must be greater than 0'
      : ''

  const handleSave = async () => {
    if (pending) return
    if (!leg) return
    const sl = Number(stoploss)
    if (!Number.isFinite(sl) || sl <= 0) return
    if (quantity <= 0) return
    // Block wrong-side stop/target (immediate exit) and an inert trailing config.
    if (directionError || targetError || trailingError) return
    const step = Number(trailingStep)
    const tgt = tgtNum
    const entry = entryPrice > 0 ? entryPrice : (ltp ?? 0)
    setPending(true)
    setSaveError('')
    try {
      const confirmed = await onSave({
        symbol: leg.symbol,
        exchange: leg.exchange,
        product,
        side,
        entry,
        quantity,
        initialSl: existing?.initialSl || sl,
        trailingEnabled,
        trailingStep: Number.isFinite(step) && step > 0 ? step : 0,
        highestPrice: existing?.highestPrice ?? entry,
        lowestPrice: existing?.lowestPrice ?? entry,
        currentSl: sl,
        target: Number.isFinite(tgt) && tgt > 0 ? tgt : 0,
        active: true,
      })
      if (confirmed === false) {
        setSaveError('Stop-loss save was not confirmed. Check the error and verify the saved SL.')
      } else {
        onOpenChange(false)
      }
    } catch {
      setSaveError('Stop-loss save was not confirmed. Verify the saved SL before trading.')
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!pending) onOpenChange(value)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>SL · Target · Trailing — {leg?.symbol ?? ''}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">
            OpenAlgo monitors this stop on the server. Keep the server and live price feed running;
            saving here does not place an exchange-held stop order.
          </p>
          {saveError && (
            <p role="alert" className="text-sm text-red-600">
              {saveError}
            </p>
          )}
          {leg?.exchange === 'CRYPTO' && <p className="text-xs text-muted-foreground">Broker order inputs and reference prices in this form are USD.</p>}
        <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">Entry</span>
              <div className="font-mono">{entryPrice > 0 ? entryPrice.toFixed(decimals) : '—'}</div>
            </div>
            <div>
              <span className="text-muted-foreground">LTP</span>
              <div className="font-mono">{ltp != null ? ltp.toFixed(decimals) : '—'}</div>
            </div>
            <div>
              <span className="text-muted-foreground">Side</span>
              <div className="font-mono">{side}</div>
            </div>
            <div>
              <span className="text-muted-foreground">Qty</span>
              <div className="font-mono">{quantity}</div>
            </div>
          </div>

          {quantity <= 0 && (
            <p className="text-xs text-red-600">
              No quantity for this leg yet — open a position (or wait for chain data) before setting
              a stop-loss.
            </p>
          )}

          <div className="space-y-1">
            <Label htmlFor="sl-price">Stop-loss price</Label>
            <Input
              id="sl-price"
              type="number"
              inputMode="decimal"
              value={stoploss}
              onChange={(e) => setStoploss(e.target.value)}
              placeholder="e.g. 270"
            />
            {directionError && <p className="text-xs text-red-600">{directionError}</p>}
          </div>

          <label className="flex items-center gap-2">
            <Checkbox
              checked={trailingEnabled}
              onCheckedChange={(v) => setTrailingEnabled(v === true)}
            />
            <span className="text-sm">Enable trailing stop-loss</span>
          </label>

          {trailingEnabled && (
            <div className="space-y-1">
              <Label htmlFor="sl-step">Trailing step</Label>
              <Input
                id="sl-step"
                type="number"
                inputMode="decimal"
                value={trailingStep}
                onChange={(e) => setTrailingStep(e.target.value)}
                placeholder="e.g. 2"
              />
              <p className="text-xs text-muted-foreground">
                Trailing starts only once price is ≥1 in profit; the stop only moves in your favor.
              </p>
              {trailingError && <p className="text-xs text-red-600">{trailingError}</p>}
            </div>
          )}

          <div className="space-y-1">
            <label className="flex items-center gap-2">
              <Checkbox
                checked={autoTarget}
                onCheckedChange={(v) => {
                  if (autoTarget && tgtNum > 0) setTargetPrice(String(tgtNum))
                  setAutoTarget(v === true)
                }}
              />
              <span className="text-sm">Auto target 1:3</span>
            </label>
            <p className="text-xs text-muted-foreground">
              Three times the initial entry-to-SL distance, before fees. The target stays fixed as SL
              trails.
            </p>
            <Label htmlFor="sl-target">Target price (optional)</Label>
            <Input
              id="sl-target"
              type="number"
              inputMode="decimal"
              value={autoTarget ? (slNum > 0 && !targetError ? String(tgtNum) : '') : targetPrice}
              disabled={autoTarget}
              onChange={(e) => setTargetPrice(e.target.value)}
              placeholder={side === 'BUY' ? 'above entry' : 'below entry'}
            />
            {targetError && <p className="text-xs text-red-600">{targetError}</p>}
          </div>
        </div>

        <DialogFooter className="gap-2">
          {existing && onClear && (
            <Button
              variant="outline"
              disabled={pending}
              onClick={async () => {
                setPending(true)
                setSaveError('')
                try {
                  if ((await onClear()) === false)
                    setSaveError('Stop-loss removal was not confirmed. Verify the saved SL.')
                  else onOpenChange(false)
                } catch {
                  setSaveError('Stop-loss removal was not confirmed. Verify the saved SL.')
                } finally {
                  setPending(false)
                }
              }}
            >
              Clear SL
            </Button>
          )}
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={
              pending ||
              quantity <= 0 ||
              !stoploss ||
              !!directionError ||
              !!targetError ||
              !!trailingError
            }
          >
            {pending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
