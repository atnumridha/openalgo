import { expect, it, vi } from 'vitest'
import { loadResearchSessions } from './chartResearchHistory'
const start = Date.UTC(2026, 9, 30, 3, 45) / 1000
const make = (time: number, count: number) =>
  Array.from({ length: count }, (_, i) => ({
    time: time + i * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
  }))
it('loads a complete previous Indian session even when the display only supplied today', async () => {
  const base = make(start, 100),
    old = make(start - 86400, 375),
    load = vi.fn(async () => old)
  const bars = await loadResearchSessions(
    base,
    true,
    false,
    { start: 555, end: 930, offset: 19800 },
    load
  )
  expect(load).toHaveBeenCalledWith('2026-10-29')
  expect(load).toHaveBeenCalledTimes(1)
  expect(bars).toHaveLength(475)
  expect(bars[0].time).toBe(start - 86400)
})
it('loads the UTC-day coverage needed for continuous previous-day research', async () => {
  const load = vi.fn(async () => [])
  await loadResearchSessions(make(start, 100), true, true, undefined, load)
  expect(load.mock.calls.map((c) => c[0])).toEqual(['2026-10-30', '2026-10-29', '2026-10-28'])
})
it('keeps ordinary setups local to the available source and retries missing prior data later', async () => {
  const base = make(start, 100),
    load = vi.fn(async () => {
      throw Error('delayed')
    })
  expect(await loadResearchSessions(base, false, false, undefined, load)).toEqual(base)
  expect(load).not.toHaveBeenCalled()
  expect(
    await loadResearchSessions(base, true, false, { start: 555, end: 930, offset: 19800 }, load)
  ).toEqual(base)
})

it('does not substitute Wednesday after Thursday history fails for a Friday chart', async () => {
  const load = vi.fn(async (date: string) => {
    if (date === '2026-10-29') throw Error('delayed')
    return make(start - 2 * 86400, 375)
  })
  const base = make(start, 100),
    result = await loadResearchSessions(
      base,
      true,
      false,
      { start: 555, end: 930, offset: 19800 },
      load
    )
  expect(load).toHaveBeenCalledTimes(1)
  expect(load).toHaveBeenCalledWith('2026-10-29')
  expect(result).toEqual(base)
})
