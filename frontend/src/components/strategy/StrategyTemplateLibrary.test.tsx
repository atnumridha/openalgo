import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ catalog: vi.fn(), install: vi.fn() }))
vi.mock('@/api/strategy_module', () => ({
  getStrategyTemplates: api.catalog,
  installStrategyTemplate: api.install,
  strategyQueryKeys: { strategies: () => ['strategies'] },
}))
import { StrategyTemplateLibrary } from './StrategyTemplateLibrary'

const templates = Array.from({ length: 9 }, (_, i) => ({
  id: `template-${i}`, name: `Earlier template ${i}`, underlying: 'NIFTY', installed_strategy_id: null,
}))
function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><StrategyTemplateLibrary /></MemoryRouter>
  </QueryClientProvider>)
}
beforeEach(() => {
  api.catalog.mockReset().mockResolvedValue(templates)
  api.install.mockReset()
})
it('keeps all nine uninstalled until the user chooses a specific template', async () => {
  show()
  expect(api.catalog).not.toHaveBeenCalled()
  expect(api.install).not.toHaveBeenCalled()
  await userEvent.click(screen.getByText('Available templates'))
  expect(await screen.findByText('Earlier template 8')).toBeVisible()
  expect(screen.getAllByRole('button', { name: /^Install Earlier template/ })).toHaveLength(9)
  expect(api.install).not.toHaveBeenCalled()
  api.install.mockImplementation(async () => {
    api.catalog.mockResolvedValue(templates.map(t => t.id === 'template-2' ? { ...t, installed_strategy_id: 42 } : t))
    return { created: true, strategy_id: 42, workflow_id: 51 }
  })
  await userEvent.click(screen.getByRole('button', { name: 'Install Earlier template 2' }))
  await waitFor(() => expect(api.install).toHaveBeenCalledWith('template-2'))
  expect(await screen.findByRole('link', { name: 'Open Earlier template 2' })).toHaveAttribute('href', '/strategy/42')
  expect(screen.getByRole('status')).toHaveTextContent('Installed in sandbox. Automation is stopped.')
  expect(api.install).toHaveBeenCalledTimes(1)
})
it('shows installation errors without claiming the strategy was installed', async () => {
  api.install.mockRejectedValue(new Error('Choose a broker connection first'))
  show()
  await userEvent.click(screen.getByText('Available templates'))
  await userEvent.click(await screen.findByRole('button', { name: 'Install Earlier template 0' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Choose a broker connection first')
  expect(screen.queryByRole('link', { name: 'Open Earlier template 0' })).not.toBeInTheDocument()
})
