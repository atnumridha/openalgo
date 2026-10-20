const validCandle = (b) => b && [b.open, b.high, b.low, b.close].every(Number.isFinite)
  && b.low > 0 && b.low <= Math.min(b.open, b.close) && b.high >= Math.max(b.open, b.close)

// Shared deterministic evaluator: completed confirmation, then a subsequent
// price break. OHLC cannot establish the order of competing intrabar touches.
// Selection, strength, expiry and buffer are app rules; see the source notes.
export function evaluateLiquiditySetup(bars, references, options = {}) {
  const { seconds = 60, tick = 0, mode = 'verified' } = options
  const continuation = mode === 'continuation' || mode === 'protected'
  const reversal = mode === 'reversal' || mode === 'verified'
  const history = [], active = new Map(), used = new Set(), firstPullbacks = new Set()
  let plan = null, cursor = 0
  const reason = mode === 'off' ? 'Setup overlay off' : !(tick > 0) ? 'Broker tick size unavailable'
    : seconds > 300 ? 'Use 1m or 5m candles for entry confirmation' : ''
  if (reason || !bars.length) return { plan, history: bars.map(() => null), reason }
  const strength = Math.max(1, Math.min(6, Math.round(Number(options.strength) || 2)))
  const lookback = Math.max(8, Math.min(100, Math.round(Number(options.trendBars) || 20)))
  const buffer = tick * Math.max(0, Math.round(Number(options.bufferTicks) || 0))
  const wait = Math.max(0, Math.min(100, Math.round(Number(options.maxWaitBars) || 0)))
  const bodyMinimum = Math.max(0.1, Math.min(1, Number(options.opposingBodyMin) || 0.5))
  const smallMaximum = Math.max(0.1, Math.min(1.5, Number(options.smallCandleRatio) || 0.75))
  const bodyRatio = (b) => b.high > b.low ? Math.abs(b.close - b.open) / (b.high - b.low) : 0
  const up = (p) => Number((Math.ceil((p - tick * 1e-8) / tick) * tick).toFixed(8))
  const down = (p) => Number((Math.floor((p + tick * 1e-8) / tick) * tick).toFixed(8))
  const events = references.slice().sort((a, b) => a.knownIndex - b.knownIndex || a.id.localeCompare(b.id))
  const pending = (p) => p && ['WAITING CONFIRMATION', 'WAITING RESPONSE', 'WAITING OPPOSITION', 'WATCHING ENTRY'].includes(p.stage)
  const live = (p) => pending(p) || p?.stage === 'TRIGGERED'
  const finish = (stage, i) => { plan.stage = stage; plan.endedAt = bars[i].time }

  for (let i = 0; i < bars.length; i++) {
    const b = bars[i], prev = bars[i - 1]
    const closed = i < bars.length - 1 || options.lastConfirmed === true
    const continuous = validCandle(b) && (!prev || (validCandle(prev) && b.time === prev.time + seconds))
    if (!continuous) {
      if (live(plan)) finish('DATA GAP', i)
      active.clear()
    }
    while (cursor < events.length && events[cursor].knownIndex <= i) {
      const e = events[cursor++]
      if ((reversal || mode === 'rally') && Number.isFinite(e.price)) active.set(`${e.frameKey}:${e.side}`, { ...e })
    }
    // Native lower-timeframe pullbacks only become available after all right
    // candles close. The previous trend extreme must still be untouched.
    if (continuation && i >= lookback + strength * 2 + 1 && continuous) {
      const end = i - 1, p = end - strength, window = bars.slice(p - strength, end + 1)
      if (window.every((v, k) => validCandle(v) && (!k || v.time === window[k - 1].time + seconds))) {
        for (const side of ['Low', 'High']) {
          const low = side === 'Low', field = low ? 'low' : 'high', price = bars[p][field]
          if (!window.every((v) => v === bars[p] || (low ? v[field] > price : v[field] < price))) continue
          const from = Math.max(0, p - lookback), prior = bars.slice(from, p)
          const targetField = low ? 'high' : 'low'
          const target = (low ? Math.max : Math.min)(...prior.map((v) => v[targetField]))
          const targetIndex = from + prior.findLastIndex((v) => v[targetField] === target)
          const retracement = bars.slice(targetIndex, i)
          if (!retracement.every((v, k) => validCandle(v) && (!k || v.time === retracement[k - 1].time + seconds))) continue
          const trend = bars.slice(Math.max(0, targetIndex - lookback + 1), targetIndex + 1)
          if (trend.length < lookback || !trend.every((v, k) => validCandle(v) && (!k || v.time === trend[k - 1].time + seconds))) continue
          const change = trend.at(-1).close - trend[0].open
          const travel = trend.reduce((sum, v, k) => sum + Math.abs(v.close - (k ? trend[k - 1].close : v.open)), 0)
          if (!(low ? change > 0 : change < 0) || !(travel > 0 && Math.abs(change) / travel >= 0.55)) continue
          if (bars.slice(targetIndex + 1, i).some((v) => low ? v.high >= target : v.low <= target)) continue
          const key = `${side}:${bars[targetIndex].time}`
          if (firstPullbacks.has(key)) continue
          firstPullbacks.add(key)
          active.set(side, { id: `pullback:${bars[p].time}:${side}`, frame: 'Pullback', side,
            frameKey: 'entry', price, target, targetIndex, knownIndex: i, pivotTime: bars[p].time })
        }
      }
    }
    if (continuation) {
      for (const [key, r] of active) {
        const targetTaken = r.side === 'Low' ? b.high >= r.target : b.low <= r.target
        const breached = mode === 'protected' && (r.side === 'Low' ? b.low < r.price : b.high > r.price)
        if (targetTaken || breached) active.delete(key)
      }
    }
    if (continuous && live(plan)) {
      const long = plan.direction === 'LONG'
      const targetHit = plan.target != null && (long ? b.high >= plan.target : b.low <= plan.target)
      if (plan.stage === 'TRIGGERED') {
        if (mode === 'rally' && i > plan.triggerIndex && prev) {
          if (long ? prev.close > prev.open : prev.close < prev.open) {
            const nextSl = long ? down(prev.low - buffer) : up(prev.high + buffer)
            const tighter = long ? nextSl > plan.sl && nextSl < prev.close : nextSl < plan.sl && nextSl > prev.close
            if (tighter) { plan.sl = nextSl; plan.trailAt = b.time }
          } else if (long ? prev.close < prev.open : prev.close > prev.open) {
            plan.exitBoundary = long ? prev.low : prev.high
          }
        }
        const stopHit = long ? b.low <= plan.sl : b.high >= plan.sl
        if (stopHit && targetHit) finish('AMBIGUOUS', i)
        else if (stopHit) finish('SL REACHED', i)
        else if (targetHit) finish('TARGET REACHED', i)
        else if (mode === 'rally' && plan.exitBoundary != null && (long ? b.low < plan.exitBoundary : b.high > plan.exitBoundary)) {
          plan.exitPrice = plan.exitBoundary; finish('RALLY EXIT', i)
        }
        if (long ? b.high >= plan.entry + plan.initialRisk : b.low <= plan.entry - plan.initialRisk) plan.oneRReachedAt ??= b.time
      } else if (mode === 'verified' && active.get(`${plan.reference.frameKey}:${plan.reference.side}`)?.id !== plan.reference.id) finish('REFERENCE REPLACED', i)
      else if (wait > 0 && i - plan.sweepIndex >= wait) finish('EXPIRED', i)
      else if (mode === 'protected' && (long ? b.low < plan.reference.price : b.high > plan.reference.price)) {
        const crossesEntry = plan.stage === 'WATCHING ENTRY' && i > plan.signalIndex && (long ? b.high > plan.entry : b.low < plan.entry)
        finish(crossesEntry ? 'AMBIGUOUS' : 'PROTECTED LEVEL BROKEN', i)
      }
      else if (continuation && (long ? b.high >= plan.reference.target : b.low <= plan.reference.target)) {
        const crossesEntry = plan.stage === 'WATCHING ENTRY' && i > plan.signalIndex && (long ? b.high > plan.entry : b.low < plan.entry)
        finish(crossesEntry ? 'AMBIGUOUS' : 'TARGET ALREADY TAKEN', i)
      }
      else if (plan.stage === 'WATCHING ENTRY' && i > plan.signalIndex) {
        const entryHit = long ? b.high > plan.entry : b.low < plan.entry
        const stopHit = long ? b.low <= plan.sl : b.high >= plan.sl
        if (entryHit && (stopHit || targetHit)) finish('AMBIGUOUS', i)
        else if (stopHit) finish('INVALIDATED', i)
        else if (entryHit) { plan.stage = 'TRIGGERED'; plan.triggeredAt = b.time; plan.triggerIndex = i }
      }
    }
    if (continuous && !live(plan) && (!plan || plan.endedAt < b.time)) {
      const candidates = [...active.values()].filter((r) => mode !== 'rally' && !used.has(r.id) && prev && i >= r.knownIndex
        && (mode === 'protected' ? closed && bodyRatio(b) >= bodyMinimum && (r.side === 'Low'
          ? b.low >= r.price && b.close > b.open
          : b.high <= r.price && b.close < b.open)
          : r.side === 'Low' ? prev.close >= r.price && b.low < r.price : prev.close <= r.price && b.high > r.price))
        .sort((a, z) => z.knownIndex - a.knownIndex || a.id.localeCompare(z.id))
      if (mode === 'rally' && closed && i >= lookback) {
        const trend = bars.slice(i - lookback, i)
        const path = trend.reduce((sum, v, k) => sum + Math.abs(v.close - (k ? trend[k - 1].close : v.open)), 0)
        const displacement = trend.at(-1).close - trend[0].open
        const meanRange = trend.reduce((sum, v) => sum + v.high - v.low, 0) / lookback
        const clean = trend.every((v, k) => validCandle(v) && (!k || v.time === trend[k - 1].time + seconds))
        if (clean && path > 0 && Math.abs(displacement) / path >= 0.55 && b.high - b.low <= meanRange * smallMaximum
          && (displacement > 0 ? b.close > b.open : b.close < b.open)) {
          candidates.push({ id: `rally:${b.time}`, frame: 'Rally', frameKey: 'entry', side: displacement > 0 ? 'Low' : 'High',
            price: displacement > 0 ? b.low : b.high, knownIndex: i })
        }
      }
      const r = candidates[0]
      if (r) {
        used.add(r.id)
        plan = { id: `${mode}:${r.id}:${b.time}`, strategy: mode, reference: { ...r },
          direction: r.side === 'Low' ? 'LONG' : 'SHORT', stage: mode === 'verified' ? 'WAITING RESPONSE' : 'WAITING CONFIRMATION',
          sweepIndex: i, sweepAt: b.time, extreme: r.side === 'Low' ? b.low : b.high,
          entry: null, sl: null, target: null }
      }
    }
    if (continuous && plan && ['WAITING CONFIRMATION', 'WAITING RESPONSE', 'WAITING OPPOSITION'].includes(plan.stage)) {
      const long = plan.direction === 'LONG'
      plan.extreme = long ? Math.min(plan.extreme, b.low) : Math.max(plan.extreme, b.high)
      const directional = long ? b.close > b.open : b.close < b.open
      if (plan.stage === 'WAITING RESPONSE' && closed && directional) {
        plan.response = { index: i, time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }
        plan.stage = 'WAITING OPPOSITION'
      } else if (plan.stage === 'WAITING OPPOSITION' && closed && i > plan.response.index && !directional
        && bodyRatio(b) >= bodyMinimum && (long ? b.close < plan.response.open : b.close > plan.response.open)) {
        plan.opposition = { index: i, time: b.time, high: b.high, low: b.low, open: b.open, close: b.close }
        plan.stage = 'WAITING CONFIRMATION'
      }
      const ready = plan.stage === 'WAITING CONFIRMATION' && closed && (mode === 'verified' ? plan.opposition?.index === i : directional)
      if (ready) {
        plan.entry = long ? up(b.high) : down(b.low)
        const stopArea = mode === 'protected' ? plan.reference.price : plan.extreme
        plan.sl = long ? down(stopArea - buffer) : up(stopArea + buffer)
        plan.initialSl = plan.sl; plan.initialRisk = Math.abs(plan.entry - plan.sl)
        const targets = continuation ? [plan.reference.target] : [...active.values()]
          .filter((r) => r.side === (long ? 'High' : 'Low')).map((r) => r.price)
        const eligible = targets.filter((p) => long ? p > plan.entry : p < plan.entry)
        const target = eligible.length ? (long ? Math.min : Math.max)(...eligible) : null
        plan.target = target == null ? null : long ? down(target) : up(target)
        plan.signalIndex = i; plan.signalAt = b.time; plan.confirmedAt = b.time + seconds
        plan.rr = plan.target == null ? null : Math.abs(plan.target - plan.entry) / Math.abs(plan.entry - plan.sl)
        plan.stage = plan.sl <= 0 ? 'INVALID STOP' : plan.target == null || !(plan.rr > 0) ? 'NO TARGET' : 'WATCHING ENTRY'
        if (plan.stage !== 'WATCHING ENTRY') plan.endedAt = b.time
      }
    }
    history.push(plan ? { ...plan, reference: { ...plan.reference } } : null)
  }
  return { plan, history, reason: plan ? '' : continuation
    ? 'Waiting for strong trend, first pullback and untouched target' : mode === 'rally'
      ? 'Waiting for a strong rally and small completed candle' : 'Waiting for a liquidity sweep' }
}

