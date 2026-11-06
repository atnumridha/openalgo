import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })
it.each([
  [undefined, 2, 0.2],
  [{volume: 0.7, repeats: 3}, 6, 0.7],
] as const)('schedules the requested audible tone profile: %j', async (options, tones, peak) => {
  vi.resetModules()
  const gain = { gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn() }
  const osc = { frequency: { value: 0 }, connect: vi.fn(() => gain), start: vi.fn(), stop: vi.fn(), type: '' }
  const ctx = { state: 'running', currentTime: 10, destination: {}, createGain: vi.fn(() => gain), createOscillator: vi.fn(() => osc) }
  vi.stubGlobal('AudioContext', class { constructor() { return ctx } })
  const { playAlertSound } = await import('./alertDelivery')
  expect(playAlertSound(options)).toBe(true)
  expect(ctx.createOscillator).toHaveBeenCalledTimes(tones)
  expect(gain.gain.exponentialRampToValueAtTime.mock.calls.filter(c => c[0] === peak)).toHaveLength(tones)
  const starts = osc.start.mock.calls.map(c => c[0])
  const stops = osc.stop.mock.calls.map(c => c[0])
  for (let i = 1; i < starts.length; i++) expect(starts[i]).toBeGreaterThanOrEqual(stops[i - 1])
})
