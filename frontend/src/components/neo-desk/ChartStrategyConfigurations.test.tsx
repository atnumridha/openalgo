import { act, fireEvent, render, screen, cleanup, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { scalpingApi } from '@/api/scalping'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { ChartStrategyConfigurations } from './ChartStrategyConfigurations.tsx'
vi.mock('@/api/scalping', () => ({ scalpingApi: { getExpiry: vi.fn(), getStrikes: vi.fn() } }))
beforeEach(() => {
  vi.mocked(scalpingApi.getExpiry).mockResolvedValue({
    status: 'success',
    data: ['03FEB80', '02JAN80'],
  })
  vi.mocked(scalpingApi.getStrikes).mockImplementation(async (underlying, _exchange, expiry) => ({
    status: 'success',
    underlying,
    expiry_date: expiry,
    fo_exchange: 'NFO',
    atm_strike: 23000,
    chain: [22800, 23000, 23200].map((strike) => ({
      strike,
      ce: { symbol: `${strike}CE`, label: '', ltp: 100 },
      pe: { symbol: `${strike}PE`, label: '', ltp: strike === 22800 ? 40 : 100 },
    })),
  }))
  localStorage.clear()
  useAuthStore.setState({
    user: { username: 'alice', broker: 'fyers', isLoggedIn: true, loginTime: null },
  })
  useThemeStore.setState({ appMode: 'live' })
})
afterEach(cleanup)
it('selects all seven templates and keeps missing rules visible', () => {
  render(<ChartStrategyConfigurations symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />)
  for (const id of ['A-01', 'A-02', 'A-03', 'A-04', 'A-05', 'A-06', 'A-07']) {
    fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: id } })
    expect(screen.getByLabelText('Strategy')).toHaveValue(id)
    expect(screen.getByText(/Unconfigured/)).toBeInTheDocument()
  }
  expect(screen.queryByRole('button', { name: /execute|place order/i })).not.toBeInTheDocument()
})
it('restores selections after remount and isolates app mode and owner', () => {
  const view = render(
    <ChartStrategyConfigurations symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />
  )
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-03' } })
  view.unmount()
  render(<ChartStrategyConfigurations symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />)
  expect(screen.getByLabelText('Strategy')).toHaveValue('A-03')
  act(() => useThemeStore.setState({ appMode: 'analyzer' }))
  expect(screen.getByLabelText('Strategy')).toHaveValue('')
  act(() => useThemeStore.setState({ appMode: 'live' }))
  expect(screen.getByLabelText('Strategy')).toHaveValue('A-03')
  act(() => useAuthStore.setState({ user: null }))
  expect(screen.getByLabelText('Strategy')).toHaveValue('')
})
it('requires user entry and direction before proposing a futures stop', () => {
  render(
    <ChartStrategyConfigurations
      symbol="NIFTY24NOV26FUT"
      exchange="NFO"
      interval="5m"
      tickSize={0.05}
    />
  )
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-06' } })
  expect(screen.getByLabelText('Actual futures entry')).toHaveValue(null)
  expect(screen.queryByText(/Proposed trigger:/)).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Actual futures entry'), { target: { value: '24000' } })
  fireEvent.change(screen.getByLabelText('Your direction'), { target: { value: 'short' } })
  expect(screen.getByText(/Proposed trigger: 24200/)).toBeInTheDocument()
  expect(screen.getByText(/not guaranteed capped monetary loss/)).toBeInTheDocument()
})
it('keeps index and premium contexts from producing a futures trigger', () => {
  const view = render(
    <ChartStrategyConfigurations
      symbol="NIFTY"
      exchange="NSE_INDEX"
      interval="5m"
      tickSize={0.05}
    />
  )
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-06' } })
  expect(screen.queryByLabelText('Actual futures entry')).not.toBeInTheDocument()
  expect(screen.getByText(/You are viewing the NIFTY index/)).toBeInTheDocument()
  view.rerender(
    <ChartStrategyConfigurations
      symbol="NIFTY03NOV2623000CE"
      exchange="NFO"
      interval="5m"
      tickSize={0.05}
    />
  )
  expect(screen.getByLabelText('Strategy')).toHaveValue('')
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-06' } })
  expect(screen.getByText(/This example needs a NIFTY contract/)).toBeInTheDocument()
  expect(screen.queryByLabelText('Actual futures entry')).not.toBeInTheDocument()
})
it('keeps editable user proposals separate from source parameters after reload', () => {
  const view = render(
    <ChartStrategyConfigurations symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />
  )
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-01' } })
  fireEvent.change(screen.getByLabelText('Your notes (optional)'), {
    target: { value: 'Proposed put spread; expiry still unresolved' },
  })
  view.unmount()
  render(<ChartStrategyConfigurations symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />)
  expect(screen.getByLabelText('Your notes (optional)')).toHaveValue(
    'Proposed put spread; expiry still unresolved'
  )
  expect(screen.getByText(/Unconfigured/)).toBeInTheDocument()
  expect(screen.getByText(/200-point protective wing/)).toBeInTheDocument()
})

