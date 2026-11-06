import type {
  ISeriesApi, ISeriesPrimitive, IPrimitivePaneRenderer, SeriesAttachedParameter,
  SeriesMarker, Time, UTCTimestamp,
} from 'lightweight-charts'

/** Fixed-size X strokes stay visible independently of the chart's small label font. */
export class EmaCrossMarks implements ISeriesPrimitive<Time>, IPrimitivePaneRenderer {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private marks: readonly SeriesMarker<UTCTimestamp>[] = []
  private readonly views = [{zOrder: () => 'top' as const, renderer: () => this}]
  private readonly dark: boolean
  constructor(series: ISeriesApi<'Line'>, dark: boolean) {
    this.dark = dark
    series.attachPrimitive(this)
  }
  attached(value: SeriesAttachedParameter<Time>) { this.attachment = value }
  detached() { this.attachment = null; this.marks = [] }
  setMarkers(marks: readonly SeriesMarker<UTCTimestamp>[]) {
    this.marks = marks
    this.attachment?.requestUpdate()
  }
  paneViews() { return this.views }
  draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]) {
    const a = this.attachment
    if (!a || !this.marks.length) return
    // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate API
    target.useMediaCoordinateSpace(({context:c,mediaSize}) => {
      c.save();c.setLineDash([]);c.lineCap='round'
      for (const m of this.marks) {
        if (!('price' in m) || typeof m.price !== 'number' || !Number.isFinite(m.price)) continue
        const x=a.chart.timeScale().timeToCoordinate(m.time), y=a.series.priceToCoordinate(m.price)
        if (x===null || y===null || !Number.isFinite(x) || !Number.isFinite(y) || x < -12 || y < -12 || x > mediaSize.width+12 || y > mediaSize.height+12) continue
        c.beginPath();c.moveTo(x-8,y-8);c.lineTo(x+8,y+8);c.moveTo(x-8,y+8);c.lineTo(x+8,y-8)
        c.lineWidth=8;c.strokeStyle=this.dark?'#11151e':'#ffffff';c.stroke()
        c.lineWidth=4;c.strokeStyle=m.color;c.stroke()
      }
      c.restore()
    })
  }
}
