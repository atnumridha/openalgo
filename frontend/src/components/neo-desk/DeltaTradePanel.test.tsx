import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { deltaChartApi, type DeltaBackendAutomation, type DeltaChartState } from '@/api/deltaChart'
import { DeltaTradePanel } from './DeltaTradePanel'
vi.mock('@/api/deltaChart', () => ({
  deltaChartApi: {
    state: vi.fn(),
    action: vi.fn(),
    connection: vi.fn(),
    manage: vi.fn(),
    automation: vi.fn(),
  },
}))
const snapshot = (changes: Partial<DeltaChartState> = {}): DeltaChartState => ({
  connected: true,
  environment: 'india_prod',
  asof: Date.now() / 1000,
  symbol: 'BTCUSD',
  account: 'account-a',
  product: { id: 27, symbol: 'BTCUSD', tick_size: 0.5, contract_value: 0.001, max_leverage: 250 },
  ticker: { mark: 70000, last: 70000, bid: 69999.5, ask: 70000.5 },
  leverage: 20,
  position: {
    version: 'position-v1',
    size: 2,
    entry: 69000,
    mark: 70000,
    pnl: 2,
    liquidation: 62000,
  },
  orders: [],
  fills: [],
  managed_plans: [],
  sizing: {
    available_balance: 16,
    currency: 'USD',
    maker_fee_rate: 0.0002,
    fee_tax_rate: 0.18,
    version: 'fixture-sizing',
  },
  ...changes,
})
beforeEach(() => {
  vi.restoreAllMocks()
  vi.resetAllMocks()
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: vi.fn(
        async (_name: unknown, _options: unknown, run: (lock: object) => Promise<void>) => run({})
      ),
    },
  })
  sessionStorage.clear()
  localStorage.clear()
  localStorage.setItem(
    'neo.delta.trade.defaults',
    JSON.stringify({ leverage: 5, balanceFraction: 1, manualQuantity: '1' })
  )
  vi.mocked(deltaChartApi.state).mockImplementation(async () => snapshot())
  vi.mocked(deltaChartApi.action).mockImplementation(async (body) => ({
    status: 'confirmed',
    message: 'Broker accepted',
    request_id: body.request_id,
  }))
})

it('clears lines and controls immediately on symbol change or disabled historical chart', async () => {
  const onState = vi.fn()
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" onState={onState} />)
  await screen.findByText('Live · India')
  vi.mocked(deltaChartApi.state).mockImplementation(() => new Promise(() => {}))
  view.rerender(<DeltaTradePanel enabled symbol="ETHUSD" onState={onState} />)
  expect(screen.queryByText(/unrealized/i)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(onState).toHaveBeenLastCalledWith(null)
  view.rerender(<DeltaTradePanel enabled={false} symbol="ETHUSD" onState={onState} />)
  expect(screen.queryByRole('button', { name: 'Place Long' })).not.toBeInTheDocument()
})
it('disables actions and chart lines for stale snapshots', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ asof: Date.now() / 1000 - 11 }))
  const onState = vi.fn()
  render(<DeltaTradePanel enabled symbol="BTCUSD" onState={onState} />)
  await screen.findByText(/Stale/)
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(onState).toHaveBeenLastCalledWith(null)
})
it('keeps uncertain submissions pending and never retries them', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  vi.mocked(deltaChartApi.action).mockRejectedValue(new Error('Network timeout'))
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
    await Promise.resolve()
  })
  await screen.findByText(/Outcome unknown/)
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
})
it('requires review for chart drag proposals and carries the order version', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      orders: [
        {
          id: 'o1',
          side: 'sell',
          size: 2,
          unfilled: 2,
          type: 'limit_order',
          kind: 'target',
          price: 72000,
          post_only: true,
          reduce_only: true,
          state: 'open',
          version: 'v1',
        },
      ],
    })
  )
  const handled = vi.fn()
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      editProposal={{ order_id: 'o1', price: 73000, nonce: 1 }}
      onProposalHandled={handled}
    />
  )
  await screen.findByRole('dialog', { name: 'Review live order' })
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Send live order' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'edit', order_id: 'o1', version: 'v1', price: 73000 })
    )
  )
  expect(handled).toHaveBeenCalled()
})
it('clears broker lines and blocks actions when polling fails or changes account', async () => {
  vi.useFakeTimers()
  try {
    const onState = vi.fn()
    render(<DeltaTradePanel enabled symbol="BTCUSD" onState={onState} />)
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByText(/unrealized/i)).toBeVisible()
    vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ account: 'account-b' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.queryByText(/unrealized/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
    expect(onState).toHaveBeenLastCalledWith(null)
    vi.mocked(deltaChartApi.state).mockRejectedValue(new Error('offline'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(onState).toHaveBeenLastCalledWith(null)
  } finally {
    vi.useRealTimers()
  }
})
it('requires whole contracts and caps at the product leverage ceiling', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      product: { id: 27, symbol: 'BTCUSD', tick_size: 0.5, contract_value: 0.001, max_leverage: 3 },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Leverage')).toHaveValue('3')
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '200' } })
  expect(screen.getByLabelText('Leverage')).toHaveValue('3')
  expect(screen.getByText('Contract limit: 3×')).toBeVisible()
  fireEvent.change(screen.getByLabelText('Quantity (lots)'), { target: { value: '1.5' } })
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
})
it('clears credentials after connecting and never includes them in order submissions', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ connected: false }))
  vi.mocked(deltaChartApi.connection).mockResolvedValue({ connected: true })
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Disconnected')
  fireEvent.change(screen.getByLabelText('Delta API key'), { target: { value: 'test-key' } })
  fireEvent.change(screen.getByLabelText('Delta API secret'), { target: { value: 'test-secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Connect Delta' }))
  expect(screen.getByLabelText('Delta API key')).toHaveValue('')
  expect(screen.getByLabelText('Delta API secret')).toHaveValue('')
  await screen.findByText(/Connection saved/)
  expect(deltaChartApi.connection).toHaveBeenCalledWith('test-key', 'test-secret')
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('preserves an uncertain request lock when the chart switches symbols', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  vi.mocked(deltaChartApi.action).mockRejectedValue(new Error('timeout'))
  vi.mocked(deltaChartApi.state).mockImplementation(async (symbol) =>
    snapshot({
      position: null,
      symbol,
      product: { id: 27, symbol, tick_size: 0.5, contract_value: 0.001, max_leverage: 200 },
    })
  )
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
    await Promise.resolve()
  })
  await screen.findByText(/Outcome unknown/)
  view.rerender(<DeltaTradePanel enabled symbol="ETHUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Pending broker outcome')
})
it('blocks actions while a broker order has an unknown outcome state', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      orders: [
        {
          id: 'uncertain',
          side: 'buy',
          size: 1,
          unfilled: 1,
          type: 'market_order',
          kind: 'entry',
          price: null,
          post_only: true,
          reduce_only: false,
          state: 'unknown',
          version: 'v1',
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('alert')).toHaveTextContent('Pending broker outcome')
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
})
it('requires a reviewed close and position SL/TP before broker mutations', async () => {
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Close position' }))
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent('2 lots')
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  fireEvent.change(screen.getByLabelText('Stop price'), { target: { value: '68000' } })
  fireEvent.change(screen.getByLabelText('Target price'), { target: { value: '72000' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add market SL' }))
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Send live order' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'protect', stop: 68000 })
    )
  )
})

it('rejects a close review when the position changes before send', async () => {
  vi.useFakeTimers()
  try {
    render(<DeltaTradePanel enabled symbol="BTCUSD" />)
    await act(async () => {
      await Promise.resolve()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Close position' }))
    vi.mocked(deltaChartApi.state).mockResolvedValue(
      snapshot({
        position: {
          version: 'position-v2',
          size: 3,
          entry: 69500,
          mark: 70000,
          pnl: 1,
          liquidation: 62000,
        },
      })
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send live order' }))
    expect(deltaChartApi.action).not.toHaveBeenCalled()
    expect(screen.getByText(/Position changed/)).toBeVisible()
  } finally {
    vi.useRealTimers()
  }
})
it('unlocks an uncertain request only after a matching confirmed broker receipt', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  vi.useFakeTimers()
  try {
    let requestId = ''
    vi.mocked(deltaChartApi.action).mockImplementation(async (body) => {
      requestId = body.request_id
      throw new Error('timeout')
    })
    render(<DeltaTradePanel enabled symbol="BTCUSD" />)
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
      await Promise.resolve()
    })
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
    vi.mocked(deltaChartApi.state).mockResolvedValue(
      snapshot({
        position: null,
        receipts: [{ request_id: requestId, status: 'confirmed', message: 'Broker accepted' }],
      })
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.getByRole('button', { name: 'Place Long' })).toBeEnabled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText(/Broker accepted/)).toBeVisible()
    expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
  } finally {
    vi.useRealTimers()
  }
})
it('renders connection controls for a minimal disconnected response', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue({
    connected: false,
    environment: 'india_prod',
    symbol: 'BTCUSD',
    message: 'Connect Delta',
  } as DeltaChartState)
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Disconnected')
  expect(screen.getByLabelText('Delta API key')).toBeVisible()
  expect(screen.getByLabelText('Leverage')).toHaveValue('5')
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
})
it('fails closed when a connected snapshot lacks product metadata', async () => {
  const state = snapshot()
  delete (state as Partial<DeltaChartState>).product
  vi.mocked(deltaChartApi.state).mockResolvedValue(state)
  const onState = vi.fn()
  render(<DeltaTradePanel enabled symbol="BTCUSD" onState={onState} />)
  await screen.findByText('Trading paused.')
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(onState).toHaveBeenLastCalledWith(null)
})
it('disables close and protection when the broker position lacks a version', async () => {
  const position = snapshot().position!
  delete (position as Partial<typeof position>).version
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Close position' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Stop price'), { target: { value: '68000' } })
  fireEvent.change(screen.getByLabelText('Target price'), { target: { value: '72000' } })
  expect(screen.getByRole('button', { name: 'Add market SL' })).toBeDisabled()
})
it('allows reviewing an edit and a close while protective trigger orders are pending', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      orders: [
        {
          id: 'stop-1',
          side: 'sell',
          size: 2,
          unfilled: 2,
          type: 'limit_order',
          kind: 'sl',
          price: 68000,
          post_only: true,
          reduce_only: true,
          state: 'pending',
          version: 'v1',
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Close position' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Edit stop-1' }))
  fireEvent.change(screen.getByLabelText('Order price'), { target: { value: '68500' } })
  fireEvent.click(screen.getByRole('button', { name: 'Review price edit' }))
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent('68,500')
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  fireEvent.click(screen.getByRole('button', { name: 'Close position' }))
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent('close')
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('shows broker update time, current leverage and the chart drag hint', async () => {
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(
    screen.getByText(/Updated .*broker leverage 20×.*account polling ~2s after each response/)
  ).toBeVisible()
  expect(screen.getByText('Drag an order line to review a price change.')).toBeVisible()
})
it.each([
  {},
  [null],
  [{ id: 'bad', state: 'open' }],
])('fails closed for malformed broker orders %j', async (orders) => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({ orders: orders as DeltaChartState['orders'] })
  )
  const onState = vi.fn()
  render(<DeltaTradePanel enabled symbol="BTCUSD" onState={onState} />)
  await screen.findByText('Trading paused.')
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(onState).toHaveBeenLastCalledWith(null)
})

