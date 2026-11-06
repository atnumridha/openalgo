export interface LabelRegion {
  left: number
  right: number
  top: number
  bottom: number
  text: string
}

/** Hover the rendered label rectangle, rather than the candle or its pointer. */
export class PatternLabelTooltip {
  private regions: LabelRegion[] = []
  private popup: HTMLDivElement
  private lastPointer: PointerEvent | null = null
  private root: HTMLElement
  constructor(root: HTMLElement) {
    this.root = root
    this.popup = document.createElement('div')
    this.popup.setAttribute('role', 'tooltip')
    Object.assign(this.popup.style, {
      display: 'none',
      position: 'fixed',
      zIndex: '10000',
      pointerEvents: 'none',
      maxWidth: '300px',
      padding: '10px 12px',
      borderRadius: '6px',
      border: '1px solid #475569',
      background: '#111827',
      color: '#f1f5f9',
      font: '12px/1.5 Inter, system-ui, sans-serif',
      whiteSpace: 'pre-line',
      boxShadow: '0 4px 16px #0006',
    })
    root.ownerDocument.body.append(this.popup)
    root.addEventListener('pointermove', this.move)
    root.addEventListener('pointerleave', this.hide)
    root.addEventListener('pointerdown', this.hide)
    root.ownerDocument.defaultView?.addEventListener('scroll', this.hide, true)
  }
  private hide = () => {
    this.popup.style.display = 'none'
    this.lastPointer = null
  }
  private move = (event: PointerEvent) => {
    const rect = this.root.getBoundingClientRect()
    const x = event.clientX - rect.left,
      y = event.clientY - rect.top
    const region = [...this.regions]
      .reverse()
      .find((r) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom)
    if (!region) {
      this.hide()
      return
    }
    this.lastPointer = event
    this.popup.textContent = region.text
    this.popup.style.display = 'block'
    const view = this.root.ownerDocument.defaultView
    const width = this.popup.offsetWidth,
      height = this.popup.offsetHeight
    this.popup.style.left = `${Math.max(8, Math.min(event.clientX + 14, (view?.innerWidth ?? 1024) - width - 8))}px`
    const below = event.clientY + 18
    this.popup.style.top = `${Math.max(8, below + height < (view?.innerHeight ?? 768) - 8 ? below : event.clientY - height - 12)}px`
  }
  setRegions(regions: LabelRegion[]) {
    this.regions = regions
    if (this.lastPointer) this.move(this.lastPointer)
    else this.hide()
  }
  dispose() {
    this.root.removeEventListener('pointermove', this.move)
    this.root.removeEventListener('pointerleave', this.hide)
    this.root.removeEventListener('pointerdown', this.hide)
    this.root.ownerDocument.defaultView?.removeEventListener('scroll', this.hide, true)
    this.popup.remove()
    this.regions = []
  }
}
