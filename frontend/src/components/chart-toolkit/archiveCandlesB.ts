import type { Bar } from './model'
export interface ArchiveCandleMatchB {
  side: 'CALL' | 'PUT' | 'NEUTRAL'
  name: string
  pattern: string
  extreme: number
}
const body = (b: Bar) => Math.abs(b.close - b.open)
const range = (b: Bar) => b.high - b.low
const up = (b: Bar) => b.close > b.open
const down = (b: Bar) => b.close < b.open
const upper = (b: Bar) => b.high - Math.max(b.open, b.close)
const lower = (b: Bar) => Math.min(b.open, b.close) - b.low
const long = (b: Bar) => body(b) >= range(b) * 0.55
const doji = (b: Bar) => body(b) <= range(b) * 0.1
const flip = (b: Bar): Bar => ({ ...b, open: -b.open, close: -b.close, high: -b.low, low: -b.high })
const near = (a: number, b: number, scale: number) => Math.abs(a - b) <= scale * 0.05
/** Completed chronological bars only. Shape descriptions use TA-Lib's pattern catalog:
 * https://ta-lib.org/functions/ (CDLRISEFALL3METHODS, MATHOLD, BREAKAWAY,
 * ADVANCEBLOCK, STALLEDPATTERN, CONCEALBABYSWALL, XSIDEGAP3METHODS,
 * TASUKIGAP, UPSIDEGAP2CROWS, 2CROWS, GAPSIDESIDEWHITE, 3STARSINSOUTH,
 * UNIQUE3RIVER, STICKSANDWICH, IDENTICAL3CROWS, TRISTAR, LADDERBOTTOM).
 * Additional names: Bulkowski, Investment Candles, Stocks & Commodities 29:5,
 * https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/InvestmentCandles2.pdf
 * Last engulfing and above/below stomach follow their trend/location convention.
 * Stomach: long first body, opposite second candle opening at/above its midpoint
 * (reflected for Below); no extra close threshold or upper bound on its open.
 * New price-line naming: Bulkowski, https://www.thepatternsite.com/8NewPriceLines.html
 * and https://onlinelibrary.wiley.com/doi/10.1002/9781119202288.ch4;
 * this local variant requires a contiguous same-color run and opposite confirmation.
 * North, top, bearish Mat Hold etc. are explicitly price-reflected local variants.
 * These are deterministic LOCAL definitions, not TA-Lib numerical parity or odds.
 * Trend is four closes before the entire pattern, moving > half mean range.
 * Long >=55% range; short <=60% first body; doji <=10% range; matching <=5%
 * max range. Named gaps are strict FULL-range gaps (conservative vs body gaps).
 * Three Methods: three descending opposite small candles within first range,
 * final long candle above first close. Mat Hold: initial gap, pullback retains
 * upper half of first body, final closes beyond all prior highs. Breakaway:
 * initial gap, continuing lows, final closes inside that initial price gap.
 * Exhaustion lines: 8/10/12/13 consecutive same-color candles with new lows/highs,
 * followed by opposite candle closing beyond preceding body's open.
 * Gapping Doji: https://thepatternsite.com/GappingUpDoji.html (theoretical
 * continuation); full-range gap from the preceding reference candle.
 * Two Black Gapping: Investment Candles above; first candle gaps below its
 * preceding reference bar, second black candle has a lower high (mirror up).
 * Collapsing Doji Star: https://www.thepatternsite.com/CollapseDojiStar.html
 * white candle in uptrend, doji fully below it, final black fully below doji.
 * Two-line Shooting Star: https://www.candlescanner.com/candlestick-patterns/two-candle-shooting-star/
 * long first white; second body >0 and <=30% range, upper shadow >=2.5x body,
 * lower shadow <=body, opening >= first close. It is a shape observation;
 * no later support-break confirmation is claimed.
 * Three Stars: second open above first close and nonzero second lower shadow.
 * Input prices must be positive and timestamps finite, strictly increasing.
 * All results refer to the final supplied candle; no future confirmation is read.
 */