it('restores an uncertain request lock after actual unmount and remount', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  vi.mocked(deltaChartApi.action).mockRejectedValue(new Error('timeout'))
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
    await Promise.resolve()
  })
  await screen.findByText(/Outcome unknown/)
  view.unmount()
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Pending broker outcome')
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
})
it('persists only minimal intent before awaiting transport and clears a matching acknowledgement', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  let finish!: (result: { status: 'confirmed'; message: string; request_id: string }) => void
  vi.mocked(deltaChartApi.action).mockImplementation((body) => {
    const intent = JSON.parse(
      sessionStorage.getItem('delta-chart:intent:v1:account-a:BTCUSD') || 'null'
    )
    expect(intent).toEqual({
      request_id: body.request_id,
      symbol: 'BTCUSD',
      account: 'account-a',
      action: 'entry',
    })
    return new Promise((resolve) => {
      finish = resolve
    })
  })
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
    await Promise.resolve()
  })
  const saved = JSON.parse(
    sessionStorage.getItem('delta-chart:intent:v1:account-a:BTCUSD') || 'null'
  )
  expect(saved).toEqual({
    request_id: expect.any(String),
    symbol: 'BTCUSD',
    account: 'account-a',
    action: 'entry',
  })
  view.unmount()
  await act(async () => {
    finish({ status: 'confirmed', message: 'Accepted', request_id: saved.request_id })
    await Promise.resolve()
  })
  expect(sessionStorage.getItem('delta-chart:intent:v1:account-a:BTCUSD')).toBeNull()
})
it('does not send when intent persistence fails', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('storage unavailable')
  })
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  await screen.findByText(/Cannot safely record/)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('keeps another account intent despite a receipt with the same request id', async () => {
  const key = 'delta-chart:intent:v1:account-a:BTCUSD'
  const intent = { request_id: 'old-rid', symbol: 'BTCUSD', account: 'account-a' }
  sessionStorage.setItem(key, JSON.stringify(intent))
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      account: 'account-b',
      receipts: [{ request_id: 'old-rid', status: 'confirmed', message: 'Other account' }],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual(intent)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('clears persisted intent after a matching rejected receipt without resubmitting', async () => {
  const key = 'delta-chart:intent:v1:account-a:BTCUSD'
  sessionStorage.setItem(
    key,
    JSON.stringify({ request_id: 'old-rid', symbol: 'BTCUSD', account: 'account-a' })
  )
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      receipts: [{ request_id: 'old-rid', status: 'rejected', message: 'Rejected by broker' }],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText(/Rejected by broker/)
  expect(sessionStorage.getItem(key)).toBeNull()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeEnabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('reviews a market long exit and market short exit without a limit price', async () => {
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Close position' }))
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent(
    'Market exit · taker fees and slippage apply'
  )
  fireEvent.click(screen.getByRole('button', { name: 'Send live order' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'close',
        side: 'sell',
        order_type: 'market_order',
      })
    )
  )
  view.unmount()
  const pos = snapshot().position!
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: { ...pos, size: -2 } }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Close position' }))
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent(
    'Market exit · taker fees and slippage apply'
  )
})

it('adds maker target separately and explains market stop slippage', async () => {
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(
    screen.getByText('Triggered SL exits at market; taker fees and slippage apply.')
  ).toBeVisible()
  fireEvent.change(screen.getByLabelText('Target price'), { target: { value: '72000' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add maker target' }))
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Send live order' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'protect', target: 72000, position_version: 'position-v1' })
    )
  )
  expect(vi.mocked(deltaChartApi.action).mock.calls[0][0]).not.toHaveProperty('stop')
})

it('allows market closes without a quote while disabling arbitrary market order price edits', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      ticker: { mark: 70000, last: 70000, bid: null, ask: null },
      orders: [
        {
          id: 'old-market',
          side: 'buy',
          size: 1,
          unfilled: 1,
          type: 'market_order',
          kind: 'entry',
          price: 70000,
          reduce_only: true,
          post_only: false,
          state: 'open',
          version: 'v1',
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Close position' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Edit old-market' })).toBeDisabled()
  expect(screen.getByText(/exit.*market \/ taker/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Close position' })).toBeEnabled()
})
it('updates fee-aware balance quantities from percentage, leverage, price and balance without submitting', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      sizing: {
        available_balance: 100,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 's1',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(
    Math.floor(99 / (70000.5 * 0.001 * (1 / 5 + 0.0002 * 1.18)))
  )
  expect(screen.getByLabelText('Leverage')).toHaveValue('5')
  for (const percent of [25, 50, 75, 100]) {
    fireEvent.click(screen.getByRole('button', { name: `${percent}%` }))
    expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(
      Math.floor(((percent / 100) * 100 * 0.99) / (70000.5 * 0.001 * (1 / 5 + 0.0002 * 1.18)))
    )
  }
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '10' } })
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(
    Math.floor((100 * 0.99) / (70000.5 * 0.001 * (1 / 10 + 0.0002 * 1.18)))
  )
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(
    Math.floor((100 * 0.99) / (70000.5 * 0.001 * (1 / 10 + 0.0002 * 1.18)))
  )
  fireEvent.change(screen.getByLabelText('Quantity (lots)'), { target: { value: '2' } })
  expect(screen.getByRole('button', { name: '100%' })).toHaveAttribute('aria-pressed', 'false')
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '5' } })
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(2)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('keeps insufficient percentage quantity at zero and rejects it on click', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      sizing: {
        available_balance: 0.01,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 's1',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: '100%' }))
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(0)
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Order not sent:')
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  expect(screen.getByText('Balance too small at this leverage')).toBeVisible()
})

