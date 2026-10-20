import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import * as core from '../../frontend/node_modules/openalgo-charts/dist/openalgo-charts.mjs'
import * as indicators from '../../frontend/node_modules/openalgo-charts/dist/openalgo-charts.indicators.mjs'

const source = new URL('../../scripts/chart_indicators/htf_liquidity.js', import.meta.url)
async function study() {
  assert.ok(existsSync(source), 'The higher-timeframe liquidity indicator must exist')
  const { default: install } = await import(`data:text/javascript;base64,${readFileSync(source).toString('base64')}`)
  let descriptor
  install({ ...core, ...indicators, registerIndicator: (d) => { descriptor = d } })
  return descriptor
}
const start = Date.parse('2026-10-15T00:00:00Z') / 1000
function bars(n, first = start, step = 300) {
  return Array.from({ length: n }, (_, i) => ({ time: first + i * step, open: 100, high: 110 + i, low: 90 - i / 10, close: 101, volume: 1 }))
}
function calculate(d, data, overrides = {}, context = {}) {
  const settings = { ...Object.fromEntries(d.inputs.map((i) => [i.key, i.default])), marking: 'legacy', setupMode: 'off', basis: 'previous', ...overrides }
  const store = {}
  const values = d.calc(data, settings, store, { symbol: 'BTCUSDFUT', interval: '5m', tickSize: 0.5, ...context })
  return { bars: data, values, settings, store }
}

test('holds completed 1H, 4H and daily highs/lows while the current candle changes', async () => {
  const d = await study()
  const data = bars(301)
  const a = calculate(d, data)
  assert.equal(a.values.h1High.at(-1), 409)
  assert.equal(a.values.h4High.at(-1), 397)
  assert.equal(a.values.d1High.at(-1), 397)
  const changed = data.map((b, i) => i === 300 ? { ...b, high: 999, low: 1 } : b)
  const b = calculate(d, changed)
  for (const key of ['h1High', 'h1Low', 'h4High', 'h4Low', 'd1High', 'd1Low']) {
    assert.equal(a.values[key].at(-1), b.values[key].at(-1), key)
  }
})

test('does not use future candles when replay only reveals a prefix', async () => {
  const d = await study()
  const data = bars(320)
  const all = calculate(d, data).values
  const prefix = calculate(d, data.slice(0, 301)).values
  for (const key of Object.keys(prefix)) assert.deepEqual(prefix[key], all[key].slice(0, 301), key)
})

test('does not call a partial first bucket or a missing-candle range complete', async () => {
  const d = await study()
  assert.equal(calculate(d, bars(20, start + 300)).values.h1High[11], null)
  const gapped = bars(25).filter((_, i) => i !== 5)
  assert.equal(calculate(d, gapped).values.h1High[11], null)
  assert.equal(calculate(d, gapped).values.h1High.at(-1), 133)
})

test('hides invalid OHLC ranges and rejects transformed candles', async () => {
  const d = await study()
  const data = bars(13)
  data[3].high = NaN
  assert.equal(calculate(d, data).values.h1High.at(-1), null)
  assert.throws(() => calculate(d, bars(13), {}, { transformed: true }), /Underlying bars|ordinary candles/)
})

test('does not relabel an older UTC range when an entire reference period is missing', async () => {
  const d = await study()
  const data = [...bars(12), ...bars(1, start + 10800)]
  assert.equal(calculate(d, data).values.h1High.at(-1), null)
})

test('groups coincident levels and includes timeframe, liquidity side and price in line text', async () => {
  const d = await study()
  const result = calculate(d, bars(301))
  const levels = d.levels(result)
  assert.equal(levels.length, 4)
  assert.ok(result.store.liquidityLines.some((l) => /4H.*1D.*Buy-side liquidity.*397\.00/.test(l.title)))
  assert.ok(result.store.liquidityLines.some((l) => /1H.*Sell-side liquidity/.test(l.title)))
  assert.ok(levels.every((l) => Number.isFinite(l.price) && l.lineWidth >= 3))
})

