/**
 * useTrailingSL — stop-loss / target / trailing-SL CONFIG + DISPLAY for the scalping terminal.
 *
 * The actual engine that watches ticks, trails the stop, and fires exits now runs
 * SERVER-SIDE (services/scalping_risk_monitor_service.py) so it keeps working even
 * after the user navigates away from /scalping or closes the browser. This hook is
 * therefore deliberately NOT an executor — it only:
 *  - loads the active SL states for display (position book SL/TP/TSL columns), and
 *    refreshes them on server events and every 5 seconds for reconciliation;
 *  - persists SL config (setSL) / clears it (clearSL) to the backend, which the
 *    server monitor then enforces.
 *
 * This split removes the double-exit risk of having both a browser engine and a
 * server engine firing. `evaluateTrail` is kept exported (unit tests + the server
 * port mirror its logic). Long legs (BUY) trail with the stop below price; short
 * legs (SELL) mirror it.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import type { ScalpingAction, ScalpingProduct, ScalpingSLState } from '@/types/scalping'
import { showToast } from '@/utils/toast'
import { useOrderEventRefresh } from './useOrderEventRefresh'

const MIN_TRAIL_PROFIT = 1 // don't trail until >= 1 rupee in profit

function errorMessage(error: unknown): string {
  const response = (error as { response?: { data?: { message?: string } } })?.response
  return response?.data?.message || (error instanceof Error ? error.message : 'Request failed')
}

export interface SLState {
  symbol: string
  exchange: string
  product: ScalpingProduct
  side: ScalpingAction
  entry: number
  quantity: number
  initialSl: number
  trailingEnabled: boolean
  trailingStep: number
  highestPrice: number
  lowestPrice: number
  currentSl: number
  target: number // take-profit price (0 = no target)
  active: boolean
}

// Keyed by exchange:symbol:product to match the DB uniqueness
// (database/scalping_db.py UniqueConstraint) and avoid MIS/NRML collisions.
export function slKey(symbol: string, exchange: string, product: string): string {
  return `${exchange}:${symbol}:${product}`
}

// Find the active SL for a specific leg + product (matches the DB scoping, so an
// MIS and an NRML SL on the same strike are never confused).
export function findLegSL(
  slMap: Record<string, SLState>,
  symbol: string,
  exchange: string,
  product: string
): SLState | undefined {
  return slMap[slKey(symbol, exchange, product)]
}

function fromBackend(s: ScalpingSLState): SLState {
  const entry = s.entry_price ?? 0
  return {
    symbol: s.symbol,
    exchange: s.exchange,
    product: s.product,
    side: s.side,
    entry,
    quantity: s.quantity ?? 0,
    initialSl: s.initial_sl ?? entry,
    trailingEnabled: s.trailing_enabled ?? false,
    trailingStep: s.trailing_step ?? 0,
    highestPrice: s.highest_price ?? entry,
    lowestPrice: s.lowest_price ?? entry,
    currentSl: s.current_sl ?? s.initial_sl ?? entry,
    target: s.target ?? 0,
    active: s.is_active ?? true,
  }
}

function toBackend(
  s: SLState
): Partial<ScalpingSLState> & Pick<ScalpingSLState, 'symbol' | 'exchange' | 'product'> {
  return {
    symbol: s.symbol,
    exchange: s.exchange,
    product: s.product,
    side: s.side,
    entry_price: s.entry,
    quantity: s.quantity,
    initial_sl: s.initialSl,
    trailing_enabled: s.trailingEnabled,
    trailing_step: s.trailingStep,
    highest_price: s.highestPrice,
    lowest_price: s.lowestPrice,
    current_sl: s.currentSl,
    target: s.target,
    is_active: s.active,
  }
}

/**
 * Pure trail evaluation. For a long (BUY) leg the stop sits below price and only
 * rises; for a short (SELL) leg it sits above price and only falls.
 * Returns the updated state and whether the stop was breached by this tick.
 */
export function evaluateTrail(
  sl: SLState,
  ltp: number
): { next: SLState; breached: boolean; reason: 'sl' | 'target' | null } {
  if (sl.side === 'SELL') {
    const lowest = Math.min(sl.lowestPrice ?? sl.entry, ltp)
    let currentSl = sl.currentSl
    if (sl.trailingEnabled && sl.trailingStep > 0 && sl.entry - ltp >= MIN_TRAIL_PROFIT) {
      const candidate = lowest + sl.trailingStep
      if (currentSl <= 0 || candidate < currentSl) currentSl = candidate
    }
    const slHit = currentSl > 0 && ltp >= currentSl // short: stop sits ABOVE price
    const targetHit = sl.target > 0 && ltp <= sl.target // short: target BELOW price
    return {
      next: { ...sl, lowestPrice: lowest, currentSl },
      breached: slHit || targetHit,
      reason: slHit ? 'sl' : targetHit ? 'target' : null,
    }
  }

  // Long leg (BUY)
  const highest = Math.max(sl.highestPrice ?? sl.entry, ltp)
  let currentSl = sl.currentSl
  if (sl.trailingEnabled && sl.trailingStep > 0 && ltp - sl.entry >= MIN_TRAIL_PROFIT) {
    const candidate = highest - sl.trailingStep
    if (candidate > currentSl) currentSl = candidate
  }
  const slHit = currentSl > 0 && ltp <= currentSl // long: stop sits BELOW price
  const targetHit = sl.target > 0 && ltp >= sl.target // long: target ABOVE price
  return {
    next: { ...sl, highestPrice: highest, currentSl },
    breached: slHit || targetHit,
    reason: slHit ? 'sl' : targetHit ? 'target' : null,
  }
}

