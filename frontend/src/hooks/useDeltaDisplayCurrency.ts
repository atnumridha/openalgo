import { useCallback, useSyncExternalStore } from 'react'
import type { DeltaDisplayCurrency } from '@/lib/deltaCurrency'

const CHANGE = 'openalgo-delta-display-currency'
const keyFor = (username?: string) => `openalgo_delta_position_currency_${username || 'session'}`
export function getDeltaDisplayCurrency(username?: string): DeltaDisplayCurrency {
  try {
    return localStorage.getItem(keyFor(username)) === 'USD' ? 'USD' : 'INR'
  } catch {
    return 'INR'
  }
}
export function subscribeDeltaDisplayCurrency(listener: () => void) {
  window.addEventListener(CHANGE, listener)
  window.addEventListener('storage', listener)
  return () => {
    window.removeEventListener(CHANGE, listener)
    window.removeEventListener('storage', listener)
  }
}
export function setDeltaDisplayCurrency(
  username: string | undefined,
  currency: DeltaDisplayCurrency
) {
  try {
    localStorage.setItem(keyFor(username), currency)
  } catch {
    return
  }
  window.dispatchEvent(new Event(CHANGE))
}
export function useDeltaDisplayCurrency(username?: string) {
  const snapshot = useCallback(() => getDeltaDisplayCurrency(username), [username])
  const currency = useSyncExternalStore(
    subscribeDeltaDisplayCurrency,
    snapshot,
    () => 'INR' as const
  )
  const setCurrency = useCallback(
    (value: DeltaDisplayCurrency) => setDeltaDisplayCurrency(username, value),
    [username]
  )
  return [currency, setCurrency] as const
}