test('toggles timeframes independently and cannot derive 1H levels from 4H candles', async () => {
  const d = await study()
  const disabled = calculate(d, bars(301), { show1H: false, show4H: false })
  assert.equal(d.levels(disabled).length, 2)
  assert.ok(disabled.store.liquidityLines.every((l) => l.title.startsWith('1D')))
  const coarse = calculate(d, bars(13, start, 14400), {}, { interval: '4h' })
  assert.equal(coarse.values.h1High.at(-1), null)
  assert.equal(coarse.values.h4High.at(-1), 121)
})

test('uses Indian session-open buckets and previous complete session for index charts', async () => {
  const d = await study()
  const day1 = Date.parse('2026-10-15T09:15:00+05:30') / 1000
  const data = [...bars(75, day1), ...bars(14, day1 + 86400)]
  const result = calculate(d, data, {}, { symbol: 'NIFTY' })
  assert.equal(result.values.h1High.at(-1), 121)
  assert.equal(result.values.d1High.at(-1), 184)
  assert.equal(result.values.h4High.at(-1), 184)
})

test('supplies empty columns and no levels for an empty chart', async () => {
  const d = await study()
  const result = calculate(d, [])
  assert.deepEqual(d.levels(result), [])
  for (const column of Object.values(result.values)) assert.equal(column.length, 0)
})

test('right-edge labels remain inside the viewport, separate close levels and clean up', async () => {
  const d = await study()
  const store = {}
  const primitives = new Set()
  const cleanup = d.attach({ store, addPrimitive: (p) => primitives.add(p), removePrimitive: (p) => assert.ok(primitives.delete(p)) })
  const primitive = [...primitives].find((p) => p.zOrder() === 'top')
  const settings = Object.fromEntries(d.inputs.map((i) => [i.key, i.default]))
  settings.basis = 'previous'
  d.calc(bars(301), settings, store, { symbol: 'BTCUSDFUT', interval: '5m' })
  const texts = []
  const canvas = new Proxy({ measureText: (t) => ({ width: t.length * 6 }), fillText: (text, x, y) => texts.push({ text, x, y }) }, { get: (o, k) => k in o ? o[k] : () => {} })
  const render = { plotWidth: 400, plotHeight: 300, dpr: 1, priceScale: { priceToY: (p) => 400 - p }, theme: { background: '#fff' } }
  primitive.draw(canvas, render)
  assert.equal(texts.length, 4)
  assert.ok(texts.every((t) => t.x === 388 && t.y >= 12 && t.y <= 288 && /Liquidity/.test(t.text)))
  assert.ok(texts[0].y >= 100, 'offscreen labels leave space for the OHLC and indicator legend')
  for (let i = 1; i < texts.length; i++) assert.ok(texts[i].y - texts[i - 1].y >= 22)
  texts.length = 0
  primitive.draw(canvas, { ...render, plotWidth: 700 })
  assert.ok(texts.every((t) => t.x === 688))
  d.calc([], settings, store, { interval: '5m' })
  texts.length = 0
  primitive.draw(canvas, render)
  assert.equal(texts.length, 0)
  cleanup()
  assert.equal(primitives.size, 0)
})

// Each item is one higher-timeframe candle. The final extra native candle
// reveals that the last reference candle has actually closed.
function structure(lows, highs = lows.map(() => 130), frame = 3600) {
  return lows.flatMap((low, j) => Array.from({ length: frame / 300 }, (_, k) => ({
    time: start + j * frame + k * 300, open: (low + highs[j]) / 2,
    high: highs[j], low, close: (low + highs[j]) / 2, volume: 1,
  }))).concat({ time: start + lows.length * frame, open: 115, high: 116, low: 114, close: 115, volume: 1 })
}
const swingSettings = { basis: 'swings', marking: 'legacy', setupMode: 'off', show4H: false, show1D: false, showTaken: true }
const lowZones = (r) => (r.store.liquidityZones || []).filter((z) => z.side === 'Low')

