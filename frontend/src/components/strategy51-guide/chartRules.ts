import type { EvaluationInput, StrategyDefinition, StrategyRow, Side, Frame } from './types'
import { expectedHourlyClose } from './session'
import {
  body,
  breakout,
  candidate,
  candleBreak,
  connectSourcePoints,
  contextPlan,
  crossDown,
  crossUp,
  green,
  nextPivot,
  present,
  red,
  reversal,
  row,
  rrTarget,
  small,
  supplied,
  swingStop,
  touches,
  waiting,
} from './ruleHelpers'
function fib(f: Frame, side: Side) {
  const hi = f.highs.at(-1),
    lo = f.lows.at(-1)
  if (!hi || !lo || hi.price <= lo.price) return
  const ok = side === 'long' ? lo.index < hi.index : hi.index < lo.index
  if (!ok) return
  return {
    hi: hi.price,
    lo: lo.price,
    levels: [0.236, 0.382, 0.5, 0.618].map((r) =>
      side === 'long' ? hi.price - r * (hi.price - lo.price) : lo.price + r * (hi.price - lo.price)
    ),
  }
}
function previousStructure(f: Frame, side: Side) {
  const h = f.highs.slice(-2),
    l = f.lows.slice(-2)
  return (
    h.length === 2 &&
    l.length === 2 &&
    (side === 'long'
      ? h[1].price > h[0].price && l[1].price > l[0].price
      : h[1].price < h[0].price && l[1].price < l[0].price)
  )
}
function macdCrossRecent(a: EvaluationInput, side: Side) {
  return a.frames.slice(Math.max(1, a.index - 8), a.index).some((f, k) => {
    const p = a.frames[Math.max(1, a.index - 8) + k - 1]
    return side === 'long'
      ? p.macd! <= p.macdSignal! && f.macd! > f.macdSignal!
      : p.macd! >= p.macdSignal! && f.macd! < f.macdSignal!
  })
}
export function chartRule(d: StrategyDefinition, a: EvaluationInput): StrategyRow {
  const { frames: f, index: i, context: ctx, settings: s } = a,
    x = f[i],
    q = f[i - 1],
    p = f[i - 2],
    b = x.bar,
    entry = b.close,
    buf = Math.max(ctx.tickSize, (q?.atr ?? 0) * 0.05),
    up = q?.trend === 'bull',
    down = q?.trend === 'bear'
  const hit = (
    side: Side,
    stop: number | undefined,
    target: number | undefined,
    extra: Parameters<typeof candidate>[6] = {}
  ) => candidate(d, a, side, i - 1, stop, target, extra)
  if (!q || !p) return waiting(d, 'Load enough completed candles for the strategy sequence')
  const swingL = swingStop(q, 'long'),
    swingH = swingStop(q, 'short')
  switch (d.id) {
    case '1.1': {
      if (!present(q.upper, q.lower, q.ema[9]))
        return row(
          d,
          'needs-data',
          'Bollinger/EMA warm-up incomplete',
          'Load at least30 completed30m candles'
        )
      const recent = f.slice(Math.max(1, i - 8), i - 1)
      const gapDown = recent.some(
        (z) =>
          z.sessionIndex === 0 &&
          z.bar.open < f[z.index - 1].bar.close &&
          f[z.index - 1].trend === 'bull'
      )
      const gapUp = recent.some(
        (z) =>
          z.sessionIndex === 0 &&
          z.bar.open > f[z.index - 1].bar.close &&
          f[z.index - 1].trend === 'bear'
      )
      const X = q.upper! - q.ema[9]!,
        Y = q.ema[9]! - q.lower!
      if (gapDown && Y > X && green(q) && touches(q, q.lower, s.touchATR) && candleBreak(a, 'long'))
        return hit('long', q.bar.low - buf, q.upper, {
          stopMethod: 'Lower-band support candle low',
          notes: ['Local BB20/2 and completed session-gap/rejection convention.'],
        })
      if (gapUp && X > Y && red(q) && touches(q, q.upper, s.touchATR) && candleBreak(a, 'short'))
        return hit('short', q.bar.high + buf, q.lower, {
          stopMethod: 'Upper-band rejection candle high',
        })
      return waiting(
        d,
        'Wait for the trend-side session gap, band rejection and later candle-close break'
      )
    }
    case '1.2': {
      if (!present(q.wr, p.wr, q.sma[14]))
        return row(
          d,
          'needs-data',
          'Williams %R14/SMA14 warm-up',
          'Load at least16 completed candles'
        )
      const recent = f.slice(Math.max(0, i - 25), i - 2)
      if (
        recent.some((z) => z.wr != null && z.wr >= -20) &&
        p.wr! <= -45 &&
        q.wr! > p.wr! &&
        p.wr! >= -60 &&
        q.bar.close > q.sma[14]! &&
        green(q) &&
        candleBreak(a, 'long')
      )
        return hit('long', swingL, undefined, {
          stopMethod: 'Confirmed preceding swing low',
          notes: [
            'The source title mentions MACD; its execution uses Williams %R14 and SMA14 only. Local -50 tolerance ±10.',
          ],
        })
      if (
        recent.some((z) => z.wr != null && z.wr <= -80) &&
        p.wr! >= -55 &&
        q.wr! < p.wr! &&
        p.wr! <= -40 &&
        q.bar.close < q.sma[14]! &&
        red(q) &&
        candleBreak(a, 'short')
      )
        return hit('short', swingH, undefined, { stopMethod: 'Confirmed preceding swing high' })
      return waiting(
        d,
        'Wait for Williams %R extreme → -50 reversal, SMA14 bias and signal-candle break'
      )
    }
    case '1.3':
    case '2.1': {
      const sides: Side[] = d.id === '1.3' ? ['long'] : ['long', 'short']
      if (d.id === '2.1' && !present(q.sma[200], f[i - 6]?.sma[200]))
        return row(
          d,
          'needs-data',
          'SMA200 warm-up incomplete',
          'Load205 completed5m candles; local200-bar SMA interpretation'
        )
      for (const side of sides) {
        const z = fib(q, side)
        if (!z) continue
        const bias =
          d.id === '1.3'
            ? up
            : side === 'long'
              ? q.bar.close > q.sma[200]! && q.sma[200]! > f[i - 6].sma[200]!
              : q.bar.close < q.sma[200]! && q.sma[200]! < f[i - 6].sma[200]!
        const level = z.levels.find((v) => touches(q, v, s.touchATR))
        if (level == null || !bias) continue
        if (
          (side === 'long' ? green(q) : red(q)) &&
          (d.id !== '1.3' || macdCrossRecent(a, side)) &&
          (d.id === '1.3' ? breakout(a, side, q.bar.close) : candleBreak(a, side))
        ) {
          const stop =
            d.id === '1.3'
              ? z.lo - buf
              : side === 'long'
                ? Math.max(z.lo, ...z.levels.filter((v) => v < q.bar.low)) - buf
                : Math.min(z.hi, ...z.levels.filter((v) => v > q.bar.high)) + buf
          return hit(side, stop, side === 'long' ? z.hi : z.lo, {
            ...connectSourcePoints(
              f,
              [q.highs.at(-1)!, q.lows.at(-1)!].map((p) => ({
                index: p.index,
                price: p.price,
                role: p.kind,
              }))
            ),
            stopMethod:
              d.id === '1.3'
                ? 'Previous confirmed impulse low'
                : 'Next Fibonacci level beyond pullback',
            notes: [
              'Confirmed3L/3R impulse anchors and .25ATR retracement tolerance are local.',
              ...(d.id === '2.1'
                ? [
                    'Source200-day wording interpreted explicitly as200 chart-bar SMA; short example uses candle low.',
                  ]
                : [
                    'Canonical MACD12-26 sign follows the chart, correcting the prose subtraction order.',
                  ]),
            ],
          })
        }
      }
      return waiting(
        d,
        'Wait for a confirmed impulse, Fibonacci pullback, trend/indicator agreement and closed trigger'
      )
    }
    case '1.4': {
      if (!s.localStructures)
        return row(
          d,
          'needs-context',
          'Body-connected triangle requires geometry',
          'Enable disclosed local structure rules or supply an annotated triangle'
        )
      const h = q.highs.slice(-2),
        l = q.lows.slice(-2)
      if (h.length < 2 || l.length < 2 || !q.volumeMean || !(q.atr! > 0))
        return waiting(d, 'Wait for a body-connected triangle after an uptrend rally')
      const top = (z: number) =>
          h[0].price + ((h[1].price - h[0].price) * (z - h[0].index)) / (h[1].index - h[0].index),
        bottom = (z: number) =>
          l[0].price + ((l[1].price - l[0].price) * (z - l[0].index)) / (l[1].index - l[0].index)
      // Structure contacts use body prices, not wick endpoints.
      const bodyTop = (j: number) => Math.max(f[j].bar.open, f[j].bar.close),
        bodyBottom = (j: number) => Math.min(f[j].bar.open, f[j].bar.close)
      const upper =
          bodyTop(h[0].index) +
          ((bodyTop(h[1].index) - bodyTop(h[0].index)) * (i - 1 - h[0].index)) /
            (h[1].index - h[0].index),
        lower =
          bodyBottom(l[0].index) +
          ((bodyBottom(l[1].index) - bodyBottom(l[0].index)) * (i - 1 - l[0].index)) /
            (l[1].index - l[0].index)
      const start = Math.min(h[0].index, l[0].index),
        prior = f.slice(Math.max(0, start - 15), start),
        rangeVol = f.slice(start, i - 1),
        rally = prior.length >= 3 && prior.at(-1)!.bar.close - prior[0].bar.open > 3 * q.atr!
      if (
        h[1].price < h[0].price &&
        l[1].price > l[0].price &&
        top(i) > bottom(i) &&
        rally &&
        rangeVol.length >= 6 &&
        rangeVol.reduce((v, z) => v + z.bar.volume, 0) / rangeVol.length < q.volumeMean &&
        green(q) &&
        body(q) > 0.6 * (q.bar.high - q.bar.low) &&
        q.bar.close > upper &&
        q.bar.volume > s.volumeFactor * q.volumeMean &&
        breakout(a, 'long', q.bar.close)
      )
        return hit('long', lower - buf, rrTarget(entry, lower - buf, 'long', 2), {
          points: [
            ...h.map((p) => ({ index: p.index, price: bodyTop(p.index), role: 'high' })),
            ...l.map((p) => ({ index: p.index, price: bodyBottom(p.index), role: 'low' })),
          ],
          segments: [
            ...(connectSourcePoints(
              f,
              h.map((p) => ({ index: p.index, price: bodyTop(p.index), role: 'high' }))
            ).segments ?? []),
            ...(connectSourcePoints(
              f,
              l.map((p) => ({ index: p.index, price: bodyBottom(p.index), role: 'low' }))
            ).segments ?? []),
          ],
          targetMethod: 'Source minimum2R',
          stopMethod: 'Lower body-connected triangle boundary',
          notes: [
            'Local body-pivot triangle, ≥3ATR rally, six-bar contraction and1.5×volume definitions.',
          ],
        })
      return waiting(
        d,
        'Wait for contracting body-defined triangle and a solid high-volume upside breakout'
      )
    }
    case '1.5': {
      const z = supplied(a, d.id)
      if (
        !z ||
        z.kind !== 'gap-zone' ||
        !z.liquidityConfirmed ||
        z.zoneLow == null ||
        z.zoneHigh == null
      )
        return row(
          d,
          'needs-context',
          'Needs dated gap zone and liquid-universe confirmation',
          'Supply an old gap zone, first-touch count and target; chart gap alone is insufficient'
        )
      if ((z.touchCount ?? 99) > 1)
        return waiting(d, 'The source excludes second and later gap-zone revisits')
      const gap = z.side === 'long' ? q.bar.open > p.bar.high : q.bar.open < p.bar.low
      if (
        gap &&
        q.bar.low <= z.zoneHigh &&
        q.bar.high >= z.zoneLow &&
        (z.side === 'long' ? green(q) : red(q)) &&
        candleBreak(a, z.side)
      )
        return hit(
          z.side,
          z.side === 'long'
            ? Math.min(q.bar.low, p.bar.high) - buf
            : Math.max(q.bar.high, p.bar.low) + buf,
          z.target,
          {
            supplied: true,
            stopMethod: 'Reversal gap extreme',
            notes: [
              'Old zone, liquidity and touch count supplied by user; not detected institutional activity.',
              'Short SL follows p63 gap-high example rather than conflicting p62 bullet.',
            ],
          }
        )
      return waiting(d, 'Wait for the first old-zone revisit and a fresh directional reversal gap')
    }
    case '1.6': {
      if (!present(q.width, p.width, q.basis))
        return row(d, 'needs-data', 'BB width warm-up', 'Load BB20/2 history')
      const widths = f
          .slice(Math.max(0, i - 11), i - 1)
          .map((z) => z.width)
          .filter((v): v is number => v != null),
        squeezed =
          widths.length >= 5 &&
          Math.min(...widths) <= s.squeezePercent &&
          Math.max(...widths) - Math.min(...widths) <= Math.max(0.25, s.squeezePercent * 0.5)
      if (squeezed && q.width! > p.width!) {
        if (q.bar.close > q.upper! && green(q) && candleBreak(a, 'long'))
          return hit('long', q.basis! - buf, undefined, {
            conditionalExit: 'bb-mid',
            stopMethod: 'Frozen middle BB snapshot',
          })
        if (q.bar.close < q.lower! && red(q) && candleBreak(a, 'short'))
          return hit('short', q.basis! + buf, undefined, {
            conditionalExit: 'bb-mid',
            stopMethod: 'Frozen middle BB snapshot',
            notes: ['Short exit above middle band follows example; the source bullet conflicts.'],
          })
      }
      return waiting(
        d,
        `Wait for BB squeeze ≤${s.squeezePercent}% and expansion breakout; exit on middle-band reversal`
      )
    }
    case '1.7': {
      if (!present(x.cloudA, x.cloudB, x.conversion, x.base, p.cloudA))
        return row(
          d,
          'needs-data',
          'Ichimoku9/26/52+26 warm-up',
          'Load at least80 completed candles'
        )
      const top = Math.max(x.cloudA!, x.cloudB!),
        bottom = Math.min(x.cloudA!, x.cloudB!)
      if (x.conversion! > x.base! && b.close > top && q.bar.close <= Math.max(q.cloudA!, q.cloudB!))
        return candidate(
          d,
          a,
          'long',
          i,
          x.cloudA! - buf,
          rrTarget(entry, x.cloudA! - buf, 'long', 3),
          {
            targetMethod: 'Selected source-discussed3R',
            stopMethod: 'Currently plotted SpanA',
            notes: [
              'Canonical SpanB midpoint corrects missing /2 in prose; cloud values calculated26 bars earlier.',
            ],
          }
        )
      if (
        x.conversion! < x.base! &&
        b.close < bottom &&
        q.bar.close >= Math.min(q.cloudA!, q.cloudB!)
      )
        return candidate(d, a, 'short', i, x.cloudA! + buf, undefined, {
          stopMethod: 'Currently plotted SpanA',
        })
      return waiting(
        d,
        'Wait for conversion/base agreement and a close through the currently plotted cloud'
      )
    }
    case '2.2': {
      if (!present(q.r1, q.s1, q.st7))
        return row(
          d,
          'needs-data',
          'Prior-session pivots / Supertrend7 needed',
          'Load completed previous-session HLC and ATR7; multiplier3 is local'
        )
      if (
        green(q) &&
        q.bar.close > q.r1! &&
        p.bar.close <= p.r1! &&
        q.bar.close > q.st7! &&
        breakout(a, 'long', q.bar.close)
      )
        return hit('long', q.st7! - buf, undefined, {
          conditionalExit: 'supertrend7',
          cutoffMinute: 915,
          stopMethod: 'Supertrend ATR7 / local multiplier3',
        })
      if (
        red(q) &&
        q.bar.close < q.s1! &&
        p.bar.close >= p.s1! &&
        q.bar.close < q.st7! &&
        breakout(a, 'short', q.bar.close)
      )
        return hit('short', q.st7! + buf, undefined, {
          conditionalExit: 'supertrend7',
          cutoffMinute: 915,
          stopMethod: 'Supertrend ATR7 / local multiplier3',
        })
      return waiting(d, 'Wait outside R1–S1 with matching Supertrend7 and a directional candle')
    }
    case '2.3': {
      if (!present(p.vwap, p.vwapSD, q.vwap, q.vwapSD))
        return row(
          d,
          'needs-data',
          'Valid traded volume/session VWAP required',
          'Load positive traded-volume candles; index volume is not synthesized'
        )
      if (red(p) && p.bar.close < p.vwap! - 2 * p.vwapSD! && green(q) && candleBreak(a, 'long'))
        return hit('long', q.bar.low - buf, q.vwap, {
          stopMethod: 'Green reversal candle low',
          targetMethod: 'Source T1 central VWAP; T2 opposite2SD band',
          notes: [
            `Source T2 snapshot ${(q.vwap! + 2 * q.vwapSD!).toFixed(4)}; single plan selects T1.`,
            `Local once-per-session cooldown; red outside CLOSE is mandatory.`,
          ],
        })
      if (green(p) && p.bar.close > p.vwap! + 2 * p.vwapSD! && red(q) && candleBreak(a, 'short'))
        return hit('short', q.bar.high + buf, q.vwap, {
          stopMethod: 'Red reversal candle high (checklist branch)',
          targetMethod: 'Source T1 central VWAP; T2 opposite2SD band',
        })
      return waiting(
        d,
        'Wait for an outside2SD close → opposite-color reversal → later candle-close break'
      )
    }
    case '2.4': {
      if (!present(q.rsi, q.vo))
        return row(
          d,
          'needs-data',
          'RSI/volume oscillator inputs unavailable',
          'Use real volume; local RSI14 and volume EMA5/10 are disclosed in Details'
        )
      if (up && q.rsi! <= 35 && Math.abs(q.vo! + 30) <= 10 && green(q) && candleBreak(a, 'long'))
        return hit('long', swingL, undefined, {
          conditionalExit: 'rsi70',
          stopMethod: 'Confirmed swing low',
          notes: ['Local RSI14/VO EMA5/10; VO ±10-point tolerance at source±30 extremes.'],
        })
      if (down && q.rsi! >= 65 && Math.abs(q.vo! - 30) <= 10 && red(q) && candleBreak(a, 'short'))
        return hit('short', swingH, undefined, {
          conditionalExit: 'rsi30',
          stopMethod: 'Confirmed swing high',
        })
      return waiting(
        d,
        'Wait for RSI30/70 and volume-oscillator extreme together, then a directional candle break'
      )
    }
    case '2.5':
    case '2.7': {
      if (!present(q.pivot, q.r1, q.s1))
        return row(
          d,
          'needs-data',
          'Completed pivot anchor missing',
          'Load previous completed session HLC; corrected Traditional R1=2P−L'
        )
      const levels = [q.s2, q.s1, q.cprLow, q.pivot, q.cprHigh, q.r1, q.r2].filter(
        (v): v is number => v != null
      )
      const width = present(q.cprHigh, q.cprLow, q.atr)
        ? (q.cprHigh! - q.cprLow!) / q.atr!
        : undefined
      if (d.id === '2.7' && width == null) return waiting(d, 'Wait for CPR and ATR width warm-up')
      for (const side of ['long', 'short'] as const) {
        const z = levels.find(
          (v) =>
            touches(q, v, s.touchATR) &&
            (side === 'long' ? green(q) && q.bar.close > v : red(q) && q.bar.close < v)
        )
        if (z == null || !candleBreak(a, side)) continue
        const crossed = f
          .slice(Math.max(0, i - 6), i - 1)
          .some((t) => (side === 'long' ? t.bar.close < z : t.bar.close > z))
        if (d.id === '2.7' && width! > 0.25 && width! < 1) continue
        return hit(
          side,
          side === 'long' ? q.bar.low - buf : q.bar.high + buf,
          nextPivot(q, side, entry),
          {
            targetMethod: 'Next existing Traditional pivot',
            stopMethod: 'Pivot reaction candle extreme',
            notes: [
              `${crossed ? 'Break/retest continuation' : 'Rejection reversal'} branch.`,
              ...(d.id === '2.7'
                ? [`Local CPR width/ATR: narrow≤.25, wide≥1; current${width!.toFixed(2)}.`]
                : []),
            ],
          }
        )
      }
      return waiting(
        d,
        d.id === '2.7'
          ? 'Wait for a narrow-CPR break or wide-CPR reversal at a pivot'
          : 'Wait for a pivot rejection or breakout/retest and later signal-candle break'
      )
    }
    case '2.6': {
      const h = a.extras.higher
      if (
        !h ||
        h.intervalSeconds !== 3600 ||
        h.symbol !== ctx.symbol ||
        (h.exchange ?? '') !== (ctx.exchange ?? '')
      )
        return row(
          d,
          'needs-data',
          'Matching completed hourly RSI14 is missing',
          'Load1h RSI14 as of each5m confirmation'
        )
      if (
        !Number.isFinite(h.observedAt) ||
        h.observedAt <
          Math.min(ctx.now, ctx.observedAt, x.bar.closeTime ?? x.bar.time + ctx.intervalSeconds)
      )
        return row(
          d,
          'needs-data',
          'Hourly request has not observed this confirming candle yet',
          'Wait for a fresh matching hourly-history reconciliation'
        )
      const asOf = Math.min(
        ctx.now,
        ctx.observedAt,
        h.observedAt,
        q.bar.closeTime ?? q.bar.time + 300
      )
      let j = h.bars.length - 1
      while (j >= 0 && (h.bars[j].closeTime ?? h.bars[j].time + 3600) > asOf) j--
      const hr = (h as typeof h & { rsi?: (number | undefined)[] }).rsi?.[j]
      const expected = expectedHourlyClose(a, asOf),
        actual = j >= 0 ? (h.bars[j].closeTime ?? h.bars[j].time + 3600) : undefined
      if (expected == null || actual !== expected)
        return row(
          d,
          'needs-data',
          'Hourly history does not reach the expected completed session bucket',
          'Wait for the latest expected hourly candle; a fresh request timestamp does not prove fresh bars'
        )
      if (hr == null)
        return row(
          d,
          'needs-data',
          'Hourly RSI14 warm-up / as-of candle unavailable',
          'Wait for15 completed matching hourly candles'
        )
      if (hr > 50 && q.rsi! < 30 && green(q) && candleBreak(a, 'long'))
        return hit('long', q.bar.low - buf, undefined, {
          conditionalExit: 'rsi-return70',
          stopMethod: '5m green signal low',
          notes: [
            `Last completed1h RSI14 ${hr.toFixed(2)}; source exit requires >70 then cross down.`,
          ],
        })
      if (hr < 50 && q.rsi! > 70 && red(q) && candleBreak(a, 'short'))
        return hit('short', q.bar.high + buf, undefined, {
          conditionalExit: 'rsi-return30',
          stopMethod: '5m red signal high',
        })
      return waiting(
        d,
        `Hourly RSI14 ${hr.toFixed(2)}; wait for opposite5m RSI extreme and signal-candle break`
      )
    }
    case '3.1': {
      for (const side of ['long', 'short'] as const) {
        const level = (side === 'long' ? p.highs : p.lows).at(-1)?.price
        if (
          previousStructure(p, side) &&
          level != null &&
          (side === 'long'
            ? p.bar.close <= level && green(q) && q.bar.close > level && q.rsi! > 50
            : p.bar.close >= level && red(q) && q.bar.close < level && q.rsi! < 50) &&
          candleBreak(a, side)
        )
          return hit(side, swingStop(q, side), undefined, {
            stopMethod: 'Confirmed opposing structure swing',
            notes: [
              'Local3L/3R HH/HL or LL/LH and RSI14>50/<50 as the unspecified momentum oscillator.',
            ],
          })
      }
      return waiting(
        d,
        'Wait for confirmed Dow structure, a swing break, momentum confirmation and later candle break'
      )
    }
    case '3.2': {
      const manual = supplied(a, d.id)
      if (
        manual?.zoneLow != null &&
        manual.zoneHigh != null &&
        (manual.side === 'long' ? green(q) : red(q)) &&
        q.bar.low <= manual.zoneHigh &&
        q.bar.high >= manual.zoneLow &&
        candleBreak(a, manual.side)
      )
        return hit(
          manual.side,
          manual.side === 'long' ? q.bar.low - buf : q.bar.high + buf,
          manual.target,
          {
            supplied: true,
            stopMethod: 'Reversal candle extreme',
            notes: [
              'User-supplied order-block/fair-value zone; not detected institutional orders.',
            ],
          }
        )
      if (!s.localStructures)
        return row(
          d,
          'needs-context',
          'Order-block/fair-value zone required',
          'Supply a dated zone or enable local imbalance interpretation'
        )
      for (let j = i - 3; j >= Math.max(2, i - 20); j--) {
        const z = f[j],
          before = f[j - 2]
        const bullish = z.bar.low > before.bar.high,
          bearish = z.bar.high < before.bar.low,
          displacement = Math.abs(z.bar.close - before.bar.open) > 2 * (z.atr ?? Infinity)
        if (!displacement) continue
        if (
          bullish &&
          q.bar.low <= z.bar.low &&
          q.bar.high >= before.bar.high &&
          green(q) &&
          candleBreak(a, 'long')
        )
          return hit('long', q.bar.low - buf, q.highs.at(-1)?.price, {
            stopMethod: 'Fair-value retracement reversal low',
            notes: [
              'Local three-candle imbalance and2ATR displacement; no claim of actual smart-money activity.',
            ],
          })
        if (
          bearish &&
          q.bar.high >= z.bar.high &&
          q.bar.low <= before.bar.low &&
          red(q) &&
          candleBreak(a, 'short')
        )
          return hit('short', q.bar.high + buf, q.lows.at(-1)?.price, {
            stopMethod: 'Fair-value retracement reversal high',
            notes: ['Local three-candle imbalance and2ATR displacement.'],
          })
      }
      return waiting(
        d,
        'Wait for aggressive displacement, a known value zone, retracement/reversal and candle break'
      )
    }
    case '3.3':
      return contextPlan(d, a, 'elliott', true)
    case '3.4': {
      for (const side of ['long', 'short'] as const) {
        const high = q.fractalHighs.at(-1),
          low = q.fractalLows.at(-1),
          level = side === 'long' ? high?.price : low?.price
        if (!present(q.sma[50], level)) continue
        if (
          (side === 'long'
            ? p.bar.close <= level! && green(q) && q.bar.close > q.sma[50]! && q.bar.close > level!
            : p.bar.close >= level! &&
              red(q) &&
              q.bar.close < q.sma[50]! &&
              q.bar.close < level!) &&
          candleBreak(a, side)
        )
          return hit(side, side === 'long' ? low?.price : high?.price, undefined, {
            stopMethod: 'Opposite confirmed4L/4R fractal',
            notes: [
              'Local strict4L/4R fractals; not a parity claim for the named custom script. SMA50 uses chart periods.',
            ],
          })
      }
      return waiting(
        d,
        'Wait for a known4L/4R fractal break with SMA50 agreement and a later candle break'
      )
    }
    case '3.5':
      return contextPlan(d, a, 'renko')
    case '3.6': {
      if (!present(q.donHigh, q.donLow, q.donMid))
        return row(
          d,
          'needs-data',
          'Donchian warm-up incomplete',
          `Load${s.donchianPeriod + 5} candles; local Donchian length${s.donchianPeriod}`
        )
      for (const side of ['long', 'short'] as const) {
        const recent = f.slice(Math.max(0, i - 6), i - 1),
          touch = recent.findIndex((t) =>
            side === 'long' ? t.bar.high >= t.donHigh! : t.bar.low <= t.donLow!
          ),
          pull =
            touch >= 0 &&
            recent
              .slice(touch + 1)
              .some((t) => (side === 'long' ? t.bar.close < t.donHigh! : t.bar.close > t.donLow!))
        if (
          pull &&
          (side === 'long'
            ? green(q) && q.bar.close > q.donHigh!
            : red(q) && q.bar.close < q.donLow!) &&
          candleBreak(a, side)
        ) {
          const stop = q.donMid! + (side === 'long' ? -buf : buf)
          return hit(side, stop, rrTarget(entry, stop, side, 2), {
            targetMethod: 'Source-discussed typical2R',
            stopMethod: 'Frozen Donchian middle band',
            notes: [
              'Prior completed Donchian20; ordered touch→pullback→rebreak. Source short trail wording conflicts; no unstated automatic trailing.',
            ],
          })
        }
      }
      return waiting(
        d,
        'Wait for Donchian band touch, an actual pullback and a rebreak; first break alone is insufficient'
      )
    }
    case '3.7':
      return contextPlan(d, a, 'gann')
    case '4.1': {
      // A completed calendar-month anchor is distinct from prior daily pivots.
      const signalDate = new Date(q.bar.time * 1000),
        monthStart = Date.UTC(signalDate.getUTCFullYear(), signalDate.getUTCMonth(), 1) / 1000,
        priorStart = Date.UTC(signalDate.getUTCFullYear(), signalDate.getUTCMonth() - 1, 1) / 1000,
        older = f
          .slice(0, i - 1)
          .filter((z) => z.bar.time >= priorStart && z.bar.time < monthStart),
        anchor = older.at(-1)
      if (!anchor)
        return row(
          d,
          'needs-data',
          'Completed prior-month pivot anchor missing',
          'Load daily history spanning at least two full calendar months'
        )
      const group = older
      if (group.length < 15 || f[0].bar.time >= priorStart)
        return row(
          d,
          'needs-data',
          'Prior-month OHLC anchor is incomplete',
          'Load verified daily history beginning before the prior calendar month'
        )
      const hi = Math.max(...group.map((z) => z.bar.high)),
        lo = Math.min(...group.map((z) => z.bar.low)),
        P = (hi + lo + anchor.bar.close) / 3,
        levels = [P, 2 * P - hi, P - hi + lo, 2 * P - lo, P + hi - lo]
      for (const side of ['long', 'short'] as const) {
        if (side === 'short' && ctx.exchange === 'NSE') continue
        const level = levels.find((v) => touches(q, v, s.touchATR))
        if (level == null) continue
        if ((side === 'long' ? up && green(q) : down && red(q)) && candleBreak(a, side)) {
          const targets = levels
            .filter((v) => (side === 'long' ? v > entry : v < entry))
            .sort((a, b) => a - b)
          return hit(
            side,
            side === 'long' ? Math.min(level, q.bar.low) - buf : Math.max(level, q.bar.high) + buf,
            side === 'long' ? targets[0] : targets.at(-1),
            {
              targetMethod: 'Next completed-month Traditional pivot',
              stopMethod: 'Monthly support/resistance reaction area',
              notes: [
                'Local explicit previous calendar-month pivot anchor; short requires a derivative chart.',
              ],
            }
          )
        }
      }
      return waiting(
        d,
        'Wait for daily trend and completed-month pivot support/resistance reaction'
      )
    }
    case '4.2': {
      if (!present(q.rsi, p.rsi, q.st10))
        return row(
          d,
          'needs-data',
          'RSI14/Supertrend10 warm-up',
          'Load completed daily candles; local ST10/3 and RSI14'
        )
      if (q.bar.close > q.st10! && crossUp(p.rsi, q.rsi, 60) && green(q) && candleBreak(a, 'long'))
        return hit('long', swingL, undefined, {
          conditionalExit: 'supertrend10',
          stopMethod: 'Checklist preceding swing low',
        })
      if (
        ctx.exchange !== 'NSE' &&
        q.bar.close < q.st10! &&
        crossDown(p.rsi, q.rsi, 40) &&
        red(q) &&
        candleBreak(a, 'short')
      )
        return hit('short', swingH, undefined, {
          conditionalExit: 'supertrend10',
          stopMethod: 'Checklist preceding swing high',
        })
      return waiting(d, 'Wait for RSI crossing60/40 with Supertrend agreement;40–60 is sideways')
    }
    case '4.3':
      return contextPlan(d, a, 'sector', true)
    case '4.4': {
      const rs = f.slice(Math.max(17, i - 60), i - 3),
        low = rs.filter((z) =>
          f.slice(z.index - 3, z.index + 4).every((y) => y.index === z.index || y.rsi! > z.rsi!)
        ),
        high = rs.filter((z) =>
          f.slice(z.index - 3, z.index + 4).every((y) => y.index === z.index || y.rsi! < z.rsi!)
        )
      if (
        low.slice(-2).length === 2 &&
        low.slice(-2).every((z) => z.rsi! < 30) &&
        crossUp(p.rsi, q.rsi, 30) &&
        candleBreak(a, 'long')
      )
        return hit('long', swingL, undefined, {
          conditionalExit: 'rsi70',
          stopMethod: 'Confirmed price swing low',
          notes: [
            'W detected on RSI14 using local3L/3R oscillator pivots; recognition is delayed, never backdated.',
          ],
        })
      if (
        high.slice(-2).length === 2 &&
        high.slice(-2).every((z) => z.rsi! > 70) &&
        crossDown(p.rsi, q.rsi, 70) &&
        candleBreak(a, 'short')
      )
        return hit('short', swingH, undefined, {
          conditionalExit: 'rsi30',
          stopMethod: 'Confirmed price swing high',
          notes: ['M detected on RSI14, not a price-chart M.'],
        })
      return waiting(
        d,
        'Wait for a confirmed RSI W below30 / M above70, threshold return and price confirmation'
      )
    }
    case '5.1': {
      if (!present(q.rsi, q.sar))
        return row(d, 'needs-data', 'HA / RSI14 / SAR warm-up', 'Load completed3m real candles')
      const bullish = q.haClose > q.haOpen && Math.abs(q.haLow - q.haOpen) < 1e-8,
        bearish = q.haClose < q.haOpen && Math.abs(q.haHigh - q.haOpen) < 1e-8
      if (bullish && q.sar! < q.bar.close && q.rsi! > 50 && candleBreak(a, 'long'))
        return hit('long', q.sar, rrTarget(entry, q.sar, 'long', 2), {
          targetMethod: 'Source2R; partial half at1R if multiple units',
          stopMethod: 'SAR.02/.02/.2 snapshot',
          partialAtR: 1,
          notes: [
            'HA confirmation only; real-candle price levels and raw-price RSI/SAR are the explicit local mapping.',
          ],
        })
      if (bearish && q.sar! > q.bar.close && q.rsi! < 50 && candleBreak(a, 'short'))
        return hit('short', q.sar, rrTarget(entry, q.sar, 'short', 2), {
          targetMethod: 'Source2R',
          stopMethod: 'SAR.02/.02/.2 snapshot',
          partialAtR: 1,
        })
      return waiting(
        d,
        'Wait for a wickless-direction HA candle, matching SAR/RSI50 and real-candle high/low break'
      )
    }
    case '5.2': {
      for (const side of ['long', 'short'] as const) {
        const pivots = (side === 'long' ? q.lows : q.highs).slice(-2)
        if (pivots.length < 2) continue
        const [a1, a2] = pivots,
          r1 = f[a1.index].rsi,
          r2 = f[a2.index].rsi,
          div =
            side === 'long' ? a2.price < a1.price && r2! >= r1! : a2.price > a1.price && r2! <= r1!
        if (
          div &&
          touches(q, side === 'long' ? q.lower : q.upper, s.touchATR) &&
          (side === 'long' ? green(q) : red(q)) &&
          candleBreak(a, side)
        )
          return hit(
            side,
            side === 'long' ? q.bar.low - buf : q.bar.high + buf,
            side === 'long' ? q.upper : q.lower,
            {
              targetMethod: 'Opposite BB20/2 snapshot',
              stopMethod: 'Reversal candle extreme',
              notes: [
                'Local RSI14/BB20/2; aligned RSI at causally recognized price pivots. RSI30/70 is not required.',
              ],
            }
          )
      }
      return waiting(
        d,
        'Wait for confirmed price/RSI divergence at a Bollinger band and reversal-candle break'
      )
    }
    case '5.3': {
      if (!present(q.vwap, q.vwapSD, q.rsi))
        return row(
          d,
          'needs-data',
          'Session VWAP / RSI needs real volume',
          'Load valid positive-volume1m history'
        )
      if (q.rsi! < 30 && touches(q, q.vwap, s.touchATR) && green(q) && candleBreak(a, 'long'))
        return hit('long', q.vwap! - buf, q.vwap! + 2 * q.vwapSD!, {
          targetMethod: 'Selected VWAP band2 snapshot (local band choice)',
          stopMethod: 'Below central VWAP',
        })
      if (q.rsi! > 70 && touches(q, q.vwap, s.touchATR) && red(q) && candleBreak(a, 'short'))
        return hit('short', q.vwap! + buf, q.vwap! - 2 * q.vwapSD!, {
          targetMethod: 'Selected VWAP band2 snapshot (local band choice)',
          stopMethod: 'Above central VWAP',
        })
      return waiting(
        d,
        'Wait for RSI30/70 and CENTRAL VWAP support/rejection; this is not the2SD outside-close setup'
      )
    }
    case '5.4': {
      const range = f.slice(Math.max(0, i - 6), i - 1),
        before = f[i - 6]
      if (range.length < 5 || !before)
        return waiting(d, 'Wait for a trend followed by4–5 small-body range candles')
      const hi = Math.max(...range.map((z) => z.bar.high)),
        lo = Math.min(...range.map((z) => z.bar.low)),
        tight = range.every(small) && hi - lo <= 2 * (q.atr ?? 0)
      for (const side of ['long', 'short'] as const)
        if (
          tight &&
          (side === 'long'
            ? before.trend === 'bull' && green(q) && q.bar.close > hi
            : before.trend === 'bear' && red(q) && q.bar.close < lo) &&
          candleBreak(a, side)
        ) {
          const stop = side === 'long' ? q.bar.low - buf : q.bar.high + buf
          return hit(side, stop, rrTarget(entry, stop, side, 3), {
            targetMethod: 'Source minimum3R',
            stopMethod: 'Finished breakout candle extreme',
            timeLimitSeconds: 600,
            notes: [
              'Local5-bar small-body (.35 range) consolidation ≤2ATR; liquidity not established by the chart alone. Source mandatory10-minute time exit.',
            ],
          })
        }
      return waiting(
        d,
        'Wait for5-candle consolidation, trend-aligned breakout and later closed confirmation'
      )
    }
    case '5.5': {
      if (!['NSE', 'NSE_INDEX', 'NFO', 'BSE', 'BSE_INDEX', 'BFO'].includes(ctx.exchange ?? ''))
        return row(
          d,
          'needs-context',
          'Exchange opening session is not defined for this source rule',
          'Use an Indian exchange session chart; a continuously traded market has no09:15 opening candle'
        )
      if (x.minute < 555 || x.minute >= 615)
        return waiting(d, 'New entries only in the first exchange-session hour (09:15–10:15 IST)')
      const last = f
        .slice(Math.max(0, i - 12), i)
        .reverse()
        .find(
          (z) =>
            z.day === x.day &&
            z.sessionIndex >= 1 &&
            z.minute < 615 &&
            z.ema[5] != null &&
            z.bar.low > z.ema[5]!
        )
      if (!last)
        return waiting(
          d,
          'Wait after the first candle for a whole candle above EMA5; source short branch only'
        )
      if (breakout(a, 'short', last.bar.low, last.index))
        return candidate(
          d,
          a,
          'short',
          last.index,
          last.bar.high + buf,
          rrTarget(entry, last.bar.high + buf, 'short', 3),
          {
            targetMethod: 'Selected source3R branch',
            stopMethod: 'Latest wholly-above-EMA5 reference high',
            notes: [
              'Local EMA5 choice from source5/7 text; screenshotEMA9 conflict is not silently adopted. No source long mirror.',
            ],
          }
        )
      return waiting(
        d,
        `Pending short reference updated to the latest non-touch candle; wait below${last.bar.low}`
      )
    }
    case '5.6': {
      if (!present(q.ema[14]))
        return row(d, 'needs-data', 'EMA14 warm-up', 'Load15 completed1m candles')
      const recent = f.slice(Math.max(0, i - 5), i - 1)
      if (
        recent.length >= 3 &&
        recent[0].bar.close > p.bar.close &&
        reversal(q, p, 'long') &&
        q.bar.close < q.ema[14]! &&
        candleBreak(a, 'long')
      )
        return hit('long', q.bar.low - buf, q.ema[14], {
          targetMethod: 'Source EMA14 snapshot',
          stopMethod: 'Bullish reversal low',
          notes: [
            'Fixed user-risk sizing only. Source loss-doubling/cap statements conflict; no automatic escalation. No EMA5 crossover requirement.',
          ],
        })
      if (
        recent.length >= 3 &&
        recent[0].bar.close < p.bar.close &&
        reversal(q, p, 'short') &&
        q.bar.close > q.ema[14]! &&
        candleBreak(a, 'short')
      )
        return hit('short', q.bar.high + buf, q.ema[14], {
          targetMethod: 'Source EMA14 snapshot',
          stopMethod: 'Bearish reversal high',
          notes: ['Signal rules retained; loss-based sizing escalation is not implemented.'],
        })
      return waiting(
        d,
        'Wait for a price reversal toward EMA14 and a signal-candle break; risk never doubles after losses'
      )
    }
    default:
      throw Error(`No chart strategy handler for ${d.id}`)
  }
}
