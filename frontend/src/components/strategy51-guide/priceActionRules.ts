import type { EvaluationInput, StrategyDefinition, StrategyRow, Side } from './types'
import {
  body,
  candidate,
  candleBreak,
  connectSourcePoints,
  green,
  pin,
  red,
  row,
  rrTarget,
  small,
  supplied,
  touches,
  waiting,
} from './ruleHelpers'
export function priceActionRule(d: StrategyDefinition, a: EvaluationInput): StrategyRow {
  const { frames: f, index: i, settings: s, context: ctx } = a,
    x = f[i],
    q = f[i - 1],
    p = f[i - 2],
    buf = Math.max(ctx.tickSize, (q?.atr ?? 0) * 0.05),
    entry = x.bar.close
  if (!q || !p) return waiting(d, 'Load enough completed candles for the price-action sequence')
  const range = f.slice(Math.max(0, i - s.rangeBars - 1), i - 1),
    hi = Math.max(...range.map((t) => t.bar.high)),
    lo = Math.min(...range.map((t) => t.bar.low))
  const hit = (
    side: Side,
    stop: number | undefined,
    target: number | undefined,
    extra: Parameters<typeof candidate>[6] = {}
  ) => candidate(d, a, side, i - 1, stop, target, extra)
  if (!s.localStructures && d.id !== '7.5')
    return row(
      d,
      'needs-context',
      'Qualitative source pattern needs annotated geometry',
      'Enable disclosed local confirmed-swing/range rules in Details'
    )
  switch (d.id) {
    case '7.1': {
      if (range.length < s.rangeBars || !(q.atr! > 0) || hi - lo > 4 * q.atr!)
        return waiting(d, 'Wait for consolidation before the EMA9/21 breakout')
      const recent = f.slice(Math.max(1, i - 10), i - 1),
        cross = (side: Side) =>
          recent.some((z) => {
            const prev = f[z.index - 1]
            return side === 'long'
              ? prev.ema[9]! <= prev.ema[21]! && z.ema[9]! > z.ema[21]!
              : prev.ema[9]! >= prev.ema[21]! && z.ema[9]! < z.ema[21]!
          })
      if (
        cross('long') &&
        green(q) &&
        q.ema[9]! > q.ema[21]! &&
        q.bar.close > hi &&
        candleBreak(a, 'long')
      )
        return hit('long', q.bar.low - buf, q.highs.find((z) => z.price > entry)?.price, {
          stopMethod: 'Selected breakout-candle low',
          notes: [
            'Local10-bar range≤4ATR and EMA crossover within preceding10 bars; source definitions are qualitative.',
          ],
        })
      if (
        cross('short') &&
        red(q) &&
        q.ema[9]! < q.ema[21]! &&
        q.bar.close < lo &&
        candleBreak(a, 'short')
      )
        return hit(
          'short',
          q.bar.high + buf,
          [...q.lows].reverse().find((z) => z.price < entry)?.price,
          { stopMethod: 'Selected breakdown-candle high' }
        )
      return waiting(
        d,
        'Wait for EMA9/21 cross after consolidation, range break and later signal-candle break'
      )
    }
    case '7.2': {
      const prior = f.slice(Math.max(0, i - 61), Math.max(0, i - s.rangeBars - 1)),
        minimum = Math.min(...prior.map((z) => z.bar.low)),
        rally = prior.length >= 20 && hi / minimum - 1 >= 0.2
      const contracted =
        range.length === s.rangeBars &&
        q.volumeMean! > 0 &&
        range.reduce((v, z) => v + z.bar.volume, 0) / range.length < q.volumeMean!
      if (
        rally &&
        contracted &&
        green(q) &&
        body(q) > 0.6 * (q.bar.high - q.bar.low) &&
        q.bar.close > hi &&
        q.bar.volume > s.volumeFactor * q.volumeMean! &&
        candleBreak(a, 'long')
      )
        return hit('long', lo - buf, rrTarget(entry, lo - buf, 'long', 3), {
          stopMethod: 'Local significant consolidation-low stop; source5%-of-range is undefined',
          targetMethod: 'Selected source-discussed3R',
          notes: [
            'Local20% preceding rally,10-bar drying-volume range,1.5×breakout volume. Source stop wording is ambiguous; this disclosed local stop is not exact author wording.',
            'No automatic pyramiding or position-profit assumption.',
          ],
        })
      return waiting(
        d,
        'Wait for ≥20% rally, drying-volume consolidation and large high-volume daily breakout'
      )
    }
    case '7.3': {
      const prior = f.slice(Math.max(0, i - 60), i - 1),
        h = q.highs.at(-1),
        l = q.lows.at(-1)
      if (!h || !l || h.price <= l.price)
        return waiting(d, 'Wait for an established range; the level-defining pin is not an entry')
      for (const side of ['long', 'short'] as const) {
        const level = side === 'long' ? l.price : h.price,
          target = side === 'long' ? h.price : l.price,
          start = Math.max(h.knownAt, l.knownAt),
          count = prior.filter(
            (z) => z.index > start && pin(z, side) && touches(z, level, s.touchATR)
          ).length
        if (
          count < 2 &&
          q.index > start &&
          pin(q, side) &&
          touches(q, level, s.touchATR) &&
          candleBreak(a, side)
        ) {
          const reward = side === 'long' ? target - entry : entry - target
          if (reward <= 0) continue
          return hit(side, entry + ((side === 'long' ? -1 : 1) * reward) / 2, target, {
            stopMethod: 'Source2R risk-distance branch: half target distance',
            targetMethod: 'Opposite established range boundary',
            notes: [
              'Local pin geometry and later closed-candle break; source entry timing unspecified.',
              `Eligible range pin occurrence${count + 1}; source avoids the third.`,
            ],
          })
        }
      }
      return waiting(
        d,
        'Wait for one of the first two eligible revisit pins at an established range boundary'
      )
    }
    case '7.4': {
      const oldHigh = p.highs.at(-1)
      if (!oldHigh) return waiting(d, 'Wait for known resistance, breakout and retest')
      const recent = f.slice(Math.max(oldHigh.knownAt, i - 12), i - 1),
        broke = recent.some((z) => z.bar.close > oldHigh.price)
      if (
        broke &&
        touches(q, oldHigh.price, s.touchATR) &&
        (pin(q, 'long') || small(q)) &&
        q.bar.close >= oldHigh.price &&
        candleBreak(a, 'long')
      )
        return hit('long', q.bar.low - buf, rrTarget(entry, q.bar.low - buf, 'long', 3), {
          targetMethod: 'Selected source3R branch',
          stopMethod: 'Long-wick retest candle low',
          notes: [
            'Local3L/3R resistance and.25ATR retest tolerance; source short mirror is not added.',
          ],
        })
      return waiting(
        d,
        'Wait for breakout → old-resistance retest → rejection/doji → later high break'
      )
    }
    case '7.5': {
      const z = supplied(a, d.id)
      if (
        !z ||
        z.kind !== 'repo' ||
        !Number.isFinite(z.newRate) ||
        !Number.isFinite(z.previousRate)
      )
        return row(
          d,
          'needs-data',
          'Dated RBI repo decision / previous rate required',
          'Supply the authoritative announcement values and timestamp; a price candle cannot detect a policy change'
        )
      if (z.newRate === z.previousRate)
        return waiting(d, 'Repo rate unchanged: source specifies no trade')
      const sameDay = Math.floor((z.asOf + 19800) / 86400) === x.day,
        closed = x.bar.closeTime ?? x.bar.time + ctx.intervalSeconds
      if (!sameDay || ((closed + 19800) % 86400) / 60 < 930)
        return waiting(d, 'Wait for the rate-changing announcement day’s market close')
      return row(
        d,
        'needs-context',
        `${z.newRate! < z.previousRate! ? 'Source Long' : 'Source Short'} Nifty derivative bias from SUPPLIED repo change`,
        'Source uses no fixed SL or target and exits after one calendar month. Choose derivative/expiry and an independent risk policy before a bounded plan.'
      )
    }
    case '7.6': {
      const lows = q.lows.slice(-3),
        highs = q.highs.filter((z) => lows.length === 3 && z.index >= lows[0].index - 10).slice(-3)
      if (lows.length < 3 || highs.length < 3 || !q.volumeMean)
        return waiting(d, 'Wait for three increasingly shallow confirmed contractions')
      const ceiling = Math.max(...highs.map((z) => z.price)),
        depth = lows.map((z) => ceiling - z.price),
        duration = lows.map((z, j) => Math.abs(highs[j].index - z.index)),
        vol = lows.map((z, j) => {
          const a = Math.min(z.index, highs[j].index),
            b = Math.max(z.index, highs[j].index),
            v = f.slice(a, b + 1)
          return v.reduce((s, t) => s + t.bar.volume, 0) / v.length
        })
      if (
        lows[0].price < lows[1].price &&
        lows[1].price < lows[2].price &&
        depth[0] > depth[1] &&
        depth[1] > depth[2] &&
        duration[0] > duration[1] &&
        duration[1] >= duration[2] &&
        vol[0] > vol[1] &&
        vol[1] >= vol[2] &&
        green(x) &&
        x.bar.close > ceiling &&
        x.bar.volume > s.volumeFactor * q.volumeMean &&
        q.bar.close <= ceiling
      )
        return candidate(
          d,
          a,
          'long',
          i,
          lows[2].price - buf,
          rrTarget(entry, lows[2].price - buf, 'long', 3),
          {
            ...connectSourcePoints(
              f,
              [...highs, ...lows].map((p) => ({ index: p.index, price: p.price, role: p.kind }))
            ),
            targetMethod: 'Selected source3R branch',
            stopMethod: 'Third contraction low',
            notes: [
              'Local confirmed3L/3R contractions, shorter recovery, declining volume and1.5×breakout volume. Entry reference is the breakout candle CLOSE; not backdated to a pivot.',
            ],
          }
        )
      return waiting(
        d,
        'Wait for the third shallower/faster lower-volume pullback and high-volume green resistance break'
      )
    }
    case '7.7': {
      for (const side of ['long', 'short'] as const) {
        const pivots = [...q.highs, ...q.lows].sort((a, b) => a.index - b.index).slice(-7),
          last = pivots.slice(-3),
          older = pivots.slice(0, -3),
          shape = side === 'long' ? ['low', 'high', 'low'] : ['high', 'low', 'high']
        if (last.length !== 3 || !last.every((p, j) => p.kind === shape[j])) continue
        const beforeH = older.filter((z) => z.kind === 'high').slice(-2),
          beforeL = older.filter((z) => z.kind === 'low').slice(-2),
          trend =
            beforeH.length === 2 &&
            beforeL.length === 2 &&
            (side === 'long'
              ? beforeH[1].price > beforeH[0].price && beforeL[1].price > beforeL[0].price
              : beforeH[1].price < beforeH[0].price && beforeL[1].price < beforeL[0].price)
        if (trend && (side === 'long' ? green(q) : red(q)) && candleBreak(a, side)) {
          const stop =
            side === 'long'
              ? Math.min(last[2].price, q.bar.low) - buf
              : Math.max(last[2].price, q.bar.high) + buf
          return hit(side, stop, rrTarget(entry, stop, side, 4), {
            ...connectSourcePoints(
              f,
              pivots.map((p) => ({ index: p.index, price: p.price, role: p.kind }))
            ),
            targetMethod: 'Source two units at1R, final unit selected4R',
            stopMethod: 'Selected pullback swing / signal extreme',
            partialAtR: 1,
            breakevenAfterPartial: true,
            notes: [
              'Local confirmed-pivot two-legged pullback. Source example: two-thirds at1R, remaining stop to entry then4R (5R alternative). No actual partial orders.',
            ],
          })
        }
      }
      return waiting(
        d,
        'Wait for HH/HL or LL/LH trend, two confirmed countertrend swing legs and signal-candle break'
      )
    }
    default:
      throw Error(`No price-action handler for ${d.id}`)
  }
}
