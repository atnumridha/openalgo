import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const module = await import(`data:text/javascript;base64,${readFileSync(new URL('../../scripts/chart_indicators/htf_liquidity.js', import.meta.url)).toString('base64')}`)
const t = 1792281600
const candle = (i, open, high, low, close) => ({ time: t + i * 60, open, high, low, close, volume: 1 })
const refs = [
  { id: 'low', frameKey: 'h1', frame: '1H', side: 'Low', price: 100, knownIndex: 0 },
  { id: 'high', frameKey: 'h4', frame: '4H', side: 'High', price: 120, knownIndex: 0 },
]
const config = { mode: 'reversal', seconds: 60, tick: 0.5, bufferTicks: 1, maxWaitBars: 8 }
const run = (data, settings = {}, levels = refs) => {
  assert.equal(typeof module.evaluateLiquiditySetup, 'function', 'source-guided setup evaluator is available')
  return module.evaluateLiquiditySetup(data, levels, { ...config, ...settings })
}
const long = [candle(0, 105, 108, 102, 104), candle(1, 99, 103, 98, 102), candle(2, 102, 103, 101, 102)]

test('sweep and closed green freeze Entry, SL and opposing liquidity Target; equality is not entry', () => {
  const r = run(long)
  assert.equal(r.plan.stage, 'WATCHING ENTRY')
  assert.deepEqual([r.plan.direction, r.plan.entry, r.plan.sl, r.plan.target], ['LONG', 103, 97.5, 120])
  assert.equal(r.plan.confirmedAt, t + 120)
  const crossed = run([...long, candle(3, 102, 104, 101, 103)])
  assert.equal(crossed.plan.stage, 'TRIGGERED')
  assert.equal(crossed.plan.triggeredAt, t + 180)
})

test('forming candle, doji, equal reference touch and confirmation own wick cannot trigger', () => {
  assert.equal(run(long.slice(0, 2)).plan.stage, 'WAITING CONFIRMATION')
  assert.equal(run([long[0], candle(1, 102, 104, 100, 103)]).plan, null)
  const doji = run([long[0], candle(1, 99, 103, 98, 99), long[2]])
  assert.equal(doji.plan.stage, 'WAITING CONFIRMATION')
  assert.equal(run(long).plan.triggeredAt, undefined)
})

test('bearish mirror, native tick rounding and first frozen confirmation survive later candles', () => {
  const data = [candle(0, 115, 118, 112, 116), candle(1, 121, 122, 117, 118), candle(2, 119, 121, 117, 118)]
  const r = run(data)
  assert.deepEqual([r.plan.direction, r.plan.entry, r.plan.sl, r.plan.target], ['SHORT', 117, 122.5, 100])
  assert.equal(run([...data, candle(3, 118, 120, 116, 119)]).plan.stage, 'TRIGGERED')
  assert.deepEqual([r.plan.entry, r.plan.sl], [117, 122.5])
})

test('touched HTF target may remain context, but unavailable opposing liquidity is explicit', () => {
  assert.equal(run(long, {}, refs.map((r) => ({ ...r, takenAt: t - 100 }))).plan.target, 120)
  const r = run(long, {}, refs.slice(0, 1))
  assert.equal(r.plan.target, null)
  assert.equal(r.plan.stage, 'NO TARGET')
})

test('unknown levels and pivots cannot act early; future changes preserve earlier decisions', () => {
  assert.equal(run(long, {}, refs.map((r) => ({ ...r, knownIndex: 3 }))).plan, null)
  const prefix = run(long)
  const all = run([...long, candle(3, 102, 105, 101, 104), candle(4, 104, 119, 103, 118)])
  assert.deepEqual(all.history.slice(0, long.length), prefix.history)
  assert.equal(all.plan.entry, 103)
  assert.equal(all.plan.sl, 97.5)
})

test('stop/entry ambiguity, same-bar stop/target and history gaps never become clean wins', () => {
  assert.equal(run([...long, candle(3, 102, 104, 97, 103)]).plan.stage, 'AMBIGUOUS')
  assert.equal(run([...long, candle(3, 102, 104, 101, 103), candle(4, 104, 121, 97, 110)]).plan.stage, 'AMBIGUOUS')
  assert.equal(run([...long, candle(8, 102, 104, 101, 103)]).plan.stage, 'DATA GAP')
  assert.equal(run(long, { tick: 0 }).reason, 'Broker tick size unavailable')
})

test('pending plan expires and stop breach invalidates without moving protection', () => {
  const quiet = [...long, candle(3, 102, 103, 101, 102), candle(4, 102, 103, 101, 102)]
  assert.equal(run(quiet, { maxWaitBars: 2 }).plan.stage, 'EXPIRED')
  assert.equal(run([...long, candle(3, 102, 103, 97, 99)]).plan.stage, 'INVALIDATED')
})