test('defaults to confirmed swing zones and waits for both right candles to close', async () => {
  const d = await study()
  assert.equal(d.inputs.find((i) => i.key === 'basis')?.default, 'swings')
  const data = structure([110, 100, 90, 101, 110])
  assert.equal(lowZones(calculate(d, data.slice(0, -1), swingSettings)).length, 0)
  const [zone] = lowZones(calculate(d, data, swingSettings))
  assert.equal(zone.price, 90)
  assert.equal(zone.shape, 'V low')
  assert.equal(zone.pivotTime, start + 2 * 3600)
  assert.equal(zone.confirmedAt, start + 5 * 3600)
  assert.ok(zone.lower < 90 && zone.upper > 90)
  assert.equal(zone.lower % 0.5, 0)
  assert.equal(zone.upper % 0.5, 0)
})

test('groups similar separated swing lows into a W without moving its original zone', async () => {
  const d = await study()
  const data = structure([110, 100, 90, 101, 110, 100, 90.5, 101, 110])
  const first = lowZones(calculate(d, data.slice(0, 61), swingSettings))[0]
  const zones = lowZones(calculate(d, data, swingSettings))
  assert.equal(zones.length, 1)
  assert.equal(zones[0].shape, 'W lows')
  assert.equal(zones[0].touches, 2)
  for (const key of ['id', 'price', 'lower', 'upper', 'confirmedAt']) assert.equal(zones[0][key], first[key], key)
})

test('marks inverted V and M highs symmetrically', async () => {
  const d = await study()
  const data = structure(Array(9).fill(80), [110, 120, 130, 119, 110, 120, 129.5, 119, 110])
  const first = calculate(d, data.slice(0, 61), swingSettings).store.liquidityZones.find((z) => z.side === 'High')
  assert.equal(first.shape, 'Inverted V high')
  const zone = calculate(d, data, swingSettings).store.liquidityZones.find((z) => z.side === 'High')
  assert.equal(zone.shape, 'M highs')
  assert.equal(zone.price, 130)
  assert.equal(zone.upper, first.upper)
})

test('equal plateaus and missing native candles do not create swing zones', async () => {
  const d = await study()
  assert.equal(lowZones(calculate(d, structure([110, 100, 90, 90, 110]), swingSettings)).length, 0)
  const gapped = structure([110, 100, 90, 101, 110]).filter((_, i) => i !== 28)
  assert.equal(lowZones(calculate(d, gapped, swingSettings)).length, 0)
  const invalid = structure([110, 100, 90, 101, 110])
  invalid[28].high = NaN
  assert.equal(lowZones(calculate(d, invalid, swingSettings)).length, 0)
})

test('zones freeze during ticks, become Taken only beyond the outer edge, and survive recalculation', async () => {
  const d = await study()
  const data = structure([110, 100, 90, 101, 110])
  const original = lowZones(calculate(d, data, swingSettings))[0]
  for (const low of [100, original.lower]) {
    const changed = data.map((b, i) => i === data.length - 1 ? { ...b, low } : b)
    assert.deepEqual(lowZones(calculate(d, changed, swingSettings))[0], original)
  }
  const crossed = data.map((b, i) => i === data.length - 1 ? { ...b, low: original.lower - 0.5 } : b)
  const taken = lowZones(calculate(d, crossed, swingSettings))[0]
  assert.equal(taken.takenAt, crossed.at(-1).time)
  assert.equal(taken.lower, original.lower)
  assert.equal(taken.upper, original.upper)
  assert.deepEqual(calculate(d, crossed, swingSettings).store.liquidityZones, calculate(d, crossed, swingSettings).store.liquidityZones)
  assert.equal(lowZones(calculate(d, crossed, { ...swingSettings, showTaken: false })).length, 0)
})

test('swing values preserve causality and work independently on 1H, 4H and daily candles', async () => {
  const d = await study()
  for (const [frame, key] of [[3600, 'h1'], [14400, 'h4'], [86400, 'd1']]) {
    const settings = { basis: 'swings', show1H: key === 'h1', show4H: key === 'h4', show1D: key === 'd1' }
    const data = structure([110, 100, 90, 101, 110, 105, 104], undefined, frame)
    const count = 5 * frame / 300 + 1
    const prefix = calculate(d, data.slice(0, count), settings)
    const full = calculate(d, data, settings)
    assert.equal(lowZones(prefix)[0].price, 90)
    for (const name of Object.keys(prefix.values)) assert.deepEqual(prefix.values[name], full.values[name].slice(0, count), name)
  }
})

