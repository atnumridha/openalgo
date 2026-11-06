// Source observations are independent of broker execution. Numeric choices are disclosed in the guide.
export const VIDEO_STRATEGIES = [
  [
    'fvg',
    'Fair Value Gap',
    'Three completed candles leave a wick gap. Wait for a confirmed move, then the midpoint pullback.',
    '00:18–00:49',
  ],
  [
    'ob',
    'Order Block',
    'Last opposite candle before a confirmed displacement. Watch its body midpoint; stop beyond its wick.',
    '00:54–01:23',
  ],
  [
    'sweep',
    'Liquidity Sweep',
    'An equal-high/low sweep is a warning. Wait for the opposing structural close, then a gap/block retest.',
    '01:27–01:46',
  ],
  [
    'bos',
    'Break of Structure',
    'A closing break in the established structure direction. A wick alone does not count. Wait for a pullback.',
    '01:51–02:09',
  ],
  [
    'choch',
    'Change of Character',
    'A closing break against the established structure. Wait for a new gap/block and a later retest.',
    '02:18–02:33',
  ],
  [
    'ifvg',
    'Inverse Fair Value Gap',
    'A confirmed gap closes through its far edge. Watch a retest from the flipped side.',
    '02:39–03:00',
  ],
  [
    'breaker',
    'Breaker Block',
    'An order block fails after a sweep and closing structure shift. Watch its retest from the new side.',
    '03:06–03:18',
  ],
  [
    'ote',
    'Optimal Trade Entry',
    'Freeze the reversal leg; watch its 62–79% retracement, using 70.5% as the reference.',
    '03:51–04:09',
  ],
  [
    'krm',
    'KRM · Keepssy Reversal Model',
    '',
    '04:18–05:00',
    'The full public video previews KRM, but the precise trigger is not published. The creator links a course waitlist; no KRM signal is guessed.',
  ],
  [
    'silver-bullet',
    'Silver Bullet',
    'Local variant: NY 10–11 on 1m/5m; sweep, structural close, then a new FVG and a later midpoint rejection.',
    'Full video 05:22–05:44; local NY window',
  ],
  [
    'supply-demand',
    'Supply / Demand',
    'Local variant: 1–3 small base candles before structural displacement; first later rejection of the wick-to-body zone.',
    'Full video 05:44–06:07; local base rules',
  ],
  [
    'support-resistance',
    'Support / Resistance',
    'Local variant: two confirmed equal pivots; closing rejection of the level, or a closing break and later flip retest.',
    'Full video 06:07–06:24; local pivot rules',
  ],
  [
    'breakout',
    'Breakout',
    'Local variant: 12-bar range with two confirmed touches per edge; closing break, later retest and directional rejection.',
    'Full video 06:24–06:46; local range rules',
  ],
  [
    'crt',
    'Candle Range Theory',
    'Local variant: three completed candles; one-edge sweep back inside candle 1, then a closing break of candle 2. Target the untouched opposite edge.',
    'Full video 06:46–07:06; local confirmation rules',
  ],
  [
    'po3',
    'Power of 3',
    'Local variant: six-bar range; one-edge sweep, opposite displacement within three bars, then a later retest. Target one range height.',
    'Full video 07:06–07:31; local rolling range',
  ],
].map(([id, name, rule, source, missing = '']) => ({
  id,
  name,
  rule,
  source,
  missing,
  supported: !!rule,
  variant: rule.startsWith('Local variant:'),
}))
const STATES = [
  'watching',
  'waiting',
  'entry',
  'invalidated',
  'target',
  'expired',
  'ambiguous',
  'unpriced',
]
const ids = VIDEO_STRATEGIES.map((s) => s.id)
const finite = Number.isFinite
const terminal = (e) => ['invalidated', 'target', 'expired', 'ambiguous'].includes(e.status)
const valid = (b) =>
  [b.time, b.open, b.high, b.low, b.close].every(finite) &&
  b.time >= 0 &&
  Math.min(b.open, b.close, b.low) > 0 &&
  b.high >= Math.max(b.open, b.close, b.low) &&
  b.low <= Math.min(b.open, b.close)
// Directed rounding keeps exact Long/Short mirror symmetry, including half-tick ties.
const round = (p, t, up) =>
  Number(((up ? Math.ceil(p / t - 1e-9) : Math.floor(p / t + 1e-9)) * t).toPrecision(14))
