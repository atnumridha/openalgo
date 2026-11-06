import { expect, it } from 'vitest'
import { rankOptionStrikes, strikeActivity, totalStrikeActivity } from './strikeRanking'
const row = (strike: number, ceOI: number, ceVolume: number, peOI = ceOI, peVolume = ceVolume) => ({
  strike, ce: { symbol: `TEST${strike}CE`, oi: ceOI, volume: ceVolume },
  pe: { symbol: `TEST${strike}PE`, oi: peOI, volume: peVolume },
})
it('ranks the overall most-traded strikes first by total volume, then OI, while retaining every strike', () => {
  const rows = [row(90, 30, 100, 70, 10), row(100, 1, 1), row(110, 50, 100, 10, 100), row(120, 50, 100, 100, 100), row(300, 0, 0)]
  expect(rankOptionStrikes(rows, 100, 'CE').map(r => r.strike)).toEqual([120,110,90,100,300])
  expect(rankOptionStrikes(rows, 100, 'PE').map(r => r.strike)).toEqual([120,110,90,100,300])
  expect(totalStrikeActivity(rows[0], 'volume')).toBe(110)
  expect(totalStrikeActivity(rows[0], 'oi')).toBe(100)
  expect(rows.map(r => r.strike)).toEqual([90,100,110,120,300])
})
it('keeps listed legs with unknown activity at the end and uses ATM/distance for exact ties', () => {
  const rows = [row(130, 0, 0), row(110, 0, 0), {strike: 100, ce: null, pe: {symbol:'TEST100PE'}}, {strike:90,ce:{symbol:'TEST90CE',oi:NaN,volume:-1},pe:null}]
  expect(rankOptionStrikes(rows, 100, 'CE').map(r => r.strike)).toEqual([110,130,90])
  expect(rankOptionStrikes(rows, 100, 'PE').map(r => r.strike)).toEqual([110,130,100])
  expect(rankOptionStrikes([row(90,0,0),row(100,0,0)],100,'CE').map(r=>r.strike)).toEqual([100,90])
  expect(strikeActivity(0)).toBe('0')
  expect(strikeActivity(undefined)).toBe('—')
  expect(strikeActivity(-1)).toBe('—')
})
