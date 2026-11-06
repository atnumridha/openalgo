import { DELTA_USD_INR } from '../neo-desk/deltaMoney'
import type { IChartApi, IPriceLine, ISeriesApi } from 'lightweight-charts'

/** Structural subset of the broker snapshot; this layer never submits a trade. */
export interface DeltaOrderLayerState {
  connected: boolean
  symbol: string
  account?: string
  product: { id?: number; tick_size: number; contract_value?: number }
  position: {
    size: number
    entry: number
    liquidation: number | null
    pnl?: number | null
    mark?: number
  } | null
  accounting?: {
    fee_status: string
    position_net_after_fees: number | null
    position_entry_fees?: number | null
    estimated_maker_exit_fee?: number | null
    estimated_exit_fee?: number | null
    exit_fee_basis?: 'maker' | 'taker'
  } | null
  orders: readonly {
    id: string
    size?: number
    kind: 'entry' | 'sl' | 'target'
    reduce_only?: boolean
    type?: 'limit_order' | 'market_order'
    price: number | null
    state: string
    version: string
  }[]
}

export interface DeltaOrderEditProposal {
  order_id: string
  price: number
  nonce: number
}

type Order = DeltaOrderLayerState['orders'][number]
type Drag = {
  pointerId: number
  order: Order
  tick: number
  offsetY: number
  preview: IPriceLine | null
  scroll: ReturnType<IChartApi['options']>['handleScroll']
}

const positive = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0
const plottable = (order: Order) =>
  Boolean(order.id) && positive(order.price) && ['open', 'pending'].includes(order.state)
const editable = (order: Order) =>
  plottable(order) &&
  (order.type !== 'market_order' || (order.kind === 'sl' && order.reduce_only === true))

/** Broker-owned lines stay at acknowledged prices while a drag produces a review proposal. */
export class DeltaOrderLayer {
  private state: DeltaOrderLayerState | null = null
  private lines: IPriceLine[] = []
  private drag: Drag | null = null
  private key = ''
  private nonce = 0
  private destroyed = false
  private closeBadge: HTMLDivElement | null = null
  private orderBadges = new Map<string, HTMLDivElement>()
  private onClose?: () => void
  private chart: IChartApi
  private series: ISeriesApi<'Candlestick'>
  private container: HTMLElement
  private onEdit: (proposal: DeltaOrderEditProposal) => void
  private labels = new Map<number, { line: IPriceLine; title: string }>()

  constructor(
    chart: IChartApi,
    series: ISeriesApi<'Candlestick'>,
    container: HTMLElement,
    onEdit: (proposal: DeltaOrderEditProposal) => void,
    onClose?: () => void
  ) {
    this.chart = chart
    this.series = series
    this.container = container
    this.onEdit = onEdit
    this.onClose = onClose
    this.chart.subscribeCrosshairMove?.(this.positionBadge)
    container.addEventListener('pointerdown', this.onDown, true)
    container.addEventListener('pointermove', this.onMove, true)
    container.addEventListener('pointerup', this.onUp, true)
    container.addEventListener('pointercancel', this.onCancel, true)
    container.addEventListener('lostpointercapture', this.onCancel, true)
    // Window handlers also cover browsers where pointer capture is unavailable.
    window.addEventListener('pointermove', this.onMove, true)
    window.addEventListener('pointerup', this.onUp, true)
    window.addEventListener('pointercancel', this.onCancel, true)
    window.addEventListener('blur', this.cancelDrag)
  }

