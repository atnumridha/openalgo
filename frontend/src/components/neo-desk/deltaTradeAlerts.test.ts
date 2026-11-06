import { beforeEach, expect, it, vi } from 'vitest'
import {
  readTradeAlerts,
  publishTradeAlert,
  dismissTradeAlert,
  tradeFillAlerts,
  nextTradeAlertSnapshot,
  backendProtectionAlerts,
} from './deltaTradeAlerts'
import type { DeltaBackendAutomation, DeltaChartState } from '@/api/deltaChart'
import { playAlertSound } from '@/lib/trading/alertDelivery'
vi.mock('@/lib/trading/alertDelivery', () => ({ playAlertSound: vi.fn(), readySound: vi.fn() }))
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})
const event = {
  id: 'order:1',
  account: 'a',
  symbol: 'BTCUSD',
  title: 'Order placed',
  message: 'Accepted, waiting for fill.',
  at: 100,
}
it('keeps each alert until manual dismissal, survives reload, and sounds once per event', () => {
  expect(publishTradeAlert(event)).toBe(true)
  expect(readTradeAlerts('a', 'BTCUSD')).toEqual([event])
  expect(publishTradeAlert(event)).toBe(false)
  expect(playAlertSound).toHaveBeenCalledOnce()
  dismissTradeAlert('a', 'BTCUSD', event.id)
  expect(readTradeAlerts('a', 'BTCUSD')).toEqual([])
  expect(publishTradeAlert(event)).toBe(false)
  expect(playAlertSound).toHaveBeenCalledOnce()
})
const state = {
  account: 'a',
  symbol: 'BTCUSD',
  asof: 100,
  position: { size: 2 },
  fills: [{ id: 'f1', side: 'buy', price: 100, size: 2 }],
} as DeltaChartState
it('announces an exit only when a new opposite fill and a smaller broker position agree', () => {
  const flat = {
    ...state,
    position: null,
    fills: [
      ...state.fills,
      { id: 'f2', side: 'sell' as const, price: 101, size: 2, created_at: 101 },
    ],
  }
  expect(tradeFillAlerts(state, flat)[0].title).toBe('Position exited')
  expect(tradeFillAlerts(state, { ...flat, fills: state.fills })).toEqual([])
  expect(tradeFillAlerts(state, { ...state, fills: flat.fills })).toEqual([])
  expect(tradeFillAlerts(null, state)).toEqual([])
  expect(tradeFillAlerts(state, { ...flat, account: 'other' })).toEqual([])
})
it('distinguishes partial exits and entry fills without inventing a full exit', () => {
  const reduced = {
    ...state,
    position: { ...state.position!, size: 1 },
    fills: [
      ...state.fills,
      { id: 'f2', side: 'sell' as const, price: 101, size: 1, created_at: 101 },
    ],
  }
  expect(tradeFillAlerts(state, reduced)[0].title).toBe('Position reduced')
  expect(tradeFillAlerts({ ...state, position: null, fills: [] }, state)[0].title).toBe(
    'Entry filled'
  )
})

it('keeps an unmatched position reduction until the delayed fill cache catches up', () => {
  const reduced = { ...state, asof: 102, position: null }
  expect(tradeFillAlerts(state, reduced)).toEqual([])
  const pending = nextTradeAlertSnapshot(state, reduced)
  const reconciled = {
    ...reduced,
    asof: 112,
    fills: [
      ...state.fills,
      { id: 'f2', side: 'sell' as const, price: 101, size: 2, created_at: 101 },
    ],
  }
  expect(tradeFillAlerts(pending, reconciled)[0]?.title).toBe('Position exited')
  expect(nextTradeAlertSnapshot(pending, reconciled)).toBe(reconciled)
})

it('keeps an alert visible in this session when storage quota is exhausted', () => {
  const e = { ...event, account: 'quota-account', id: 'quota-event' }
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('Full', 'QuotaExceededError')
  })
  try {
    expect(publishTradeAlert(e)).toBe(true)
    expect(readTradeAlerts(e.account, e.symbol)).toEqual([e])
  } finally {
    vi.restoreAllMocks()
  }
})

const backend = (changes: Partial<DeltaBackendAutomation> = {}): DeltaBackendAutomation => ({
  owner: 'backend',
  account: 'a',
  symbol: 'BTCUSD',
  enabled: true,
  leverage: 50,
  balance_fraction: 1,
  manual_quantity: 1,
  generation: 'g',
  status: 'protection_blocked',
  message: 'Replacement SL was rejected',
  checked_at: 100,
  next_check_at: 102,
  context: null,
  events: [
    {
      id: 17,
      at: 100,
      kind: 'protection_blocked',
      details: {
        plan_id: 'plan-1',
        message: 'Replacement SL was rejected',
        plan_status: 'blocked',
      },
    },
  ],
  ...changes,
})
it('persists and sounds a backend protection failure once across polls, recovery and manual dismissal', () => {
  const automation = backend()
  const alerts = backendProtectionAlerts(automation, 'a', 'BTCUSD')
  expect(alerts).toHaveLength(1)
  expect(alerts[0]).toMatchObject({ account: 'a', symbol: 'BTCUSD', title: 'Protection blocked' })
  expect(alerts[0].message).toContain('Replacement SL was rejected')
  for (const alert of alerts) publishTradeAlert(alert)
  for (const alert of backendProtectionAlerts({ ...automation, checked_at: 102 }, 'a', 'BTCUSD'))
    publishTradeAlert(alert)
  expect(readTradeAlerts('a', 'BTCUSD')).toEqual(alerts)
  expect(playAlertSound).toHaveBeenCalledOnce()
  expect(
    backendProtectionAlerts(backend({ status: 'managing', events: [] }), 'a', 'BTCUSD')
  ).toEqual([])
  expect(readTradeAlerts('a', 'BTCUSD')).toEqual(alerts)
  dismissTradeAlert('a', 'BTCUSD', alerts[0].id)
  for (const alert of backendProtectionAlerts(automation, 'a', 'BTCUSD')) publishTradeAlert(alert)
  expect(readTradeAlerts('a', 'BTCUSD')).toEqual([])
  expect(playAlertSound).toHaveBeenCalledOnce()
})
it('ignores pending events, another account and malformed failure details', () => {
  expect(
    backendProtectionAlerts(
      backend({
        events: [
          {
            id: 1,
            at: 100,
            kind: 'protection_pending',
            details: {
              plan_id: 'p',
              message: 'Waiting for acknowledgement',
              plan_status: 'pending',
            },
          },
        ],
      }),
      'a',
      'BTCUSD'
    )
  ).toEqual([])
  expect(backendProtectionAlerts(backend(), 'b', 'BTCUSD')).toEqual([])
  expect(
    backendProtectionAlerts(
      backend({ events: [{ id: 2, at: 100, kind: 'protection_blocked', details: {} }] }),
      'a',
      'BTCUSD'
    )
  ).toEqual([])
  expect(playAlertSound).not.toHaveBeenCalled()
})
it('keeps distinct protection failure events distinct for the same plan', () => {
  const first = backendProtectionAlerts(backend(), 'a', 'BTCUSD')[0]
  const repeatedIncident = backend()
  repeatedIncident.events[0].id = 18
  const second = backendProtectionAlerts(repeatedIncident, 'a', 'BTCUSD')[0]
  expect(first.id).not.toBe(second.id)
})
