import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'
import type { StrategySummary } from '@/types/strategy_module'

const api = vi.hoisted(() => ({ install: vi.fn() }))
vi.mock('@/api/strategy_module', () => ({
  installScalpingPack: api.install,
  strategyQueryKeys: { strategies: () => ['strategies'] },
}))

import { ScalpingStrategies } from './ScalpingStrategies'

function show(rows: StrategySummary[] = []) {
  const callbacks = { onStart: vi.fn(), onStop: vi.fn(), onMode: vi.fn() }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ScalpingStrategies rows={rows} busy={false} {...callbacks} />
      </MemoryRouter>
    </QueryClientProvider>
  )
  return callbacks
}
beforeEach(() => {
  api.install.mockReset()
})
it('adds three presets with one action and shows installation failures', async () => {
  api.install.mockRejectedValue(new Error('Broker connection required'))
  show()
  expect(screen.getByText('EMA 9/15')).toBeInTheDocument()
  expect(screen.getByText('EMA 50/200 + regime')).toBeInTheDocument()
  expect(screen.getByText('Opening-box breakout')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add all 3 strategies' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Broker connection required')
  expect(api.install).toHaveBeenCalledTimes(1)
  expect(screen.queryByText('MACD + EMA 200')).not.toBeInTheDocument()
  expect(screen.queryByText('5 EMA reversal')).not.toBeInTheDocument()
})
it('starts the selected sandbox setup without implying an immediate order', async () => {
  const row = {
    id: 12,
    scalp_profile: 'ema915',
    automation_state: 'disabled',
    status: 'stopped',
    live_enabled: false,
  } as StrategySummary
  const cb = show([row])
  await userEvent.click(screen.getByRole('button', { name: 'Start sandbox' }))
  expect(cb.onStart).toHaveBeenCalledWith(row)
  expect(screen.getByText('Sandbox · Stopped')).toBeInTheDocument()
})
it('stops armed live automation and prevents changing mode while active', async () => {
  const row = {
    id: 12,
    scalp_profile: 'ema915',
    automation_state: 'armed',
    status: 'stopped',
    live_enabled: true,
  } as StrategySummary
  const cb = show([row])
  expect(screen.getByRole('button', { name: 'Use sandbox' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Stop automation' }))
  expect(cb.onStop).toHaveBeenCalledWith(row)
})
