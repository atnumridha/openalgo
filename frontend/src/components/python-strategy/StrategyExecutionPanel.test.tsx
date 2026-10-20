import { cleanup, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { StrategyExecutionPanel } from './StrategyExecutionPanel'

const api = vi.hoisted(() => ({
  getStrategy: vi.fn(),
  getLogFiles: vi.fn(),
  getLogContent: vi.fn(),
}))
vi.mock('@/api/python-strategy', () => ({ pythonStrategyApi: api }))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function setup(record: object, options: { age?: number; running?: boolean; fail?: boolean } = {}) {
  const updated = new Date(Date.now() - (options.age || 0)).toISOString()
  api.getStrategy.mockResolvedValue({
    status: options.running === false ? 'stopped' : 'running',
    last_started: null,
  })
  api.getLogFiles.mockResolvedValue([{ name: 'run.log', last_modified: updated, size_kb: 1 }])
  api.getLogContent.mockResolvedValue({ content: JSON.stringify(record), last_updated: updated })
  if (options.fail) api.getLogFiles.mockRejectedValue(new Error('network'))
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <StrategyExecutionPanel strategyId="confluence" />
      </QueryClientProvider>
    </MemoryRouter>
  )
}

it('shows the actual entry blockers and zero daily net without inventing trade counts', async () => {
  setup({
    mode: 'live',
    execution_enabled: false,
    status: 'monitoring',
    position: null,
    entry_wait: ['Auto top-up is ON', 'Isolated margin unconfirmed'],
    daily: { net: '0' },
    decision: { action: 'HOLD', reason: 'Insufficient agreement' },
  })
  const panel = await screen.findByRole('region', { name: 'Strategy execution' })
  expect(await within(panel).findByText('Monitoring only')).toBeInTheDocument()
  expect(within(panel).getByText('Auto top-up is ON')).toBeInTheDocument()
  expect(within(panel).getByText('No open position reported')).toBeInTheDocument()
  expect(within(panel).getByText(/₹0.00/)).toBeInTheDocument()
  expect(within(panel).getByRole('link', { name: 'Trade Book' })).toHaveAttribute(
    'href',
    '/tradebook'
  )
  expect(within(panel).getByRole('link', { name: 'Logs' })).toHaveAttribute('href', '/python/confluence/logs')
})

it('shows confirmed fill evidence and order ID; a pending order is not called executed', async () => {
  setup({
    mode: 'live',
    status: 'running',
    execution_enabled: true,
    position: {
      entry_id: 12345,
      qty: 2,
      filled: 0,
      open_qty: 0,
      entry_open: true,
      side: 'sell',
      entry: '83000',
    },
  })
  expect(await screen.findByText('Entry pending · no fill')).toBeInTheDocument()
  expect(screen.getByText('12345')).toBeInTheDocument()
  expect(screen.getByText('0 / 2 contracts')).toBeInTheDocument()
  expect(screen.queryByText('Trade executed · position open')).not.toBeInTheDocument()
})

it('never shows an old enabled report as current when stale or stopped', async () => {
  setup(
    { mode: 'live', status: 'running', execution_enabled: true, position: null },
    { age: 180000 }
  )
  expect(await screen.findByText('Report is stale')).toBeInTheDocument()
  expect(screen.queryByText('Scanning · entries enabled')).not.toBeInTheDocument()
  cleanup()
  setup(
    { mode: 'live', status: 'running', execution_enabled: true, position: null },
    { running: false }
  )
  expect(await screen.findByText('Process stopped')).toBeInTheDocument()
  expect(screen.queryByText('Scanning · entries enabled')).not.toBeInTheDocument()
})

it('shows unavailable rather than zero execution on a read failure', async () => {
  setup({}, { fail: true })
  expect(await screen.findByText('Execution status unavailable')).toBeInTheDocument()
  expect(screen.queryByText('No open position reported')).not.toBeInTheDocument()
})
