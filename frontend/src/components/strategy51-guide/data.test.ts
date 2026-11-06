import { expect, it } from 'vitest'
import { deriveOptionEvidence } from './useStrategy51Data'
const t = Date.UTC(2026, 10, 2, 4, 0) / 1000
const bars = [{ time: t, open: 150, high: 155, low: 145, close: 152, volume: 100 }]
const underlying = [{ time: t, open: 100, high: 102, low: 99, close: 101, volume: 0 }]
const chain = {
  status: 'success',
  underlying: 'TEST',
  expiry_date: '09NOV26',
  fo_exchange: 'NFO',
  atm_strike: 120,
  chain: [90, 100, 110, 120, 130].map((strike) => ({
    strike,
    ce: { symbol: `TEST09NOV26${strike}CE`, label: '', exists: true },
    pe: { symbol: `TEST09NOV26${strike}PE`, label: '', exists: true },
  })),
}
it('uses the historical baseline underlying OPEN rather than current ATM/spot for selection', () => {
  const wrong = deriveOptionEvidence('TEST09NOV26120CE', 'NFO', bars, underlying, chain)
  expect(wrong?.selections?.some((x) => x.kind === 'atm')).toBe(false)
  const right = deriveOptionEvidence('TEST09NOV26100CE', 'NFO', bars, underlying, chain)
  expect(right?.selections?.find((x) => x.kind === 'atm')).toMatchObject({
    time: t,
    source: 'verified-history',
  })
})
it('never turns present OI or missing exact baseline bars into historical selection evidence', () => {
  const x = deriveOptionEvidence('TEST09NOV26100CE', 'NFO', bars, underlying, chain)
  expect(x?.selections?.some((s) => s.kind === 'highest-oi')).toBe(false)
  expect(deriveOptionEvidence('TEST09NOV26100CE', 'NFO', bars, [], chain)?.selections).toEqual([])
  expect(
    deriveOptionEvidence('TEST09NOV26100CE', 'NFO', bars, underlying, {
      ...chain,
      expiry_date: '16NOV26',
    })
  ).toBeUndefined()
})
it('accepts explicitly supplied dated OI identity without inventing an ATM baseline and keeps it scoped to the chart interval', () => {
  const time = t - 600,
    premium = [{ ...bars[0], time }],
    manual = [
      {
        strategyId: '6.3',
        kind: 'risk' as const,
        symbol: 'TEST09NOV26100CE',
        exchange: 'NFO',
        intervalSeconds: 300,
        asOf: time,
        side: 'long' as const,
        description: 'Supplied 09:20 highest-OI snapshot',
      },
    ]
  const evidence = deriveOptionEvidence('TEST09NOV26100CE', 'NFO', premium, [], chain, manual, 300)
  expect(evidence?.selections).toEqual([
    expect.objectContaining({ kind: 'highest-oi', source: 'supplied', time }),
  ])
  expect(
    deriveOptionEvidence('TEST09NOV26100CE', 'NFO', premium, [], chain, manual, 60)?.selections
  ).toEqual([])
})
