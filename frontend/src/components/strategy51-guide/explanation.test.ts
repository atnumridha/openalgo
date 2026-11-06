import { expect, it } from 'vitest'
import { explainStrategy51, formatStrategy51Price, STRATEGY51_EXPLANATIONS } from './explanation'
import { STRATEGIES_51 } from './catalog'
import { DEFAULT_STRATEGY51_SETTINGS as settings } from './settings'
import { example, time } from './explanationFixtures'
it('explains the pictured Donchian evidence and actual price progress without a fresh-entry instruction', () => {
  const r = explainStrategy51(example(), settings)
  expect(r.why).toMatch(/20.candle.*channel/i)
  expect(r.why).toMatch(/pullback/i)
  expect(r.why).toContain('24,870.00')
  expect(r.now).toContain('25,030.35')
  expect(r.now).toContain('156.50')
  expect(r.scenario).toContain('256.25')
  expect(r.invalidation).toContain('24,667.48')
  expect(r.next).toMatch(/closed|review/i)
  expect(r.confirmed).toContain('06 Nov')
})
it('uses the reversed price direction for short references and separates forming observations', () => {
  const r = example()
  r.readiness = 'ready'
  r.viewMode = 'live'
  r.plan = { ...r.plan!, side: 'short', entry: 100, stop: 110, target: 80 }
  r.forming = { time: time + 2700, price: 95 }
  const text = explainStrategy51(r, settings)
  expect(text.now).toMatch(/forming/i)
  expect(text.now).toContain('5.00')
  expect(text.scenario).toContain('15.00')
  expect(text.invalidation).toMatch(/at or above.*110.00/i)
  expect(text.next).toMatch(/existing|reference/i)
})
it('labels local targets and never implies a conditional exit has a fixed price objective', () => {
  const r = example()
  r.plan!.targetOrigin = 'local'
  expect(explainStrategy51(r, settings).scenario).toMatch(/local/i)
  r.plan!.target = undefined
  r.plan!.conditionalExit = 'rsi70'
  expect(explainStrategy51(r, settings).scenario).toMatch(/RSI.*70/)
})
it('explains unavailable data and ended references without carrying an active-entry instruction', () => {
  const r = example()
  r.readiness = 'unavailable'
  r.plan = undefined
  r.reason = 'Quote source disconnected'
  expect(explainStrategy51(r, settings).next).toMatch(/verified|source/i)
  expect(explainStrategy51(r, settings).why).toContain('disconnected')
  r.readiness = 'ready'
  r.lastPlan = { ...example().plan!, status: 'target-touched' }
  expect(explainStrategy51(r, settings).why).toMatch(/target.*reached|target.*touched/i)
})
it('has a plain rule explanation for every book ID and formats prices without raw calculation tails', () => {
  for (const d of STRATEGIES_51) expect(STRATEGY51_EXPLANATIONS[d.id]?.length).toBeGreaterThan(25)
  expect(formatStrategy51Price(25286.5973, 0.05)).toBe('25,286.60')
  expect(formatStrategy51Price(0.00085, 0.00001)).toBe('0.00085')
})

it('keeps replay separate from market closure and treats a forming target touch as provisional', () => {
  const r = example()
  r.viewMode = 'history'
  expect(explainStrategy51(r, settings).next).toContain('History/replay review only')
  expect(explainStrategy51(r, settings).next).not.toMatch(/market closed/i)
  r.viewMode = 'live'
  r.readiness = 'ready'
  r.forming = { time, price: 25300 }
  expect(explainStrategy51(r, settings).next).toMatch(/confirmation is pending/)
  expect(r.plan?.status).toBe('active')
})
it('shows source conditional exits beside a local target and names a changed trend', () => {
  const r = example()
  r.plan!.targetOrigin = 'local'
  r.plan!.conditionalExit = 'rsi70'
  r.trend = 'bear'
  const text = explainStrategy51(r, settings)
  expect(text.scenario).toMatch(/Local target.*RSI reaches 70/)
  expect(text.now).toMatch(/trend opposes/)
})
