import type { BookBar, BookFormation, BookPivot, BookSettings, BookSide } from './types'
import { body, bodyTop, bodyBottom, upperWick, lowerWick, direction, mean, validBar } from './math'
/** Geometry only. Prior trend, optional filters and later price confirmation are applied by the engine. */
export function detectCandles(
  bars: BookBar[],
  i: number,
  s: BookSettings,
  tick: number,
  atr: number,
  pivots: BookPivot[]
): BookFormation[] {
  const out: BookFormation[] = []
  const b = bars[i]
  if (!b || !validBar(b) || !Number.isFinite(atr) || atr <= 0) return out
  const at = (n: number) => bars[i - n]
  const available = (n: number) => i >= n - 1 && bars.slice(i - n + 1, i + 1).every(validBar)
  const long = (x: BookBar, index: number) => {
    const prior = bars.slice(Math.max(0, index - s.averageBodyPeriod), index)
    return (
      body(x) >= (x.high - x.low) * s.longBody &&
      prior.length === s.averageBodyPeriod &&
      prior.every(validBar) &&
      body(x) >= mean(prior.map(body))
    )
  }
  const small = (x: BookBar) => body(x) <= (x.high - x.low) * s.smallBody
  const add = (
    id: string,
    name: string,
    side: BookSide | 'neutral',
    n: number,
    photo: number,
    stop: number,
    mode: BookFormation['mode'] = 'reversal',
    extra: Partial<BookFormation> = {}
  ) => {
    if (s.disabledPatterns.includes(id)) return
    const rows = bars.slice(i - n + 1, i + 1)
    out.push({
      patternId: id,
      name,
      side,
      sourcePhotos: [photo],
      kind: 'candle',
      mode,
      startIndex: i - n + 1,
      endIndex: i,
      recognitionIndex: i,
      trigger: side === 'short' ? b.low : b.high,
      stopAnchor: stop,
      stopMethod: 'Source formation extreme',
      targetMethod: 'r-multiple',
      scale: atr,
      contacts: n,
      rank: side === 'neutral' ? 4 : 3,
      points: rows.flatMap((x, j) => [
        { time: x.time, index: i - n + 1 + j, price: x.high, role: 'high' },
        { time: x.time, index: i - n + 1 + j, price: x.low, role: 'low' },
      ]),
      segments: [],
      notes: [],
      confirmationRule: 'later-close',
      ...extra,
    })
  }
  const range = b.high - b.low,
    bull = b.close > b.open,
    bear = b.close < b.open
  const low = lowerWick(b),
    up = upperWick(b)
  if (small(b) && low >= s.dominantWickRatio * body(b) && up <= s.negligibleWick * range) {
    const swing = pivots.filter((p) => p.side === 'low' && p.recognitionIndex < i).at(-1)
    add('hammer', 'Hammer', 'long', 1, 44, Math.min(b.low, swing?.price ?? b.low), 'reversal', {
      stopMethod: 'Source swing low (or lower pattern low)',
    })
    add('hanging-man', 'Hanging man', 'short', 1, 42, b.high)
  }
  if (small(b) && up >= s.dominantWickRatio * body(b) && low <= s.negligibleWick * range) {
    add('inverted-hammer', 'Inverted hammer', 'long', 1, 43, b.low, 'reversal', {
      trigger: bodyTop(b),
      confirmationRule: 'inverted-body',
      notes: [
        'Source next opening above real body; confirmed green close above body is a local closed-candle policy.',
      ],
    })
    add('shooting-star', 'Shooting star', 'short', 1, 41, b.high)
  }
  if (
    body(b) >= s.marubozuBody * range &&
    up <= s.marubozuWick * range &&
    low <= s.marubozuWick * range &&
    direction(b) !== 'neutral'
  )
    add(
      bull ? 'bull-marubozu' : 'bear-marubozu',
      bull ? 'Bullish marubozu' : 'Bearish marubozu',
      bull ? 'long' : 'short',
      1,
      46,
      bull ? b.low : b.high,
      'neutral',
      {
        rank: 4,
        notes: [
          'Local later-close trigger; the source describes conviction, not a standalone plan.',
        ],
      }
    )
  const doji = (x: BookBar) => body(x) <= s.dojiBody * (x.high - x.low)
  if (doji(b)) {
    add('doji', 'Doji', 'neutral', 1, 45, b.low, 'neutral')
    if (up >= s.spinningWick * range && low >= s.spinningWick * range)
      add('long-legged-doji', 'Long-legged doji', 'neutral', 1, 45, b.low, 'neutral')
    if (up <= s.negligibleWick * range)
      add('dragonfly-doji', 'Dragonfly doji', 'neutral', 1, 45, b.low, 'neutral')
    if (low <= s.negligibleWick * range)
      add('gravestone-doji', 'Gravestone doji', 'neutral', 1, 45, b.low, 'neutral')
    if (available(2) && doji(at(1)!))
      add('double-doji', 'Double doji', 'neutral', 2, 45, Math.min(b.low, at(1)!.low), 'neutral', {
        trigger: Math.max(b.high, at(1)!.high),
      })
  }
  if (small(b) && up >= s.spinningWick * range && low >= s.spinningWick * range)
    add('spinning-top', 'Spinning top', 'neutral', 1, 46, b.low, 'neutral')
  if (available(2)) {
    const a = at(1)!,
      abull = a.close > a.open,
      abear = a.close < a.open,
      tol = Math.max(s.minToleranceTicks * tick, s.equalCandleATR * atr)
    if (abear && bull && Math.abs(a.low - b.low) <= tol)
      add('tweezer-bottom', 'Tweezer bottom', 'long', 2, 29, Math.min(a.low, b.low))
    if (abull && bear && Math.abs(a.high - b.high) <= tol)
      add('tweezer-top', 'Tweezer top', 'short', 2, 30, Math.max(a.high, b.high))
    const contained =
      bodyTop(b) <= bodyTop(a) && bodyBottom(b) >= bodyBottom(a) && body(b) < body(a)
    if (long(a, i - 1) && contained) {
      if (abear && bull)
        add('bull-harami', 'Bullish harami', 'long', 2, 34, b.low, 'reversal', {
          stopMethod: 'Source second candle low',
        })
      if (abull && bear)
        add('bear-harami', 'Bearish harami', 'short', 2, 33, a.high, 'reversal', {
          stopMethod: 'Source first candle high',
        })
    }
    const midpoint = (a.open + a.close) / 2
    if (
      abear &&
      bull &&
      b.close > midpoint &&
      b.close < a.open &&
      (s.gapPolicy === 'continuous' || b.open < a.close)
    )
      add('piercing-line', 'Piercing line', 'long', 2, 36, Math.min(a.low, b.low))
    if (
      abull &&
      bear &&
      b.close < midpoint &&
      b.close > a.open &&
      (s.gapPolicy === 'continuous' || b.open > a.close)
    )
      add('dark-cloud-cover', 'Dark cloud cover', 'short', 2, 35, Math.max(a.high, b.high))
    const engulf =
      bodyTop(b) >= bodyTop(a) &&
      bodyBottom(b) <= bodyBottom(a) &&
      (bodyTop(b) > bodyTop(a) || bodyBottom(b) < bodyBottom(a)) &&
      (!s.strictRangeEngulfing || (b.high >= a.high && b.low <= a.low))
    if (engulf) {
      if (abear && bull)
        add('bull-engulfing', 'Bullish engulfing', 'long', 2, 39, b.low, 'reversal', {
          stopMethod: 'Source second candle low; not the first candle low',
          notes: [
            'Explicit mode also requires confirming open above second close (local interpretation).',
          ],
        })
      if (abull && bear)
        add('bear-engulfing', 'Bearish engulfing', 'short', 2, 40, b.high, 'reversal', {
          stopMethod: 'Source second candle high; not the first candle high',
          notes: [
            'Explicit mode also requires confirming open below second close (local interpretation).',
          ],
        })
    }
  }
  if (available(3)) {
    const a = at(2)!,
      m = at(1)!,
      mid = (a.open + a.close) / 2
    if (long(a, i - 2) && small(m) && body(m) < body(a)) {
      if (
        a.close < a.open &&
        bull &&
        b.close > mid &&
        (s.gapPolicy === 'continuous' || (bodyTop(m) < a.close && b.open > bodyTop(m)))
      )
        add('morning-star', 'Morning star', 'long', 3, 38, Math.min(a.low, m.low, b.low))
      if (
        a.close > a.open &&
        bear &&
        b.close < mid &&
        (s.gapPolicy === 'continuous' || (bodyBottom(m) > a.close && b.open < bodyBottom(m)))
      )
        add('evening-star', 'Evening star', 'short', 3, 37, Math.max(a.high, m.high, b.high))
    }
    const rows = [a, m, b]
    const opens = rows
      .slice(1)
      .every((x, j) => x.open > bodyBottom(rows[j]!) && x.open < bodyTop(rows[j]!))
    if (opens && rows.every((x, j) => long(x, i - 2 + j))) {
      if (
        rows.every(
          (x) => x.close > x.open && upperWick(x) <= s.negligibleWick * (x.high - x.low)
        ) &&
        a.close < m.close &&
        m.close < b.close
      )
        add('three-white-soldiers', 'Three white soldiers', 'long', 3, 32, a.low)
      if (
        rows.every(
          (x) => x.close < x.open && lowerWick(x) <= s.negligibleWick * (x.high - x.low)
        ) &&
        a.close > m.close &&
        m.close > b.close
      )
        add('three-black-crows', 'Three black crows', 'short', 3, 31, a.high)
    }
  }
  if (available(5)) {
    const a = at(4)!,
      corrections = [at(3)!, at(2)!, at(1)!]
    const contained = corrections.every(
      (x) => x.high <= a.high && x.low >= a.low && body(x) < body(a)
    )
    if (long(a, i - 4) && contained) {
      if (
        a.close > a.open &&
        bull &&
        corrections.every((x) => x.close < x.open) &&
        b.close > Math.max(a.close, ...corrections.map((x) => x.high))
      )
        add(
          'rising-three-methods',
          'Rising three methods',
          'long',
          5,
          28,
          Math.min(...corrections.map((x) => x.low)),
          'continuation',
          {
            stopMethod: 'Source corrective-candle lows; conservative conflict resolution',
            stopCheckFrom: i,
            notes: [
              'Corrective stop must remain below the confirming entry; earlier impulse wick is not retrospective invalidation.',
            ],
          }
        )
      if (
        a.close < a.open &&
        bear &&
        corrections.every((x) => x.close > x.open) &&
        b.close < Math.min(a.close, ...corrections.map((x) => x.low))
      )
        add(
          'falling-three-methods',
          'Falling three methods',
          'short',
          5,
          28,
          Math.max(...corrections.map((x) => x.high)),
          'continuation',
          {
            stopMethod: 'Source corrective-candle highs; conservative conflict resolution',
            stopCheckFrom: i,
          }
        )
    }
  }
  return out
}
