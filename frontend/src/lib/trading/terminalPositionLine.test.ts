/**
 * A position draws one line on the chart, whatever asks for the book.
 *
 * A fill, a placement and the 8s timer can all poll within a second, and a
 * chart rebuild can leave a line behind. Each of those once left a second
 * LONG label over the first. Asserted on the real chart, by counting the
 * primitives that carry the position id.
 */
import type { Bar, Chart } from 'openalgo-charts'
import { PriceLine } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'

type State = {
  chart: Chart
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  chartToolsReady: Promise<void>
  trade: unknown
  posLine: PriceLine | null
  buildChart(): void
  loadIndicators(): Promise<void>
  renderPosition(row: Record<string, unknown> | undefined): void
  pollBook(): Promise<void>
}

const BTC_LONG = {
  symbol: 'BTCUSDFUT',
  exchange: 'CRYPTO',
  product: 'NRML',
  quantity: 59,
  average_price: 84646.5,
  mark_price: 84657.5,
  lot_size: 0.001,
}

const terminals: TradingTerminal[] = []

beforeEach(() => {
  localStorage.clear()
  const context = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
      getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  )
})

afterEach(() => {
  for (const terminal of terminals.splice(0)) terminal.destroy()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

async function mount() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container,
    legendEl: document.createElement('div'),
    storageKey: 'oa-trading-position-line',
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast() {},
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
  state.loadIndicators = async () => {}
  state.sym = {
    symbol: 'BTCUSDFUT',
    exchange: 'CRYPTO',
    name: 'BTCUSDFUT',
    lotsize: 1,
    lots: true,
    tick: 0.5,
    freezeQty: 0,
    quoteOnly: false,
    productOptions: ['NRML'],
    product: 'NRML',
  }
  state.interval = '5m'
  state.rawBars = [60, 120, 180, 240].map((time) => ({
    time,
    open: 84600,
    high: 84700,
    low: 84500,
    close: 84650,
    volume: 10,
  }))
  state.buildChart()
  await state.chartToolsReady
  return { terminal, state }
}

function positionLines(chart: Chart): PriceLine[] {
  return chart
    .panes()
    .flatMap((pane) => pane.primitives())
    .filter((p): p is PriceLine => p instanceof PriceLine && p.options().id === 'position')
}

/** Serve one position book to the terminal, as /api/v1/positionbook would. */
function serveBook(terminal: TradingTerminal, rows: Record<string, unknown>[]) {
  const state = terminal as unknown as State
  state.trade = { getOrders: async () => [] }
  return vi
    .spyOn(terminal, 'api')
    .mockImplementation(async () => ({ status: 'success', data: rows }) as never)
}

describe('one line per position', () => {
  it('draws one line when the same position is rendered twice', async () => {
    const { state } = await mount()
    state.renderPosition(BTC_LONG)
    state.renderPosition(BTC_LONG)
    expect(positionLines(state.chart)).toHaveLength(1)
  })

  it('draws no line for a position of quantity 0', async () => {
    const { state } = await mount()
    state.renderPosition(BTC_LONG)
    state.renderPosition({ ...BTC_LONG, quantity: 0 })
    expect(positionLines(state.chart)).toHaveLength(0)
    expect(state.posLine).toBeNull()
  })

  it('draws one line when three polls overlap', async () => {
    const { terminal, state } = await mount()
    const api = serveBook(terminal, [BTC_LONG])
    await Promise.all([state.pollBook(), state.pollBook(), state.pollBook()])
    expect(positionLines(state.chart)).toHaveLength(1)
    // The first read, plus one more for the callers that arrived during it.
    expect(api.mock.calls.filter(([path]) => path === 'positionbook')).toHaveLength(2)
  })

  it('removes a line left behind on the chart instead of adding beside it', async () => {
    const { state } = await mount()
    state.chart.addPriceLine({ price: 84000, color: '#2e7d6b', id: 'position' }, 0)
    state.renderPosition(BTC_LONG)
    const lines = positionLines(state.chart)
    expect(lines).toHaveLength(1)
    expect(lines[0].price).toBe(84646.5)
  })

  it('labels the line in dollars at the 0.001 BTC contract value when USD is selected', async () => {
    localStorage.setItem('openalgo_delta_position_currency_session', 'USD')
    const { state } = await mount()
    state.renderPosition(BTC_LONG)
    const label = String(positionLines(state.chart)[0].options().leftLabel)
    expect(label).toContain('Gross +$0.65')
    expect(label).not.toContain('₹')
  })
})

it('keeps chart prices in USD while P&L follows the configured currency', async () => {
  const { setDeltaDisplayCurrency } = await import('@/hooks/useDeltaDisplayCurrency')
  const { state } = await mount()
  const before = structuredClone(state.rawBars)
  state.renderPosition(BTC_LONG)
  expect(String(positionLines(state.chart)[0].options().leftLabel)).toContain('@ $84,646.50')
  expect(String(positionLines(state.chart)[0].options().leftLabel)).toContain('Gross +₹')
  expect(state.chart.panes()[0].priceScale.format(100)).toBe('$100.00')
  setDeltaDisplayCurrency(undefined, 'USD')
  expect(state.chart.panes()[0].priceScale.format(100)).toBe('$100.00')
  expect(state.rawBars).toEqual(before)
  expect(positionLines(state.chart)).toHaveLength(1)
  setDeltaDisplayCurrency(undefined, 'INR')
  expect(state.chart.panes()[0].priceScale.format(100)).toBe('$100.00')
})