const closeAt = (b, o) => {
  const s = o.session ?? (o.indian ? { start: 555, end: 930, offset: 19800 } : null)
  const nominal = b.time + o.seconds
  if (!s || o.seconds >= 86400) return nominal
  const day = Math.floor((b.time + s.offset) / 86400) * 86400 - s.offset
  return Math.min(nominal, day + s.end * 60)
}
const stamp = (b, o) => Math.floor((b.time + (o.session?.offset ?? (o.indian ? 19800 : 0))) / 86400)
const newYorkClock = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})
export function videoSilverWindow(opened, closed, seconds) {
  if (![60, 300].includes(seconds)) return false
  const clock = (time) =>
    Object.fromEntries(
      newYorkClock.formatToParts(new Date(time * 1000)).map((x) => [x.type, x.value])
    )
  const a = clock(opened),
    b = clock(closed)
  const minute = (x) => Number(x.hour) * 60 + Number(x.minute)
  return (
    !['Sat', 'Sun'].includes(a.weekday) &&
    a.weekday === b.weekday &&
    minute(a) >= 600 &&
    minute(b) < 660
  )
}
const reason = (e) =>
  ({
    watching:
      e.kind === 2
        ? 'Sweep confirmed; wait for an opposing structural close and a new gap/block.'
        : e.kind === 4
          ? 'Structure changed; wait for a new gap/block and a later retest.'
          : e.kind === 14
            ? 'Range swept; wait for opposite displacement within three candles, then a later retest.'
            : 'Geometry observed; confirmed displacement and structure are still missing.',
    waiting:
      'Confirmed observation; wait for the watched price and a later directional closing rejection.',
    entry:
      e.kind === 11 || e.kind === 13
        ? 'Completed rejection/confirmation observed. Review this close reference; no fill is assumed.'
        : 'Later completed candle reached the watched price and rejected in this direction. Review the close reference; no fill is assumed.',
    invalidated: 'Reference invalidated; wait for a new setup.',
    target: 'The reference target was already touched; this is history, not a fresh entry.',
    expired: 'Setup expired or source history was interrupted; wait for a new setup.',
    ambiguous:
      'Stop and target, or entry and an exit, overlap in one OHLC candle. Their order is unknown; wait.',
    unpriced: 'Target unavailable — wait for a new setup. No target has been invented.',
  })[e.status]