it('shows controlled source changes without carrying over another template draft', () => {
  const change = vi.fn()
  const props = {
    symbol: 'NIFTY24NOV26FUT',
    exchange: 'NFO',
    interval: '5m',
    tickSize: 0.05,
    onSelectedIdChange: change,
  }
  const view = render(<ChartStrategyConfigurations {...props} selectedId="A-06" />)
  expect(screen.getByLabelText('Strategy')).toHaveValue('A-06')
  expect(screen.getByLabelText('Strategy').closest('section')).toBeVisible()
  fireEvent.change(screen.getByLabelText('Actual futures entry'), { target: { value: '24000' } })
  fireEvent.change(screen.getByLabelText('Your notes (optional)'), {
    target: { value: 'Nifty only draft' },
  })
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-07' } })
  expect(change).toHaveBeenCalledWith('A-07')
  // Parent owns selection: a request alone must not mutate the displayed source.
  expect(screen.getByLabelText('Strategy')).toHaveValue('A-06')
  view.rerender(<ChartStrategyConfigurations {...props} selectedId="A-07" />)
  expect(screen.getByLabelText('Strategy')).toHaveValue('A-07')
  expect(screen.getByLabelText('Your notes (optional)')).toHaveValue('')
  expect(screen.queryByLabelText('Actual futures entry')).not.toBeInTheDocument()
  view.rerender(<ChartStrategyConfigurations {...props} selectedId="A-06" />)
  expect(screen.getByLabelText('Actual futures entry')).toHaveValue(24000)
  expect(screen.getByLabelText('Your notes (optional)')).toHaveValue('Nifty only draft')
  view.unmount()
  render(<ChartStrategyConfigurations {...props} />)
  expect(screen.getByLabelText('Strategy')).toHaveValue('A-06')
})
it('rejects non-source controlled IDs instead of restoring a previous template', () => {
  render(
    <ChartStrategyConfigurations
      symbol="NIFTY"
      exchange="NSE_INDEX"
      interval="5m"
      selectedId="ema_cross_5m"
    />
  )
  expect(screen.getByLabelText('Strategy')).toHaveValue('')
  expect(screen.queryByText(/Unconfigured/)).not.toBeInTheDocument()
})

it('reveals an illustrative preview for each source and preserves structured legs on return', async () => {
  const result = render(
    <ChartStrategyConfigurations symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />
  )
  for (const id of ['A-01', 'A-02', 'A-03', 'A-04', 'A-05', 'A-06', 'A-07']) {
    fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: id } })
    expect(screen.getByRole('img', { name: /Illustrative.*preview/ })).toBeVisible()
    expect(screen.getByText(/Choose a strike and expiry below/)).toBeVisible()
  }
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-01' } })
  await waitFor(() => expect(screen.getByLabelText('Strike price')).toHaveValue('23000'))
  fireEvent.change(screen.getByLabelText('Leg 1 premium'), { target: { value: '100' } })
  fireEvent.change(screen.getByLabelText('Leg 2 premium'), { target: { value: '40' } })
  expect(screen.getByLabelText('Preview calculation')).toHaveTextContent(
    'Possible profit / loss at expiry'
  )
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-02' } })
  fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'A-01' } })
  await waitFor(() => expect(screen.getByLabelText('Strike price')).toHaveValue('23000'))
  expect(screen.getByLabelText('Leg 1 premium')).toHaveValue(100)
  result.unmount()
  render(<ChartStrategyConfigurations symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />)
  await waitFor(() => expect(screen.getByLabelText('Leg 2 premium')).toHaveValue(40))
})