it('presents a single selected-side action, locked maker GTC, margin and fee-inclusive funds', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      leverage: 50,
      sizing: {
        available_balance: 100,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 's1',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Leverage')).toHaveValue('5')
  expect(screen.queryByRole('button', { name: 'Long', exact: true })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Place Short' })).not.toBeInTheDocument()
  expect(screen.getByText('GTC')).toBeVisible()
  expect(screen.getByText(/Available margin: USD 100/)).toBeVisible()
  expect(screen.getByText(/Funds required: USD 98.1163/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '10%' }))
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(0)
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('disables balance buttons when the broker snapshot becomes stale', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      asof: Date.now() / 1000 - 11,
      sizing: {
        available_balance: 100,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 's1',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText(/Stale broker data/)
  expect(screen.getByRole('button', { name: '25%' })).toBeDisabled()
})
it('shows live Delta wallet, P&L and fee estimates without subtracting fees from balance twice', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      accounting: {
        currency: 'USD',
        balance: 100,
        available_balance: 80,
        position_gross_pnl: 2,
        position_entry_fees: 0.2,
        estimated_maker_exit_fee: 0.3,
        estimated_exit_fee: 0.3,
        exit_fee_basis: 'taker' as const,
        position_net_after_fees: 1.5,
        fee_status: 'verified',
        message: 'Net excludes funding and realized results.',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByText('Balance').parentElement).toHaveTextContent('USD 100')
  expect(screen.getByText('Balance').parentElement).toHaveTextContent('₹8,500.00')
  expect(screen.getByText('Available').parentElement).toHaveTextContent('USD 80')
  expect(screen.getByText('Live P&L (before fees)').parentElement).toHaveTextContent('₹170.00')
  expect(screen.getByText('Entry fees paid').parentElement).toHaveTextContent('₹17.00')
  expect(screen.getByText('Est. closing fees (taker)').parentElement).toHaveTextContent('₹25.50')
  expect(screen.getByText('Est. net P&L after fees').parentElement).toHaveTextContent('₹127.50')
  expect(screen.getByText('₹127.50')).toHaveClass('text-emerald-500')
  expect(
    screen.getByText(
      'Fees include GST. Paid entry fees stay fixed until another fill. Closing fee varies with mark; actual cost is known after exit. Balance already reflects charged fees.'
    )
  ).toBeVisible()
  expect(screen.getByText('Fixed conversion $1 = ₹85')).toBeVisible()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('keeps unverifiable fees and net unavailable and colors verified negative net red', async () => {
  const accounting = {
    currency: 'USD',
    balance: 50,
    available_balance: 40,
    position_gross_pnl: -2,
    position_entry_fees: null,
    estimated_maker_exit_fee: 0.3,
    estimated_exit_fee: 0.3,
    exit_fee_basis: 'taker' as const,
    position_net_after_fees: 99,
    fee_status: 'incomplete' as const,
    message: 'Entry fees are not verified.',
  }
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ accounting }))
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByText('Entry fees paid').parentElement).toHaveTextContent('—')
  expect(screen.getByText('Est. net P&L after fees').parentElement).toHaveTextContent('—')
  expect(screen.queryByText('₹8,415.00')).not.toBeInTheDocument()
  expect(screen.getByText('Entry fees are not verified.')).toBeVisible()
  view.unmount()
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      accounting: {
        ...accounting,
        position_entry_fees: 0.2,
        position_net_after_fees: -2.5,
        fee_status: 'verified',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByText('-₹212.50')).toHaveClass('text-rose-500')
})
it('clears the live account summary when the chart is disabled or its snapshot is stale', async () => {
  const accounting = {
    currency: 'USD',
    balance: 100,
    available_balance: 80,
    position_gross_pnl: 2,
    position_entry_fees: 0,
    estimated_maker_exit_fee: 0.3,
    estimated_exit_fee: 0.3,
    exit_fee_basis: 'taker' as const,
    position_net_after_fees: 1.7,
    fee_status: 'verified' as const,
    message: 'Verified.',
  }
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ accounting }))
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('region', { name: 'Delta account summary' })).toBeVisible()
  expect(screen.getByText('Entry fees paid').parentElement).toHaveTextContent('₹0.00')
  view.rerender(<DeltaTradePanel enabled={false} symbol="BTCUSD" />)
  expect(screen.queryByRole('region', { name: 'Delta account summary' })).not.toBeInTheDocument()
  view.unmount()
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({ accounting, asof: Date.now() / 1000 - 11 })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText(/Stale broker data/)
  expect(screen.queryByRole('region', { name: 'Delta account summary' })).not.toBeInTheDocument()
})
it('shows broker-provided flat-position zeros without claiming historical fees are zero', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      accounting: {
        currency: 'USD',
        balance: 100,
        available_balance: 80,
        position_gross_pnl: 0,
        position_entry_fees: 0,
        estimated_maker_exit_fee: 0,
        estimated_exit_fee: 0,
        exit_fee_basis: 'taker',
        position_net_after_fees: 0,
        fee_status: 'flat',
        message: 'Zero position costs do not represent historical trading fees.',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByText('No open position')).toBeVisible()
  for (const label of [
    'Live P&L (before fees)',
    'Entry fees paid',
    'Est. closing fees (taker)',
    'Est. net P&L after fees',
  ])
    expect(screen.getByText(label).parentElement).toHaveTextContent('₹0.00')
  expect(
    screen.getByText('Zero position costs do not represent historical trading fees.')
  ).toBeVisible()
  expect(screen.getByText('Balance').parentElement).toHaveTextContent('USD 100')
  expect(screen.getByText('Balance').parentElement).toHaveTextContent('₹8,500.00')
})
it('keeps missing flat metrics unavailable and displays zero selected coin quantity', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      accounting: {
        currency: 'USD',
        balance: 100,
        available_balance: 80,
        position_gross_pnl: null,
        position_entry_fees: null,
        estimated_maker_exit_fee: null,
        estimated_exit_fee: null,
        exit_fee_basis: 'taker',
        position_net_after_fees: null,
        fee_status: 'flat',
        message: '',
      },
      sizing: {
        available_balance: 0.01,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 's1',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByText('Entry fees paid').parentElement).toHaveTextContent('—')
  expect(screen.getByText('Est. net P&L after fees').parentElement).toHaveTextContent('—')
  fireEvent.click(screen.getByRole('button', { name: '100%' }))
  expect(screen.getByText('1 lot = 0.001 BTC · selected total 0 BTC')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeEnabled()
})
const managedRisk = () => {
  const now = Date.now() / 1000
  const end = Math.floor(now / 60) * 60 - 60
  return {
    symbol: 'BTCUSD',
    intervalSeconds: 60,
    sourceTime: end,
    observedAt: now,
    direction: 'up' as const,
    bars: Array.from({ length: 15 }, (_, i) => ({
      time: end - (14 - i) * 60,
      open: 70000,
      high: 70002,
      low: 69998,
      close: 70000,
      volume: 1,
    })),
    support: null,
    resistance: null,
  }
}
it('defaults managed entry on, previews protection and submits only its explicitly reviewed plan', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByText('Required SL / target from chart trend')).toBeVisible()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.getByText(/Automatic checks while this live chart is open/)).toBeVisible()
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledWith(
    expect.objectContaining({ auto_protection: expect.any(Object) })
  )
})
it('explains a paused entry when the quote has moved beyond the last confirmed candle', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({ position: null, ticker: { mark: 70010, last: 70010, bid: 70010, ask: 70011 } })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByText(/Price moved too far from the last confirmed candle/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Order not sent:')
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('requires protection for real charts and offers no manual opt-out when the plan is unavailable', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={null} />)
  await screen.findByText('Live · India')
  expect(screen.getByText('Required SL / target from chart trend')).toBeVisible()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Waiting for trend' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Waiting for trend' })).toBeDisabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('keeps an obvious close action visible when flat and reviews a market close when active', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const flat = render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Close position' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Close position' })).toBeDisabled()
  flat.unmount()
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot())
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  const close = screen.getByRole('button', { name: 'Close position' })
  expect(close).toBeEnabled()
  fireEvent.click(close)
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent(
    'Market exit · taker fees and slippage apply'
  )
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('shows an explicit pause when a managed plan belongs to a different chart interval', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      managed_plans: [
        {
          id: 'p1',
          status: 'active',
          message: 'Protected',
          side: 'buy',
          entry_order_id: 'entry1',
          entry_price: 69000,
          initial_stop: 68000,
          stop: 68000,
          target: 72000,
          source_time: managedRisk().sourceTime,
          interval_seconds: 300,
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByText(/return to the plan's chart interval/)).toBeVisible()
  expect(deltaChartApi.manage).not.toHaveBeenCalled()
})
it('opens the same explicit close review once for a chart close proposal', async () => {
  const handled = vi.fn()
  const view = render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      closeProposal={null}
      onCloseProposalHandled={handled}
    />
  )
  await screen.findByText('Live · India')
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      closeProposal={{ nonce: 7 }}
      onCloseProposalHandled={handled}
    />
  )
  await screen.findByRole('dialog', { name: 'Review live order' })
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent('close')
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  expect(handled).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      closeProposal={{ nonce: 7 }}
      onCloseProposalHandled={handled}
    />
  )
  expect(screen.queryByRole('dialog', { name: 'Review live order' })).not.toBeInTheDocument()
  expect(handled).toHaveBeenCalledTimes(1)
})
it('defers a chart edit proposal until live action checks are ready and consumes it once', async () => {
  let finish!: (state: DeltaChartState) => void
  vi.mocked(deltaChartApi.state).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const handled = vi.fn()
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      editProposal={{ order_id: 'sl1', price: 68500, nonce: 99 }}
      onProposalHandled={handled}
    />
  )
  expect(screen.queryByRole('dialog', { name: 'Review live order' })).not.toBeInTheDocument()
  await act(async () => {
    finish(
      snapshot({
        orders: [
          {
            id: 'sl1',
            side: 'sell',
            size: 2,
            unfilled: 2,
            type: 'limit_order',
            kind: 'sl',
            price: 68000,
            post_only: true,
            reduce_only: true,
            state: 'pending',
            version: 'v1',
          },
        ],
      })
    )
    await Promise.resolve()
  })
  await screen.findByRole('dialog', { name: 'Review live order' })
  expect(handled).toHaveBeenCalledTimes(1)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('reviews adoption of an existing position without a new entry and preserves its tighter old SL', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      orders: [
        {
          id: 'old-sl',
          side: 'sell',
          size: 2,
          unfilled: 2,
          type: 'market_order',
          kind: 'sl',
          price: 69997,
          post_only: false,
          reduce_only: true,
          state: 'pending',
          version: 'old-v1',
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Review automatic SL for this position' }))
  const dialog = screen.getByRole('dialog', { name: 'Review live order' })
  expect(dialog).toHaveTextContent('69,997')
  expect(dialog).toHaveTextContent(
    'Existing SL stays active until the full-size market SL replacement is acknowledged.'
  )
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Register automatic protection' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'adopt',
        position_version: 'position-v1',
        auto_protection: expect.objectContaining({ stop: 69997 }),
        existing_stop: { id: 'old-sl', version: 'old-v1' },
        existing_target: null,
      })
    )
  )
  expect(vi.mocked(deltaChartApi.action).mock.calls[0][0]).not.toHaveProperty('size')
})
it('invalidates adoption if the reviewed existing SL version changes', async () => {
  vi.useFakeTimers()
  try {
    const stop = {
      id: 'old-sl',
      side: 'sell' as const,
      size: 2,
      unfilled: 2,
      type: 'market_order' as const,
      kind: 'sl' as const,
      price: 69997,
      post_only: false,
      reduce_only: true,
      state: 'pending',
      version: 'v1',
    }
    vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ orders: [stop] }))
    const risk = managedRisk()
    render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
    await act(async () => {
      await Promise.resolve()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Review automatic SL for this position' }))
    vi.mocked(deltaChartApi.state).mockResolvedValue(
      snapshot({ orders: [{ ...stop, version: 'v2' }] })
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Register automatic protection' }))
    expect(deltaChartApi.action).not.toHaveBeenCalled()
    expect(screen.getByText(/Position or existing protection changed/)).toBeVisible()
  } finally {
    vi.useRealTimers()
  }
})
it('starts the countdown immediately only after a confirmed new entry acknowledgement', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
    await Promise.resolve()
  })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled())
})
it('initializes the countdown from the latest broker placement instead of restarting after reload', async () => {
  const placed = Date.now() / 1000 - 300
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      managed_plans: [
        {
          id: 'entry-plan',
          status: 'active',
          message: 'Protected',
          side: 'buy',
          entry_order_id: 'broker-entry',
          entry_request_id: 'entry-rid',
          placed_at: placed,
          entry_price: 69000,
          initial_stop: 68000,
          stop: 68000,
          target: 72000,
          source_time: managedRisk().sourceTime,
          interval_seconds: 60,
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('timer')).toHaveTextContent('25:00')
  expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled()
})
it('does not start the countdown for confirmed close acknowledgements', async () => {
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Close position' }))
  fireEvent.click(screen.getByRole('button', { name: 'Send live order' }))
  await screen.findByText(/Broker accepted/)
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
})

it.each([
  'blocked',
  'active',
  'pending',
] as const)('allows reviewed protection recovery only for blocked plans, not %s ownership', async (status) => {
  vi.mocked(deltaChartApi.manage).mockResolvedValue({
    status: 'confirmed',
    message: 'Checked',
    plan_id: 'prior-plan',
    plan_status: status,
  })
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      managed_plans: [
        {
          id: 'prior-plan',
          status,
          message: 'Broker protection changed',
          side: 'buy',
          entry_order_id: 'prior-entry',
          entry_price: 69000,
          initial_stop: 68000,
          stop: 68000,
          target: 72000,
          source_time: managedRisk().sourceTime,
          interval_seconds: 60,
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  if (status === 'blocked') {
    const review = screen.getByRole('button', { name: 'Review updated position protection' })
    expect(review).toBeEnabled()
    expect(
      screen.getByText('The broker protection changed. Review it again to resume automatic checks.')
    ).toBeVisible()
    fireEvent.click(review)
    expect(screen.getByRole('dialog', { name: 'Review live order' })).toHaveTextContent('adopt')
  } else {
    expect(
      screen.getByRole('button', { name: 'Review automatic SL for this position' })
    ).toBeDisabled()
  }
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('explains pending entry and keeps the automatic entry action blocked without a broker mutation', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      pending: [{ request_id: 'waiting', action: 'entry', message: 'Reconciling' }],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(
    screen.getByText('Entry paused: a broker request is pending reconciliation.')
  ).toBeVisible()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Short', exact: true })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('explains an existing managed-chart position while keeping close available', async () => {
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(
    screen.getByText('Entry paused: close the existing position before opening a new entry.')
  ).toBeVisible()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Close position' })).toBeEnabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('explains resting orders blocking a managed-chart entry', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      orders: [
        {
          id: 'entry1',
          side: 'buy',
          size: 1,
          unfilled: 1,
          type: 'limit_order',
          kind: 'entry',
          price: 69000,
          reduce_only: false,
          post_only: true,
          state: 'open',
          version: 'v1',
        },
      ],
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(
    screen.getByText('Entry paused: cancel existing open orders before opening a new entry.')
  ).toBeVisible()
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeDisabled()
})

it('reveals and focuses a chart close review during pending reconciliation without sending', async () => {
  const handled = vi.fn()
  const scrollIntoView = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scrollIntoView,
  })
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({ pending: [{ request_id: 'pending', action: 'entry', message: 'Reconciling' }] })
  )
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" onCloseProposalHandled={handled} />)
  await screen.findByText('Live · India')
  const panel = screen.getByLabelText('Delta live trading')
  panel.removeAttribute('open')
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      closeProposal={{ nonce: 99 }}
      onCloseProposalHandled={handled}
    />
  )
  const dialog = await screen.findByRole('dialog', { name: 'Review live order' })
  expect(dialog).toHaveFocus()
  expect(panel).toHaveAttribute('open')
  expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
  expect(screen.getByRole('button', { name: 'Send live order' })).toBeDisabled()
  expect(
    screen.getByText('Submission paused: a broker request is pending reconciliation.')
  ).toBeVisible()
  expect(handled).toHaveBeenCalledTimes(1)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('opens a chart close review while an automatic broker check is still in flight', async () => {
  vi.mocked(deltaChartApi.manage).mockImplementation(() => new Promise(() => {}))
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      managed_plans: [
        {
          id: 'owned',
          status: 'active',
          message: 'Protected',
          side: 'buy',
          entry_order_id: 'entry1',
          entry_price: 69000,
          initial_stop: 68000,
          stop: 68000,
          target: 72000,
          source_time: managedRisk().sourceTime,
          interval_seconds: 60,
        },
      ],
    })
  )
  const risk = managedRisk(),
    handled = vi.fn()
  const view = render(
    <DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} onCloseProposalHandled={handled} />
  )
  await waitFor(() => expect(deltaChartApi.manage).toHaveBeenCalledTimes(1))
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={risk}
      closeProposal={{ nonce: 101 }}
      onCloseProposalHandled={handled}
    />
  )
  expect(await screen.findByRole('dialog', { name: 'Review live order' })).toHaveFocus()
  expect(
    screen.getByText('Submission paused: automatic protection is being checked with the broker.')
  ).toBeVisible()
  expect(screen.getByRole('button', { name: 'Send live order' })).toBeDisabled()
  expect(handled).toHaveBeenCalledTimes(1)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('permits a reviewed market SL trigger edit but never submits a chart drag automatically', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      orders: [
        {
          id: 'market-sl',
          side: 'sell',
          size: 2,
          unfilled: 2,
          type: 'market_order',
          kind: 'sl',
          price: 68000,
          reduce_only: true,
          post_only: false,
          state: 'pending',
          version: 'sl-v1',
        },
      ],
    })
  )
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      editProposal={{ order_id: 'market-sl', price: 68500, nonce: 999 }}
    />
  )
  const dialog = await screen.findByRole('dialog', { name: 'Review live order' })
  expect(dialog).toHaveTextContent('Market SL · taker fees and slippage apply')
  expect(screen.getByRole('button', { name: 'Edit market-sl' })).toBeEnabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Send live order' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'edit',
        order_id: 'market-sl',
        price: 68500,
        version: 'sl-v1',
      })
    )
  )
})