  update(state: DeltaOrderLayerState | null, enabled = true) {
    if (this.destroyed) return
    const next = enabled && state?.connected ? state : null
    const key = next
      ? JSON.stringify([
          next.symbol,
          next.account,
          next.product.id,
          next.product.tick_size,
          next.position && [next.position.size, next.position.entry, next.position.liquidation],
          next.orders.map((order) => [
            order.id,
            order.kind,
            order.price,
            order.state,
            order.version,
            order.reduce_only,
            order.type,
          ]),
        ])
      : ''
    this.state = next
    this.positionBadge()
    if (key === this.key) return
    this.cancelDrag()
    this.clearLines()
    this.key = key
    if (!next) return
    if (next.position && next.position.size !== 0) {
      this.addLine(next.position.entry, '#3b82f6', 'LIVE ENTRY')
      this.addLine(next.position.liquidation, '#94a3b8', 'LIQUIDATION', 2)
    }
    for (const order of next.orders) {
      if (!plottable(order)) continue
      this.addLine(
        order.price,
        order.kind === 'sl' ? '#ef4444' : order.kind === 'target' ? '#22c55e' : '#f59e0b',
        `${order.kind === 'sl' ? 'LIVE SL' : order.kind === 'target' ? 'LIVE TARGET' : order.reduce_only ? 'PENDING EXIT' : 'PENDING ENTRY'}${order.type === 'market_order' ? ' (MARKET)' : ''} #${order.id}`
      )
    }
  }

  private pricePaneHeight() {
    return this.chart.panes?.()[0]?.getHeight?.() ?? this.container.getBoundingClientRect().height
  }

  private positionBadge = () => {
    this.protectionBadges()
    const position = this.state?.position
    if (
      this.destroyed ||
      !position ||
      !Number.isFinite(position.size) ||
      position.size === 0 ||
      !this.onClose
    ) {
      this.closeBadge?.remove()
      this.closeBadge = null
      return
    }
    if (!this.closeBadge) {
      const badge = document.createElement('div')
      badge.className =
        'absolute right-24 z-30 flex items-center overflow-hidden rounded border bg-background text-xs shadow-sm'
      badge.dataset.deltaPosition = 'true'
      const label = document.createElement('span')
      label.className = 'px-2 py-1 tabular-nums'
      const close = document.createElement('button')
      close.type = 'button'
      close.className =
        'border-l px-2 py-1 font-bold hover:bg-muted focus-visible:outline focus-visible:outline-ring'
      close.setAttribute('aria-label', 'Close Delta position from chart')
      close.title = 'Review a reduce-only market close of this position'
      close.textContent = '×'
      close.addEventListener('pointerdown', (event) => event.stopPropagation())
      close.addEventListener('click', (event) => {
        event.stopPropagation()
        if (this.state?.position) this.onClose?.()
      })
      badge.append(label, close)
      this.container.append(badge)
      this.closeBadge = badge
    }
    const y = this.series.priceToCoordinate(position.entry)
    const height = this.pricePaneHeight()
    this.closeBadge.style.top = `${y != null && y > 18 && y < height - 28 ? y - 14 : 18}px`
    const net =
      this.state?.accounting?.fee_status === 'verified' &&
      this.state.accounting.exit_fee_basis === 'taker'
        ? this.state.accounting.position_net_after_fees
        : null
    const hasNet = typeof net === 'number' && Number.isFinite(net)
    const pnl = hasNet ? net : position.pnl
    const known = typeof pnl === 'number' && Number.isFinite(pnl)
    this.closeBadge.style.borderColor = known && pnl < 0 ? '#ef4444' : '#10b981'
    this.closeBadge.style.color = known && pnl < 0 ? '#ef4444' : '#10b981'
    this.closeBadge.firstElementChild!.textContent =
      `${Math.abs(position.size)} lots · ${known ? `${pnl >= 0 ? '+' : ''}₹${(pnl * DELTA_USD_INR).toFixed(2)} ${hasNet ? 'net' : 'before fees'}` : 'Live position'}`
  }