it('loads expiry and ATM dropdowns and derives premiums from selected listed strikes', async () => {
  render(
    <ChartStrategyConfigurations
      symbol="NIFTY"
      exchange="NSE_INDEX"
      interval="5m"
      selectedId="A-01"
    />
  )
  const anchor = await screen.findByRole('combobox', { name: 'Strike price' })
  expect(screen.queryByPlaceholderText('Enter a strike')).not.toBeInTheDocument()
  await waitFor(() => expect(anchor).toHaveValue('23000'))
  expect(screen.getByRole('combobox', { name: 'Expiry date' })).toHaveValue('02JAN80')
  await waitFor(() => expect(screen.getByLabelText('Leg 1 premium')).toHaveValue(100))
  expect(screen.getByLabelText('Leg 2 premium')).toHaveValue(40)
  fireEvent.change(anchor, { target: { value: '23200' } })
  await waitFor(() => expect(screen.getByLabelText('Leg 2 premium')).toHaveValue(100))
  fireEvent.change(anchor, { target: { value: '22800' } })
  await waitFor(() => expect(screen.getByLabelText('Leg 2 premium')).toHaveValue(null))
  expect(screen.getByText(/not listed or have no usable quote/i)).toBeInTheDocument()
})
it('shows unavailable listings without falling back to manual strike entry', async () => {
  vi.mocked(scalpingApi.getExpiry).mockResolvedValue({ status: 'success', data: [] })
  render(
    <ChartStrategyConfigurations
      symbol="NIFTY"
      exchange="NSE_INDEX"
      interval="5m"
      selectedId="A-01"
    />
  )
  await screen.findByText(/No active listed expiries/)
  expect(screen.getByRole('combobox', { name: 'Strike price' })).toBeDisabled()
  expect(screen.queryByPlaceholderText('Enter a strike')).not.toBeInTheDocument()
})
it('replaces strikes and premiums when a different listed expiry is selected', async () => {
  vi.mocked(scalpingApi.getStrikes).mockImplementation(async (underlying, _exchange, expiry) => {
    const later = expiry === '03FEB80'
    const atm = later ? 24000 : 23000
    return {
      status: 'success',
      underlying,
      expiry_date: expiry,
      fo_exchange: 'NFO',
      atm_strike: atm,
      chain: [atm - 200, atm].map((strike) => ({
        strike,
        ce: { symbol: `${expiry}${strike}CE`, label: '', ltp: later ? 150 : 100 },
        pe: { symbol: `${expiry}${strike}PE`, label: '', ltp: later ? 80 : 40 },
      })),
    }
  })
  render(
    <ChartStrategyConfigurations
      symbol="NIFTY"
      exchange="NSE_INDEX"
      interval="5m"
      selectedId="A-01"
    />
  )
  await waitFor(() => expect(screen.getByLabelText('Strike price')).toHaveValue('23000'))
  fireEvent.change(screen.getByLabelText('Expiry date'), {
    target: { value: '03FEB80' },
  })
  await waitFor(() => expect(screen.getByLabelText('Strike price')).toHaveValue('24000'))
  expect(screen.getByLabelText('Leg 1 premium')).toHaveValue(80)
  expect(screen.getByLabelText('Leg 2 premium')).toHaveValue(80)
  expect(screen.queryByRole('option', { name: '23000 · ATM' })).not.toBeInTheDocument()
})

it('configures a matching option chart from its selected strike without treating premium units as underlying units', async () => {
  render(
    <ChartStrategyConfigurations
      symbol="NIFTY03FEB8023200CE"
      exchange="NFO"
      interval="5m"
      selectedId="A-01"
    />
  )
  expect(screen.queryByText(/This chart has different instrument/)).not.toBeInTheDocument()
  await waitFor(() => expect(screen.getByLabelText('Strike price')).toHaveValue('23200'))
  expect(screen.getByLabelText('Expiry date')).toHaveValue('03FEB80')
  expect(scalpingApi.getStrikes).toHaveBeenCalledWith('NIFTY', 'NFO', '03FEB80', 20, {
    quotes: true,
  })
  expect(screen.getByText(/You are viewing the option price/)).toBeInTheDocument()
})
