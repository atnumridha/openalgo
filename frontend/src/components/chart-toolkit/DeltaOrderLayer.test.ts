import { describe, expect, it, vi } from 'vitest'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { DeltaOrderLayer, type DeltaOrderLayerState } from './DeltaOrderLayer'

function fixture() {
  const lines: Array<{ options: Record<string, unknown>; applyOptions: ReturnType<typeof vi.fn> }> =
    []
  const removed = vi.fn()
  const series = {
    createPriceLine: vi.fn((options) => {
      const line = { options, applyOptions: vi.fn((next) => Object.assign(options, next)) }
      lines.push(line)
      return line
    }),
    removePriceLine: removed,
    priceToCoordinate: (price: number) => price,
    coordinateToPrice: (y: number) => y,
  }
  const scroll = {
    mouseWheel: true,
    pressedMouseMove: false,
    horzTouchDrag: true,
    vertTouchDrag: false,
  }
  const chart = { options: () => ({ handleScroll: scroll }), applyOptions: vi.fn() }
  const container = document.createElement('div')
  container.getBoundingClientRect = () =>
    ({ top: 10, left: 0, right: 500, width: 500, height: 500 }) as DOMRect
  container.setPointerCapture = vi.fn()
  container.releasePointerCapture = vi.fn()
  const onEdit = vi.fn()
  const onClose = vi.fn()
  const layer = new DeltaOrderLayer(
    chart as unknown as IChartApi,
    series as unknown as ISeriesApi<'Candlestick'>,
    container,
    onEdit,
    onClose
  )
  const pointer = (type: string, price: number, id = 1) => {
    const event = new MouseEvent(type, {
      clientY: price + 10,
      clientX: 100,
      button: 0,
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'pointerId', { value: id })
    container.dispatchEvent(event)
    return event
  }
  const state: DeltaOrderLayerState = {
    connected: true,
    symbol: 'BTCUSD',
    product: { tick_size: 0.5 },
    position: { size: 1, entry: 100, liquidation: 50 },
    orders: [
      { id: 'sl', kind: 'sl', price: 90, state: 'open', version: 'v1' },
      { id: 'tp', kind: 'target', price: 120, state: 'pending', version: 'v1' },
      { id: 'entry', kind: 'entry', price: 80, state: 'open', version: 'v1' },
    ],
  }
  return {
    layer,
    state,
    lines,
    removed,
    onEdit,
    onClose,
    pointer,
    chart,
    scroll,
    container,
    series,
  }
}

describe('DeltaOrderLayer', () => {
  it('labels acknowledged entry, protection, liquidation and pending entry separately', () => {
    const f = fixture()
    f.layer.update(f.state)
    expect(f.lines.map((line) => line.options.title)).toEqual([
      'LIVE ENTRY',
      'LIQUIDATION',
      'LIVE SL #sl',
      'LIVE TARGET #tp',
      'PENDING ENTRY #entry',
    ])
    expect(f.lines.every((line) => line.options.lineVisible && line.options.axisLabelVisible)).toBe(
      true
    )
    expect(f.lines.map((line) => line.options.color)).toEqual([
      '#3b82f6',
      '#94a3b8',
      '#ef4444',
      '#22c55e',
      '#f59e0b',
    ])
    expect(f.onEdit).not.toHaveBeenCalled()
  })

  it('proposes a tick-rounded edit while retaining acknowledged price until refreshed', () => {
    const f = fixture()
    f.layer.update(f.state)
    expect(f.pointer('pointerdown', 91).defaultPrevented).toBe(true)
    f.pointer('pointermove', 94.3)
    expect(f.lines.at(-1)?.options.title).toBe('PROPOSED #sl')
    expect(f.lines[2].options.price).toBe(90)
    f.pointer('pointerup', 94.3)
    expect(f.onEdit).toHaveBeenCalledWith({ order_id: 'sl', price: 94.5, nonce: 1 })
    expect(f.removed).toHaveBeenCalledWith(f.lines.at(-1))
    expect(f.chart.applyOptions).toHaveBeenLastCalledWith({ handleScroll: f.scroll })
    expect(f.lines[2].options.price).toBe(90)
  })

  it('preserves a drag across unchanged polls and cancels on broker version change', () => {
    const f = fixture()
    f.layer.update(f.state)
    f.pointer('pointerdown', 90)
    f.layer.update(structuredClone(f.state))
    f.pointer('pointerup', 93)
    expect(f.onEdit).toHaveBeenCalledTimes(1)
    f.pointer('pointerdown', 90)
    f.layer.update({ ...f.state, orders: f.state.orders.map((o) => ({ ...o, version: 'v2' })) })
    f.pointer('pointerup', 95)
    expect(f.onEdit).toHaveBeenCalledTimes(1)
  })

  it('does not intercept candles, fixed position lines, closed orders, or no-op/cancelled drags', () => {
    const f = fixture()
    f.layer.update({
      ...f.state,
      orders: [
        ...f.state.orders,
        { id: 'closed', kind: 'sl', price: 160, state: 'closed', version: 'v1' },
      ],
    })
    expect(f.pointer('pointerdown', 200).defaultPrevented).toBe(false)
    expect(f.pointer('pointerdown', 100).defaultPrevented).toBe(false)
    expect(f.pointer('pointerdown', 160).defaultPrevented).toBe(false)
    f.pointer('pointerdown', 90)
    f.pointer('pointerup', 90.1)
    f.pointer('pointerdown', 90)
    f.pointer('pointercancel', 95)
    expect(f.onEdit).not.toHaveBeenCalled()
  })

  it('retains every ID at coincident prices and avoids ambiguous edits', () => {
    const f = fixture()
    f.layer.update({ ...f.state, orders: [...f.state.orders, { ...f.state.orders[0], id: 'sl2' }] })
    expect(f.lines[2].options.title).toBe('LIVE SL #sl / LIVE SL #sl2')
    expect(f.pointer('pointerdown', 90).defaultPrevented).toBe(false)
    f.pointer('pointerup', 95)
    expect(f.onEdit).not.toHaveBeenCalled()
  })

  it('ignores other pointers and cancels lost capture or release outside the chart', () => {
    const f = fixture()
    f.layer.update(f.state)
    f.pointer('pointerdown', 90)
    f.pointer('pointerup', 94, 2)
    expect(f.onEdit).not.toHaveBeenCalled()
    f.pointer('lostpointercapture', 94)
    f.pointer('pointerup', 94)
    f.pointer('pointerdown', 90)
    f.pointer('pointerup', 700)
    expect(f.onEdit).not.toHaveBeenCalled()
    expect(f.chart.applyOptions).toHaveBeenLastCalledWith({ handleScroll: f.scroll })
  })

  it('clears disconnected/disabled/missing state and removes all handlers on destroy', () => {
    const f = fixture()
    f.layer.update(f.state)
    f.pointer('pointerdown', 90)
    f.pointer('pointermove', 94)
    f.layer.update(null)
    f.pointer('pointerup', 94)
    expect(f.removed).toHaveBeenCalledTimes(f.lines.length)
    expect(f.onEdit).not.toHaveBeenCalled()
    f.layer.update(f.state, false)
    expect(f.lines).toHaveLength(6)
    f.layer.update({ ...f.state, connected: false })
    expect(f.lines).toHaveLength(6)
    f.layer.update(f.state)
    f.layer.destroy()
    f.layer.destroy()
    expect(f.pointer('pointerdown', 90).defaultPrevented).toBe(false)
    expect(f.removed).toHaveBeenCalledTimes(f.lines.length)
    const count = f.lines.length
    f.layer.update(f.state)
    expect(f.lines).toHaveLength(count)
  })
})

it('labels a resting reduce-only close as an exit instead of an entry', () => {
  const f = fixture()
  f.layer.update({
    ...f.state,
    orders: [
      { id: 'close', kind: 'entry', price: 110, state: 'open', version: 'v1', reduce_only: true },
    ],
  })
  expect(f.lines.some((line) => line.options.title === 'PENDING EXIT #close')).toBe(true)
  expect(f.lines.some((line) => line.options.title === 'PENDING ENTRY #close')).toBe(false)
})

it('shows a quantity/P&L badge with chart close review and removes it when flat or disabled', () => {
  const f = fixture()
  f.layer.update({ ...f.state, position: { ...f.state.position!, pnl: 0.14 } })
  const button = f.container.querySelector('button')!
  expect(button.getAttribute('aria-label')).toBe('Close Delta position from chart')
  expect(f.container.textContent).toContain('+₹11.90 before fees')
  button.click()
  expect(f.onClose).toHaveBeenCalledTimes(1)
  expect(f.onEdit).not.toHaveBeenCalled()
  f.layer.update({ ...f.state, position: null })
  expect(f.container.querySelector('button')).toBeNull()
  f.layer.update(f.state)
  f.layer.update(null, false)
  expect(f.container.querySelector('button')).toBeNull()
  f.layer.destroy()
})

it('keeps legacy market protection visible but does not pretend its type can be edited as maker-only', () => {
  const f = fixture()
  f.layer.update({ ...f.state, orders: [{ ...f.state.orders[0], type: 'market_order' }] })
  expect(f.lines.some((line) => String(line.options.title).includes('LIVE SL (MARKET)'))).toBe(true)
  f.pointer('pointerdown', 90)
  f.pointer('pointerup', 95)
  expect(f.onEdit).not.toHaveBeenCalled()
  f.layer.destroy()
})

it('uses verified net P&L in the position badge and labels gross fallback honestly', () => {
  const f = fixture()
  f.layer.update({
    ...f.state,
    position: { ...f.state.position!, pnl: 0.14 },
    accounting: { fee_status: 'verified', exit_fee_basis: 'taker', position_net_after_fees: 0.1 },
  })
  expect(f.container.textContent).toContain('+₹8.50 net')
  f.layer.update({
    ...f.state,
    position: { ...f.state.position!, pnl: 0.14 },
    accounting: { fee_status: 'incomplete', position_net_after_fees: null },
  })
  expect(f.container.textContent).toContain('+₹11.90 before fees')
  f.layer.destroy()
})

it('shows fee-deducted INR estimates at the stop and target without changing USD order prices', () => {
  const f = fixture()
  f.layer.update({
    ...f.state,
    product: { tick_size: 0.5, contract_value: 0.001 },
    position: { ...f.state.position!, mark: 110 },
    accounting: {
      fee_status: 'verified',
      position_net_after_fees: 0.005,
      position_entry_fees: 0.001,
      estimated_maker_exit_fee: 0.002,
      estimated_exit_fee: 0.002,
      exit_fee_basis: 'taker',
    },
  })
  const sl = f.container.querySelector('[data-delta-order="sl"]')!
  const tp = f.container.querySelector('[data-delta-order="tp"]')!
  expect(sl.textContent).toContain('−₹1.07 net est.')
  expect(tp.textContent).toContain('+₹1.43 net est.')
  expect(
    f.lines.find((line) => String(line.options.title).includes('LIVE SL'))?.options.price
  ).toBe(90)
  f.layer.update(null)
  expect(f.container.querySelector('[data-delta-order]')).toBeNull()
  f.layer.destroy()
})

it('keeps protective badges out of the volume and RSI panes', () => {
  const f = fixture()
  Object.assign(f.chart, { panes: () => [{ getHeight: () => 110 }] })
  f.layer.update(f.state)
  expect((f.container.querySelector('[data-delta-order="tp"]') as HTMLElement).style.display).toBe(
    'none'
  )
  expect(
    (f.container.querySelector('[data-delta-order="sl"]') as HTMLElement).style.display
  ).not.toBe('none')
  f.pointer('pointerdown', 90)
  f.pointer('pointerup', 120)
  expect(f.onEdit).not.toHaveBeenCalled()
  f.layer.destroy()
})
it('permits dragging reduce-only market SL triggers while market entries and exits stay non-draggable', () => {
  const f = fixture()
  f.layer.update({
    ...f.state,
    orders: [{ ...f.state.orders[0], type: 'market_order', reduce_only: true }],
  })
  f.pointer('pointerdown', 90)
  f.pointer('pointerup', 95)
  expect(f.onEdit).toHaveBeenCalledWith({ order_id: 'sl', price: 95, nonce: 1 })
  f.onEdit.mockClear()
  f.layer.update({
    ...f.state,
    orders: [{ ...f.state.orders[0], kind: 'entry', type: 'market_order', reduce_only: true }],
  })
  f.pointer('pointerdown', 90)
  f.pointer('pointerup', 95)
  expect(f.onEdit).not.toHaveBeenCalled()
  f.layer.destroy()
})
it('uses taker costs at market SL but maker costs for the resting target', () => {
  const f = fixture()
  f.layer.update({
    ...f.state,
    product: { tick_size: 0.5, contract_value: 0.001 },
    position: { ...f.state.position!, mark: 110 },
    accounting: {
      fee_status: 'verified',
      position_net_after_fees: 0,
      position_entry_fees: 0.001,
      estimated_maker_exit_fee: 0.002,
      estimated_exit_fee: 0.002,
      exit_fee_basis: 'taker',
      estimated_exit_fee: 0.005,
      exit_fee_basis: 'taker',
    },
  })
  expect(f.container.querySelector('[data-delta-order="sl"]')!.textContent).toContain(
    '−₹1.28 net est.'
  )
  expect(f.container.querySelector('[data-delta-order="tp"]')!.textContent).toContain(
    '+₹1.43 net est.'
  )
  f.layer.destroy()
})