  private protectionBadges() {
    const state = this.state,
      position = state?.position
    const orders =
      position && position.size !== 0 && !this.destroyed
        ? state!.orders.filter(
            (order) => plottable(order) && (order.kind === 'sl' || order.kind === 'target')
          )
        : []
    const active = new Set(orders.map((order) => order.id))
    for (const [id, badge] of this.orderBadges)
      if (!active.has(id)) {
        badge.remove()
        this.orderBadges.delete(id)
      }
    for (const order of orders) {
      let badge = this.orderBadges.get(order.id)
      if (!badge) {
        badge = document.createElement('div')
        badge.className =
          'absolute right-24 z-20 rounded border bg-background px-2 py-1 text-[10px] shadow-sm tabular-nums'
        badge.dataset.deltaOrder = order.id
        badge.title = editable(order)
          ? 'Drag to review this order price'
          : 'Existing market stop; review automatic SL to replace safely'
        this.container.append(badge)
        this.orderBadges.set(order.id, badge)
      }
      const y = this.series.priceToCoordinate(order.price!)
      const height = this.pricePaneHeight()
      badge.style.display = y == null || y < 0 || y > height ? 'none' : ''
      badge.style.top = `${(y ?? 0) - 12}px`
      const color = order.kind === 'sl' ? '#ef4444' : '#10b981'
      badge.style.color = color
      badge.style.borderColor = color
      badge.style.cursor = editable(order) ? 'ns-resize' : 'default'
      const value = this.projectedPnl(order)
      badge.textContent = `${order.kind === 'sl' ? 'SL' : 'Target'} · ${value ?? 'Live order'}`
    }
  }

  private projectedPnl(order: Order): string | null {
    const state = this.state,
      position = state?.position
    const cv = state?.product.contract_value
    if (
      !position ||
      !positive(cv) ||
      !positive(order.price) ||
      !Number.isFinite(position.size) ||
      !position.size
    )
      return null
    const quantity = positive(order.size)
      ? Math.min(Math.abs(position.size), order.size)
      : Math.abs(position.size)
    let pnl = (order.price - position.entry) * quantity * cv * (position.size > 0 ? 1 : -1)
    const accounting = state?.accounting
    const entryFees = accounting?.position_entry_fees,
      exitFees =
        order.kind === 'sl'
          ? accounting?.exit_fee_basis === 'taker'
            ? accounting.estimated_exit_fee
            : null
          : accounting?.estimated_maker_exit_fee
    const net =
      accounting?.fee_status === 'verified' &&
      typeof entryFees === 'number' &&
      Number.isFinite(entryFees) &&
      entryFees >= 0 &&
      typeof exitFees === 'number' &&
      Number.isFinite(exitFees) &&
      exitFees >= 0 &&
      positive(position.mark)
    if (net)
      pnl -=
        (quantity / Math.abs(position.size)) *
        (entryFees! + (exitFees! * order.price) / position.mark!)
    if (!Number.isFinite(pnl)) return null
    return `${pnl >= 0 ? '+' : '−'}₹${Math.abs(pnl * DELTA_USD_INR).toFixed(2)} ${net ? 'net est.' : 'before fees'}`
  }

  private addLine(price: number | null, color: string, title: string, lineStyle: 0 | 2 = 0) {
    if (!positive(price)) return
    const existing = this.labels.get(price)
    if (existing) {
      existing.title += ` / ${title}`
      existing.line.applyOptions({ title: existing.title })
      return
    }
    const line = this.series.createPriceLine({
      price,
      color,
      title,
      lineWidth: 2,
      lineStyle,
      lineVisible: true,
      axisLabelVisible: true,
    })
    this.lines.push(line)
    this.labels.set(price, { line, title })
  }

  private clearLines() {
    for (const line of this.lines) this.series.removePriceLine(line)
    this.lines = []
    this.labels.clear()
  }

  private coordinate(event: PointerEvent): number | null {
    const bounds = this.container.getBoundingClientRect()
    const y = event.clientY - bounds.top
    if (
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      y < 0 ||
      y > this.pricePaneHeight()
    )
      return null
    return y
  }

  private proposedPrice(event: PointerEvent): number | null {
    if (!this.drag) return null
    const coordinate = this.coordinate(event)
    if (coordinate == null) return null
    const price = this.series.coordinateToPrice(coordinate - this.drag.offsetY)
    if (!positive(price)) return null
    // Remove binary floating-point tails, including for fractional/sub-cent ticks.
    const rounded = Number((Math.round(price / this.drag.tick) * this.drag.tick).toPrecision(14))
    return positive(rounded) ? rounded : null
  }

