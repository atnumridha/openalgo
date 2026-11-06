import { expect, it } from 'vitest'
import { parseChartTarget, chartTargetUrl } from './chartTarget'
import { makePresets } from './presets'
it('round-trips the exact option contract, timeframe and selected candle family', () => {
  const d = makePresets().find((p) => p.name === 'Engulfing')!
  d.interval = '5m'
  const url = chartTargetUrl({ symbol: 'NIFTY03NOV2623000PE', exchange: 'NFO' }, d)
  expect(parseChartTarget(url.split('?')[1])).toEqual({
    symbol: 'NIFTY03NOV2623000PE',
    exchange: 'NFO',
    interval: '5m',
    candlePattern: 'engulfing',
    candleStudy: true,
  })
})
it('rejects invalid targets without accepting markup, external URLs or an unsupported frame', () => {
  for (const search of [
    'symbol=<script>&exchange=NSE&interval=1m',
    'symbol=BTCUSD&exchange=DELTA&interval=13m',
    'symbol=https://bad.test&exchange=NSE',
  ])
    expect(parseChartTarget(search)).toBeNull()
  expect(parseChartTarget('')).toBeNull()
})
it('preserves special characters using proper query encoding and does not enable a disabled candle condition', () => {
  const d = makePresets().find((p) => p.name === 'Engulfing')!
  d.rule.children[0].enabled = false
  const url = chartTargetUrl({ symbol: 'M&M', exchange: 'NSE' }, d)
  expect(url).toContain('M%26M')
  expect(url).not.toContain('study=')
  expect(parseChartTarget(url.split('?')[1])?.symbol).toBe('M&M')
})
