import { expect, it } from 'vitest'
import { STRATEGIES_51 } from './catalog'
it('contains all51 book strategies exactly once with source pages and risk/exit rules', () => {
  expect(STRATEGIES_51).toHaveLength(51)
  expect(new Set(STRATEGIES_51.map((x) => x.id)).size).toBe(51)
  expect(STRATEGIES_51.filter((x) => x.id.startsWith('6.'))).toHaveLength(13)
  for (const s of STRATEGIES_51) {
    expect(s.title.length).toBeGreaterThan(6)
    expect(s.pages[0]).toBeGreaterThan(0)
    expect(s.entry.length).toBeGreaterThan(5)
    expect(s.stop.length).toBeGreaterThan(5)
    expect(s.exit.length).toBeGreaterThan(5)
  }
  expect(STRATEGIES_51.find((x) => x.id === '1.2')?.notes.join(' ')).toMatch(/MACD.*title/i)
  expect(STRATEGIES_51.find((x) => x.id === '7.5')?.stop).toMatch(/no fixed stop/i)
})