/**
 * Potential liquidity around confirmed 1H / 4H / daily V/W and inverted-V/M swings.
 * Draft/source file: validate with the chart-indicator gate before installing.
 * Uses native chart bars and the library's higher-timeframe fold, never orders
 * or order-book data. A missing candle invalidates its whole reference period.
 */
export default function ({ registerIndicator, securitySeries, intervalToSeconds, IndicatorInputError, pivotHigh, pivotLow, atr, trueRange }) {
  const frames = [
    { key: 'h1', label: '1H', interval: '1h', seconds: 3600, toggle: 'show1H', style: 'dotted', width: 3 },
    { key: 'h4', label: '4H', interval: '4h', seconds: 14400, toggle: 'show4H', style: 'dashed', width: 3 },
    { key: 'd1', label: '1D', interval: '1d', seconds: 86400, toggle: 'show1D', style: 'solid', width: 4 },
  ]
  const valid = (b) => [b.open, b.high, b.low, b.close].every(Number.isFinite)
    && b.low > 0 && b.low <= Math.min(b.open, b.close)
    && b.high >= Math.max(b.open, b.close)

  function swingZones(bars, completed, frame, settings, tick, values, referenceEvents) {
    const source = settings.marking !== 'legacy'
    const strength = Math.max(1, Math.min(6, Math.round(Number(settings.strength) || 2)))
    const keep = Math.max(1, Math.min(3, Math.round(Number(settings.zonesPerSide) || 1)))
    const width = Math.max(0.02, Math.min(0.5, Number(settings.zoneWidth) || 0.1))
    const highs = completed.map((b) => b.high), lows = completed.map((b) => b.low)
    const closes = completed.map((b) => b.close)
    const pivots = { High: pivotHigh(highs, strength, strength), Low: pivotLow(lows, strength, strength) }
    const volatility = atr(highs, lows, closes, 14)
    const ranges = trueRange(highs, lows, closes)
    const events = new Map()
    for (let j = strength * 2; j < completed.length; j++) {
      const p = j - strength, candle = completed[p], window = completed.slice(j - strength * 2, j + 1)
      if (window.some((b) => b.segment !== candle.segment)) continue
      for (const side of ['High', 'Low']) {
        const price = pivots[side][j]
        if (!Number.isFinite(price)) continue
        // Strict neighbours exclude flat plateaus even if the library resolves ties.
        if (window.some((b) => b !== candle && (side === 'High' ? b.high >= price : b.low <= price))) continue
        const seed = ranges.slice(Math.max(0, p - 13), p + 1).filter(Number.isFinite)
        const scale = Number.isFinite(volatility[p]) ? volatility[p] : seed.reduce((a, b) => a + b, 0) / seed.length
        const half = Math.max(tick * 2, scale * width, price * 0.000001)
        const lower = source ? price : tick > 0 ? Math.floor((price - half) / tick) * tick : price - half
        const upper = source ? price : tick > 0 ? Math.ceil((price + half) / tick) * tick : price + half
        if (!(lower > 0 && upper >= lower)) continue
        const index = completed[j].knownIndex
        const event = { id: `${frame.key}:${side}:${candle.start}`, side, price, lower, upper,
          pivotTime: side === 'High' ? candle.highTime : candle.lowTime, confirmedAt: bars[index].time,
          lastPivotTime: side === 'High' ? candle.highTime : candle.lowTime, lastPivotPrice: price,
          updatedAt: bars[index].time, touches: 1, takenAt: null, segment: candle.segment,
          shape: side === 'Low' ? 'V low' : 'Inverted V high', frame: frame.label, frameKey: frame.key,
          lineWidth: frame.width, lineStyle: frame.style, knownIndex: index, source }
        events.set(index, [...(events.get(index) || []), event])
        referenceEvents?.push({ ...event })
      }
    }
    const zones = { High: [], Low: [] }
    for (let i = 0; i < bars.length; i++) {
      for (const event of events.get(i) || []) {
        const list = zones[event.side], prior = list.at(-1)
        // Only consecutive same-side confirmed pivots can form a W/M. The
        // original band stays fixed; a second touch never drags it to price.
        if (!source && prior && prior.segment === event.segment && prior.takenAt == null && event.price >= prior.lower && event.price <= prior.upper) {
          prior.touches++
          prior.lastPivotTime = event.pivotTime
          prior.lastPivotPrice = event.price
          prior.updatedAt = event.confirmedAt
          prior.shape = event.side === 'Low' ? 'W lows' : 'M highs'
        } else {
          list.push(event)
          if (list.length > keep) list.shift()
        }
      }
      for (const side of ['High', 'Low']) {
        for (const z of zones[side]) {
          if (z.takenAt == null && valid(bars[i]) && (side === 'High' ? bars[i].high > z.upper : bars[i].low < z.lower)) z.takenAt = bars[i].time
        }
        const visible = zones[side].filter((z) => source || settings.showTaken === true || z.takenAt == null)
        values[frame.key + side][i] = visible.at(-1)?.price ?? null
      }
    }
    return [...zones.High, ...zones.Low].filter((z) => source || settings.showTaken === true || z.takenAt == null)
  }

  function zoneLines(zones, settings, precision) {
    return zones.map((z) => {
      const color = !z.source && z.takenAt != null ? '#747b86' : z.side === 'High'
        ? String(settings.highColor || '#168b75') : String(settings.lowColor || '#d65259')
      const label = z.source ? `${z.frame} Liquidity ${z.side} · ${z.price.toFixed(precision)}${z.takenAt != null ? ' · Swept' : ''}`
        : `${z.frame} Liquidity · ${z.shape} · ${z.lower.toFixed(precision)}–${z.upper.toFixed(precision)}${z.takenAt != null ? ' · Taken' : ''}`
      return { ...z, color, label, title: label }
    })
  }

  function displayLines(all, settings, precision) {
    if (settings.basis === 'previous' || settings.display === 'detailed') return all
    // Choose by confirmation time, never distance to a moving live quote.
    // Retain the underlying zones and reference values for the detailed view.
    return frames.flatMap((frame) => {
      const newest = all.filter((l) => !l.reference && l.frameKey === frame.key && (l.source || l.takenAt == null))
        .sort((a, b) => b.updatedAt - a.updatedAt || b.confirmedAt - a.confirmedAt || a.id.localeCompare(b.id))[0]
      if (!newest) return []
      return [{ ...newest, compact: true,
        label: `${frame.label} Liquidity ${newest.side} · ${newest.price.toFixed(precision)}${newest.source && newest.takenAt != null ? ' · Swept' : ''}` }]
    })
  }

  // Keep the existing daily column and setting keys for saved workspaces.
  const referenceKeys = (frame) => frame.key === 'd1'
    ? ['dayOpen', 'priorDayHigh', 'priorDayLow', 'priorBodyHigh', 'priorBodyLow']
    : ['Open', 'PriorHigh', 'PriorLow', 'BodyHigh', 'BodyLow'].map((suffix) => frame.key + suffix)

  function periodReferences(bars, current, previous, coverage, frame, settings, values, precision) {
    let period = null, references = []
    const [openKey, highKey, lowKey, bodyHighKey, bodyLowKey] = referenceKeys(frame)
    for (let i = 0; i < bars.length; i++) {
      const bucket = coverage.get(current.bucketStart[i])
      if (!bucket) continue
      if (period !== bucket.start) {
        period = bucket.start
        references = []
        const add = (key, price, title, side, enabled) => {
          if (!enabled || !Number.isFinite(price)) return
          references.push({ key, price, lower: price, upper: price, confirmedAt: bars[i].time,
            side, takenAt: null, title, lineWidth: 2, lineStyle: side === 'Open' ? 'dashed' : frame.style, reference: true })
        }
        // Require the real first period candle for its opening price. A late
        // history page must never substitute its first observed bar as the open.
        add(openKey, bucket.firstValid && current.bucketStart[i] === bucket.start ? current.open[i] : null,
          `${frame.label} Open · colour flip`, 'Open', settings.showDailyOpen !== false)
        const hasPrior = values[frame.key + 'High'][i] != null && values[frame.key + 'Low'][i] != null
        add(highKey, hasPrior ? previous.high[i] : null, `${frame.label} Liquidity · Prior high`, 'High', settings.showPriorDay !== false)
        add(lowKey, hasPrior ? previous.low[i] : null, `${frame.label} Liquidity · Prior low`, 'Low', settings.showPriorDay !== false)
        add(bodyHighKey, hasPrior ? Math.max(previous.open[i], previous.close[i]) : null,
          `${frame.label} Liquidity · Body high`, 'High', settings.showDailyBody === true)
        add(bodyLowKey, hasPrior ? Math.min(previous.open[i], previous.close[i]) : null,
          `${frame.label} Liquidity · Body low`, 'Low', settings.showDailyBody === true)
      }
      for (const r of references) {
        if (r.takenAt == null && valid(bars[i]) && (r.side === 'High' ? bars[i].high > r.price : r.side === 'Low' && bars[i].low < r.price)) r.takenAt = bars[i].time
        values[r.key][i] = settings.showTaken !== true && r.takenAt != null ? null : r.price
      }
    }
    return references.filter((r) => settings.showTaken === true || r.takenAt == null).map((r) => {
      const direction = bars.at(-1).close > r.price ? 'Above open' : bars.at(-1).close < r.price ? 'Below open' : 'At open'
      const color = r.takenAt != null ? '#747b86' : r.side === 'Open' ? '#426bb3'
        : r.side === 'High' ? String(settings.highColor || '#168b75') : String(settings.lowColor || '#d65259')
      return { ...r, color, label: `${r.title} · ${r.price.toFixed(precision)}${r.side === 'Open' ? ' · ' + direction : r.takenAt != null ? ' · Taken' : ''}` }
    })
  }

  // Bands begin when the swing became known. Source-pivot markers are shown
  // only after confirmation; they identify the origin, not an earlier signal.
  function zoneBands(store) {
    return {
      zOrder: () => 'bottom',
      draw(c, rc) {
        const xAt = (time) => rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(time))
        c.save(); c.scale(rc.dpr, rc.dpr)
        for (const z of [...(store.liquidityDisplay || []), ...(store.setupDisplay || [])]) {
          if (z.lower == null) continue
          const upper = rc.priceScale.priceToY(z.upper), lower = rc.priceScale.priceToY(z.lower)
          const y = rc.priceScale.priceToY(z.price)
          const left = z.planPrice ? 0 : Math.max(0, Math.min(rc.plotWidth, xAt(z.confirmedAt)))
          const top = Math.max(0, Math.min(upper, lower)), bottom = Math.min(rc.plotHeight, Math.max(upper, lower))
          if (bottom > top) {
            c.fillStyle = z.color; c.globalAlpha = z.takenAt == null ? 0.1 : 0.035
            c.fillRect(left, top, rc.plotWidth - left, bottom - top)
          }
          c.globalAlpha = z.source || z.takenAt == null ? 0.9 : 0.45
          c.strokeStyle = z.color; c.lineWidth = z.lineWidth
          c.setLineDash(z.lineStyle === 'dotted' ? [2, 5] : z.lineStyle === 'dashed' ? [9, 6] : [])
          if (y >= 0 && y <= rc.plotHeight) {
            c.beginPath(); c.moveTo(left, y); c.lineTo(rc.plotWidth, y); c.stroke()
            // A light lead joins the historical origin to the confirmed band.
            // The thicker projection starts only when the swing became known.
            const origin = z.reference ? left : Math.max(0, xAt(z.pivotTime))
            if (origin < left) {
              c.globalAlpha = 0.35; c.lineWidth = 1; c.setLineDash([3, 5])
              c.beginPath(); c.moveTo(origin, y); c.lineTo(left, y); c.stroke()
            }
            for (const [time, price] of z.reference ? [] : new Map([[z.pivotTime, z.price], [z.lastPivotTime, z.lastPivotPrice]])) {
              const x = xAt(time)
              if (x < 0 || x > rc.plotWidth) continue
              c.setLineDash([]); c.beginPath(); c.arc(x, rc.priceScale.priceToY(price), 4, 0, Math.PI * 2); c.stroke()
            }
          }
        }
        c.restore()
      },
    }
  }

  function lines({ bars = [], values, settings = {} }) {
    if (!values || !bars.length) return []
    const end = bars.length - 1
    const groups = new Map()
    for (const f of frames) {
      if (settings[f.toggle] === false) continue
      for (const side of ['High', 'Low']) {
        const price = values[f.key + side]?.[end]
        if (price == null || !Number.isFinite(price)) continue
        const key = `${side}:${price}`
        const group = groups.get(key)
        if (group) {
          group.labels.push(f.label)
          group.lineWidth = f.width
          group.lineStyle = f.style
        } else {
          groups.set(key, {
            price, side, labels: [f.label], lineWidth: f.width, lineStyle: f.style,
            color: side === 'High' ? String(settings.highColor || '#168b75') : String(settings.lowColor || '#d65259'),
          })
        }
      }
    }
    const precision = values.precision?.[end] ?? 2
    return [...groups.values()].map((g) => ({
      price: g.price, color: g.color, lineWidth: g.lineWidth, lineStyle: g.lineStyle,
      title: `${g.labels.join(' / ')} ${g.side === 'High' ? 'Buy-side' : 'Sell-side'} liquidity · ${g.side} ${g.price.toFixed(precision)}`,
      label: `${g.labels.join('/')} Liquidity ${g.side} ${g.price.toFixed(precision)}`,
    }))
  }

  // Screen-space labels follow the pane edge during pan/zoom. A time-anchored
  // drawing would scroll offscreen. Label count is bounded by the zone setting.
  function rightLabels(store) {
    return {
      zOrder: () => 'top',
      draw(c, rc) {
        const rows = [...(store.liquidityDisplay || []), ...(store.setupDisplay || [])].map((l) => ({ ...l, rawY: rc.priceScale.priceToY(l.price) }))
          .filter((l) => Number.isFinite(l.rawY)).sort((a, b) => a.rawY - b.rawY)
        if (!rows.length || rc.plotWidth < 80 || rc.plotHeight < 30) return
        // Leave the upper-left OHLC/indicator legend area unobscured even when
        // several out-of-range daily/4H labels are pinned at the upper edge.
        const top = Math.min(rows.every((r) => r.compact) ? 70 : 150, rc.plotHeight / 3), bottom = rc.plotHeight - 12
        const gap = Math.min(24, (bottom - top) / Math.max(1, rows.length - 1))
        let previous = top - gap
        for (const r of rows) { r.y = Math.max(previous + gap, Math.min(bottom, Math.max(top, r.rawY))); previous = r.y }
        if (previous > bottom) {
          rows[rows.length - 1].y = bottom
          for (let i = rows.length - 2; i >= 0; i--) rows[i].y = Math.min(rows[i].y, rows[i + 1].y - gap)
        }
        c.save()
        c.scale(rc.dpr, rc.dpr)
        c.font = '600 12px system-ui, sans-serif'
        c.textAlign = 'right'
        c.textBaseline = 'middle'
        const edge = rc.plotWidth - 6
        for (const r of rows) {
          const text = `${r.rawY < 0 ? 'Above: ' : r.rawY > rc.plotHeight ? 'Below: ' : ''}${r.label}`
          const width = Math.min(rc.plotWidth - 12, c.measureText(text).width + 12)
          c.fillStyle = rc.theme.background === 'transparent' ? '#17212b' : rc.theme.background
          c.fillRect(edge - width, r.y - 10, width, 20)
          c.strokeStyle = r.color
          c.lineWidth = 1.5
          c.strokeRect(edge - width, r.y - 10, width, 20)
          if (Math.abs(r.y - r.rawY) > 2 && r.rawY >= 0 && r.rawY <= rc.plotHeight) {
            c.beginPath(); c.moveTo(edge - width - 5, r.rawY); c.lineTo(edge - width, r.y); c.stroke()
          }
          c.fillStyle = r.color
          c.fillText(text, edge - 6, r.y, width - 12)
        }
        c.restore()
      },
    }
  }

  function setupPanel(store) {
    return { zOrder: () => 'top', draw(c, rc) {
      if (!store.setupStatus || rc.plotWidth < 300 || rc.plotHeight < 180) return
      const p = store.setup?.plan
      const title = store.setupMode === 'continuation' ? 'Trend continuation' : 'HTF sweep reversal'
      const text = [title + (p ? ` · ${p.direction}` : ''), store.setupStatus, store.setupDetail]
      const width = Math.min(470, rc.plotWidth - 24), x = 12, y = rc.plotHeight - 87
      c.save(); c.scale(rc.dpr, rc.dpr)
      c.fillStyle = rc.theme.background === 'transparent' ? '#17212b' : rc.theme.background
      c.globalAlpha = 0.96; c.fillRect(x, y, width, 76); c.globalAlpha = 1
      c.strokeStyle = p?.direction === 'LONG' ? '#168b75' : p?.direction === 'SHORT' ? '#d65259' : '#747b86'
      c.lineWidth = 2; c.beginPath(); c.moveTo(x, y); c.lineTo(x, y + 76); c.stroke()
      c.textAlign = 'left'; c.textBaseline = 'middle'
      text.forEach((line, i) => {
        c.font = `${i === 1 ? 600 : 400} ${i === 2 ? 11 : 12}px system-ui, sans-serif`
        c.fillStyle = i === 1 ? c.strokeStyle : '#747b86'
        c.fillText(line || '', x + 10, y + 14 + i * 23, width - 20)
      })
      c.restore()
    } }
  }

  registerIndicator({
    id: 'oa-htf-liquidity',
    name: 'Liquidity Zones · 1H / 4H / 1D',
    category: 'Custom',
    placement: 'onchart',
    inputs: [
      { key: 'marking', type: 'select', label: 'Marking method', default: 'source', options: [
        { value: 'source', label: 'Source-guided · fixed turning-point lines' },
        { value: 'legacy', label: 'Legacy · ATR swing zones' },
      ], tooltip: 'Videos use selected historical turns. Automatic strict pivots and newest-turn ranking are app assumptions. Source mode retains swept lines, with no ATR band.' },
      { key: 'setupMode', type: 'select', label: 'Entry setup', default: 'reversal', options: [
        { value: 'reversal', label: 'Higher-timeframe sweep reversal' },
        { value: 'continuation', label: 'Trend continuation · untouched target' },
        { value: 'off', label: 'Off · liquidity only' },
      ], tooltip: 'On 1m–5m candles: sweep, first completed green/red candle, then high/low break. These chart plans do not submit orders.' },
      { key: 'bufferTicks', type: 'number', label: 'SL beyond pattern · ticks', default: 1, min: 1, max: 20, step: 1,
        tooltip: 'App assumption: SL beyond the sweep-to-confirmation extreme. Target is opposing known liquidity, never a fabricated fixed multiple.' },
      { key: 'maxWaitBars', type: 'number', label: 'Watch expires after candles', default: 8, min: 2, max: 100, step: 1,
        tooltip: 'App assumption: counted from the sweep, one candidate per reference. Frozen prices do not follow later candles.' },
      { key: 'trendBars', type: 'number', label: 'Continuation trend lookback', default: 20, min: 8, max: 100, step: 1,
        tooltip: 'App rule: directional close displacement / close travel at least 0.55 before the first pullback. Reversals do not inherit this filter.' },
      { key: 'manualLevel', type: 'number', label: 'Selected liquidity price · 0 = auto', default: 0, min: 0, step: 0.5,
        tooltip: 'Optional trader-selected reference for one timeframe. Set Active from to prevent historical backdating.' },
      { key: 'manualSide', type: 'select', label: 'Selected level side', default: 'Low', options: [
        { value: 'Low', label: 'Low · watch for long reversal' }, { value: 'High', label: 'High · watch for short reversal' },
      ] },
      { key: 'manualFrame', type: 'select', label: 'Selected level timeframe', default: 'h1', options: frames.map((f) => ({ value: f.key, label: f.label })) },
      { key: 'manualFrom', type: 'time', label: 'Selected level active from', default: 0,
        tooltip: 'First chart candle at or after this time can use your selected level. Prices are in the symbol quote currency.' },
      { key: 'display', type: 'select', label: 'Chart detail', default: 'focused', options: [
        { value: 'focused', label: 'One liquidity line per timeframe' },
        { value: 'detailed', label: 'Detailed · all enabled levels' },
      ], tooltip: 'At most three references. Source mode keeps swept levels; the active setup reference takes precedence in its timeframe. Legacy layers are available in Detailed view.' },
      { key: 'basis', type: 'select', label: 'Liquidity source', default: 'swings', options: [
        { value: 'swings', label: 'Confirmed historical turns' },
        { value: 'previous', label: 'Previous completed period high / low' },
      ], tooltip: 'Potential liquidity inferred from price structure, not measured resting orders. Source-guided setups require historical turns; previous-period mode is liquidity only.' },
      { key: 'strength', type: 'number', label: 'Swing candles on each side', default: 2, min: 1, max: 6, step: 1,
        tooltip: 'Two right-hand completed candles confirm each higher-timeframe swing. Until then no zone is drawn.' },
      { key: 'zoneWidth', type: 'number', label: 'Legacy zone half-width · ATR multiple', default: 0.1, min: 0.02, max: 0.5, step: 0.02,
        tooltip: 'Frozen at the original swing using its timeframe ATR14, with a two-tick minimum. Nearby repeated pivots form W/M zones without moving the band.' },
      { key: 'zonesPerSide', type: 'number', label: 'Zones per side per timeframe', default: 1, min: 1, max: 3, step: 1 },
      { key: 'showTaken', type: 'boolean', label: 'Show taken zones in grey', default: false,
        tooltip: 'Taken means an observed candle traded strictly beyond the outer edge. Touching the band alone does not remove it.' },
      { key: 'showDailyOpen', type: 'boolean', label: 'Period opens · 1H / 4H / 1D', default: true,
        tooltip: 'Each period has its own fixed open: its candle is green above it and red below it. The line changes only when that period rolls over.' },
      { key: 'showPriorDay', type: 'boolean', label: 'Previous candle wick high / low', default: true,
        tooltip: 'Previous completed candle for each enabled timeframe. Broken levels stay hidden until that reference period rolls over.' },
      { key: 'showDailyBody', type: 'boolean', label: 'Previous candle body edges', default: false },
      { key: 'show1H', type: 'boolean', label: '1 hour levels', default: true },
      { key: 'show4H', type: 'boolean', label: '4 hour levels', default: true },
      { key: 'show1D', type: 'boolean', label: 'Daily levels', default: true },
      { key: 'market', type: 'select', label: 'Reference session', default: 'auto', options: [
        { value: 'auto', label: 'Auto: Indian indices / otherwise UTC 24h' },
        { value: 'utc', label: '24-hour market · UTC day' },
        { value: 'india', label: 'India · 09:15–15:30 IST' },
      ], tooltip: 'Crypto uses UTC hour/4-hour/day boundaries. Indian index symbols use session-open boundaries.' },
      { key: 'highColor', type: 'color', label: 'High / buy-side line', default: '#168b75' },
      { key: 'lowColor', type: 'color', label: 'Low / sell-side line', default: '#d65259' },
    ],
    // Hidden columns retain values for the data window without drawing staircases
    // across old periods. The primitives render the retained zones.
    plots: [...frames.flatMap((f) => ['High', 'Low'].map((side) => ({
      key: f.key + side, title: `${f.label} liquidity ${side.toLowerCase()}`,
      type: 'line', style: { visible: false, color: 'transparent' },
    }))), ...['Entry', 'SL', 'Target'].map((key) => ({ key: 'setup' + key, title: key,
      type: 'line', style: { visible: false, color: 'transparent' } }))],
    attach(ctx) {
      const primitive = rightLabels(ctx.store), bands = zoneBands(ctx.store), panel = setupPanel(ctx.store)
      ctx.addPrimitive?.(primitive)
      ctx.addPrimitive?.(bands)
      ctx.addPrimitive?.(panel)
      return () => { ctx.removePrimitive?.(primitive); ctx.removePrimitive?.(bands); ctx.removePrimitive?.(panel)
        for (const key of ['liquidityLines', 'liquidityZones', 'liquidityDisplay', 'setup', 'setupDisplay', 'setupStatus', 'setupDetail', 'setupMode']) delete ctx.store[key] }
    },
    calc(bars, settings, store, ctx) {
      store.liquidityLines = []
      store.liquidityZones = []
      store.liquidityDisplay = []
      store.setupDisplay = []; store.setupStatus = ''; store.setupDetail = ''; store.setup = null
      if (ctx?.transformed) {
        throw new IndicatorInputError('Use ordinary candles or set Compute on to Underlying bars for liquidity levels.')
      }
      const n = bars.length
      const values = Object.fromEntries(frames.flatMap((f) => ['High', 'Low'].map((s) => [f.key + s, Array(n).fill(null)])))
      for (const key of ['Entry', 'SL', 'Target']) values['setup' + key] = Array(n).fill(null)
      for (const key of frames.flatMap(referenceKeys)) values[key] = Array(n).fill(null)
      const referenceLines = []
      let referenceEvents = []
      const tick = Number(ctx?.tickSize)
      const precision = Number.isFinite(tick) && tick > 0
        ? Math.min(8, Math.max(2, (String(tick).split('.')[1] || '').length)) : 2
      values.precision = Array(n).fill(precision)
      if (!n) return values
      const seconds = ctx?.interval ? intervalToSeconds(ctx.interval) : bars[1]?.time - bars[0].time
      if (!(seconds > 0) || !Number.isFinite(seconds)) return values
      const india = settings.market === 'india' || (settings.market !== 'utc' && /^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX|BANKEX)/i.test(ctx?.symbol || ''))
      const zone = india ? 'Asia/Kolkata' : 'UTC'
      const offset = india ? 19800 : 0
      for (const f of frames) {
        if (settings[f.toggle] === false || seconds > f.seconds || f.seconds % seconds !== 0) continue
        const opts = { timezone: zone, ...(india && f.interval !== '1d' ? { session: '0915-1530' } : {}) }
        const current = securitySeries(bars, f.interval, opts)
        const previous = securitySeries(bars, f.interval, { ...opts, offset: 1 })
        // Validate coverage separately; all OHLC aggregation belongs to the
        // chart library. bucketStart is the first observed bar, not proof that
        // the actual start or end of the period was present.
        const coverage = new Map()
        const completed = []
        let lastFirst = null, segment = 0
        for (let i = 0; i < n; i++) {
          const b = bars[i]
          const first = current.bucketStart[i]
          if (first == null) continue
          let bucket = coverage.get(first)
          if (!bucket) {
            const midnight = Math.floor((b.time + offset) / 86400) * 86400 - offset
            const open = midnight + (india ? 9 * 3600 + 15 * 60 : 0)
            const close = india ? midnight + 15 * 3600 + 30 * 60 : midnight + 86400
            const expected = f.interval === '1d' ? open : open + Math.floor((b.time - open) / f.seconds) * f.seconds
            bucket = { valid: b.time === expected, firstValid: valid(b), last: b.time - seconds, high: -Infinity, low: Infinity,
              start: expected, sessionOpen: open, sessionClose: close,
              end: Math.min(expected + f.seconds, close) }
            coverage.set(first, bucket)
          }
          bucket.valid = bucket.valid && valid(b) && b.time === bucket.last + seconds && b.time < bucket.end
          if (b.high > bucket.high) { bucket.high = b.high; bucket.highTime = b.time }
          if (b.low < bucket.low) { bucket.low = b.low; bucket.lowTime = b.time }
          bucket.last = b.time
        }
        for (let i = 0; i < n; i++) {
          const first = previous.bucketStart[i]
          const bucket = first == null ? null : coverage.get(first)
          if (!bucket?.valid || bucket.last + seconds !== bucket.end || bars[i].time < bucket.end) continue
          const next = coverage.get(current.bucketStart[i])
          const overnight = india && next?.start === next?.sessionOpen
            && bucket.end === bucket.sessionClose && bucket.end < next.start
          if (!next || (bucket.end !== next.start && !overnight)) continue
          values[f.key + 'High'][i] = previous.high[i]
          values[f.key + 'Low'][i] = previous.low[i]
          if (first !== lastFirst) {
            const last = completed.at(-1)
            const adjacent = !last || last.end === bucket.start || (india && bucket.start === bucket.sessionOpen && last.end === last.sessionClose)
            if (!adjacent) segment++
            completed.push({ ...bucket, open: previous.open[i], high: previous.high[i], low: previous.low[i], close: previous.close[i], knownIndex: i, segment })
            lastFirst = first
          }
        }
        if (settings.basis !== 'previous') {
          referenceLines.push(...periodReferences(bars, current, previous, coverage, f, settings, values, precision))
          store.liquidityZones.push(...swingZones(bars, completed, f, settings, Number.isFinite(tick) && tick > 0 ? tick : 0, values, referenceEvents))
        }
      }
      store.liquidityLines = settings.basis === 'previous' ? lines({ bars, values, settings }) : [...zoneLines(store.liquidityZones, settings, precision), ...referenceLines]
      store.liquidityDisplay = displayLines(store.liquidityLines, settings, precision)
      if (settings.marking !== 'legacy' && settings.basis !== 'previous') {
        if (Number(settings.manualLevel) > 0) {
          const frame = frames.find((f) => f.key === settings.manualFrame) || frames[0]
          const knownIndex = Number(settings.manualFrom) > 0 ? bars.findIndex((b) => b.time >= Number(settings.manualFrom)) : -1
          referenceEvents = referenceEvents.filter((e) => e.frameKey !== frame.key)
          store.liquidityDisplay = store.liquidityDisplay.filter((e) => e.frameKey !== frame.key)
          if (knownIndex >= 0 && settings[frame.toggle] !== false) {
            const price = Number(settings.manualLevel), time = bars[knownIndex].time
            const manual = { id: `manual:${frame.key}:${time}:${price}`, knownIndex, confirmedAt: time, updatedAt: time,
              frameKey: frame.key, frame: frame.label, side: settings.manualSide === 'High' ? 'High' : 'Low', price,
              lower: price, upper: price, source: true, pivotTime: time, lineWidth: frame.width, lineStyle: frame.style }
            manual.takenAt = bars.slice(knownIndex).find((b) => valid(b) && (manual.side === 'Low' ? b.low < price : b.high > price))?.time ?? null
            referenceEvents.push(manual)
            store.liquidityDisplay.push(...zoneLines([manual], settings, precision).map((l) => ({ ...l, compact: true })))
          }
        }
        store.setupMode = settings.setupMode || 'reversal'
        store.setup = evaluateLiquiditySetup(bars, referenceEvents, { ...settings, mode: store.setupMode,
          seconds, tick, lastConfirmed: ctx?.barState?.isConfirmed === true })
        const p = store.setup.plan
        if (store.setupMode !== 'off') {
          const stamp = p ? new Intl.DateTimeFormat('en-GB', { timeZone: ctx?.timezone || 'UTC', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
            .format(new Date((p.endedAt || p.triggeredAt || p.confirmedAt || p.sweepAt) * 1000)) : ''
          store.setupStatus = p ? `${p.endedAt != null ? 'LAST SETUP · ' : ''}${p.stage}${p.entry != null && p.stage === 'WATCHING ENTRY' ? ` · ${p.direction === 'LONG' ? 'above' : 'below'} ${p.entry.toFixed(precision)}` : ''}` : store.setup.reason
          store.setupDetail = p ? `${stamp} · Ref ${p.reference.price.toFixed(precision)} · ${p.rr == null ? 'Target unavailable' : `1:${p.rr.toFixed(2)} gross, before fees`}`
            : 'Auto selection is an app rule · 1m–5m confirmation'
          if (Number(settings.manualLevel) > 0 && !(Number(settings.manualFrom) > 0)) store.setupStatus = 'Set selected level Active from before using it'
        }
        for (let i = 0; i < n; i++) {
          const h = store.setup.history[i]
          for (const [key, field] of [['Entry', 'entry'], ['SL', 'sl'], ['Target', 'target']]) values['setup' + key][i] = h?.[field] ?? null
        }
        if (p) {
          const ref = p.reference
          if (ref.frameKey !== 'entry') {
            store.liquidityDisplay = store.liquidityDisplay.filter((l) => l.frameKey !== ref.frameKey)
            store.liquidityDisplay.push(...zoneLines([{ ...ref, takenAt: p.sweepAt, source: true }], settings, precision).map((l) => ({ ...l, compact: true })))
          }
          const ended = p.endedAt != null
          store.setupDisplay = [['entry', 'Entry', '#326dcc'], ['sl', 'SL', '#d65259'], ['target', 'Target', '#168b75']]
            .filter(([key]) => Number.isFinite(p[key])).map(([key, label, color]) => ({
              price: p[key], lower: p[key], upper: p[key], confirmedAt: p.confirmedAt, reference: true, compact: true, planPrice: true,
              color, lineWidth: key === 'sl' ? 3 : 2, lineStyle: ended ? 'dotted' : 'solid',
              label: `${label} · ${p[key].toFixed(precision)}${ended ? ' · ended' : key === 'entry' ? ' · ' + (p.stage === 'TRIGGERED' ? 'triggered' : 'watch') : ''}`,
            }))
        }
      }
      return values
    },
    // Legacy range mode retains native tags; swing zones use bounded primitives.
    levels: (ctx) => ctx.settings?.basis === 'previous' ? lines(ctx).map((l) => ({ ...l, title: '' })) : [],
  })
}