// `reloadSignal` (e.g. the app's Analyze/Live mode) re-loads the SL states when
// it changes, so the displayed SLs match the active trading mode.
export function useTrailingSL(reloadSignal?: unknown) {
  const [slMap, setSlMap] = useState<Record<string, SLState>>({})
  const [slAvailable, setSlAvailable] = useState(false)
  const loadSerialRef = useRef(0)
  const revisionRef = useRef(0)
  const scopeGenerationRef = useRef(0)
  const scopeRef = useRef(reloadSignal)
  scopeRef.current = reloadSignal

  const warnedRef = useRef(false)
  // Refresh on risk-monitor/order events and reconcile every 5 seconds in case
  // an event was missed. Only the newest request may replace displayed state.
  const loadStates = useCallback(() => {
    const serial = ++loadSerialRef.current
    const revision = revisionRef.current
    const scope = scopeRef.current
    scalpingApi
      .getSLStates()
      .then((resp) => {
        if (resp.status !== 'success') throw new Error('Failed to load stop-losses')
        if (serial !== loadSerialRef.current || revision !== revisionRef.current || scope !== scopeRef.current) return
        const restored: Record<string, SLState> = {}
        for (const s of resp.data) {
          restored[slKey(s.symbol, s.exchange, s.product)] = fromBackend(s)
        }
        setSlMap(restored)
        setSlAvailable(true)
      })
      .catch(() => {
        if (serial !== loadSerialRef.current || revision !== revisionRef.current || scope !== scopeRef.current) return
        setSlAvailable(false)
        if (!warnedRef.current) {
          warnedRef.current = true
          showToast.error('Failed to load active stop-losses — verify manually', 'orders')
        }
      })
  }, [])

  // Reload on mount and whenever the reload signal (trading mode) changes.
  // reloadSignal is a deliberate re-run trigger (not used inside the effect).
  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadSignal is an intentional refresh trigger
  useEffect(() => {
    scopeGenerationRef.current++
    revisionRef.current++
    setSlMap({})
    setSlAvailable(false)
    loadStates()
    const timer = setInterval(loadStates, 5000)
    return () => clearInterval(timer)
  }, [loadStates, reloadSignal])

  useOrderEventRefresh(loadStates, {
    events: ['scalping_sl_update', 'order_event', 'analyzer_update', 'close_position_event'],
    delay: 200,
  })

  // A displayed stop must have a server acknowledgement. Transport failures
  // can have uncertain outcomes, so preserve the last confirmed state and warn.
  const setSL = useCallback(
    async (sl: SLState): Promise<boolean> => {
      const scope = scopeRef.current
      const generation = scopeGenerationRef.current
      revisionRef.current++
      try {
        const response = await scalpingApi.saveSL(toBackend(sl))
        if (response.status !== 'success' || !response.data) {
          throw new Error(response.message || 'Stop-loss save was not confirmed')
        }
        if (scope === scopeRef.current && generation === scopeGenerationRef.current) {
          revisionRef.current++
          // Request, commit and response order can differ. Always re-read the
          // canonical state; an acknowledgement is not the latest configuration.
          loadStates()
        }
        return true
      } catch (error) {
        showToast.error(
          `Stop-loss save not confirmed: ${errorMessage(error)}. Verify the saved SL before trading.`,
          'orders'
        )
        return false
      }
    },
    [loadStates]
  )

  const clearSL = useCallback(
    async (symbol: string, exchange: string, product: string): Promise<boolean> => {
      const scope = scopeRef.current
      const generation = scopeGenerationRef.current
      revisionRef.current++
      try {
        const response = await scalpingApi.deleteSL(symbol, exchange, product)
        if (response.status !== 'success' || response.deleted !== true)
          throw new Error('Stop-loss removal was not confirmed')
        if (scope === scopeRef.current && generation === scopeGenerationRef.current) {
          revisionRef.current++
          loadStates()
        }
        return true
      } catch (error) {
        showToast.error(
          `Stop-loss removal not confirmed: ${errorMessage(error)}. Verify the saved SL.`,
          'orders'
        )
        return false
      }
    },
    [loadStates]
  )

  return { slMap, slAvailable, setSL, clearSL }
}
