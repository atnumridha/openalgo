import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useThemeStore } from '@/stores/themeStore'
import { useAuthStore } from '@/stores/authStore'
import { combinedTerminalApi } from '@/api/combinedTerminal'
import { CombinedTerminal } from './CombinedTerminal'

vi.mock('@/components/kotak-assistant/KotakAssistantChart', () => ({
  KotakAssistantChart: ({ title, externalSource }: { title: string; externalSource?: { id: string } }) => <div aria-label={title}>Chart source {externalSource?.id}</div>,
}))
vi.mock('@/api/combinedTerminal', async (load) => ({ ...(await load<typeof import('@/api/combinedTerminal')>()), combinedTerminalApi: {
  config: vi.fn(), snapshot: vi.fn(), market: vi.fn(), chart: vi.fn(), select: vi.fn(),
  preview: vi.fn(), enter: vi.fn(), mutateTrade: vi.fn(), configure: vi.fn(),
} }))
const now = () => Date.now() / 1000
const ref = (id: string) => ({ id, owner: 'u', broker: id === 'kotak' ? 'kotak' : 'flattrade', account: id, mode: 'live' })
const state = () => ({ mode: 'live', setup_required: false, updated_at: now(), settings: { reminder_seconds: 120 },
  connections: ['kotak', 'flat'].map(id => ({ connection: ref(id), entry_ready: true, books_complete: true, quotes_fresh: true, captured_at: now(), funds: { availablecash: 30000 }, error: null as string | null })),
  summary: { complete: true, realized_net: 100, estimated_open_net: 50, estimated_total_net: 150 },
  day: { date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date()), entries: 1, reserved_entries: 0, remaining_entries: 2, max_entries: 3, loss_limit: 1000, profit_target: 2000, net: 150, entry_allowed: true, count_verified: true, updated_at: now(), loss_reached: false, profit_reached: false },
  positions: [{ trade_id: '["kotak","kotak","live","trade","legacy"]', connection_id: 'kotak', broker: 'kotak', symbol: 'NIFTY22OCT2623000CE', managed: true, quantity: 65, entry: 100, current_sl: 95, target: 110, ltp: 101, net_open: 50, status: 'open', data_fresh: true }], history: [], fills: [],
})
const market = (id: string) => ({ underlying: 'NIFTY', expiry: '22OCT26', expiries: ['22OCT26'], exchange: 'NFO', symbol: 'NIFTY22OCT2623000CE',
  chain: { atm_strike: 23000, chain: [{ strike: 23000, ce: { symbol: 'NIFTY22OCT2623000CE' }, pe: { symbol: 'NIFTY22OCT2623000PE' } }] },
  strike: 23000, ce: { symbol: 'NIFTY22OCT2623000CE' }, pe: { symbol: 'NIFTY22OCT2623000PE' },
  index_quote: { ltp: 23000, time: now() }, metadata: { lot: 65, tick: .05, freeze: 1800 },
  quote: { ltp: id === 'flat' ? 110 : 100, bid: 99.95, ask: id === 'flat' ? 110 : 100, time: now(), source: id }, quotes: {},
  setup: { stage: 'waiting_break', reason: 'Waiting for level break', eligible: false, evidence: [] },
  template: { entry: id === 'flat' ? 110 : 100, sl: 90, target: 120, quantity: 65, risk: 666, reward: 1270, costs: 12.5, net_rr: 1.9, fits: true },
})
function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CombinedTerminal /></QueryClientProvider>)
}
describe('combined broker terminal', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear()
    useAuthStore.setState({ user: { username: 'u', broker: 'kotak', isLoggedIn: true, loginTime: null } })
    useThemeStore.setState({ appMode: 'live' })
    vi.mocked(combinedTerminalApi.config).mockResolvedValue({ enabled: true })
    vi.mocked(combinedTerminalApi.snapshot).mockImplementation(async () => state() as never)
    vi.mocked(combinedTerminalApi.market).mockImplementation(async id => market(id) as never)
    vi.mocked(combinedTerminalApi.select).mockResolvedValue({} as never)
    vi.mocked(combinedTerminalApi.preview).mockResolvedValue({ preview_id: 'p1', connection: ref('kotak'), expires: now() + 5, plan: { risk: 666, reward: 1270, costs: 12.5, net_rr: 1.9 } } as never)
    vi.mocked(combinedTerminalApi.enter).mockResolvedValue({ operation_id: 'o1', state: 'accepted' } as never)
    vi.mocked(combinedTerminalApi.mutateTrade).mockResolvedValue({ state: 'accepted' } as never)
  })
  it('defaults to Kotak and uses Flattrade data only after manual selection', async () => {
    mount()
    await waitFor(() => expect(screen.getByLabelText('Entry price ₹')).toHaveValue(100))
    expect(screen.getByLabelText('Execution broker')).toHaveValue('kotak')
    expect(screen.getByText('Daily trading limits · Kotak Neo + Flattrade')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Execution broker'), { target: { value: 'flat' } })
    await waitFor(() => expect(screen.getByLabelText('Entry price ₹')).toHaveValue(110))
    expect(combinedTerminalApi.enter).not.toHaveBeenCalled()
  })
  it('does not let a pending old-broker preview enable a new-broker buy', async () => {
    let resolve!: (value: never) => void
    vi.mocked(combinedTerminalApi.preview).mockImplementation(() => new Promise(r => { resolve = r }))
    mount()
    await screen.findByDisplayValue('100')
    fireEvent.click(screen.getByRole('button', { name: 'Review Kotak Neo order' }))
    await waitFor(() => expect(combinedTerminalApi.preview).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('Execution broker'), { target: { value: 'flat' } })
    await waitFor(() => expect(screen.getByLabelText('Entry price ₹')).toHaveValue(110))
    await act(async () => resolve({ preview_id: 'old', connection: ref('kotak'), expires: now() + 5, plan: {} } as never))
    expect(screen.queryByRole('button', { name: /Buy.*Flattrade/ })).not.toBeInTheDocument()
    expect(combinedTerminalApi.enter).not.toHaveBeenCalled()
  })
  it('routes an existing Kotak exit by its trade id while Flattrade is selected', async () => {
    mount(); await screen.findByText('NIFTY22OCT2623000CE', { selector: 'strong' })
    fireEvent.change(screen.getByLabelText('Execution broker'), { target: { value: 'flat' } })
    fireEvent.click(screen.getByRole('button', { name: 'Exit NIFTY22OCT2623000CE on Kotak Neo' }))
    await waitFor(() => expect(combinedTerminalApi.mutateTrade).toHaveBeenCalledWith('["kotak","kotak","live","trade","legacy"]', 'exit', expect.objectContaining({ request_id: expect.any(String) })))
  })
  it('preserves ticket edits during refresh and requires no signal confirmation for manual review', async () => {
    mount(); await waitFor(() => expect(screen.getByLabelText('Entry price ₹')).toHaveValue(100))
    fireEvent.change(screen.getByLabelText('Entry price ₹'), { target: { value: '101' } })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh accounts' }))
    await waitFor(() => expect(combinedTerminalApi.snapshot).toHaveBeenCalledTimes(2))
    expect(screen.getByLabelText('Entry price ₹')).toHaveValue(101)
    expect(screen.getByRole('button', { name: 'Review Kotak Neo order' })).toBeEnabled()
  })
  it('keeps exits available when shared entry limits are reached', async () => {
    const data = state(); data.day.entries = 3; data.day.remaining_entries = 0; data.day.entry_allowed = false
    vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(data as never)
    mount(); await screen.findByText('NIFTY22OCT2623000CE', { selector: 'strong' })
    expect(screen.getByRole('button', { name: 'Review Kotak Neo order' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Exit NIFTY22OCT2623000CE on Kotak Neo' })).toBeEnabled()
  })
  it('shows a disconnected broker without using the other broker to make it ready', async () => {
    const data = state(); data.connections[1].entry_ready = false; data.connections[1].error = 'Static IP or broker login required'
    vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(data as never)
    mount(); await screen.findByText('Static IP or broker login required')
    fireEvent.change(screen.getByLabelText('Execution broker'), { target: { value: 'flat' } })
    expect(screen.getByRole('button', { name: 'Review Flattrade order' })).toBeDisabled()
  })
  it('keeps an exit available after a stop-change request', async () => {
    mount(); await screen.findByText('NIFTY22OCT2623000CE', { selector: 'strong' })
    fireEvent.click(screen.getByRole('button', { name: 'Update SL on Kotak Neo' }))
    await waitFor(() => expect(combinedTerminalApi.mutateTrade).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Exit NIFTY22OCT2623000CE on Kotak Neo' })).toBeEnabled()
  })

  it('allows a fresh review after a definitive pre-dispatch rejection', async () => {
    vi.mocked(combinedTerminalApi.enter).mockRejectedValue({response:{status:409,data:{submission:'not_submitted',message:'Preview expired'}}})
    mount(); await waitFor(() => expect(screen.getByLabelText('Entry price ₹')).toHaveValue(100))
    fireEvent.click(screen.getByRole('button', {name:'Review Kotak Neo order'}))
    fireEvent.click(await screen.findByRole('button', {name:'Buy 1 lot on Kotak Neo'}))
    await screen.findByText(/Preview expired/)
    expect(screen.getByRole('button', {name:'Review Kotak Neo order'})).toBeEnabled()
    expect(screen.queryByText(/outcome needs reconciliation/)).not.toBeInTheDocument()
  })
  it('allows a manual exit retry after fresh definitive rejection', async () => {
    let rejected=false
    vi.mocked(combinedTerminalApi.snapshot).mockImplementation(async()=>{const s=state();if(rejected)s.positions[0].status='exit_rejected';return s as never})
    mount(); await screen.findByText('NIFTY22OCT2623000CE', {selector:'strong'})
    const label='Exit NIFTY22OCT2623000CE on Kotak Neo'
    fireEvent.click(screen.getByRole('button', {name:label}))
    await waitFor(()=>expect(screen.getByRole('button',{name:label})).toBeDisabled())
    rejected=true;fireEvent.click(screen.getByRole('button',{name:'Refresh accounts'}))
    await waitFor(()=>expect(screen.getByRole('button',{name:label})).toBeEnabled())
  })

})
