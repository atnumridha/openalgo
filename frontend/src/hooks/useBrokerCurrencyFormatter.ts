import { useMemo } from 'react'
import { makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useDeltaDisplayCurrency } from './useDeltaDisplayCurrency'

export function useBrokerCurrencyFormatter(broker?: string | null) {
  const { user } = useAuthStore()
  const [currency] = useDeltaDisplayCurrency(user?.username)
  return useMemo(() => makeFormatCurrency(broker, currency), [broker, currency])
}

/** Instrument quotes keep the broker's native denomination; only cash P&L uses the preference. */
export function useBrokerPriceFormatter(broker?: string | null) {
  return useMemo(() => makeFormatCurrency(broker), [broker])
}