it('shows the taker exit fee estimate instead of the legacy maker fee estimate', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      accounting: {
        currency: 'USD',
        balance: 100,
        available_balance: 80,
        position_gross_pnl: 4,
        position_entry_fees: 0.5,
        estimated_maker_exit_fee: 0.1,
        estimated_exit_fee: 1,
        exit_fee_basis: 'taker',
        position_net_after_fees: 2.5,
        fee_status: 'verified',
        message: '',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByText('Est. closing fees (taker)').parentElement).toHaveTextContent('₹85.00')
  expect(screen.getByText('Est. net P&L after fees').parentElement).toHaveTextContent('₹212.50')
})

it.each([
  'missing',
  'wrong-basis',
] as const)('keeps market net P&L unknown with %s exit fee evidence', async (mode) => {
  const accounting: NonNullable<DeltaChartState['accounting']> = {
    currency: 'USD',
    balance: 100,
    available_balance: 80,
    position_gross_pnl: 4,
    position_entry_fees: 0.5,
    estimated_maker_exit_fee: 0.1,
    position_net_after_fees: 3.4,
    fee_status: 'verified',
    message: '',
  }
  if (mode === 'wrong-basis') {
    accounting.estimated_exit_fee = 0.1
    accounting.exit_fee_basis = 'maker'
  }
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ accounting }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  expect(screen.getByText('Est. net P&L after fees').parentElement).toHaveTextContent('—')
})