export function videoStrategyGuide(input, options) {
  const events = [],
    history = []
  let segment = [],
    pivots = [],
    zones = [],
    bias = 0,
    atr = null,
    seed = 0,
    count = 0,
    last = null,
    closedTime = null,
    lastBarTime = null
  let available =
    options.standard !== false &&
    finite(options.seconds) &&
    options.seconds > 0 &&
    options.seconds < 86400 &&
    finite(options.asOf) &&
    finite(options.tickSize) &&
    options.tickSize > 0
  let unavailable =
    options.seconds >= 86400
      ? 'Video strategies currently require an intraday chart. Daily and higher session continuity is not implemented.'
      : options.standard === false
        ? 'Use standard time-based candles.'
        : 'Verified candles and a valid tick size are required.'
  const t = options.tickSize
  const session = !!(options.session || options.indian)
  const remember = (e) =>
    history.push({ id: e.id, strategy: e.strategy, at: closedTime, status: e.status })
  const change = (e, status) => {
    if (e.status !== status) {
      e.status = status
      e.reason = reason(e)
      remember(e)
    }
  }
  const reset = () => {
    for (const e of events) if (!terminal(e)) change(e, 'expired')
    segment = []
    pivots = []
    zones = []
    bias = 0
    atr = null
    seed = 0
    count = 0
    last = null
  }
  const latest = (kind) => events.findLast((e) => e.kind === kind)
  const target = (side, watch, c) => {
    const levels = pivots.filter(
      (p) =>
        p.side === side &&
        (side > 0 ? p.price > Math.max(watch, c.close) : p.price < Math.min(watch, c.close)) &&
        segment.every((b) => b.i <= p.knownIndex || (side > 0 ? b.high < p.price : b.low > p.price))
    )
    return levels.length
      ? side > 0
        ? Math.min(...levels.map((p) => p.price))
        : Math.max(...levels.map((p) => p.price))
      : null
  }
  const create = (kind, side, b, fields = {}, qualified = true) => {
    const e = {
      id: `${kind}:${closedTime}:${side}`,
      strategy: ids[kind],
      kind,
      side,
      status: 'watching',
      createdAt: closedTime,
      barTime: b.time,
      createdIndex: b.i,
      confirmedAt: qualified ? closedTime : null,
      confirmedBar: qualified ? b.time : null,
      entryAt: null,
      entryBar: null,
      watch: null,
      entry: null,
      stop: null,
      target: null,
      low: b.low,
      high: b.high,
      trigger: null,
      evidence: [b.time],
      reason: '',
      priced: false,
      ...fields,
    }
    if (e.watch != null) e.watch = round(e.watch, t, side > 0)
    if (e.stop != null) e.stop = round(e.stop, t, side < 0)
    if (e.target != null) e.target = round(e.target, t, side < 0)
    e.priced =
      [e.watch, e.stop, e.target].every((v) => v != null && finite(v) && v > 0) &&
      (side > 0 ? e.stop < e.watch && e.watch < e.target : e.target < e.watch && e.watch < e.stop)
    e.status = qualified ? (e.priced ? 'waiting' : 'unpriced') : 'watching'
    e.reason = reason(e)
    events.push(e)
    remember(e)
    if (events.length > 160) events.shift()
    return e
  }
  if (available)
    for (let index = 0; index < input.length; index++) {
      const raw = input[index]
      if (!finite(raw.time) || raw.time > options.asOf) continue
      if (closeAt(raw, options) > options.asOf) continue
      closedTime = closeAt(raw, options)
      lastBarTime = raw.time
      if (!valid(raw) || (last && raw.time <= last.time)) {
        reset()
        available = false
        unavailable = 'Invalid candle prices or ordering; wait for reconciled history.'
        continue
      }
      available = true
      const b = { ...raw, i: index, atrBefore: atr }
      if (
        last &&
        (b.time - last.time !== options.seconds ||
          (session && stamp(b, options) !== stamp(last, options)))
      )
        reset()
      const prior = last
      segment.push(b)
      if (segment.length > 300) segment.shift()
      const n = segment.length
      if (n >= 5) {
        const p = segment[n - 3],
          ns = [segment[n - 5], segment[n - 4], segment[n - 2], b]
        const hi = ns.every((q) => p.high > q.high),
          lo = ns.every((q) => p.low < q.low)
        if (hi !== lo) {
          const point = {
            side: hi ? 1 : -1,
            price: hi ? p.high : p.low,
            index: p.i,
            time: p.time,
            knownIndex: b.i,
            used: false,
          }
          const tail = pivots.at(-1)
          if (tail?.side === point.side) {
            if (point.side > 0 ? point.price > tail.price : point.price < tail.price)
              pivots[pivots.length - 1] = point
          } else pivots.push(point)
        }
      }
      pivots = pivots.filter((p) => b.i - p.index <= 300)
      const hs = pivots.filter((p) => p.side === 1),
        ls = pivots.filter((p) => p.side === -1)
      if (!bias && hs.length >= 2 && ls.length >= 2) {
        if (hs.at(-1).price > hs.at(-2).price && ls.at(-1).price > ls.at(-2).price) bias = 1
        else if (hs.at(-1).price < hs.at(-2).price && ls.at(-1).price < ls.at(-2).price) bias = -1
      }
      const high = hs.at(-1),
        low = ls.at(-1)
      let breakSide = 0,
        breakLevel = null,
        origin = null,
        breakKind = -1
      if (bias && high && !high.used && b.close > high.price) {
        breakSide = 1
        breakLevel = high
        origin = low
        high.used = true
      } else if (bias && low && !low.used && b.close < low.price) {
        breakSide = -1
        breakLevel = low
        origin = high
        low.used = true
      }
      if (breakSide) {
        breakKind = breakSide === bias ? 3 : 4
        bias = breakSide
      }
      const displacement = (bar, side) =>
        bar.atrBefore != null &&
        Math.abs(bar.close - bar.open) >= bar.atrBefore &&
        (side > 0
          ? bar.close > bar.open && bar.close >= bar.low + 0.75 * (bar.high - bar.low)
          : bar.close < bar.open && bar.close <= bar.low + 0.25 * (bar.high - bar.low))
      // Resolve older plans before this bar creates any new observation.
      for (const e of events) {
        if (terminal(e) || e.createdIndex >= b.i) continue
        if (e.status !== 'entry' && b.i - e.createdIndex > 20) {
          change(e, 'expired')
          continue
        }
        if (
          e.status !== 'entry' &&
          ((e.kind === 9 && !videoSilverWindow(b.time, closedTime, options.seconds)) ||
            (e.kind === 14 && e.status === 'watching' && b.i - e.createdIndex > 3))
        ) {
          change(e, 'expired')
          continue
        }
        if (
          [11, 12].includes(e.kind) &&
          e.trigger != null &&
          (e.side > 0 ? b.close < e.trigger : b.close > e.trigger)
        ) {
          change(e, 'invalidated')
          continue
        }
        const stopped = e.stop != null && (e.side > 0 ? b.low <= e.stop : b.high >= e.stop)
        const hit = e.target != null && (e.side > 0 ? b.high >= e.target : b.low <= e.target)
        const reached = e.watch != null && (e.side > 0 ? b.low <= e.watch : b.high >= e.watch)
        if (stopped && hit) {
          change(e, 'ambiguous')
          continue
        }
        if (stopped) {
          change(e, 'invalidated')
          continue
        }
        if (hit) {
          change(e, e.entryAt ? 'target' : 'invalidated')
          continue
        }
        if (breakSide && breakSide !== e.side) {
          change(e, 'invalidated')
          continue
        }
        if (
          e.kind === 2 &&
          e.status === 'watching' &&
          e.confirmedAt == null &&
          e.trigger != null &&
          (e.side > 0 ? b.close > e.trigger : b.close < e.trigger)
        )
          e.confirmedAt = closedTime
        if (
          e.status === 'waiting' &&
          reached &&
          (e.side > 0
            ? b.close > b.open && b.close > e.watch
            : b.close < b.open && b.close < e.watch)
        ) {
          const entry = round(b.close, t, e.side > 0)
          if (e.kind === 12) e.stop = round(e.side > 0 ? b.low - t : b.high + t, t, e.side < 0)
          if (
            e.side > 0 ? e.stop < entry && entry < e.target : e.target < entry && entry < e.stop
          ) {
            e.entry = entry
            e.entryAt = closedTime
            e.entryBar = b.time
            change(e, 'entry')
          } else change(e, 'invalidated')
        }
      }
      const markClose = (e) => {
        if (
          e.priced &&
          (e.side > 0
            ? b.low > e.stop && b.high < e.target && e.stop < b.close && b.close < e.target
            : b.high < e.stop && b.low > e.target && e.target < b.close && b.close < e.stop)
        ) {
          e.entry = round(b.close, t, e.side > 0)
          e.entryAt = closedTime
          e.entryBar = b.time
          change(e, 'entry')
        }
      }
      // Resolve simultaneous level candidates before recording one method observation.
      // A confirmed rejection outranks a waiting flip, independently of price direction.
      const levelCandidates = []
      if (atr != null)
        for (const levelSide of [1, -1]) {
          const cluster = (levelSide > 0 ? ls : hs).slice(-2),
            tol = Math.max(2 * t, 0.1 * atr)
          if (
            cluster.length < 2 ||
            cluster[1].index - cluster[0].index < 3 ||
            Math.abs(cluster[0].price - cluster[1].price) > tol
          )
            continue
          const lo = Math.min(...cluster.map((p) => p.price)),
            hi = Math.max(...cluster.map((p) => p.price))
          const bounce =
            levelSide > 0
              ? b.low <= hi && b.close > hi && b.close > b.open
              : b.high >= lo && b.close < lo && b.close < b.open
          const flipped =
            prior &&
            (levelSide > 0
              ? prior.close >= lo && b.close < lo - t
              : prior.close <= hi && b.close > hi + t)
          if (!bounce && !flipped) continue
          const side = flipped ? -levelSide : levelSide,
            old = latest(11)
          if (old && !terminal(old) && old.side === side && old.evidence[1] === cluster[1].time)
            continue
          const watch = bounce ? b.close : side > 0 ? hi : lo,
            stop = side > 0 ? Math.min(lo, b.low) - t : Math.max(hi, b.high) + t,
            tp = target(side, watch, b)
          const w = round(watch, t, side > 0),
            sl = round(stop, t, side < 0),
            targetPrice = tp == null ? null : round(tp, t, side < 0)
          const priced =
            targetPrice != null &&
            (side > 0 ? sl < w && w < targetPrice : targetPrice < w && w < sl)
          const enters =
            bounce &&
            priced &&
            (side > 0 ? b.low > sl && b.high < targetPrice : b.high < sl && b.low > targetPrice)
          levelCandidates.push({
            side,
            bounce,
            score: enters ? 0 : priced ? 1 : 2,
            sourceIndex: cluster[1].index,
            watch,
            stop,
            target: tp,
            low: lo,
            high: hi,
            trigger: bounce ? (side > 0 ? lo : hi) : watch,
            evidence: [cluster[0].time, cluster[1].time, b.time],
          })
        }
      const level = levelCandidates.sort(
        (a, b) => a.score - b.score || b.sourceIndex - a.sourceIndex
      )[0]
      if (level) {
        const { side, bounce, score, sourceIndex, ...fields } = level
        const e = create(11, side, b, fields)
        if (bounce) markClose(e)
      }
      // A bounded rolling range, qualified by distinct confirmed pivot touches.
      if (atr != null && n >= 13 && (!latest(12) || terminal(latest(12)))) {
        const range = segment.slice(n - 13, n - 1),
          lo = Math.min(...range.map((q) => q.low)),
          hi = Math.max(...range.map((q) => q.high)),
          tol = Math.max(2 * t, 0.1 * atr)
        const touches = (side) =>
          pivots.filter(
            (p) =>
              p.side === side &&
              p.index >= range[0].i &&
              p.index <= range.at(-1).i &&
              Math.abs(p.price - (side > 0 ? hi : lo)) <= tol
          ).length
        const side =
          b.close >= hi + t && prior.close <= hi
            ? 1
            : b.close <= lo - t && prior.close >= lo
              ? -1
              : 0
        if (side && hi - lo <= 4 * atr && touches(1) >= 2 && touches(-1) >= 2) {
          const watch = side > 0 ? hi : lo
          create(12, side, b, {
            watch,
            trigger: watch,
            stop: side > 0 ? lo - t : hi + t,
            target: target(side, watch, b),
            low: lo,
            high: hi,
            evidence: [range[0].time, range.at(-1).time, b.time],
          })
        }
      }
      // PO3 keeps the original accumulation range fixed at its manipulation candle.
      const pendingPO3 = latest(14)
      if (
        pendingPO3 &&
        pendingPO3.status === 'watching' &&
        b.i > pendingPO3.createdIndex &&
        b.i - pendingPO3.createdIndex <= 3 &&
        displacement(b, pendingPO3.side) &&
        (pendingPO3.side > 0 ? b.close > pendingPO3.trigger : b.close < pendingPO3.trigger)
      ) {
        pendingPO3.confirmedAt = closedTime
        pendingPO3.confirmedBar = b.time
        change(pendingPO3, pendingPO3.priced ? 'waiting' : 'unpriced')
      }
      if (atr != null && n >= 7 && (!latest(14) || terminal(latest(14)))) {
        const range = segment.slice(n - 7, n - 1),
          lo = Math.min(...range.map((q) => q.low)),
          hi = Math.max(...range.map((q) => q.high)),
          span = hi - lo
        const side =
          b.low < lo && b.high <= hi && b.close > lo && b.close < hi
            ? 1
            : b.high > hi && b.low >= lo && b.close > lo && b.close < hi
              ? -1
              : 0
        if (side && span > 0 && span <= 2 * atr)
          create(
            14,
            side,
            b,
            {
              watch: side > 0 ? hi : lo,
              trigger: side > 0 ? hi : lo,
              stop: side > 0 ? b.low - t : b.high + t,
              target: side > 0 ? hi + span : lo - span,
              low: lo,
              high: hi,
              evidence: [range[0].time, range.at(-1).time, b.time],
            },
            false
          )
      }
      if (n >= 3) {
        const a = segment[n - 3],
          m = segment[n - 2]
        const side =
          m.low < a.low &&
          m.high <= a.high &&
          m.close > a.low &&
          m.close < a.high &&
          b.close > m.high &&
          b.close < a.high &&
          b.close > b.open
            ? 1
            : m.high > a.high &&
                m.low >= a.low &&
                m.close > a.low &&
                m.close < a.high &&
                b.close < m.low &&
                b.close > a.low &&
                b.close < b.open
              ? -1
              : 0
        if (
          side &&
          (side > 0 ? b.high < a.high && b.low > m.low - t : b.low > a.low && b.high < m.high + t)
        ) {
          const e = create(13, side, b, {
            watch: b.close,
            stop: side > 0 ? m.low - t : m.high + t,
            target: side > 0 ? a.high : a.low,
            low: a.low,
            high: a.high,
            evidence: [a.time, m.time, b.time],
          })
          markClose(e)
        }
      }
      // Equal-level sweep: no entry is implied until its later structural close and zone retest.
      if (atr != null)
        for (const side of [1, -1]) {
          const cluster = (side > 0 ? ls : hs).slice(-2),
            tol = Math.max(2 * t, 0.1 * atr)
          if (
            cluster.length !== 2 ||
            cluster[1].index - cluster[0].index < 3 ||
            Math.abs(cluster[0].price - cluster[1].price) > tol
          )
            continue
          const lo = Math.min(...cluster.map((p) => p.price)),
            hi = Math.max(...cluster.map((p) => p.price))
          const trigger = side > 0 ? high : low
          const swept = side > 0 ? b.low < lo && b.close > hi : b.high > hi && b.close < lo
          const opposite =
            side > 0 ? b.high > (high?.price ?? Infinity) : b.low < (low?.price ?? -Infinity)
          if (swept && !opposite && trigger && b.i - trigger.index <= 300) {
            const e = create(
              2,
              side,
              b,
              {
                trigger: trigger.price,
                stop: side > 0 ? b.low - t : b.high + t,
                target: target(side, trigger.price, b),
                low: lo,
                high: hi,
                evidence: [cluster[0].time, cluster[1].time, b.time],
              },
              false
            )
            e.confirmedAt = null
          }
        }
      if (breakSide && breakLevel) {
        const side = breakSide,
          watch = breakLevel.price,
          stop = origin ? (side > 0 ? origin.price - t : origin.price + t) : null
        create(
          breakKind,
          side,
          b,
          {
            watch: breakKind === 3 ? watch : null,
            trigger: watch,
            stop,
            target: target(side, watch, b),
            low: watch,
            high: watch,
            evidence: [breakLevel.time, b.time],
          },
          breakKind === 3
        )
        if (displacement(b, side)) {
          const opposite = segment
            .slice(Math.max(0, n - 4), n - 1)
            .reverse()
            .find((p) => (side > 0 ? p.close < p.open : p.close > p.open))
          if (opposite) {
            const watch = (opposite.open + opposite.close) / 2
            const e = create(1, side, b, {
              watch,
              stop: side > 0 ? opposite.low - t : opposite.high + t,
              target: target(side, watch, b),
              low: opposite.low,
              high: opposite.high,
              evidence: [opposite.time, b.time],
            })
            zones.push({
              kind: 1,
              side,
              low: e.low,
              high: e.high,
              record: e,
              at: index,
              converted: false,
            })
          }
          const base = []
          for (let j = n - 2; j >= Math.max(0, n - 4); j--) {
            const q = segment[j],
              candidate = [q, ...base]
            if (
              q.atrBefore == null ||
              Math.abs(q.close - q.open) > 0.5 * q.atrBefore ||
              Math.max(...candidate.map((x) => x.high)) - Math.min(...candidate.map((x) => x.low)) >
                1.5 * atr
            )
              break
            base.unshift(q)
          }
          if (base.length) {
            const lo =
              side > 0
                ? Math.min(...base.map((x) => x.low))
                : Math.min(...base.map((x) => Math.min(x.open, x.close)))
            const hi =
              side > 0
                ? Math.max(...base.map((x) => Math.max(x.open, x.close)))
                : Math.max(...base.map((x) => x.high))
            const watch = side > 0 ? hi : lo
            create(10, side, b, {
              watch,
              stop: side > 0 ? lo - t : hi + t,
              target: target(side, watch, b),
              low: lo,
              high: hi,
              evidence: [base[0].time, base.at(-1).time, b.time],
            })
          }
          if (origin) {
            const extreme = side > 0 ? b.high : b.low,
              span = Math.abs(extreme - origin.price),
              watch = extreme - side * 0.705 * span
            create(7, side, b, {
              watch,
              stop,
              target: extreme,
              low: Math.min(extreme - side * 0.62 * span, extreme - side * 0.79 * span),
              high: Math.max(extreme - side * 0.62 * span, extreme - side * 0.79 * span),
              evidence: [origin.time, b.time],
            })
          }
        }
      }
      if (n >= 3) {
        const a = segment[n - 3],
          m = segment[n - 2]
        const side = b.low > a.high ? 1 : b.high < a.low ? -1 : 0
        if (side) {
          const lo = side > 0 ? a.high : b.high,
            hi = side > 0 ? b.low : a.low,
            watch = (lo + hi) / 2
          const structural = events.findLast(
            (e) => [3, 4].includes(e.kind) && e.side === side && b.i - e.createdIndex <= 5
          )
          const qualified = !!structural && displacement(m, side)
          const e = create(
            0,
            side,
            b,
            {
              watch,
              stop: side > 0 ? a.low - t : a.high + t,
              target: target(side, watch, b),
              low: lo,
              high: hi,
              evidence: [a.time, m.time, b.time],
            },
            qualified
          )
          const sweep = latest(2)
          if (
            qualified &&
            videoSilverWindow(b.time, closedTime, options.seconds) &&
            sweep &&
            !terminal(sweep) &&
            sweep.side === side &&
            sweep.confirmedAt &&
            sweep.createdAt < closedTime &&
            (!latest(9) || terminal(latest(9)))
          ) {
            create(9, side, b, {
              watch,
              stop: sweep.stop,
              target: target(side, watch, b),
              low: lo,
              high: hi,
              evidence: [...sweep.evidence, a.time, m.time, b.time],
            })
          }
          if (qualified)
            zones.push({ kind: 0, side, low: lo, high: hi, record: e, at: index, converted: false })
        }
      }
      // Closing failures create a new inverse identity; the old plan stays retired.
      for (const z of zones) {
        if (z.converted || index - z.at > 20 || z.at === index) continue
        const failed = z.side > 0 ? b.close < z.low : b.close > z.high
        if (failed && !z.failedAt) {
          z.failedAt = index
          change(z.record, 'invalidated')
        }
        if (!z.failedAt) continue
        const side = -z.side
        const sweep = events.findLast(
          (e) =>
            e.kind === 2 &&
            e.side === side &&
            e.createdIndex < z.failedAt &&
            z.failedAt - e.createdIndex <= 5
        )
        if (z.kind === 1 && (!sweep || breakSide !== side)) continue
        const kind = z.kind === 0 ? 5 : 6,
          watch = z.kind === 0 ? (z.low + z.high) / 2 : (z.record.watch ?? (z.low + z.high) / 2)
        create(kind, side, b, {
          watch,
          stop: side > 0 ? z.low - t : z.high + t,
          target: target(side, watch, b),
          low: z.low,
          high: z.high,
          evidence: [...z.record.evidence, b.time],
        })
        z.converted = true
      }
      zones = zones.filter((z) => index - z.at <= 20)
      // A sweep/CHoCH needs a genuinely later new zone, never its own-bar retrospective retest.
      for (const kind of [2, 4]) {
        const e = latest(kind)
        if (!e || terminal(e) || e.status !== 'watching') continue
        const confirmation = kind === 4 ? e.createdAt : e.confirmedAt
        if (!confirmation) continue
        const zone = zones.findLast(
          (z) =>
            z.side === e.side &&
            !z.converted &&
            z.record.createdAt >= confirmation &&
            z.record.createdAt > e.createdAt
        )
        if (zone) {
          e.watch = zone.record.watch
          e.low = zone.low
          e.high = zone.high
          e.confirmedAt = closedTime
          e.confirmedBar = b.time
          e.priced =
            [e.watch, e.stop, e.target].every((v) => v != null && v > 0) &&
            (e.side > 0
              ? e.stop < e.watch && e.watch < e.target
              : e.target < e.watch && e.watch < e.stop)
          change(e, e.priced ? 'waiting' : 'unpriced')
        }
      }
      const tr = prior
        ? Math.max(b.high - b.low, Math.abs(b.high - prior.close), Math.abs(b.low - prior.close))
        : b.high - b.low
      if (atr == null) {
        seed += tr
        count++
        if (count === 14) atr = seed / 14
      } else atr = (atr * 13 + tr) / 14
      last = b
    }
  if (closedTime == null) {
    available = false
    if (options.seconds < 86400 && options.standard !== false)
      unavailable = 'Waiting for verified completed candles.'
  }
  const readings = VIDEO_STRATEGIES.map((s) => {
    const event = events.findLast((e) => e.strategy === s.id) ?? null
    return {
      ...s,
      status: !s.supported ? 'incomplete' : !available ? 'unavailable' : (event?.status ?? 'none'),
      event,
      reason: !s.supported
        ? s.missing
        : !available
          ? unavailable
          : (event?.reason ??
            (s.id === 'silver-bullet' &&
            !videoSilverWindow(
              lastBarTime ?? options.asOf,
              closedTime ?? options.asOf,
              options.seconds
            )
              ? 'Outside the local Silver Bullet window: weekdays 10–11 New York on 1m/5m.'
              : 'No matching confirmed sequence in the loaded candles.')),
    }
  })
  return {
    available,
    reason: available
      ? 'Completed source candles only; chart guidance, not an order.'
      : unavailable,
    closedTime,
    lastBarTime,
    asOf: options.asOf,
    seconds: options.seconds,
    readings,
    events,
    history,
  }
}