test('continuation needs strong prior trend, first pullback and untouched opposing extreme', () => {
  const up = Array.from({ length: 24 }, (_, i) => candle(i, 70 + i * 2, 73 + i * 2, 69 + i * 2, 72 + i * 2))
  const tail = [candle(24, 117, 118, 112, 114), candle(25, 114, 115, 108, 110),
    candle(26, 110, 114, 109, 112), candle(27, 112, 116, 111, 115),
    candle(28, 109, 113, 107, 112), candle(29, 112, 113, 111, 112)]
  const r = run([...up, ...tail], { mode: 'continuation', strength: 2, trendBars: 20 })
  assert.equal(r.plan?.stage, 'WATCHING ENTRY')
  assert.deepEqual([r.plan.reference.price, r.plan.entry, r.plan.sl, r.plan.target], [108, 113, 106.5, 119])
  const taken = tail.map((b, i) => i === 3 ? { ...b, high: 119 } : b)
  assert.equal(run([...up, ...taken], { mode: 'continuation', strength: 2, trendBars: 20 }).plan, null)
  assert.match(run(long, { mode: 'continuation', seconds: 3600 }).reason, /1m.*5m/)
})

test('continuation mirrors shorts and disqualifies the opposing target before entry', () => {
  const rise = Array.from({ length: 24 }, (_, i) => candle(i, 70 + i * 2, 73 + i * 2, 69 + i * 2, 72 + i * 2))
  const tail = [candle(24, 117, 118, 112, 114), candle(25, 114, 115, 108, 110),
    candle(26, 110, 114, 109, 112), candle(27, 112, 116, 111, 115),
    candle(28, 109, 113, 107, 112), candle(29, 112, 113, 111, 112)]
  const mirror = (b) => ({ ...b, open: 200 - b.open, high: 200 - b.low, low: 200 - b.high, close: 200 - b.close })
  const short = [...rise, ...tail].map(mirror)
  const p = run(short, { mode: 'continuation' }).plan
  assert.deepEqual([p.direction, p.entry, p.sl, p.target], ['SHORT', 87, 93.5, 81])
  const entryAndTarget = mirror(candle(30, 112, 119, 111, 118))
  assert.equal(run([...short, entryAndTarget], { mode: 'continuation' }).plan.stage, 'AMBIGUOUS')
})

test('continuation cannot bridge a missing candle between its trend target and pullback', () => {
  const trend = Array.from({ length: 24 }, (_, i) => candle(i, 70 + i * 2, 73 + i * 2, 69 + i * 2, 72 + i * 2))
  const tail = [candle(24, 117, 118, 114, 116), candle(25, 116, 117, 111, 113),
    candle(26, 113, 114, 108, 110), candle(27, 110, 114, 109, 112), candle(28, 112, 116, 111, 115),
    candle(29, 109, 113, 107, 112), candle(30, 112, 113, 111, 112)]
    .map((b) => ({ ...b, time: b.time + 600 }))
  assert.equal(run([...trend, ...tail], { mode: 'continuation' }).plan, null)
})

test('triggered plans retain prices to SL or target and do not rearm on the same reference', () => {
  const entry = candle(3, 102, 105, 101, 104)
  const target = candle(4, 104, 120, 103, 119)
  const won = run([...long, entry, target])
  assert.equal(won.plan.stage, 'TARGET REACHED')
  assert.equal(won.plan.target, 120)
  assert.equal(run([...long, entry, candle(4, 104, 105, 97.5, 98)]).plan.stage, 'SL REACHED')
  const repeat = run([...long, entry, target, candle(5, 102, 105, 98, 104)])
  assert.equal(repeat.plan.id, won.plan.id)
  assert.equal(repeat.plan.stage, 'TARGET REACHED')
})

test('ATR/trend context does not block a higher-timeframe reversal and missing tick is guarded', () => {
  const p = run(long, { trendBars: 100 }).plan
  assert.equal(p.stage, 'WATCHING ENTRY')
  assert.equal(run(long, { tick: NaN }).plan, null)
  const fractional = long.map((b) => ({ ...b, high: b.high + 0.1, low: b.low - 0.1 }))
  assert.equal(run(fractional).plan.entry, 103.5)
  assert.equal(run(fractional).plan.sl, 97)
})

const verified = [candle(0, 105, 108, 102, 104), candle(1, 99, 103, 98, 102),
  candle(2, 102, 104, 97, 98), candle(3, 99, 104, 98, 103)]
test('verified reversal waits for failed initial buying and a completed strong seller before a later renewed break', () => {
  const settings = { mode: 'verified', bufferTicks: 0, maxWaitBars: 0 }
  assert.equal(run(verified.slice(0, 2), settings).plan.stage, 'WAITING RESPONSE')
  assert.equal(run(verified.slice(0, 3), settings).plan.stage, 'WAITING OPPOSITION')
  const watched = run(verified, settings).plan
  assert.equal(watched.stage, 'WATCHING ENTRY')
  assert.deepEqual([watched.entry, watched.sl, watched.target], [104, 97, 120])
  assert.equal(watched.response.index, 1)
  assert.equal(watched.opposition.index, 2)
  assert.equal(watched.triggeredAt, undefined)
  const triggered = run([...verified, candle(4, 103, 105, 102, 104)], settings).plan
  assert.equal(triggered.stage, 'TRIGGERED')
  assert.equal(triggered.triggeredAt, t + 240)
})