it('places a one-click managed entry using a fresh best bid and attached protection', async () => {
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(snapshot({ position: null }))
    .mockResolvedValue(
      snapshot({ position: null, ticker: { mark: 70000, last: 70000, bid: 69999, ask: 70001 } })
    )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'entry',
        side: 'buy',
        order_type: 'limit_order',
        price: 69999,
        leverage: 5,
        auto_protection: expect.objectContaining({
          stop: expect.any(Number),
          target: expect.any(Number),
        }),
      })
    )
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(deltaChartApi.state).toHaveBeenCalledTimes(2)
})
it.each([
  'account',
  'position',
  'quote',
  'stale',
  'error',
  'tick',
  'cap',
  'funds',
  'orders',
  'trend',
  'metadata',
] as const)('stops one-click entry on fresh preflight %s failure', async (failure) => {
  vi.mocked(deltaChartApi.state).mockResolvedValueOnce(snapshot({ position: null }))
  const fresh = snapshot({ position: null })
  if (failure === 'account') fresh.account = 'another-account'
  if (failure === 'position') fresh.position = snapshot().position
  if (failure === 'quote') fresh.ticker.bid = null
  if (failure === 'stale') fresh.asof -= 20
  if (failure === 'tick') fresh.ticker.bid = 69999.6
  if (failure === 'cap') fresh.product.max_leverage = 1
  if (failure === 'metadata') fresh.product.tick_size = NaN
  if (failure === 'funds')
    fresh.sizing = {
      available_balance: 1,
      currency: 'USD',
      maker_fee_rate: 0.0002,
      fee_tax_rate: 0.18,
      version: 's1',
    }
  if (failure === 'orders')
    fresh.orders = [
      {
        id: 'resting',
        side: 'buy',
        size: 1,
        unfilled: 1,
        type: 'limit_order',
        kind: 'entry',
        price: 69000,
        post_only: true,
        reduce_only: false,
        state: 'open',
        version: 'v1',
      },
    ]
  if (failure === 'trend') fresh.ticker.bid = 70010
  if (failure === 'error') vi.mocked(deltaChartApi.state).mockRejectedValue(new Error('offline'))
  else vi.mocked(deltaChartApi.state).mockResolvedValue(fresh)
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  const feedback = await screen.findByRole('alert')
  expect(feedback).toHaveTextContent(/Order not sent:/)
  await waitFor(() => expect(feedback).toHaveFocus())
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('locks a double click before entry preflight and never retries an unknown outcome', async () => {
  let finish!: (state: DeltaChartState) => void
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(snapshot({ position: null }))
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
  vi.mocked(deltaChartApi.action).mockRejectedValue(new Error('timeout'))
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  const place = screen.getByRole('button', { name: 'Place Long' })
  fireEvent.click(place)
  fireEvent.click(place)
  expect(deltaChartApi.state).toHaveBeenCalledTimes(2)
  await act(async () => {
    finish(snapshot({ position: null }))
    await Promise.resolve()
  })
  await screen.findByText(/Outcome unknown/)
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
})

it.each([
  'unmount',
  'disabled',
  'symbol',
  'away-back',
] as const)('never submits if chart scope is %s during entry preflight', async (change) => {
  let finish!: (state: DeltaChartState) => void
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(snapshot({ position: null }))
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
  const risk = managedRisk()
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  const pendingPreflight = finish
  if (change === 'unmount') {
    view.unmount()
    render(<DeltaTradePanel enabled symbol="ETHUSD" riskContext={risk} />)
  } else if (change === 'disabled')
    view.rerender(<DeltaTradePanel enabled={false} symbol="BTCUSD" riskContext={risk} />)
  else {
    view.rerender(<DeltaTradePanel enabled symbol="ETHUSD" riskContext={risk} />)
    if (change === 'away-back')
      view.rerender(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  }
  await act(async () => {
    pendingPreflight(snapshot({ position: null }))
    await Promise.resolve()
  })
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  expect(sessionStorage.getItem('delta-chart:intent:v1:account-a:BTCUSD')).toBeNull()
})
it('captures side, whole lots and leverage at click while refreshing the best quote', async () => {
  let finish!: (state: DeltaChartState) => void
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(
      snapshot({
        position: null,
        sizing: {
          available_balance: 100,
          currency: 'USD',
          maker_fee_rate: 0.0002,
          fee_tax_rate: 0.18,
          version: 'manual-capture',
        },
      })
    )
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Leverage')).toHaveValue('5')
  expect(screen.getByText('One click checks, then places or shows an error.')).toBeVisible()
  fireEvent.change(screen.getByLabelText('Quantity (lots)'), { target: { value: '3' } })
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '10' } })
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  expect(screen.getByRole('button', { name: 'Checking / placing…' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Quantity (lots)'), { target: { value: '5' } })
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '20' } })
  await act(async () => {
    finish(
      snapshot({
        position: null,
        sizing: {
          available_balance: 100,
          currency: 'USD',
          maker_fee_rate: 0.0002,
          fee_tax_rate: 0.18,
          version: 'manual-capture',
        },
      })
    )
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledWith(
    expect.objectContaining({ side: 'buy', size: 3, leverage: 10, price: 69999.5 })
  )
})
it('recalculates the selected balance fraction using fresh margin, fees and sizing version', async () => {
  const sizing = {
    available_balance: 100,
    currency: 'USD',
    maker_fee_rate: 0.0002,
    fee_tax_rate: 0.18,
    version: 's1',
  }
  const initial = snapshot({ position: null, sizing })
  const fresh = snapshot({
    position: null,
    sizing: { ...sizing, available_balance: 200, version: 's2' },
  })
  vi.mocked(deltaChartApi.state).mockResolvedValueOnce(initial).mockResolvedValue(fresh)
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: '50%' }))
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        balance_fraction: 0.5,
        sizing_version: 's2',
        size: Math.floor((0.5 * 200 * 0.99) / (70000.5 * 0.001 * (1 / 5 + 0.0002 * 1.18))),
      })
    )
  )
})
it('places Short at the freshly fetched best offer with a downtrend market SL plan', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'down' }}
    />
  )
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Place Short' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        side: 'sell',
        order_type: 'limit_order',
        price: 70000.5,
        auto_protection: expect.any(Object),
      })
    )
  )
})
it('stops if the closed-candle direction changes during entry preflight', async () => {
  let finish!: (state: DeltaChartState) => void
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(snapshot({ position: null }))
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
  const risk = managedRisk()
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  view.rerender(
    <DeltaTradePanel enabled symbol="BTCUSD" riskContext={{ ...risk, direction: 'down' }} />
  )
  await act(async () => {
    finish(snapshot({ position: null }))
    await Promise.resolve()
  })
  expect(screen.getByText(/Order not sent:/)).toBeVisible()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('automatically waits on an unconfirmed direction without needing a check button', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'sideways' }}
    />
  )
  await screen.findByText('Live · India')
  const place = screen.getByRole('button', { name: 'Waiting for trend' })
  expect(place).toBeDisabled()
  expect(deltaChartApi.state).toHaveBeenCalledTimes(1)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('rejects a directional 1m entry when higher confirmation is missing, without sending an order', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'up', entryAligned: false }}
    />
  )
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Entry pause reason')).toHaveTextContent('two chart timeframes')
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('timeframes')
  expect(deltaChartApi.state).toHaveBeenCalledTimes(2)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('respects a manual 5x selection even when low balance defaults to 50x', async () => {
  localStorage.removeItem('neo.delta.trade.defaults')
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      sizing: {
        available_balance: 7.25031016,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 'balance-check',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Leverage')).toHaveValue('50')
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '5' } })
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(0)
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('cannot fund the selected whole lots')
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('does not treat a 100-point move after the confirmed candle as entry confirmation', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({ position: null, ticker: { mark: 70100, last: 70100, bid: 70100, ask: 70100.5 } })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Price moved too far from the last confirmed candle'
  )
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('places a 2R reviewed target without shortening it at nearby resistance', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), resistance: 70004 }}
    />
  )
  await screen.findByText('Live · India')
  expect(screen.queryByLabelText('Entry pause reason')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        auto_protection: expect.objectContaining({ stop: 69993.5, target: 70011.5 }),
      })
    )
  )
})