export function recognizeArchiveCandlesB(history: Bar[]): ArchiveCandleMatchB[] {
  if (
    !history.length ||
    history.some(
      (b, i) =>
        !Number.isFinite(b.time) ||
        (i > 0 && b.time <= history[i - 1].time) ||
        b.low <= 0 ||
        ![b.open, b.close, b.high, b.low].every(Number.isFinite) ||
        b.high <= b.low ||
        b.high < Math.max(b.open, b.close) ||
        b.low > Math.min(b.open, b.close)
    )
  )
    return []
  const out: ArchiveCandleMatchB[] = []
  for (const bullish of [true, false]) {
    const bars = bullish ? history : history.map(flip)
    const c = bars.at(-1)!,
      p = bars.at(-2),
      a = bars.at(-3),
      z = bars.at(-4),
      w = bars.at(-5)
    const trend = (n: number) => {
      const pre = bars.slice(0, -n).slice(-4)
      if (pre.length < 4) return 0
      const d = pre[3].close - pre[0].close
      return Math.abs(d) > pre.reduce((s, b) => s + range(b), 0) / 8 ? Math.sign(d) : 0
    }
    const add = (id: string, bullName: string, bearName: string, n: number, reverse = false) => {
      const isBull = reverse ? !bullish : bullish
      const shape = history.slice(-n)
      out.push({
        side: isBull ? 'CALL' : 'PUT',
        name: bullish ? bullName : bearName,
        pattern: `archive-${id}`,
        extreme: isBull
          ? Math.min(...shape.map((b) => b.low))
          : Math.max(...shape.map((b) => b.high)),
      })
    }
    if (w && z && a && p && trend(5) > 0 && up(w) && long(w) && up(c) && long(c)) {
      const middle = [z, a, p]
      if (
        middle.every(
          (b) => down(b) && body(b) <= body(w) * 0.6 && b.high < w.high && b.low > w.low
        ) &&
        z.close > a.close &&
        a.close > p.close &&
        c.open > p.close &&
        c.close > w.close
      )
        add('three-methods', 'Rising Three Methods', 'Falling Three Methods', 5)
      if (
        z.low > w.high &&
        middle.every((b) => down(b) && body(b) <= body(w) * 0.6) &&
        z.close > a.close &&
        a.close > p.close &&
        Math.min(a.low, p.low) > (w.open + w.close) / 2 &&
        c.open > p.close &&
        c.close > Math.max(w.high, z.high, a.high, p.high)
      )
        add('mat-hold', 'Bullish Mat Hold', 'Bearish Mat Hold', 5)
    }
    if (w && z && a && p && trend(5) < 0) {
      if (
        down(w) &&
        long(w) &&
        down(z) &&
        z.high < w.low &&
        down(p) &&
        a.low < z.low &&
        p.low < a.low &&
        up(c) &&
        long(c) &&
        c.close > z.high &&
        c.close < w.low
      )
        add('breakaway', 'Bullish Breakaway', 'Bearish Breakaway', 5)
      if (
        [w, z, a].every(down) &&
        w.close > z.close &&
        z.close > a.close &&
        w.open > z.open &&
        z.open > a.open &&
        down(p) &&
        p.close < a.close &&
        upper(p) > body(p) &&
        up(c) &&
        long(c) &&
        c.open > p.high &&
        c.close > p.high
      )
        add('ladder', 'Ladder Bottom', 'Ladder Top', 5)
    }
    if (
      z &&
      a &&
      p &&
      trend(4) < 0 &&
      [z, a, p, c].every(down) &&
      [z, a].every((b) => body(b) >= range(b) * 0.9) &&
      a.close < z.close &&
      p.high > a.close &&
      p.open < a.low &&
      upper(p) > body(p) &&
      c.open > p.high &&
      c.close < p.low
    )
      add(
        'concealing-baby-swallow',
        'Concealing Baby Swallow',
        'Concealing Baby Swallow (Bearish Mirror)',
        4
      )
    if (
      a &&
      p &&
      trend(3) > 0 &&
      up(a) &&
      up(p) &&
      p.low > a.high &&
      down(c) &&
      c.open < p.close &&
      c.open > p.open
    ) {
      if (c.close < a.close && c.close > a.open)
        add('gap-three-methods', 'Upside Gap Three Methods', 'Downside Gap Three Methods', 3)
      if (c.close > a.high && c.close < p.low)
        add('tasuki-gap', 'Upside Tasuki Gap', 'Downside Tasuki Gap', 3)
    }
    if (a && p && trend(3) < 0) {
      if (
        [a, p, c].every(down) &&
        long(a) &&
        lower(a) > body(a) * 0.5 &&
        body(p) < body(a) &&
        p.open < a.open &&
        p.open > a.close &&
        lower(p) > 0 &&
        p.close < a.close &&
        p.low > a.low &&
        c.high < p.high &&
        c.low > p.low &&
        body(c) < body(p) &&
        upper(c) <= range(c) * 0.1 &&
        lower(c) <= range(c) * 0.1
      )
        add('three-stars', 'Three Stars in the South', 'Three Stars in the North', 3)
      if (
        down(a) &&
        long(a) &&
        down(p) &&
        p.open < a.open &&
        p.close > a.close &&
        p.low < a.low &&
        lower(p) > body(p) &&
        up(c) &&
        body(c) < body(a) * 0.6 &&
        c.open > p.low &&
        c.close < p.close
      )
        add('unique-three-river', 'Unique Three River Bottom', 'Unique Three River Top', 3)
      if (
        down(a) &&
        up(p) &&
        down(c) &&
        p.low > a.close &&
        near(a.close, c.close, Math.max(range(a), range(c)))
      )
        add('stick-sandwich', 'Bullish Stick Sandwich', 'Bearish Stick Sandwich', 3)
      if (
        [a, p, c].every((b) => up(b) && long(b) && upper(b) <= range(b) * 0.2) &&
        p.close > a.close &&
        c.close > p.close &&
        near(p.open, a.close, Math.max(range(a), range(p))) &&
        near(c.open, p.close, Math.max(range(p), range(c)))
      )
        add('identical-three', 'Identical Three Soldiers', 'Identical Three Crows', 3)
      if ([a, p, c].every(doji) && p.high < a.low && c.low > p.high)
        add('tristar', 'Bullish TriStar', 'Bearish TriStar', 3)
    }
    if (
      a &&
      p &&
      trend(2) > 0 &&
      up(p) &&
      long(p) &&
      up(c) &&
      long(c) &&
      p.low > a.high &&
      c.high > p.high
    )
      add('two-gapping-lines', 'Two White Gapping Candles', 'Two Black Gapping Candles', 2)
    if (p && trend(2) > 0 && doji(c) && c.low > p.high)
      add('gapping-doji', 'Gapping Up Doji', 'Gapping Down Doji', 2)
    if (
      bullish &&
      p &&
      trend(2) > 0 &&
      up(p) &&
      long(p) &&
      body(c) > 0 &&
      body(c) <= range(c) * 0.3 &&
      upper(c) >= body(c) * 2.5 &&
      lower(c) <= body(c) &&
      c.open >= p.close
    )
      add('shooting-star-two-line', 'Two-Candle Shooting Star', '', 2, true)
    if (
      bullish &&
      a &&
      p &&
      trend(3) > 0 &&
      up(a) &&
      long(a) &&
      doji(p) &&
      p.high < a.low &&
      down(c) &&
      long(c) &&
      c.high < p.low
    )
      add('collapsing-doji-star', 'Collapsing Doji Star', '', 3, true)
    if (p && trend(2) < 0) {
      if (up(p) && down(c) && c.open > p.close && c.close < p.open)
        add('last-engulfing', 'Last Engulfing Bottom', 'Last Engulfing Top', 2)
      if (down(p) && long(p) && up(c) && c.open >= (p.open + p.close) / 2)
        add('stomach', 'Above the Stomach', 'Below the Stomach', 2)
    }
    for (const n of [8, 10, 12, 13]) {
      const run = bars.slice(-(n + 1), -1)
      if (
        trend(n + 1) < 0 &&
        run.length === n &&
        run.every(
          (b, i) => down(b) && (i === 0 || (b.low < run[i - 1].low && b.close < run[i - 1].close))
        ) &&
        up(c) &&
        c.close > run[n - 1].open
      )
        add(`new-price-${n}`, `${n} New Price Lines Bottom`, `${n} New Price Lines Top`, n + 1)
    }
    // These traditional names have bearish-only geometry; avoid inventing labels.
    if (bullish && a && p && trend(3) > 0 && up(a) && long(a)) {
      if (
        up(p) &&
        up(c) &&
        p.open > a.open &&
        p.open < a.close &&
        c.open > p.open &&
        c.open <= p.close &&
        p.close > a.close &&
        c.close > p.close
      ) {
        if (body(p) < body(a) && body(c) < body(p) && upper(p) > upper(a) && upper(c) > upper(p))
          add('advance-block', 'Advance Block', 'Advance Block', 3, true)
        if (long(p) && body(c) < body(p) * 0.5 && c.open >= p.close - body(p) * 0.1)
          add(
            'stalled',
            'Deliberation / Stalled Pattern',
            'Deliberation / Stalled Pattern',
            3,
            true
          )
      }
      if (down(p) && p.low > a.high && down(c)) {
        if (c.open > p.open && c.close < p.close && c.close > a.high)
          add('upside-gap-two-crows', 'Upside Gap Two Crows', 'Upside Gap Two Crows', 3, true)
        if (c.open < p.open && c.open > p.close && c.close < a.close && c.close > a.open)
          add('two-crows', 'Two Crows', 'Two Crows', 3, true)
      }
    }
    // White lines remain white in BOTH continuations; do not price-reflect colors.
    if (
      bullish &&
      a &&
      p &&
      up(p) &&
      up(c) &&
      near(c.open, p.open, Math.max(range(p), range(c))) &&
      near(body(c), body(p), Math.max(range(p), range(c)))
    ) {
      if (trend(3) > 0 && up(a) && Math.min(p.low, c.low) > a.high)
        add('side-by-side-white-up', 'Upside Gap Side-by-side White Lines', '', 3)
      if (trend(3) < 0 && down(a) && Math.max(p.high, c.high) < a.low)
        add('side-by-side-white-down', 'Downside Gap Side-by-side White Lines', '', 3, true)
    }
  }
  return out
}
