// Behavioral checks of the actual Pine source using independent PineTS 0.13.0.
// Usage: PINETS_MODULE=/absolute/path/to/pinets node --test scripts/tradingview/tests/bb_chikou.test.cjs
// This does not replace compilation and visual checks inside TradingView.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PineTS } = require(process.env.PINETS_MODULE || 'pinets');
const sourcePath = path.join(__dirname, '../bb_chikou_nifty_sensex.pine');

function candles(tail, { scale = 1, historicalHigh = false, nextDay = false, baseLength = 60, tightFrom = Infinity, startAt = '09:15:00' } = {}) {
  // Use past candles: the independent runtime classifies future timestamps as unconfirmed.
  const start = Date.parse(`2025-10-27T${startAt}+05:30`);
  const base = Array.from({ length: baseLength }, (_, i) => {
    const amplitude = i >= tightFrom ? 0.1 : 1;
    const close = 100 + (i % 2 ? amplitude : -amplitude);
    return { open: close, high: historicalHigh && i === baseLength + 1 - 26 ? 110 : close + 0.05, low: close - 0.05, close };
  });
  return [...base, ...tail].map((bar, i) => {
    const openTime = start + i * 60000 + (nextDay && i === 61 ? 86400000 : 0);
    return { ...Object.fromEntries(Object.entries(bar).map(([k, v]) => [k, v * scale])),
      volume: 0, openTime, closeTime: openTime + 60000 };
  });
}
const up = { open: 101, high: 103.2, low: 100.8, close: 103 };
const buy = { open: 103, high: 104.2, low: 102.8, close: 104 };
const down = { open: 99, high: 99.2, low: 96.8, close: 97 };
const sell = { open: 97, high: 97.2, low: 95.8, close: 96 };

async function run(data, mutate = s => s) {
  assert.ok(fs.existsSync(sourcePath), 'indicator source must exist');
  const source = mutate(fs.readFileSync(sourcePath, 'utf8')) + '\nplot(buySignal ? 1 : 0, "Test buy")\nplot(sellSignal ? 1 : 0, "Test sell")\n';
  const result = await new PineTS(data, 'NSE:NIFTY', '1').run(source);
  const values = name => result.plots[name].data.map(p => p.value);
  return { buys: values('Test buy'), sells: values('Test sell'), values };
}

test('upper touch followed by next close above setup high gives one buy and 1R levels', async () => {
  const r = await run(candles([up, buy]));
  assert.equal(r.buys[60], 0);
  assert.equal(r.buys[61], 1);
  assert.equal(r.buys.reduce((a, b) => a + b, 0), 1);
  assert.equal(r.sells[61], 0);
  assert.equal(r.values('Entry')[61], 104);
  const stop = r.values('Initial stop')[61];
  assert.ok(stop < 104);
  assert.ok(Math.abs(r.values('Target')[61] - (104 + 104 - stop)) < 1e-8);
});

test('lower touch followed by next close below setup low gives sell and symmetric 1R', async () => {
  const r = await run(candles([down, sell]));
  assert.equal(r.sells[61], 1);
  assert.equal(r.buys[61], 0);
  const stop = r.values('Initial stop')[61];
  assert.ok(stop > 96);
  assert.ok(Math.abs(r.values('Target')[61] - (96 - (stop - 96))) < 1e-8);
});

test('wick crossing setup high without a confirming close gives no buy', async () => {
  const r = await run(candles([up, { ...buy, close: 102.2 }]));
  assert.equal(r.buys[61], 0);
});

test('setup expires after the immediately following candle', async () => {
  const r = await run(candles([up, { open: 101, high: 102, low: 100.5, close: 101 }, buy]));
  assert.equal(r.buys[62], 0);
});

test('historical wick obstruction blocks full-candle Chikou clearance', async () => {
  const r = await run(candles([up, buy], { historicalHigh: true }));
  assert.equal(r.buys[61], 0);
});

test('no signal during warmup', async () => {
  const r = await run(candles([up, buy]).slice(-15));
  assert.ok(r.buys.every(v => v === 0));
  assert.ok(r.sells.every(v => v === 0));
});

test('same percentage path works at Nifty and Sensex price scales without volume', async () => {
  for (const scale of [250, 800]) {
    const r = await run(candles([up, buy], { scale }));
    assert.equal(r.buys[61], 1);
    assert.equal(r.values('Entry')[61], 104 * scale);
  }
});

test('yesterday setup cannot trigger on the next trading day', async () => {
  const r = await run(candles([up, buy], { nextDay: true }));
  assert.equal(r.buys[61], 0);
});

test('unconfirmed bars cannot signal (inject unconfirmed state into actual source)', async () => {
  const r = await run(candles([up, buy]), s => s.replaceAll('barstate.isconfirmed', 'false'));
  assert.ok(r.buys.every(v => v === 0));
  assert.ok(r.sells.every(v => v === 0));
});

test('close-only Chikou mode allows a historical wick that full-candle mode blocks', async () => {
  const r = await run(candles([up, buy], { historicalHigh: true }), s => s.replace('input.string("Full candle"', 'input.string("Close only"'));
  assert.equal(r.buys[61], 1);
});

test('latest entry, initial stop, and target stay frozen while the band keeps moving', async () => {
  const r = await run(candles([up, buy, { open: 104, high: 105.2, low: 103.8, close: 105 }]));
  assert.equal(r.buys[62], 0);
  for (const title of ['Entry', 'Initial stop', 'Target']) assert.equal(r.values(title)[62], r.values(title)[61]);
  assert.notEqual(r.values('BB middle / SMA')[62], r.values('BB middle / SMA')[61]);
});

test('cash session blocks premarket confirmations', async () => {
  const r = await run(candles([up, buy], { startAt: '07:00:00' }));
  assert.equal(r.buys[61], 0);
});

test('squeeze filter blocks a breakout without enough contraction history', async () => {
  const r = await run(candles([up, buy]), s => s.replace('input.bool(false, "Require recent squeeze', 'input.bool(true, "Require recent squeeze'));
  assert.equal(r.buys[61], 0);
});

test('squeeze filter permits expansion after a measured contraction', async () => {
  const r = await run(candles([up, buy], { baseLength: 100, tightFrom: 70 }), s => s.replace('input.bool(false, "Require recent squeeze', 'input.bool(true, "Require recent squeeze'));
  assert.equal(r.buys[101], 1);
});

test('same-day gap cannot join a setup to a nonadjacent confirmation', async () => {
  const data = candles([up, buy]);
  data[61].openTime += 60000;
  data[61].closeTime += 60000;
  const r = await run(data);
  assert.equal(r.buys[61], 0);
});