it('selects the confirmed trend automatically and updates direction when the trend changes', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const view = render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'down' }}
    />
  )
  await screen.findByText('Live · India')
  expect(screen.queryByRole('button', { name: 'Short', exact: true })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Place Short' })).toBeEnabled()
  view.rerender(
    <DeltaTradePanel enabled symbol="BTCUSD" riskContext={{ ...managedRisk(), direction: 'up' }} />
  )
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeEnabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('defaults to 100% balance sizing and recalculates lots immediately with leverage', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      sizing: {
        available_balance: 100,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 'default100',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: '100%' })).toHaveAttribute('aria-pressed', 'true')
  const expected = (leverage: number) =>
    Math.floor(99 / (70000.5 * 0.001 * (1 / leverage + 0.0002 * 1.18)))
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(expected(5))
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '10' } })
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(expected(10))
  expect(screen.getByRole('button', { name: 'Place Long' })).toBeEnabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('defaults low verified balance to 50x and 100% affordable lots without sending', async () => {
  localStorage.removeItem('neo.delta.trade.defaults')
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      position: null,
      ticker: { mark: 78000, last: 78000, bid: 77999.5, ask: 78000 },
      sizing: {
        available_balance: 7.25,
        currency: 'USD',
        maker_fee_rate: 0.0002,
        fee_tax_rate: 0.18,
        version: 'low-balance',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Leverage')).toHaveValue('50')
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(4)
  expect(screen.getByRole('button', { name: '100%' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '25' } })
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(2)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('uses one automatic entry button, no Long/Short selector, and a check action for an unconfirmed trend', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const view = render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'down' }}
    />
  )
  await screen.findByText('Live · India')
  expect(screen.queryByRole('button', { name: 'Long', exact: true })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Short', exact: true })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Place Short' })).toBeEnabled()
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'sideways' }}
    />
  )
  expect(screen.getByRole('button', { name: 'Waiting for trend' })).toBeDisabled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('keeps auto trading off by default, then sends one protected entry per eligible candle', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const risk = managedRisk()
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledTimes(1))
  expect(deltaChartApi.action).toHaveBeenCalledWith(
    expect.objectContaining({ action: 'entry', side: 'buy', auto_protection: expect.any(Object) })
  )
  expect(vi.mocked(deltaChartApi.action).mock.calls[0][0]).not.toHaveProperty('entry_mode')
  view.rerender(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={{ ...risk }} />)
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
})
it('automatically waits for confirmation and enters when the same closed-candle context becomes eligible', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const risk = managedRisk()
  const view = render(
    <DeltaTradePanel enabled symbol="BTCUSD" riskContext={{ ...risk, direction: 'sideways' }} />
  )
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  view.rerender(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledTimes(1))
})
it('stops an unsent automatic entry when toggled off during fresh preflight', async () => {
  let finish!: (state: DeltaChartState) => void
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(snapshot({ position: null }))
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await waitFor(() => expect(deltaChartApi.state).toHaveBeenCalledTimes(2))
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await act(async () => {
    finish(snapshot({ position: null }))
    await Promise.resolve()
  })
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
})
it('disarms automatic entries on a chart interval change', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const risk = { ...managedRisk(), direction: 'sideways' as const }
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeChecked()
  view.rerender(
    <DeltaTradePanel enabled symbol="BTCUSD" riskContext={{ ...risk, intervalSeconds: 300 }} />
  )
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('does not retry an uncertain automatic order and retains pending reconciliation', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  vi.mocked(deltaChartApi.action).mockRejectedValue(new Error('Network timeout'))
  const risk = managedRisk()
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await screen.findByText(/Outcome unknown/)
  view.rerender(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={{ ...risk }} />)
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText('Auto trading status')).toHaveTextContent(
    'Waiting for broker confirmation'
  )
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
})
it('recovers Auto after verified reconciliation without repeating the already-attempted candle', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const risk = managedRisk()
  const first = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledTimes(1))
  first.unmount()
  sessionStorage.clear()
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  await waitFor(() => expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeChecked())
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
})
it('can enter on a later eligible candle after the prior trade is flat, without repeating the old signal', async () => {
  const base = Date.now()
  vi.spyOn(Date, 'now').mockReturnValue(base)
  vi.mocked(deltaChartApi.state).mockImplementation(async () => snapshot({ position: null }))
  const risk = managedRisk()
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledTimes(1))
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Checking / placing…' })).not.toBeInTheDocument()
  )
  vi.mocked(Date.now).mockReturnValue(base + 60000)
  view.rerender(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledTimes(2))
  expect(vi.mocked(deltaChartApi.action).mock.calls[0][0].request_id).not.toBe(
    vi.mocked(deltaChartApi.action).mock.calls[1][0].request_id
  )
})