test('does not bridge missing higher-timeframe periods, and filters coarse chart intervals', async () => {
  const d = await study()
  const data = structure([110, 100, 90, 101, 110]).filter((b) => b.time < start + 3600 || b.time >= start + 7200)
  assert.equal(lowZones(calculate(d, data, swingSettings)).length, 0)
  assert.equal(lowZones(calculate(d, bars(15, start, 14400), swingSettings, { interval: '4h' })).length, 0)
})

test('keeps a bounded number of zones with explanatory right-side labels', async () => {
  const d = await study()
  const data = structure([110, 100, 90, 101, 110, 90, 80, 101, 110, 80, 70, 100, 110])
  const result = calculate(d, data, { ...swingSettings, zonesPerSide: 2 })
  assert.equal(lowZones(result).length, 2)
  assert.ok(result.store.liquidityLines.filter((l) => !l.reference).every((l) => /1H Liquidity.*V low.*\d.*\d/.test(l.label)))
  assert.ok(result.store.liquidityLines.some((l) => /Taken/.test(l.label)))
  assert.deepEqual(d.levels(result), [])
})

test('bands start at confirmation and right labels show the frozen price range', async () => {
  const d = await study(), store = {}, primitives = []
  d.attach({ store, addPrimitive: (p) => primitives.push(p) })
  const settings = { ...Object.fromEntries(d.inputs.map((i) => [i.key, i.default])), ...swingSettings, display: 'detailed' }
  d.calc(structure([110, 100, 90, 101, 110]), settings, store, { symbol: 'BTCUSDFUT', interval: '5m', tickSize: 0.5 })
  const rects = [], texts = [], origins = []
  const canvas = new Proxy({
    measureText: (t) => ({ width: t.length * 6 }),
    fillText: (text, x, y) => texts.push({ text, x, y }),
    fillRect: (...r) => rects.push(r), arc: (...r) => origins.push(r),
  }, { get: (o, k) => k in o ? o[k] : () => {} })
  const rc = { plotWidth: 600, plotHeight: 300, dpr: 1, priceScale: { priceToY: (p) => 400 - p * 2 },
    timeScale: { indexToX: (i) => i * 50 }, dataLayer: { timeToIndexFloat: (t) => (t - start) / 3600 }, theme: { background: '#fff' } }
  primitives.find((p) => p.zOrder() === 'bottom').draw(canvas, rc)
  assert.equal(rects[0][0], 250)
  assert.equal(rects[0][2], 350)
  assert.equal(origins[0][0], 100)
  primitives.find((p) => p.zOrder() === 'top').draw(canvas, rc)
  const swingLabel = texts.find((t) => /1H Liquidity.*V low.*–/.test(t.text))
  assert.ok(swingLabel)
  assert.equal(swingLabel.x, 588)
})

test('top-down mode shows fixed daily open and previous day wicks, hiding taken references by default', async () => {
  const d = await study()
  assert.equal(d.inputs.find((i) => i.key === 'showTaken').default, false)
  const data = structure([80, 85], [130, 135], 86400)
  const result = calculate(d, data, { basis: 'swings', show1H: false, show4H: false })
  assert.equal(result.values.dayOpen.at(-1), 115)
  assert.equal(result.values.priorDayHigh.at(-1), 135)
  assert.equal(result.values.priorDayLow.at(-1), 85)
  assert.ok(result.store.liquidityLines.some((l) => /1D Open.*colour flip/.test(l.label)))
  assert.ok(result.store.liquidityLines.some((l) => /1D Liquidity.*Prior high.*135/.test(l.label)))
  assert.ok(result.store.liquidityLines.some((l) => /1D Liquidity.*Prior low.*85/.test(l.label)))
})