  private onDown = (event: PointerEvent) => {
    if (event.target instanceof Element && event.target.closest('[data-delta-position]')) return
    if (this.destroyed || this.drag || event.button !== 0 || event.isPrimary === false) return
    const state = this.state
    const y = this.coordinate(event)
    if (!state || y == null || !positive(state.product.tick_size)) return
    const badgeId =
      event.target instanceof Element
        ? event.target.closest<HTMLElement>('[data-delta-order]')?.dataset.deltaOrder
        : undefined
    const candidates = state.orders
      .filter((order) => editable(order) && (!badgeId || order.id === badgeId))
      .flatMap((order) => {
        const coordinate = this.series.priceToCoordinate(order.price!)
        return coordinate != null && (badgeId || Math.abs(coordinate - y) <= 6)
          ? [{ order, distance: Math.abs(coordinate - y) }]
          : []
      })
      .sort((a, b) => a.distance - b.distance)
    if (!candidates.length) return
    // Overlapping broker orders are ambiguous: use the order panel to choose their ID.
    if (candidates[1] && Math.abs(candidates[0].distance - candidates[1].distance) < 0.01) return
    const scroll = this.chart.options().handleScroll
    this.drag = {
      pointerId: event.pointerId,
      order: { ...candidates[0].order },
      tick: state.product.tick_size,
      offsetY: badgeId ? y - (this.series.priceToCoordinate(candidates[0].order.price!) ?? y) : 0,
      preview: null,
      scroll: typeof scroll === 'object' ? { ...scroll } : scroll,
    }
    this.chart.applyOptions({ handleScroll: false })
    event.preventDefault()
    event.stopImmediatePropagation()
    try {
      this.container.setPointerCapture(event.pointerId)
    } catch {
      /* Window handlers remain active. */
    }
  }

  private onMove = (event: PointerEvent) => {
    this.positionBadge()
    const drag = this.drag
    if (!drag || event.pointerId !== drag.pointerId) return
    event.preventDefault()
    event.stopImmediatePropagation()
    const price = this.proposedPrice(event)
    if (price == null) return
    if (drag.preview) drag.preview.applyOptions({ price })
    else
      drag.preview = this.series.createPriceLine({
        price,
        color: '#94a3b8',
        title: `PROPOSED #${drag.order.id}`,
        lineWidth: 1,
        lineStyle: 2,
        lineVisible: true,
        axisLabelVisible: true,
      })
  }

  private onUp = (event: PointerEvent) => {
    const drag = this.drag
    if (!drag || event.pointerId !== drag.pointerId) return
    const price = this.proposedPrice(event)
    event.preventDefault()
    event.stopImmediatePropagation()
    this.cancelDrag()
    if (price != null && Math.abs(price - drag.order.price!) > drag.tick * 1e-8)
      this.onEdit({ order_id: drag.order.id, price, nonce: ++this.nonce })
  }

  private onCancel = (event: PointerEvent) => {
    if (this.drag && event.pointerId === this.drag.pointerId) this.cancelDrag()
  }

  private cancelDrag = () => {
    const drag = this.drag
    if (!drag) return
    this.drag = null
    if (drag.preview) this.series.removePriceLine(drag.preview)
    this.chart.applyOptions({ handleScroll: drag.scroll })
    try {
      this.container.releasePointerCapture(drag.pointerId)
    } catch {
      /* Capture may already be lost. */
    }
  }

  destroy() {
    if (this.destroyed) return
    this.cancelDrag()
    this.clearLines()
    this.state = null
    this.key = ''
    this.destroyed = true
    this.closeBadge?.remove()
    this.closeBadge = null
    for (const badge of this.orderBadges.values()) badge.remove()
    this.orderBadges.clear()
    this.chart.unsubscribeCrosshairMove?.(this.positionBadge)
    this.container.removeEventListener('pointerdown', this.onDown, true)
    this.container.removeEventListener('pointermove', this.onMove, true)
    this.container.removeEventListener('pointerup', this.onUp, true)
    this.container.removeEventListener('pointercancel', this.onCancel, true)
    this.container.removeEventListener('lostpointercapture', this.onCancel, true)
    window.removeEventListener('pointermove', this.onMove, true)
    window.removeEventListener('pointerup', this.onUp, true)
    window.removeEventListener('pointercancel', this.onCancel, true)
    window.removeEventListener('blur', this.cancelDrag)
  }
}