it('starts at 50x/100% without saved settings and saves editable leverage and fixed lots', async () => {
  localStorage.removeItem('neo.delta.trade.defaults')
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Leverage')).toHaveValue('50')
  expect(screen.getByRole('button', { name: '100%' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.change(screen.getByLabelText('Leverage'), { target: { value: '25' } })
  fireEvent.change(screen.getByLabelText('Quantity (lots)'), { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save defaults' }))
  expect(screen.getByLabelText('Trading defaults status')).toHaveTextContent('Defaults saved')
  view.unmount()
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  expect(screen.getByLabelText('Leverage')).toHaveValue('25')
  expect(screen.getByLabelText('Quantity (lots)')).toHaveValue(3)
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('stops automatic entries when manual close is requested, without removing protection or sending the close', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot())
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Close position' }))
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toBeVisible()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('turns Auto off if its candle tracking record is corrupt', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  localStorage.setItem('delta-chart:auto-entry:v1:account-a:BTCUSD:60', 'invalid-json')
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(screen.getByLabelText('Auto trading status')).toHaveTextContent(
    'safe request tracking is unavailable'
  )
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it.each([
  'blocked',
  'active',
  'completed',
] as const)('rejects automatic entry when a %s managed plan appears during fresh preflight', async (status) => {
  const risk = managedRisk()
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(snapshot({ position: null }))
    .mockResolvedValue(
      snapshot({
        position: null,
        managed_plans: [
          {
            id: 'new-plan',
            status,
            message: 'Newly observed',
            side: 'buy',
            entry_order_id: 'old-order',
            entry_price: 70000,
            initial_stop: 69990,
            stop: 69990,
            target: 70020,
            source_time: risk.sourceTime,
            interval_seconds: 60,
          },
        ],
      })
    )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Another managed trade exists or this candle already has a trade'
  )
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('revokes a pending automatic entry across tabs even before the storage event arrives', async () => {
  let finish!: (s: DeltaChartState) => void
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(snapshot({ position: null }))
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await waitFor(() => expect(deltaChartApi.state).toHaveBeenCalledTimes(2))
  localStorage.removeItem('delta-chart:auto-resume:v1:account-a:BTCUSD:60')
  await act(async () => {
    finish(snapshot({ position: null }))
    await Promise.resolve()
  })
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('allows OFF while saved Auto recovery waits for protection reconciliation', async () => {
  localStorage.setItem(
    'delta-chart:auto-resume:v1:account-a:BTCUSD:60',
    JSON.stringify({
      version: 1,
      generation: 'g',
      account: 'account-a',
      symbol: 'BTCUSD',
      seconds: 60,
      settings: { leverage: 50, balanceFraction: 1, manualQuantity: '1' },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText(/Recovery paused:/)
  expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeChecked()
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(localStorage.getItem('delta-chart:auto-resume:v1:account-a:BTCUSD:60')).toBeNull()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('allows a manual maker-only best-bid Long with mandatory protection while trend entry waits', async () => {
  const risk = { ...managedRisk(), direction: 'sideways' as const, entryAligned: false }
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={risk} />)
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Waiting for trend' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Place manual Long' }))
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledOnce())
  expect(deltaChartApi.action).toHaveBeenCalledWith(
    expect.objectContaining({
      action: 'entry',
      entry_mode: 'manual',
      side: 'buy',
      price: 69999.5,
      order_type: 'limit_order',
      auto_protection: expect.objectContaining({
        stop: expect.any(Number),
        target: expect.any(Number),
      }),
    })
  )
})
it('allows manual Short at best offer and still rejects missing closed-candle SL evidence', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const view = render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={managedRisk()} />)
  await screen.findByText('Live · India')
  fireEvent.change(screen.getByLabelText('Manual direction'), { target: { value: 'sell' } })
  fireEvent.click(screen.getByRole('button', { name: 'Place manual Short' }))
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledOnce())
  expect(deltaChartApi.action).toHaveBeenCalledWith(
    expect.objectContaining({ side: 'sell', price: 70000.5, entry_mode: 'manual' })
  )
  vi.mocked(deltaChartApi.action).mockClear()
  view.rerender(
    <DeltaTradePanel enabled symbol="BTCUSD" riskContext={{ ...managedRisk(), bars: [] }} />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Place manual Short' }))
  await screen.findByText(/Order not sent:/)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('keeps Auto OFF available during broker outage and revokes its saved restart permission', async () => {
  vi.useFakeTimers()
  try {
    vi.mocked(deltaChartApi.state)
      .mockResolvedValueOnce(snapshot({ position: null }))
      .mockRejectedValue(new Error('offline'))
    render(
      <DeltaTradePanel
        enabled
        symbol="BTCUSD"
        riskContext={{ ...managedRisk(), direction: 'sideways' }}
      />
    )
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2001)
    })
    expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeChecked()
    expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeEnabled()
    fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
    expect(localStorage.getItem('delta-chart:auto-resume:v1:account-a:BTCUSD:60')).toBeNull()
    expect(deltaChartApi.action).not.toHaveBeenCalled()
  } finally {
    vi.useRealTimers()
  }
})

it('keeps OFF available when candle history disappears while Auto is armed', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  const view = render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'sideways' }}
    />
  )
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  view.rerender(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={null} />)
  expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeChecked()
  expect(screen.getByRole('switch', { name: 'Auto trading' })).toBeEnabled()
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(localStorage.getItem('delta-chart:auto-resume:v1:account-a:BTCUSD:60')).toBeNull()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('keeps the manual action visible without expanding anything and explains the Auto interlock', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(snapshot({ position: null }))
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...managedRisk(), direction: 'sideways' }}
    />
  )
  await screen.findByText('Live · India')
  expect(screen.getByRole('button', { name: 'Place manual Long' })).toBeVisible()
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(screen.getByRole('button', { name: 'Place manual Long' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Place manual Long' })).toBeDisabled()
  expect(screen.getByText('Turn Auto off to place a manual order.')).toBeVisible()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

const scalpRisk = () => ({
  ...managedRisk(),
  trendSummary: '1m: Uptrend · 5m: Uptrend',
  bars: managedRisk().bars.map((b) => ({ ...b, high: 70030, low: 69970 })),
})
const scalpSnapshot = () =>
  snapshot({ position: null, sizing: { ...snapshot().sizing!, taker_fee_rate: 0.0005 } })
it('does not inherit legacy Auto permission when the independent scalp mode is introduced', async () => {
  localStorage.setItem(
    'delta-chart:auto-resume:v1:account-a:BTCUSD:60',
    JSON.stringify({
      version: 1,
      generation: 'old',
      account: 'account-a',
      symbol: 'BTCUSD',
      seconds: 60,
      settings: { leverage: 50, balanceFraction: 1, manualQuantity: '1' },
    })
  )
  vi.mocked(deltaChartApi.state).mockResolvedValue(scalpSnapshot())
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await screen.findByText('Live · India')
  expect(screen.getByRole('switch', { name: 'Auto trading' })).not.toBeChecked()
  expect(screen.getByLabelText('Scalping timeframes')).toHaveTextContent(
    '1m: Uptrend · 5m: Uptrend'
  )
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('resumes the verified scoped scalp permission with a protected maker entry exactly once', async () => {
  localStorage.setItem(
    'delta-chart:auto-resume:v1:account-a:BTCUSD:60:scalp-1m-5m-v1',
    JSON.stringify({
      version: 1,
      generation: 'scalp',
      strategy: 'scalp-1m-5m-v1',
      account: 'account-a',
      symbol: 'BTCUSD',
      seconds: 60,
      settings: { leverage: 50, balanceFraction: 1, manualQuantity: '1' },
    })
  )
  vi.mocked(deltaChartApi.state).mockResolvedValue(scalpSnapshot())
  const view = render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledTimes(1))
  expect(deltaChartApi.action).toHaveBeenCalledWith(
    expect.objectContaining({
      action: 'entry',
      side: 'buy',
      order_type: 'limit_order',
      price: 69999.5,
      auto_protection: expect.objectContaining({ interval_seconds: 60 }),
    })
  )
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.action).toHaveBeenCalledTimes(1)
})
it('blocks fee-negative scalp targets before Auto reserves or sends the candle', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(scalpSnapshot())
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={managedRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  expect(screen.getByLabelText('Auto trading status')).toHaveTextContent(/fees/i)
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('rechecks fees from the fresh broker response immediately before a scalp submission', async () => {
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(scalpSnapshot())
    .mockResolvedValue({
      ...scalpSnapshot(),
      sizing: { ...scalpSnapshot().sizing!, taker_fee_rate: 0.01 },
    })
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Place Long' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/fees/i))
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
it('rechecks the strategy-scoped permission while a fresh Auto preflight is pending', async () => {
  let finish!: (s: DeltaChartState) => void
  vi.mocked(deltaChartApi.state)
    .mockResolvedValueOnce(scalpSnapshot())
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('switch', { name: 'Auto trading' }))
  await waitFor(() => expect(deltaChartApi.state).toHaveBeenCalledTimes(2))
  localStorage.removeItem('delta-chart:auto-resume:v1:account-a:BTCUSD:60:scalp-1m-5m-v1')
  await act(async () => {
    finish(scalpSnapshot())
    await Promise.resolve()
  })
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('confirms blocked legacy-interval adoption with the same management context used for its review', async () => {
  const risk = scalpRisk(),
    now = Date.now() / 1000,
    end = Math.floor(now / 900) * 900 - 900
  const legacy = {
    ...risk,
    intervalSeconds: 900,
    sourceTime: end,
    bars: risk.bars.map((b, i) => ({ ...b, time: end - (14 - i) * 900 })),
  }
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      managed_plans: [
        {
          id: 'legacy',
          status: 'blocked',
          message: 'Changed protection',
          side: 'buy',
          entry_order_id: 'legacy-entry',
          entry_price: 69000,
          initial_stop: 68000,
          stop: 68000,
          target: 72000,
          source_time: end,
          interval_seconds: 900,
        },
      ],
    })
  )
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={risk}
      chartRiskContext={legacy}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await screen.findByText('Live · India')
  fireEvent.click(screen.getByRole('button', { name: 'Review updated position protection' }))
  expect(screen.getByRole('dialog', { name: 'Review live order' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Register automatic protection' }))
  await waitFor(() =>
    expect(deltaChartApi.action).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'adopt',
        auto_protection: expect.objectContaining({ source_time: end, interval_seconds: 900 }),
      })
    )
  )
})

it('keeps live net P&L and fee deductions beside the close control', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      accounting: {
        currency: 'USD',
        fee_status: 'verified',
        exit_fee_basis: 'taker',
        position_gross_pnl: 2,
        position_entry_fees: 0.2,
        estimated_exit_fee: 0.3,
        position_net_after_fees: 1.5,
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  expect(await screen.findByLabelText('Live profit after fees')).toHaveTextContent('₹127.50')
  expect(screen.getByLabelText('Live fee deductions')).toHaveTextContent('₹17.00')
  expect(screen.getByLabelText('Live execution status')).toHaveTextContent('Position open')
})

const backendStatus = (changes: Partial<DeltaBackendAutomation> = {}): DeltaBackendAutomation => ({
  owner: 'backend',
  enabled: false,
  account: 'account-a',
  symbol: 'BTCUSD',
  leverage: 50,
  balance_fraction: 1,
  manual_quantity: 1,
  generation: 'backend-generation',
  status: 'off',
  message: 'New entries stopped',
  checked_at: null,
  next_check_at: null,
  context: null,
  events: [],
  ...changes,
})
const legacyScalpPermissionKey = 'delta-chart:auto-resume:v1:account-a:BTCUSD:60:scalp-1m-5m-v1'
function saveLegacyScalpOn() {
  localStorage.setItem(
    legacyScalpPermissionKey,
    JSON.stringify({
      version: 1,
      generation: 'legacy-explicit-on',
      strategy: 'scalp-1m-5m-v1',
      account: 'account-a',
      symbol: 'BTCUSD',
      seconds: 60,
      settings: { leverage: 50, balanceFraction: 1, manualQuantity: '1' },
    })
  )
}

it('backend ownership prevents React automatic entries as eligible chart candles update', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue({
    ...scalpSnapshot(),
    automation: backendStatus({ enabled: true, status: 'waiting' }),
  })
  const view = render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  expect(await screen.findByRole('switch', { name: 'Auto' })).toBeChecked()
  expect(screen.queryByRole('switch', { name: 'Auto trading' })).not.toBeInTheDocument()
  for (const direction of ['down', 'up'] as const) {
    view.rerender(
      <DeltaTradePanel
        enabled
        symbol="BTCUSD"
        riskContext={{ ...scalpRisk(), direction }}
        executionMode="scalp-1m-5m-v1"
      />
    )
    await act(async () => {
      await Promise.resolve()
    })
  }
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  expect(deltaChartApi.manage).not.toHaveBeenCalled()
  expect(deltaChartApi.automation).not.toHaveBeenCalled()
})

it('migrates a legacy explicit On permission with exactly one backend POST and no browser entry', async () => {
  saveLegacyScalpOn()
  vi.mocked(deltaChartApi.state).mockResolvedValue({
    ...scalpSnapshot(),
    automation: backendStatus({ generation: '' }),
  })
  vi.mocked(deltaChartApi.automation).mockResolvedValue({
    status: 'confirmed',
    automation: backendStatus({ enabled: true, status: 'waiting' }),
  })
  const view = render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await waitFor(() => expect(screen.getByRole('switch', { name: 'Auto' })).toBeChecked())
  view.rerender(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={{ ...scalpRisk() }}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.automation).toHaveBeenCalledExactlyOnceWith({
    account: 'account-a',
    symbol: 'BTCUSD',
    enabled: true,
    leverage: 50,
    balance_fraction: 1,
    manual_quantity: 1,
  })
  expect(localStorage.getItem(legacyScalpPermissionKey)).toBeNull()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('a persisted backend Off generation revokes old local On instead of migrating it again', async () => {
  saveLegacyScalpOn()
  vi.mocked(deltaChartApi.state).mockResolvedValue({
    ...scalpSnapshot(),
    automation: backendStatus({ generation: 'persisted-off' }),
  })
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  expect(await screen.findByRole('switch', { name: 'Auto' })).not.toBeChecked()
  await waitFor(() => expect(localStorage.getItem(legacyScalpPermissionKey)).toBeNull())
  expect(deltaChartApi.automation).not.toHaveBeenCalled()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it('backend On keeps manual direction and submission disabled', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue({
    ...scalpSnapshot(),
    automation: backendStatus({ enabled: true, status: 'waiting' }),
  })
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await screen.findByRole('switch', { name: 'Auto' })
  expect(screen.getByLabelText('Manual direction')).toBeDisabled()
  const manual = screen.getByRole('button', { name: 'Place manual Long' })
  expect(manual).toBeDisabled()
  fireEvent.click(manual)
  expect(screen.getByText('Turn Auto off to place a manual order.')).toBeVisible()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})

it.each([
  'buy',
  'sell',
] as const)('backend Off manual %s requests trend management with protected maker entry', async (side) => {
  vi.mocked(deltaChartApi.state).mockResolvedValue({
    ...scalpSnapshot(),
    automation: backendStatus(),
  })
  render(
    <DeltaTradePanel
      enabled
      symbol="BTCUSD"
      riskContext={scalpRisk()}
      executionMode="scalp-1m-5m-v1"
    />
  )
  await screen.findByRole('switch', { name: 'Auto' })
  if (side === 'sell')
    fireEvent.change(screen.getByLabelText('Manual direction'), { target: { value: 'sell' } })
  const manual = screen.getByRole('button', {
    name: `Place manual ${side === 'buy' ? 'Long' : 'Short'}`,
  })
  await waitFor(() => expect(manual).toBeEnabled())
  fireEvent.click(manual)
  await waitFor(() => expect(deltaChartApi.action).toHaveBeenCalledOnce())
  expect(deltaChartApi.action).toHaveBeenCalledWith(
    expect.objectContaining({
      action: 'entry',
      entry_mode: 'manual',
      target_mode: 'trend',
      side,
      order_type: 'limit_order',
      price: side === 'buy' ? 69999.5 : 70000.5,
      auto_protection: expect.objectContaining({
        stop: expect.any(Number),
        target: expect.any(Number),
      }),
    })
  )
  expect(deltaChartApi.automation).not.toHaveBeenCalled()
})

it.each([
  false,
  true,
])('explains adaptive structural profit protection only for backend mode=%s', async (backend) => {
  vi.mocked(deltaChartApi.state).mockResolvedValue(
    snapshot({
      ...(backend ? { automation: backendStatus() } : {}),
      accounting: {
        currency: 'USD',
        balance: 100,
        available_balance: 80,
        position_gross_pnl: 2,
        position_entry_fees: 0.2,
        estimated_maker_exit_fee: 0.3,
        estimated_exit_fee: 0.3,
        exit_fee_basis: 'taker',
        position_net_after_fees: 1.5,
        fee_status: 'verified',
        message: '',
      },
    })
  )
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  await screen.findByText('Live · India')
  if (backend) {
    const policy = screen.getByText(/USD 0\.15 net \(₹12\.75\)/)
    expect(policy).toHaveTextContent(/reduces structural risk before that threshold/)
    expect(policy).toHaveTextContent(
      /covers actual fees and a tick of profit when structure allows/
    )
    expect(policy).toHaveTextContent(/₹10 when structure allows/)
    expect(policy).toHaveTextContent(/completed candles and ATR/)
    expect(policy).toHaveTextContent(/no fixed ₹10 giveback exit or 2R profit cap/i)
  } else {
    expect(screen.getByText(/up to ₹10 planned giveback from the observed peak/)).toBeVisible()
  }
})
it('keeps a recovered backend protection failure visible in trade alerts until manual dismissal', async () => {
  let automation = backendStatus({
    enabled: true,
    status: 'protection_blocked',
    message: 'Owned SL update rejected',
    events: [
      {
        id: 91,
        at: Date.now() / 1000,
        kind: 'protection_blocked',
        details: {
          plan_id: 'owned-plan',
          message: 'Owned SL update rejected',
          plan_status: 'blocked',
        },
      },
    ],
  })
  vi.mocked(deltaChartApi.state).mockImplementation(async () => snapshot({ automation }))
  render(<DeltaTradePanel enabled symbol="BTCUSD" />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Owned SL update rejected')
  expect(screen.getByLabelText('Trade alerts')).toHaveTextContent('Protection blocked')
  expect(screen.getByLabelText('Trade alerts')).toHaveTextContent('Owned SL update rejected')
  automation = { ...automation, status: 'managing', message: 'Protection verified', events: [] }
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument(), {
    timeout: 3500,
  })
  expect(screen.getByLabelText('Trade alerts')).toHaveTextContent('Owned SL update rejected')
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss Protection blocked' }))
  expect(screen.queryByLabelText('Trade alerts')).not.toBeInTheDocument()
  expect(deltaChartApi.action).not.toHaveBeenCalled()
  expect(deltaChartApi.automation).not.toHaveBeenCalled()
})


it('updates advisory preview for the selected manual short without placing an order', async () => {
  vi.mocked(deltaChartApi.state).mockResolvedValue({...scalpSnapshot(), automation: backendStatus()})
  const onGuidance = vi.fn()
  render(<DeltaTradePanel enabled symbol="BTCUSD" riskContext={scalpRisk()} executionMode="scalp-1m-5m-v1" onGuidance={onGuidance} />)
  await screen.findByLabelText('Manual direction')
  fireEvent.change(screen.getByLabelText('Manual direction'), {target:{value:'sell'}})
  await waitFor(() => expect(onGuidance).toHaveBeenLastCalledWith(expect.objectContaining({plan:expect.objectContaining({side:'sell'})})))
  const guide = onGuidance.mock.lastCall![0]
  expect(guide.plan.stop).toBeGreaterThan(guide.plan.entry)
  expect(deltaChartApi.action).not.toHaveBeenCalled()
})