test('daily open stays fixed while candle colour changes, and a crossed prior high stays taken', async () => {
  const d = await study(), settings = { basis: 'swings', show1H: false, show4H: false }
  const data = structure([80, 85], [130, 135], 86400)
  const red = data.map((b, i) => i === data.length - 1 ? { ...b, close: 114 } : b)
  const green = data.map((b, i) => i === data.length - 1 ? { ...b, close: 116 } : b)
  for (const b of [red, green]) assert.equal(calculate(d, b, settings).values.dayOpen.at(-1), 115)
  assert.ok(calculate(d, red, settings).store.liquidityLines.some((l) => /Below open/.test(l.label)))
  assert.ok(calculate(d, green, settings).store.liquidityLines.some((l) => /Above open/.test(l.label)))
  const touched = data.map((b, i) => i === data.length - 1 ? { ...b, high: 135 } : b)
  assert.equal(calculate(d, touched, settings).values.priorDayHigh.at(-1), 135)
  const crossed = data.map((b, i) => i === data.length - 1 ? { ...b, high: 136 } : b)
  crossed.push({ ...data.at(-1), time: data.at(-1).time + 300 })
  assert.equal(calculate(d, crossed, settings).values.priorDayHigh.at(-1), null)
  assert.ok(calculate(d, crossed, { ...settings, showTaken: true }).store.liquidityLines.some((l) => /Prior high.*Taken/.test(l.label)))
})

test('daily body edges are optional and unavailable session opens are not invented', async () => {
  const d = await study(), data = structure([80, 85], [130, 135], 86400)
  const s = { basis: 'swings', show1H: false, show4H: false, showDailyBody: true, showTaken: true }
  const result = calculate(d, data, s)
  assert.equal(result.values.priorBodyHigh.at(-1), 110)
  assert.equal(result.values.priorBodyLow.at(-1), 110)
  const missing = data.slice(0, -1).concat({ ...data.at(-1), time: data.at(-1).time + 300 })
  assert.equal(calculate(d, missing, s).values.dayOpen.at(-1), null)
  assert.ok(!calculate(d, data, { ...s, showDailyBody: false }).store.liquidityLines.some((l) => /Body/.test(l.label)))
})

test('separate confirmed swings across a history gap are not asserted to be a W', async () => {
  const d = await study()
  const a = structure([110, 100, 90, 101, 110])
  const b = structure([110, 100, 90, 101, 110]).map((bar) => ({ ...bar, time: bar.time + 7 * 3600 }))
  const zone = lowZones(calculate(d, [...a, ...b], swingSettings))[0]
  assert.equal(zone.shape, 'V low')
  assert.equal(zone.pivotTime, start + 9 * 3600)
})

test('1H and 4H have independent fixed opens, prior wicks and optional body edges', async () => {
  const d = await study()
  for (const [key, label, seconds] of [['h1', '1H', 3600], ['h4', '4H', 14400]]) {
    const data = structure([80, 85], [130, 135], seconds)
    const settings = { basis: 'swings', showTaken: true, showDailyBody: true }
    const result = calculate(d, data, settings)
    assert.equal(result.values[key + 'Open'].at(-1), 115)
    assert.equal(result.values[key + 'PriorHigh'].at(-1), 135)
    assert.equal(result.values[key + 'PriorLow'].at(-1), 85)
    assert.equal(result.values[key + 'BodyHigh'].at(-1), 110)
    assert.equal(result.values[key + 'BodyLow'].at(-1), 110)
    assert.ok(result.store.liquidityLines.some((l) => l.label.startsWith(`${label} Open · colour flip`)))
    const red = data.map((b, i) => i === data.length - 1 ? { ...b, close: 114 } : b)
    const green = data.map((b, i) => i === data.length - 1 ? { ...b, close: 116 } : b)
    for (const [b, direction] of [[red, 'Below open'], [green, 'Above open']]) {
      const r = calculate(d, b, settings)
      assert.equal(r.values[key + 'Open'].at(-1), 115)
      assert.ok(r.store.liquidityLines.some((l) => l.label.startsWith(`${label} Open`) && l.label.endsWith(direction)))
    }
  }
})