test('verified short mirrors buyer failure; weak/doji opposition and unfinished candles do not qualify', () => {
  const settings = { mode: 'verified', bufferTicks: 0, maxWaitBars: 0 }
  const mirror = (b) => ({ ...b, open: 220 - b.open, high: 220 - b.low, low: 220 - b.high, close: 220 - b.close })
  const short = run(verified.map(mirror), settings).plan
  assert.deepEqual([short.direction, short.entry, short.sl, short.target], ['SHORT', 116, 123, 100])
  const weak = [verified[0], verified[1], candle(2, 101, 108, 96, 98), verified[3]]
  assert.equal(run(weak, settings).plan.stage, 'WAITING OPPOSITION')
  const noFailure = [verified[0], verified[1], candle(2, 105, 106, 100, 101), verified[3]]
  assert.equal(run(noFailure, settings).plan.stage, 'WAITING OPPOSITION')
  assert.equal(run(verified.slice(0, 3), settings).plan.entry, null)
})

test('verified plan survives arbitrary watch duration, cancels replaced references and is causal across reload', () => {
  const settings = { mode: 'verified', maxWaitBars: 0 }
  const quiet = [...verified, ...Array.from({ length: 20 }, (_, k) => candle(k + 4, 101, 104, 99, 102))]
  const p = run(quiet, settings)
  assert.equal(p.plan.stage, 'WATCHING ENTRY')
  assert.equal(p.plan.entry, 104)
  const prefix = run(verified, settings)
  assert.deepEqual(p.history.slice(0, verified.length - 1), prefix.history.slice(0, -1))
  assert.deepEqual(run(quiet, settings), p)
  const replaced = [...refs, { ...refs[0], id: 'new-low', price: 95, knownIndex: 4 }]
  assert.equal(run(quiet, settings, replaced).plan.stage, 'REFERENCE REPLACED')
})

function risingPullback() {
  return [...Array.from({ length: 24 }, (_, i) => candle(i, 70 + i * 2, 73 + i * 2, 69 + i * 2, 72 + i * 2)),
    candle(24, 117, 118, 112, 114), candle(25, 114, 115, 108, 110),
    candle(26, 110, 114, 109, 112), candle(27, 112, 116, 111, 115),
    candle(28, 111, 115, 110, 114), candle(29, 114, 115, 112, 114)]
}
test('protected continuation forms above an intact low and invalidates its breach instead of requiring a sweep', () => {
  const settings = { mode: 'protected', bufferTicks: 0, maxWaitBars: 0 }
  const data = risingPullback(), p = run(data, settings).plan
  assert.deepEqual([p.stage, p.direction, p.entry, p.sl, p.target], ['WATCHING ENTRY', 'LONG', 115, 108, 119])
  assert.equal(run([...data, candle(30, 114, 116, 110, 115)], settings).plan.stage, 'TRIGGERED')
  assert.equal(run([...data, candle(30, 114, 115, 107, 110)], settings).plan.stage, 'PROTECTED LEVEL BROKEN')
  const breached = data.map((b, i) => i === 28 ? { ...b, low: 107 } : b)
  assert.equal(run(breached, settings).plan, null)
})

test('rally mode uses a small closed candle and trails only from prior completed candles without loosening', () => {
  const data = [...Array.from({ length: 24 }, (_, i) => candle(i, 70 + i * 2, 73 + i * 2, 69 + i * 2, 72 + i * 2)),
    candle(24, 115, 117, 115, 116), candle(25, 116, 118, 115.5, 117),
    candle(26, 117, 119, 116, 118), candle(27, 118, 119, 117, 117.5), candle(28, 118, 119, 117, 118)]
  const settings = { mode: 'rally', bufferTicks: 0, maxWaitBars: 0 }
  const watched = run(data.slice(0, 25), { ...settings, lastConfirmed: true }).plan
  assert.deepEqual([watched.stage, watched.entry, watched.sl, watched.target], ['WATCHING ENTRY', 117, 115, 120])
  const live = run(data.slice(0, 27), settings).plan
  assert.equal(live.stage, 'TRIGGERED')
  assert.equal(live.initialSl, 115)
  assert.equal(live.sl, 115.5)
  const all = run(data, settings)
  assert.equal(all.plan.sl, 116)
  assert.ok(all.history.filter((p) => p?.triggeredAt).every((p, k, a) => !k || p.sl >= a[k - 1].sl))
  const exit = run([...data, candle(29, 118, 119, 116.5, 117)], settings).plan
  assert.equal(exit.stage, 'RALLY EXIT')
})
