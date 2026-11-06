import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { deltaChartApi, type DeltaBackendAutomation } from '@/api/deltaChart'
import { playAlertSound } from '@/lib/trading/alertDelivery'
import { readTradeAlerts, dismissTradeAlert } from './deltaTradeAlerts'
import { DeltaBackendAuto } from './DeltaBackendAuto'
vi.mock('@/lib/trading/alertDelivery', () => ({ playAlertSound: vi.fn(), readySound: vi.fn() }))
vi.mock('@/api/deltaChart', () => ({ deltaChartApi: { automation: vi.fn() } }))
const fixture = (changes: Partial<DeltaBackendAutomation> = {}): DeltaBackendAutomation => ({
  owner: 'backend',
  enabled: false,
  account: 'account-a',
  symbol: 'BTCUSD',
  leverage: 5,
  balance_fraction: 1,
  manual_quantity: 1,
  generation: 'g1',
  status: 'off',
  message: 'New entries stopped',
  checked_at: 100,
  next_check_at: 110,
  context: {
    source_time: 95,
    direction: 'up',
    higher_direction: 'down',
    trend_summary: 'Mixed trend',
    patterns: [{ name: 'Hammer' }],
  },
  events: [
    { id: 1, at: 90, kind: 'waiting', source_time: 85, details: { reason: 'Mixed intervals' } },
  ],
  ...changes,
})
const props = () => ({
  automation: fixture(),
  account: 'account-a',
  symbol: 'BTCUSD',
  valid: true,
  leverage: 12,
  balanceFraction: 0.25,
  manualQuantity: '3',
  onChanged: vi.fn(),
})
beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
})
afterEach(() => {
  vi.useRealTimers()
})
it('sends displayed settings and waits for backend acknowledgement before showing On', async () => {
  const p = props()
  let confirm!: (value: unknown) => void
  vi.mocked(deltaChartApi.automation).mockImplementation(
    () =>
      new Promise((resolve) => {
        confirm = resolve
      })
  )
  render(<DeltaBackendAuto {...p} />)
  fireEvent.click(screen.getByRole('switch', { name: 'Auto' }))
  expect(deltaChartApi.automation).toHaveBeenCalledWith({
    symbol: 'BTCUSD',
    account: 'account-a',
    enabled: true,
    leverage: 12,
    balance_fraction: 0.25,
    manual_quantity: 3,
  })
  expect(screen.getByRole('switch')).not.toBeChecked()
  expect(screen.getByRole('switch')).toBeDisabled()
  const automation = fixture({ enabled: true, generation: 'g2', status: 'waiting' })
  await act(async () => confirm({ status: 'confirmed', automation }))
  expect(p.onChanged).toHaveBeenCalledWith(automation)
})
it('stops the running symbol with no settings even when the view and settings are invalid', async () => {
  const p = {
    ...props(),
    symbol: 'ETHUSD',
    valid: false,
    manualQuantity: '',
    automation: fixture({ enabled: true }),
  }
  vi.mocked(deltaChartApi.automation).mockResolvedValue({
    status: 'confirmed',
    automation: fixture(),
  })
  render(<DeltaBackendAuto {...p} />)
  expect(screen.getByText(/Running BTCUSD/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('switch'))
  await waitFor(() => expect(p.onChanged).toHaveBeenCalled())
  expect(deltaChartApi.automation).toHaveBeenCalledWith({
    symbol: 'BTCUSD',
    account: 'account-a',
    enabled: false,
  })
})
it('blocks a different account and invalid enabling settings', () => {
  const p = props()
  const view = render(<DeltaBackendAuto {...p} account="account-b" />)
  expect(screen.getByRole('switch')).toBeDisabled()
  view.rerender(<DeltaBackendAuto {...p} manualQuantity="0" balanceFraction={null} />)
  expect(screen.getByRole('switch')).toBeDisabled()
  expect(deltaChartApi.automation).not.toHaveBeenCalled()
})
it('uses a safe quantity placeholder when balance sizing is selected', async () => {
  vi.mocked(deltaChartApi.automation).mockResolvedValue({
    status: 'confirmed',
    automation: fixture({ enabled: true }),
  })
  render(<DeltaBackendAuto {...props()} manualQuantity="" />)
  fireEvent.click(screen.getByRole('switch'))
  await waitFor(() =>
    expect(deltaChartApi.automation).toHaveBeenCalledWith(
      expect.objectContaining({ manual_quantity: 1 })
    )
  )
})
it('keeps unknown outcomes blocked until a fresh backend check and never retries automatically', async () => {
  vi.mocked(deltaChartApi.automation).mockRejectedValue(new Error('Network timeout'))
  const p = props()
  const view = render(<DeltaBackendAuto {...p} />)
  fireEvent.click(screen.getByRole('switch'))
  expect(await screen.findByRole('alert')).toHaveTextContent(/waiting for fresh backend status/i)
  expect(screen.getByRole('switch')).toBeDisabled()
  view.rerender(<DeltaBackendAuto {...p} automation={fixture()} />)
  expect(screen.getByRole('switch')).toBeDisabled()
  view.rerender(<DeltaBackendAuto {...p} automation={fixture({ checked_at: 101 })} />)
  expect(screen.getByRole('switch')).not.toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Network timeout')
  expect(deltaChartApi.automation).toHaveBeenCalledTimes(1)
})
it('shows explicit rejection and permits a deliberate new attempt', async () => {
  vi.mocked(deltaChartApi.automation).mockRejectedValue({
    response: { status: 409, data: { message: 'Account busy' } },
  })
  render(<DeltaBackendAuto {...props()} />)
  fireEvent.click(screen.getByRole('switch'))
  expect(await screen.findByRole('alert')).toHaveTextContent('Account busy')
  expect(screen.getByRole('switch')).not.toBeDisabled()
})
it('displays current directions, aging candle data and inspectable trend memory', () => {
  vi.useFakeTimers()
  vi.setSystemTime(100_000)
  render(<DeltaBackendAuto {...props()} />)
  expect(screen.getByText(/1m: up/)).toHaveTextContent('5m: down')
  expect(screen.getByText(/Candle data: 5s old/)).toHaveTextContent('Next check in 10s')
  act(() => {
    vi.advanceTimersByTime(2000)
  })
  expect(screen.getByText(/Candle data: 7s old/)).toHaveTextContent('Next check in 8s')
  fireEvent.click(screen.getByText('Trend memory'))
  expect(screen.getByText(/Mixed intervals/)).toBeInTheDocument()
  expect(screen.getByText(/Hammer/)).toBeInTheDocument()
  expect(screen.getByText(/Mac awake/)).toBeInTheDocument()
  expect(deltaChartApi.automation).not.toHaveBeenCalled()
})
it('does not apply an acknowledgement from an account that changed during the request', async () => {
  let confirm!: (value: unknown) => void
  vi.mocked(deltaChartApi.automation).mockImplementation(
    () =>
      new Promise((resolve) => {
        confirm = resolve
      })
  )
  const p = props()
  const view = render(<DeltaBackendAuto {...p} />)
  fireEvent.click(screen.getByRole('switch'))
  view.rerender(
    <DeltaBackendAuto {...p} account="account-b" automation={fixture({ account: 'account-b' })} />
  )
  await act(async () => confirm({ status: 'confirmed', automation: fixture({ enabled: true }) }))
  expect(p.onChanged).not.toHaveBeenCalled()
})
it('releases an uncertain default Off configuration only after a newer observed status snapshot', async () => {
  vi.mocked(deltaChartApi.automation).mockRejectedValue(new Error('Network timeout'))
  const p = { ...props(), automation: fixture({ generation: '', checked_at: null }) }
  const view = render(<DeltaBackendAuto {...p} observedAt={200} />)
  fireEvent.click(screen.getByRole('switch'))
  expect(await screen.findByRole('alert')).toHaveTextContent(/waiting for fresh backend status/i)
  view.rerender(<DeltaBackendAuto {...p} observedAt={200} />)
  expect(screen.getByRole('switch')).toBeDisabled()
  view.rerender(<DeltaBackendAuto {...p} observedAt={199} />)
  expect(screen.getByRole('switch')).toBeDisabled()
  view.rerender(<DeltaBackendAuto {...p} observedAt={201} />)
  expect(screen.getByRole('switch')).not.toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Network timeout')
  expect(deltaChartApi.automation).toHaveBeenCalledTimes(1)
})
it('announces blocked protection despite stale strategy data and persists its audible event after recovery', () => {
  const automation = fixture({
    status: 'protection_blocked',
    message: 'SL change rejected',
    events: [
      {
        id: 31,
        at: 100,
        kind: 'protection_blocked',
        details: { plan_id: 'p', message: 'SL change rejected', plan_status: 'blocked' },
      },
    ],
  })
  const p = props()
  const view = render(<DeltaBackendAuto {...p} valid={false} automation={automation} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Protection blocked')
  expect(screen.getByRole('alert')).toHaveTextContent('SL change rejected')
  expect(readTradeAlerts('account-a', 'BTCUSD')).toHaveLength(1)
  view.rerender(
    <DeltaBackendAuto {...p} valid={false} automation={{ ...automation, checked_at: 101 }} />
  )
  expect(playAlertSound).toHaveBeenCalledOnce()
  view.rerender(
    <DeltaBackendAuto {...p} automation={fixture({ status: 'managing', events: [] })} />
  )
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  const [alert] = readTradeAlerts('account-a', 'BTCUSD')
  expect(alert.message).toContain('SL change rejected')
  dismissTradeAlert('account-a', 'BTCUSD', alert.id)
  view.rerender(<DeltaBackendAuto {...p} automation={automation} />)
  expect(readTradeAlerts('account-a', 'BTCUSD')).toHaveLength(0)
  expect(playAlertSound).toHaveBeenCalledOnce()
})
it('shows pending protection without repeatedly sounding an alert', () => {
  const p = props()
  const automation = fixture({
    status: 'protection_pending',
    message: 'Waiting for SL acknowledgement',
    events: [
      {
        id: 41,
        at: 100,
        kind: 'protection_pending',
        details: {
          plan_id: 'p',
          message: 'Waiting for SL acknowledgement',
          plan_status: 'pending',
        },
      },
    ],
  })
  const view = render(<DeltaBackendAuto {...p} automation={automation} />)
  expect(screen.getByRole('status')).toHaveTextContent('Protection pending')
  expect(screen.getByRole('status')).toHaveTextContent('Waiting for SL acknowledgement')
  view.rerender(<DeltaBackendAuto {...p} automation={{ ...automation, checked_at: 102 }} />)
  expect(readTradeAlerts('account-a', 'BTCUSD')).toEqual([])
  expect(playAlertSound).not.toHaveBeenCalled()
})
it('does not publish another account protection event into this account alerts', () => {
  const p = props()
  render(
    <DeltaBackendAuto
      {...p}
      automation={fixture({
        account: 'another-account',
        status: 'protection_blocked',
        events: [
          {
            id: 51,
            at: 100,
            kind: 'protection_blocked',
            details: { plan_id: 'p', message: 'Other account failure', plan_status: 'blocked' },
          },
        ],
      })}
    />
  )
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(readTradeAlerts('account-a', 'BTCUSD')).toEqual([])
  expect(playAlertSound).not.toHaveBeenCalled()
})