test('intraday references retire strict crossings and do not invent missing opens or prior candles', async () => {
  const d = await study(), settings = { basis: 'swings' }
  for (const [key, seconds] of [['h1', 3600], ['h4', 14400]]) {
    const data = structure([80, 85], [130, 135], seconds)
    const touched = data.map((b, i) => i === data.length - 1 ? { ...b, high: 135, low: 85 } : b)
    let r = calculate(d, touched, settings)
    assert.equal(r.values[key + 'PriorHigh'].at(-1), 135)
    assert.equal(r.values[key + 'PriorLow'].at(-1), 85)
    const crossed = data.map((b, i) => i === data.length - 1 ? { ...b, high: 136, low: 84 } : b)
    crossed.push({ ...data.at(-1), time: data.at(-1).time + 300 })
    r = calculate(d, crossed, settings)
    assert.equal(r.values[key + 'PriorHigh'].at(-1), null)
    assert.equal(r.values[key + 'PriorLow'].at(-1), null)
    const missingOpen = data.slice(0, -1).concat({ ...data.at(-1), time: data.at(-1).time + 300 })
    assert.equal(calculate(d, missingOpen, settings).values[key + 'Open'].at(-1), null)
    const missingPrior = data.filter((_, i) => i !== data.length - 3)
    assert.equal(calculate(d, missingPrior, settings).values[key + 'PriorHigh'].at(-1), null)
  }
})

test('reference rollovers and replay are independent across all three timeframes', async () => {
  const d = await study(), settings = { basis: 'swings', showTaken: true, showDailyBody: true }
  const data = structure(Array(25).fill(90), Array(25).fill(130))
  // At the new UTC day all three opens coincide. Only the 1H open then rolls.
  data[288].open = 113
  data[300].open = 117
  data[300].high = 118
  const r = calculate(d, data, settings)
  assert.equal(r.values.h1Open.at(-1), 117)
  assert.equal(r.values.h4Open.at(-1), 113)
  assert.equal(r.values.dayOpen.at(-1), 113)
  const prefix = calculate(d, data.slice(0, 290), settings)
  for (const key of Object.keys(prefix.values)) assert.deepEqual(prefix.values[key], r.values[key].slice(0, 290), key)
  const hidden = calculate(d, data, { ...settings, show4H: false })
  assert.ok(!hidden.store.liquidityLines.some((l) => l.label.startsWith('4H ')))
  const layersOff = calculate(d, data, { ...settings, showDailyOpen: false, showPriorDay: false, showDailyBody: false })
  assert.ok(!layersOff.store.liquidityLines.some((l) => l.reference))
})

test('default display keeps one newest untaken swing zone per timeframe and no extra references', async () => {
  const d = await study()
  assert.equal(d.inputs.find((i) => i.key === 'display')?.default, 'focused')
  const data = structure([110, 100, 90, 101, 110, 90, 80, 101, 110, 80, 70, 100, 110], undefined, 86400)
  const r = calculate(d, data, { basis: 'swings', showTaken: true, zonesPerSide: 3 })
  assert.ok(r.store.liquidityDisplay.length > 0)
  assert.ok(r.store.liquidityDisplay.length <= 3)
  assert.ok(r.store.liquidityDisplay.every((l) => !l.reference && l.takenAt == null))
  for (const key of ['h1', 'h4', 'd1']) {
    const shown = r.store.liquidityDisplay.filter((l) => l.frameKey === key)
    const candidates = r.store.liquidityLines.filter((l) => l.frameKey === key && l.takenAt == null)
    assert.equal(shown.length, candidates.length ? 1 : 0)
    if (shown.length) {
      assert.equal(shown[0].updatedAt, Math.max(...candidates.map((l) => l.updatedAt)))
      assert.ok(shown[0].label.length < 50)
      assert.match(shown[0].label, /Liquidity (High|Low)/)
    }
  }
  const detailed = calculate(d, data, { ...r.settings, display: 'detailed' })
  assert.deepEqual(detailed.values, r.values)
  assert.deepEqual(detailed.store.liquidityDisplay, detailed.store.liquidityLines)
  assert.ok(detailed.store.liquidityDisplay.some((l) => l.reference))
})

