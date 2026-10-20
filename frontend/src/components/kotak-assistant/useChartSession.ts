import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { adminApi } from '@/api/admin'
import { useAuthStore } from '@/stores/authStore'
import { istSessionDate } from './chartReplay'
import { chartSessionOpen, chartSessionWindow } from './chartSession'

/** All panes share one calendar read per IST date; unused dates expire from the query cache. */
export function useChartSession(exchange: string, now: number, enabled = true) {
  const username = useAuthStore((state) => state.user?.username)
  const date = istSessionDate(now)
  const calendar = useQuery({
    queryKey: ['chart-session-calendar', username, date],
    queryFn: () => adminApi.checkTimings(date),
    enabled: enabled && !!exchange,
    staleTime: 60000,
    gcTime: 5 * 60000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  })
  const window = useMemo(
    () => (calendar.data ? chartSessionWindow(calendar.data, date, exchange) : null),
    [calendar.data, date, exchange]
  )
  const state =
    calendar.isError || (calendar.data && !window)
      ? 'unavailable'
      : !window
        ? 'checking'
        : chartSessionOpen(window, now)
          ? 'open'
          : 'closed'
  return { window: calendar.isError ? null : window, state }
}
