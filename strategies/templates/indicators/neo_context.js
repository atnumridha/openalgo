// Chart studies are visual context; executable strategy rules stay on the server.
export default function ({ registerIndicator, pivotHigh, pivotLow, nulls }) {
  registerIndicator({
    id: 'neo-donchian', name: 'Donchian 20 + EMA 200', category: 'Neo Desk', placement: 'onchart', inputs: [],
    plots: [
      { key: 'upper', type: 'line', title: 'Upper', style: { color: '#5b8def', lineWidth: 1, priceLineVisible: false, lastValueVisible: false } },
      { key: 'lower', type: 'line', title: 'Lower', style: { color: '#5b8def', lineWidth: 1, priceLineVisible: false, lastValueVisible: false } },
      { key: 'ema', type: 'line', title: 'EMA 200', style: { color: '#dca94c', lineWidth: 2, priceLineVisible: false, lastValueVisible: false } },
    ],
    calc(bars) {
      let seed = null
      const upper = [], lower = [], ema = []
      for (let i = 0; i < bars.length; i++) {
        const prior = bars.slice(Math.max(0, i - 20), i)
        upper.push(prior.length === 20 ? Math.max(...prior.map(b => b.high)) : null)
        lower.push(prior.length === 20 ? Math.min(...prior.map(b => b.low)) : null)
        seed = seed == null ? bars[i].close : seed + 2 / 201 * (bars[i].close - seed)
        ema.push(seed)
      }
      return { upper, lower, ema }
    },
  })
  registerIndicator({
    id: 'neo-structure', name: 'FVG + pivot levels', category: 'Neo Desk', placement: 'onchart',
    inputs: [
      { key: 'zones', label: 'Show unfilled FVG zones', type: 'boolean', default: true },
      { key: 'levels', label: 'Show nearest pivot support / resistance', type: 'boolean', default: true },
      { key: 'zoneCount', label: 'Maximum FVG zones', type: 'number', default: 3, min: 1, max: 6, step: 1 },
      { key: 'zoneLabels', label: 'Print FVG labels on candles', type: 'boolean', default: false },
    ],
    plots: [
      { key: 'ph', type: 'line', title: 'Confirmed resistance', style: { visible: false } },
      { key: 'pl', type: 'line', title: 'Confirmed support', style: { visible: false } },
    ],
    calc(bars) {
      return { ph: nulls(pivotHigh(bars.map(b => b.high), 3, 3)), pl: nulls(pivotLow(bars.map(b => b.low), 3, 3)) }
    },
    draws({ bars, values, settings = {} }) {
      if (bars.length < 8) return []
      const out = [], last = bars.length - 1, end = bars[last].time, close = bars[last].close
      const begin = Math.max(2, bars.length - 120)
      if (settings.zones !== false) {
        const zones = []
        // Only completed origin bars form a zone; later bars may fill it.
        for (let i = begin; i < last; i++) {
          const bull = bars[i].low > bars[i - 2].high
          const bear = bars[i].high < bars[i - 2].low
          if (!bull && !bear) continue
          // A session-opening gap is not a three-candle intraday FVG.
          const day = t => Math.floor((t + 19800) / 86400)
          if (day(bars[i].time) !== day(bars[i - 2].time)) continue
          const bottom = bull ? bars[i - 2].high : bars[i].high
          const top = bull ? bars[i].low : bars[i - 2].low
          let filled = false
          for (let j = i + 1; j <= last; j++) {
            if (bull ? bars[j].low <= bottom : bars[j].high >= top) { filled = true; break }
          }
          if (!filled) zones.push({ i, bottom, top, bull, distance: Math.min(Math.abs(close - bottom), Math.abs(close - top)) })
        }
        const limit = Math.min(6, Math.max(1, Math.floor(Number(settings.zoneCount) || 3)))
        for (const z of zones.sort((a, b) => a.distance - b.distance || b.i - a.i).slice(0, limit)) {
          const name = z.bull ? 'Bullish FVG' : 'Bearish FVG'
          out.push({ kind: 'box', from: { time: bars[z.i].time, price: z.bottom }, to: { time: end, price: z.top },
            color: z.bull ? '#26a69a' : '#ef5350', fillColor: z.bull ? '#26a69a' : '#ef5350', opacity: 0.06, lineWidth: 1,
            text: settings.zoneLabels === true ? name : undefined,
            tooltip: `${name}\n${z.bottom.toFixed(2)} – ${z.top.toFixed(2)}\nUnfilled three-candle price gap`, id: `fvg-${bars[z.i].time}-${z.bull ? 'bull' : 'bear'}`,
          })
        }
      }
      if (settings.levels !== false) {
        for (const [key, side, color] of [['ph', 'R', '#ef5350'], ['pl', 'S', '#26a69a']]) {
          const candidates = []
          // A pivot appears only after three subsequent completed bars confirm it.
          for (let i = begin; i + 3 < last; i++) {
            const price = values[key]?.[i]
            if (price != null && (key === 'ph' ? price >= close : price <= close)) candidates.push({ i, price })
          }
          candidates.sort((a, b) => Math.abs(a.price - close) - Math.abs(b.price - close) || b.i - a.i)
          const level = candidates[0]
          if (!level) continue
          out.push({ kind: 'line', from: { time: bars[level.i + 3].time, price: level.price }, to: { time: end, price: level.price }, color, lineWidth: 1, lineStyle: 'dashed' })
          out.push({ kind: 'label', at: { time: end, price: level.price }, text: `${side} ${level.price.toFixed(2)}`, color, textColor: '#ffffff', fontSize: 10, align: 'right',
            tooltip: key === 'ph' ? 'Confirmed pivot resistance / potential buy-stop liquidity' : 'Confirmed pivot support / potential sell-stop liquidity' })
        }
      }
      return out
    },
  })
}