export function chooseVideoSetup(result, selectedId = '') {
  if (!result.available)
    return { event: null, action: 'Unavailable', reason: result.reason, mixed: false }
  const current = result.readings.flatMap((r) =>
    r.event && r.event.status === 'entry' && r.event.entryAt === result.closedTime ? [r.event] : []
  )
  const mixed = new Set(current.map((e) => e.side)).size > 1
  if (mixed)
    return {
      event: null,
      action: 'Wait',
      reason: 'Mixed evidence — current Long and Short conditions disagree.',
      mixed: true,
    }
  const selected = selectedId ? result.readings.find((r) => r.id === selectedId) : null
  if (selected && !selected.event)
    return {
      event: null,
      action: selected.supported ? 'Wait' : 'Rules incomplete',
      reason: selected.reason,
      mixed: false,
    }
  const priority = (e) =>
    e.status === 'waiting' ? 0 : e.status === 'unpriced' ? 1 : e.status === 'watching' ? 2 : 3
  const candidates = result.readings.flatMap((r) =>
    r.event && ['waiting', 'entry', 'watching', 'unpriced'].includes(r.event.status)
      ? [r.event]
      : []
  )
  const event =
    selected?.event ??
    current[0] ??
    candidates.sort(
      (a, b) => priority(a) - priority(b) || b.createdAt - a.createdAt || a.kind - b.kind
    )[0] ??
    null
  const fresh = event?.status === 'entry' && event.entryAt === result.closedTime
  return {
    event,
    action: fresh
      ? event.side > 0
        ? 'Review Long'
        : 'Review Short'
      : event && terminal(event)
        ? 'History'
        : 'Wait',
    reason:
      event?.status === 'entry' && !fresh
        ? 'Entry condition was on an earlier candle; this is history. Wait for a new setup.'
        : (event?.reason ?? 'No fresh confirmed entry condition.'),
    mixed: false,
  }
}
export const videoStatusCode = (status) => STATES.indexOf(status)

// Confirmed active matches for the default compact chart view; history is not a fresh action.
export function activeVideoSetups(result) {
  if (!result.available) return []
  return result.readings
    .flatMap((r) =>
      r.event &&
      r.event.confirmedAt != null &&
      (r.event.status === 'waiting' ||
        (r.event.status === 'entry' && r.event.entryAt === result.closedTime))
        ? [r.event]
        : []
    )
    .sort(
      (a, b) =>
        (b.entryAt === result.closedTime) - (a.entryAt === result.closedTime) ||
        b.createdAt - a.createdAt ||
        a.kind - b.kind
    )
}
