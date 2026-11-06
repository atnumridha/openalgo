import type { Bar } from './model'
import { recognizeGuideReversal } from './pinterestCandlePatterns'

export interface ExtendedCandleMatch {
  side: 'CALL' | 'PUT' | 'NEUTRAL'
  name: string
  pattern: string
  extreme: number
}

const body = (b: Bar) => Math.abs(b.close - b.open)
const range = (b: Bar) => b.high - b.low
const upper = (b: Bar) => b.high - Math.max(b.open, b.close)
const lower = (b: Bar) => Math.min(b.open, b.close) - b.low
const up = (b: Bar) => b.close > b.open
const down = (b: Bar) => b.close < b.open
const doji = (b: Bar) => body(b) <= range(b) * 0.1
const long = (b: Bar) => body(b) >= range(b) * 0.55
const marubozu = (b: Bar) =>
  body(b) >= range(b) * 0.9 && upper(b) <= range(b) * 0.05 && lower(b) <= range(b) * 0.05
const flip = (b: Bar): Bar => ({ ...b, open: -b.open, high: -b.low, low: -b.high, close: -b.close })

/** Shape observations only; caller supplies completed candles in chronological order.
 * Reference names come from candlestick sheets; numeric thresholds are explicit local
 * operational definitions, not calibrated success probabilities or trade instructions.
 * Context: net close move over four bars preceding the WHOLE pattern must exceed
 * half their mean range. All reversal patterns oppose this trend; three-line strike
 * continues it. Marubozu only needs an established trend, of either direction.
 * Doji <=10% body/range. Spinning top >10% and <=35%, both shadows >=body.
 * Long bodies >=55%; Marubozu >=90% with each shadow <=5% of range.
 * Tweezers allow 5% of the larger candle range between matching extremes.
 * Soldiers/crows have long bodies, <=20% terminal shadows, opens in the preceding
 * body, and progressively advancing closes. Inside/outside require a final close
 * beyond the first/second body's end respectively. Kicker requires two Marubozu
 * candles with a strict full-range gap. Abandoned baby requires a doji isolated
 * by strict full-range gaps on BOTH sides. Doji stars require body gaps on BOTH
 * sides and a final long body closing beyond the first body's midpoint.
 * Three-line strike: three soldiers/crows, then an opposite long body opening
 * beyond the third close and closing beyond the first open (continuation label).
 * Directional extreme is the pattern's low/high; neutral uses its final close.
 * No live-bar timing, future data, mutation, or execution is performed here.
 */
export function recognizeExtendedCandles(history: Bar[]): ExtendedCandleMatch[] {
  if (
    !history.length ||
    history.some(
      (b) =>
        ![b.open, b.high, b.low, b.close].every(Number.isFinite) ||
        b.high < Math.max(b.open, b.close) ||
        b.low > Math.min(b.open, b.close) ||
        b.high <= b.low
    )
  )
    return []
  const matches: ExtendedCandleMatch[] = []
  const guide = recognizeGuideReversal(history)
  if (guide) matches.push(guide)
  const last = history[history.length - 1]
  if (doji(last))
    matches.push({ side: 'NEUTRAL', name: 'Doji', pattern: 'extended-doji', extreme: last.close })
  else if (
    body(last) <= range(last) * 0.35 &&
    upper(last) >= body(last) &&
    lower(last) >= body(last)
  ) {
    matches.push({
      side: 'NEUTRAL',
      name: 'Spinning Top',
      pattern: 'extended-spinning-top',
      extreme: last.close,
    })
  }
  for (const bullish of [true, false]) {
    // Reflecting prices lets each predicate share the same precise bullish geometry.
    const bars = bullish ? history : history.map(flip)
    const c = bars.at(-1)!,
      p = bars.at(-2),
      a = bars.at(-3),
      z = bars.at(-4)
    const trend = (span: number) => {
      const before = bars.slice(0, -span).slice(-4)
      if (before.length < 4) return 0
      const change = before[3].close - before[0].close
      const average = before.reduce((total, b) => total + range(b), 0) / 4
      return Math.abs(change) > average * 0.5 ? Math.sign(change) : 0
    }
    const add = (id: string, bullName: string, bearName: string, span: number) => {
      const shape = history.slice(-span)
      matches.push({
        side: bullish ? 'CALL' : 'PUT',
        name: bullish ? bullName : bearName,
        pattern: `extended-${id}`,
        extreme: bullish
          ? Math.min(...shape.map((b) => b.low))
          : Math.max(...shape.map((b) => b.high)),
      })
    }
    const soldiers = (x: Bar, y: Bar, third: Bar) =>
      [x, y, third].every((b) => up(b) && long(b) && upper(b) <= range(b) * 0.2) &&
      y.open > x.open &&
      y.open < x.close &&
      third.open > y.open &&
      third.open < y.close &&
      y.close > x.close &&
      third.close > y.close
    if (up(c) && marubozu(c) && trend(1) !== 0)
      add('marubozu', 'Bullish Marubozu', 'Bearish Marubozu', 1)
    if (p && trend(2) < 0 && down(p) && up(c)) {
      if (
        long(p) &&
        long(c) &&
        Math.abs(p.low - c.low) <= Math.max(range(p), range(c)) * 0.05 &&
        c.close > (p.open + p.close) / 2
      )
        add('tweezer', 'Tweezer Bottom', 'Tweezer Top', 2)
      if (marubozu(p) && marubozu(c) && c.low > p.high)
        add('kicker', 'Bullish Kicker', 'Bearish Kicker', 2)
    }
    if (a && p && trend(3) < 0) {
      if (soldiers(a, p, c)) add('soldiers-crows', 'Three White Soldiers', 'Three Black Crows', 3)
      if (down(a) && long(a) && up(p) && up(c) && long(c)) {
        if (p.open > a.close && p.close < a.open && body(p) <= body(a) * 0.6 && c.close > a.open)
          add('three-inside', 'Three Inside Up', 'Three Inside Down', 3)
        if (p.open <= a.close && p.close >= a.open && body(p) > body(a) && c.close > p.close)
          add('three-outside', 'Three Outside Up', 'Three Outside Down', 3)
      }
      if (down(a) && long(a) && doji(p) && up(c) && long(c) && c.close > (a.open + a.close) / 2) {
        if (p.high < a.low && c.low > p.high)
          add('abandoned-baby', 'Bullish Abandoned Baby', 'Bearish Abandoned Baby', 3)
        if (Math.max(p.open, p.close) < a.close && c.open > Math.max(p.open, p.close))
          add('doji-star', 'Morning Doji Star', 'Evening Doji Star', 3)
      }
    }
    if (
      z &&
      a &&
      p &&
      trend(4) > 0 &&
      soldiers(z, a, p) &&
      down(c) &&
      long(c) &&
      c.open > p.close &&
      c.close < z.open
    )
      add('three-line-strike', 'Bullish Three-Line Strike', 'Bearish Three-Line Strike', 4)
  }
  return matches
}
