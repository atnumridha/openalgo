import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { adminApi } from '@/api/admin'
import { scalpingApi } from '@/api/scalping'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { candleKey, publishChartCandles } from './chartCandleStore'
import { TradeIndicators } from './TradeIndicators'

vi.mock('@/api/scalping', () => ({ scalpingApi: { getHistory: vi.fn() } }))
vi.mock('@/api/admin', () => ({ adminApi: { checkTimings: vi.fn() } }))
const now = Date.parse('2026-10-15T12:05:30+05:30') / 1000
const bucket = Math.floor((now + 19800) / 300) * 300
const bars = Array.from({ length: 20 }, (_, i) => ({
  time: bucket - (20 - i) * 300,
  open: 100 + i,
  high: 101 + i,
  low: 99 + i,
  close: 100 + i,
  volume: 650 + i,
}))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(adminApi.checkTimings).mockImplementation(async (date) => ({
    date,
    timings: [{ exchange: 'NFO', start_time: '09:15', end_time: '15:40' }],
  }))
  useAuthStore.setState({ user: { username: 'indicator-test', broker: 'kotak' } as never })
  useThemeStore.setState({ appMode: 'live' })
})
function show(symbol: string, fetchHistory = false, time = now, ltp = 120) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TradeIndicators
        symbol={symbol}
        exchange="NFO"
        interval="5m"
        quote={{ ltp, volume: 100000, time, observed_time: time, source: 'Live feed' }}
        now={time}
        fetchHistory={fetchHistory}
      />
    </QueryClientProvider>
  )
}
it('reuses selected-chart candles for tracking without requesting history', async () => {
  publishChartCandles(candleKey('indicator-test', 'live', 'TRACKCE', 'NFO', '5m'), bars)
  show('TRACKCE')
  await waitFor(() => expect(screen.getByRole('img')).toHaveAccessibleName(/100.00, Overbought$/))
  expect(screen.getByLabelText('Day traded volume')).toHaveTextContent('1,00,000')
  expect(screen.getByText('Current 5m bar volume')).toBeInTheDocument()
  expect(screen.getByLabelText('Current buyer quantity')).toHaveTextContent('Unavailable')
  expect(scalpingApi.getHistory).not.toHaveBeenCalled()
})
it('leaves missing RSI unavailable in tracking-only mode without an API request', () => {
  show('MISSINGCE')
  expect(screen.getByRole('img')).toHaveAccessibleName(/Unavailable/)
  expect(scalpingApi.getHistory).not.toHaveBeenCalled()
})
it('refreshes old cached candles for a managed trade when its chart is no longer selected', async () => {
  publishChartCandles(
    candleKey('indicator-test', 'live', 'OLDCE', 'NFO', '5m'),
    bars.map((b) => ({ ...b, time: b.time - 3600 }))
  )
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({ status: 'success', candles: bars } as never)
  show('OLDCE', true)
  await waitFor(() => expect(screen.getByRole('img')).toHaveAccessibleName(/100.00, Overbought$/))
  expect(scalpingApi.getHistory).toHaveBeenCalledWith('OLDCE', 'NFO', '5m')
})
it('keeps the RSI historical and current volume unavailable after the verified session closes', async () => {
  const closedAt = Date.parse('2026-10-15T15:40:30+05:30') / 1000
  publishChartCandles(
    candleKey('indicator-test', 'live', 'CLOSEDCE', 'NFO', '5m'),
    bars.map((bar) => ({ ...bar, time: bar.time + closedAt - now }))
  )
  show('CLOSEDCE', false, closedAt, 40)
  await waitFor(() => expect(screen.getByText(/Market closed/)).toBeInTheDocument())
  expect(screen.getByRole('img')).toHaveAccessibleName(/100.00, Overbought, not live$/)
  expect(screen.getByLabelText('Current bar volume')).toHaveTextContent('Unavailable')
})
it('shows calendar failure without treating a newly received quote as a forming candle', async () => {
  vi.mocked(adminApi.checkTimings).mockRejectedValue(Error('Offline'))
  publishChartCandles(candleKey('indicator-test', 'live', 'NOCALENDARCE', 'NFO', '5m'), bars)
  show('NOCALENDARCE', false, now, 40)
  await waitFor(() => expect(screen.getByText(/Calendar unavailable/)).toBeInTheDocument())
  expect(screen.getByRole('img')).toHaveAccessibleName(/100.00, Overbought, not live$/)
  expect(screen.getByLabelText('Current bar volume')).toHaveTextContent('Unavailable')
})
