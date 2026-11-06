import type { StrategyBar, Frame, Pivot, Side, StrategySession } from './types'
type N = number | undefined
export function sma(values: readonly N[], n: number): N[] {
  const out: N[] = []
  let sum = 0,
    valid = 0
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v != null && Number.isFinite(v)) {
      sum += v
      valid++
    }
    const old = values[i - n]
    if (i >= n && old != null && Number.isFinite(old)) {
      sum -= old
      valid--
    }
    out.push(i >= n - 1 && valid === n ? sum / n : undefined)
  }
  return out
}
export function ema(values: readonly N[], n: number): N[] {
  let seed: number[] = [],
    previous: N
  return values.map((v) => {
    if (v == null || !Number.isFinite(v)) {
      seed = []
      previous = undefined
      return undefined
    }
    if (previous == null) {
      seed.push(v)
      if (seed.length < n) return undefined
      previous = seed.reduce((a, b) => a + b, 0) / n
    } else previous += (2 / (n + 1)) * (v - previous)
    return previous
  })
}
function rma(values: readonly N[], n: number): N[] {
  let seed: number[] = [],
    v: N
  return values.map((x) => {
    if (x == null || !Number.isFinite(x)) {
      seed = []
      v = undefined
      return undefined
    }
    if (v == null) {
      seed.push(x)
      if (seed.length < n) return undefined
      v = seed.reduce((a, b) => a + b, 0) / n
    } else v = (v * (n - 1) + x) / n
    return v
  })
}
export function rsi(c: readonly number[], n = 14): N[] {
  const gain = rma(
      c.map((v, i) => (i ? Math.max(0, v - c[i - 1]) : undefined)),
      n
    ),
    loss = rma(
      c.map((v, i) => (i ? Math.max(0, c[i - 1] - v) : undefined)),
      n
    )
  return c.map((_, i) =>
    gain[i] == null || loss[i] == null
      ? undefined
      : loss[i] === 0
        ? gain[i] === 0
          ? 50
          : 100
        : 100 - 100 / (1 + gain[i]! / loss[i]!)
  )
}
export function strictPivots(b: readonly StrategyBar[], right = 3): Pivot[] {
  const out: Pivot[] = []
  for (let i = right; i < b.length - right; i++) {
    if (b.slice(i - right, i + right + 1).every((x, j) => j === right || x.high < b[i].high))
      out.push({ index: i, knownAt: i + right, price: b[i].high, kind: 'high' })
    if (b.slice(i - right, i + right + 1).every((x, j) => j === right || x.low > b[i].low))
      out.push({ index: i, knownAt: i + right, price: b[i].low, kind: 'low' })
  }
  return out
}
function supertrend(b: readonly StrategyBar[], atr: N[], mult: number): { value: N; side: Side }[] {
  let upper: N,
    lower: N,
    side: Side = 'long'
  return b.map((x, i) => {
    const a = atr[i]
    if (a == null) return { value: undefined, side }
    const u = (x.high + x.low) / 2 + mult * a,
      l = (x.high + x.low) / 2 - mult * a,
      prev = b[i - 1]?.close
    upper = upper == null || u < upper || (prev != null && prev > upper) ? u : upper
    lower = lower == null || l > lower || (prev != null && prev < lower) ? l : lower
    if (side === 'short' && x.close > upper) side = 'long'
    else if (side === 'long' && x.close < lower) side = 'short'
    return { value: side === 'long' ? lower : upper, side }
  })
}
function sar(b: readonly StrategyBar[]): N[] {
  if (!b.length) return []
  let long = true,
    ep = b[0].high,
    af = 0.02,
    value = b[0].low
  return b.map((x, i) => {
    if (!i) return value
    value += af * (ep - value)
    if (long) {
      value = Math.min(value, b[i - 1].low, b[Math.max(0, i - 2)].low)
      if (x.low < value) {
        long = false
        value = ep
        ep = x.low
        af = 0.02
      } else if (x.high > ep) {
        ep = x.high
        af = Math.min(0.2, af + 0.02)
      }
    } else {
      value = Math.max(value, b[i - 1].high, b[Math.max(0, i - 2)].high)
      if (x.high > value) {
        long = true
        value = ep
        ep = x.high
        af = 0.02
      } else if (x.low < ep) {
        ep = x.low
        af = Math.min(0.2, af + 0.02)
      }
    }
    return value
  })
}
export function buildFrames(
  b: readonly StrategyBar[],
  seconds: number,
  offset = 19800,
  options: {
    voFast?: number
    voSlow?: number
    donchianPeriod?: number
    supertrendMultiplier?: number
    session?: StrategySession | null
  } = {}
): Frame[] {
  const session =
    options.session === undefined
      ? { start: offset === 0 ? 0 : 555, end: offset === 0 ? 1440 : 930, offset }
      : options.session
  const c = b.map((x) => x.close),
    v = b.map((x) => x.volume),
    periods = [5, 7, 9, 14, 20, 21, 50, 200],
    ems = Object.fromEntries(periods.map((n) => [n, ema(c, n)])),
    sms = Object.fromEntries([14, 20, 50, 200].map((n) => [n, sma(c, n)])),
    rs = rsi(c),
    e12 = ema(c, 12),
    e26 = ema(c, 26),
    macd = c.map((_, i) => (e12[i] != null && e26[i] != null ? e12[i]! - e26[i]! : undefined)),
    signal = ema(macd, 9),
    tr = b.map((x, i) =>
      Math.max(
        x.high - x.low,
        i ? Math.abs(x.high - b[i - 1].close) : 0,
        i ? Math.abs(x.low - b[i - 1].close) : 0
      )
    ),
    at = rma(tr, 14),
    at7 = rma(tr, 7),
    st7 = supertrend(b, at7, options.supertrendMultiplier ?? 3),
    st10 = supertrend(b, rma(tr, 10), options.supertrendMultiplier ?? 3),
    sv = sma(v, 20),
    vf = ema(v, options.voFast ?? 5),
    vs = ema(v, options.voSlow ?? 10),
    ps = sar(b),
    p3 = strictPivots(b, 3),
    p4 = strictPivots(b, 4)
  const highs: Pivot[] = [],
    lows: Pivot[] = [],
    fh: Pivot[] = [],
    fl: Pivot[] = [],
    out: Frame[] = []
  let p3i = 0,
    p4i = 0,
    day = -Infinity,
    sessionIndex = -1,
    ws = 0,
    wp = 0,
    wpp = 0,
    volumeValid = false,
    covered = false,
    priorClose = NaN,
    sessionEnd = NaN,
    haO = 0,
    haC = 0,
    dh = 0,
    dl = 0,
    dc = 0,
    pivot: N,
    r1: N,
    r2: N,
    s1: N,
    s2: N,
    bc: N,
    tc: N
  for (let i = 0; i < b.length; i++) {
    const x = b[i],
      newDay = Math.floor((x.time + offset) / 86400)
    if (newDay !== day) {
      if (day !== -Infinity && covered && priorClose === sessionEnd) {
        pivot = (dh + dl + dc) / 3
        r1 = 2 * pivot - dl
        r2 = pivot + dh - dl
        s1 = 2 * pivot - dh
        s2 = pivot - dh + dl
        bc = (dh + dl) / 2
        tc = 2 * pivot - bc
      } else {
        pivot = r1 = r2 = s1 = s2 = bc = tc = undefined
      }
      day = newDay
      ws = wp = wpp = 0
      volumeValid = false
      covered = false
      priorClose = NaN
      sessionIndex = -1
    }
    const sessionStart = day * 86400 - offset + (session?.start ?? 0) * 60
    sessionEnd = day * 86400 - offset + (session?.end ?? 0) * 60
    const inside = !!session && x.time >= sessionStart && x.time < sessionEnd
    if (inside) {
      if (x.time === sessionStart) {
        covered = true
        volumeValid = true
        sessionIndex = 0
        ws = wp = wpp = 0
        dh = x.high
        dl = x.low
      } else {
        if (x.time !== priorClose) covered = false
        if (sessionIndex >= 0) sessionIndex++
        dh = Math.max(dh, x.high)
        dl = Math.min(dl, x.low)
      }
      const close = x.closeTime ?? Math.min(x.time + seconds, sessionEnd)
      if (!(close > x.time && close <= sessionEnd)) covered = false
      priorClose = close
      dc = x.close
      if (!(x.volume > 0)) volumeValid = false
      const typical = (x.high + x.low + x.close) / 3
      if (x.volume > 0) {
        ws += x.volume
        wp += typical * x.volume
        wpp += typical * typical * x.volume
      }
    }
    while (p3i < p3.length && p3[p3i].knownAt <= i) {
      const p = p3[p3i++]
      ;(p.kind === 'high' ? highs : lows).push(p)
    }
    while (p4i < p4.length && p4[p4i].knownAt <= i) {
      const p = p4[p4i++]
      ;(p.kind === 'high' ? fh : fl).push(p)
    }
    const range = (n: number, field: 'high' | 'low', end = i) =>
      b
        .slice(Math.max(0, end - n + 1), end + 1)
        .reduce(
          (a, z) => (field === 'high' ? Math.max(a, z.high) : Math.min(a, z.low)),
          field === 'high' ? -Infinity : Infinity
        )
    const mid = (n: number) => (i >= n - 1 ? (range(n, 'high') + range(n, 'low')) / 2 : undefined)
    const conversion = mid(9),
      base = mid(26),
      rawA = conversion != null && base != null ? (conversion + base) / 2 : undefined,
      basis = sms[20][i],
      sd =
        basis != null
          ? Math.sqrt(c.slice(i - 19, i + 1).reduce((a, z) => a + (z - basis) ** 2, 0) / 20)
          : undefined
    haO = i ? (haO + haC) / 2 : (x.open + x.close) / 2
    haC = (x.open + x.high + x.low + x.close) / 4
    const n = options.donchianPeriod ?? 20,
      donH = i >= n ? range(n, 'high', i - 1) : undefined,
      donL = i >= n ? range(n, 'low', i - 1) : undefined,
      hh = range(14, 'high'),
      ll = range(14, 'low')
    const em = Object.fromEntries(periods.map((n) => [n, ems[n][i]])),
      sm = Object.fromEntries([14, 20, 50, 200].map((n) => [n, sms[n][i]])),
      fast = em[20],
      slow = em[50]
    out.push({
      bar: x,
      index: i,
      ema: em,
      sma: sm,
      atr: at[i],
      atr7: at7[i],
      rsi: rs[i],
      wr: i >= 13 && hh > ll ? (-100 * (hh - x.close)) / (hh - ll) : undefined,
      macd: macd[i],
      macdSignal: signal[i],
      basis,
      upper: sd != null ? basis! + 2 * sd : undefined,
      lower: sd != null ? basis! - 2 * sd : undefined,
      width: sd != null && basis! > 0 ? (400 * sd) / basis! : undefined,
      volumeMean: sv[i],
      vo: vf[i] != null && vs[i]! > 0 ? (100 * (vf[i]! - vs[i]!)) / vs[i]! : undefined,
      vwap: inside && covered && volumeValid && ws > 0 ? wp / ws : undefined,
      vwapSD:
        inside && covered && volumeValid && ws > 0
          ? Math.sqrt(Math.max(0, wpp / ws - (wp / ws) ** 2))
          : undefined,
      pivot,
      r1,
      r2,
      s1,
      s2,
      cprLow: bc != null && tc != null ? Math.min(bc, tc) : undefined,
      cprHigh: bc != null && tc != null ? Math.max(bc, tc) : undefined,
      st7: st7[i].value,
      st10: st10[i].value,
      st7Side: st7[i].side,
      st10Side: st10[i].side,
      donHigh: donH,
      donLow: donL,
      donMid: donH != null && donL != null ? (donH + donL) / 2 : undefined,
      conversion,
      base,
      rawSpanA: rawA,
      rawSpanB: mid(52),
      cloudA: out[i - 26]?.rawSpanA,
      cloudB: out[i - 26]?.rawSpanB,
      haOpen: haO,
      haClose: haC,
      haHigh: Math.max(x.high, haO, haC),
      haLow: Math.min(x.low, haO, haC),
      sar: ps[i],
      highs: highs.slice(-8),
      lows: lows.slice(-8),
      fractalHighs: fh.slice(-4),
      fractalLows: fl.slice(-4),
      trend:
        fast != null && slow != null && i >= 5
          ? fast > slow && fast > ems[20][i - 5]!
            ? 'bull'
            : fast < slow && fast < ems[20][i - 5]!
              ? 'bear'
              : 'neutral'
          : 'neutral',
      day,
      minute: ((((x.time + offset) % 86400) + 86400) % 86400) / 60,
      sessionIndex,
    })
  }
  return out
}