test('focused zone selection stays fixed through live price moves and hides taken zones', async () => {
  const d = await study(), data = structure([110, 100, 90, 101, 110])
  const r = calculate(d, data, swingSettings)
  const original = r.store.liquidityDisplay[0]
  for (const close of [114, 116]) {
    const changed = data.map((b, i) => i === data.length - 1 ? { ...b, close } : b)
    assert.deepEqual(calculate(d, changed, swingSettings).store.liquidityDisplay, r.store.liquidityDisplay)
  }
  const crossed = data.map((b, i) => i === data.length - 1 ? { ...b, low: original.lower - 0.5 } : b)
  assert.equal(calculate(d, crossed, swingSettings).store.liquidityDisplay.length, 0)
})

test('source markings use fixed wick lines, retain swept references and keep one per timeframe', async () => {
  const d = await study(), data = structure([110, 100, 90, 101, 110])
  const settings = { ...swingSettings, marking: 'source', showTaken: false }
  const before = calculate(d, data, settings)
  const z = before.store.liquidityDisplay[0]
  assert.equal(z.lower, 90)
  assert.equal(z.upper, 90)
  const changed = data.map((b, i) => i === data.length - 1 ? { ...b, low: 89 } : b)
  const after = calculate(d, changed, settings)
  assert.equal(after.store.liquidityDisplay.length, 1)
  assert.equal(after.store.liquidityDisplay[0].price, 90)
  assert.match(after.store.liquidityDisplay[0].label, /Swept/)
})

test('source setup exposes status and never fabricates entry levels on an hourly chart', async () => {
  const d = await study()
  const r = calculate(d, bars(10, start, 3600), { marking: 'source', basis: 'swings', setupMode: 'reversal' }, { interval: '1h' })
  assert.match(r.store.setupStatus, /1m.*5m/)
  assert.deepEqual(r.store.setupDisplay, [])
  assert.ok(r.values.setupEntry.every((v) => v == null))
})

test('manual reference activation cannot backdate a signal and produces chart risk levels after confirmation', async () => {
  const d = await study(), data = bars(5)
  Object.assign(data[1], { open: 105, high: 106, low: 101, close: 102 })
  Object.assign(data[2], { open: 99, high: 103, low: 98, close: 102 })
  Object.assign(data[3], { open: 102, high: 103, low: 101, close: 102 })
  const settings = { marking: 'source', basis: 'swings', setupMode: 'reversal', manualLevel: 100, manualSide: 'Low', manualFrame: 'h1', manualFrom: data[2].time }
  const r = calculate(d, data.slice(0, 4), settings)
  assert.equal(r.store.setup.plan.entry, 103)
  assert.equal(r.store.setup.plan.sl, 97.5)
  assert.equal(r.store.setup.plan.target, null)
  assert.ok(r.store.setupDisplay.some((l) => /SL/.test(l.label)))
  assert.equal(r.values.setupEntry[1], null)
  const late = calculate(d, data.slice(0, 4), { ...settings, manualFrom: data[3].time })
  assert.equal(late.store.setup.plan, null)
})

test('manual liquidity marks strict sweeps independently of the entry setup and retains equality', async () => {
  const d = await study(), data = bars(2)
  Object.assign(data[0], { open: 105, high: 108, low: 102, close: 104 })
  Object.assign(data[1], { open: 104, high: 105, low: 100, close: 102 })
  const settings = { marking: 'source', basis: 'swings', setupMode: 'off', manualLevel: 100, manualSide: 'Low', manualFrame: 'h1', manualFrom: data[0].time }
  assert.doesNotMatch(calculate(d, data, settings).store.liquidityDisplay[0].label, /Swept/)
  data[1].low = 98
  for (const setupMode of ['off', 'continuation']) {
    const r = calculate(d, data, { ...settings, setupMode })
    assert.match(r.store.liquidityDisplay[0].label, /Swept/)
    assert.equal(r.store.liquidityDisplay[0].takenAt, data[1].time)
  }
})
