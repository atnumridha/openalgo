import { describe, it, expect } from 'vitest'
import { PremiumAlertMonitor } from './premiumAlerts'
const rule = { id: 'a', label: 'Support', price: 100, enabled: true, fired: false }
describe('repeating premium quote alerts', () => {
  it('sounds on every new touch but not while price stays at the level', () => {
    const m = new PremiumAlertMonitor()
    const update = (price: number, time: number) => m.update([rule], { price, time }, time, true)
    expect(update(105, 1000)).toEqual([])
    expect(update(100, 2000)).toEqual(['a'])
    expect(update(100, 3000)).toEqual([])
    expect(update(101, 4000)).toEqual([])
    expect(update(100, 5000)).toEqual(['a'])
    expect(update(99, 6000)).toEqual([])
    expect(update(100, 7000)).toEqual(['a'])
  })
  it('repeats crossings in either direction, including jumps across the level', () => {
    const m = new PremiumAlertMonitor()
    m.update([rule], { price: 105, time: 1000 }, 1000, true)
    expect(m.update([rule], { price: 99, time: 2000 }, 2000, true)).toEqual(['a'])
    expect(m.update([rule], { price: 101, time: 3000 }, 3000, true)).toEqual(['a'])
    expect(m.update([rule], { price: 99, time: 4000 }, 4000, true)).toEqual(['a'])
  })
  it('rearms saved alerts that previously fired and tracks levels independently', () => {
    const m = new PremiumAlertMonitor()
    const rules = [{ ...rule, fired: true }, { ...rule, id: 'b', price: 102 }]
    m.update(rules, { price: 105, time: 1000 }, 1000, true)
    expect(m.update(rules, { price: 101, time: 2000 }, 2000, true)).toEqual(['b'])
    expect(m.update(rules, { price: 99, time: 3000 }, 3000, true)).toEqual(['a'])
    expect(m.update(rules, { price: 105, time: 4000 }, 4000, true)).toEqual(['a', 'b'])
  })
  it('does not backfill new levels or trigger on stale, replay, duplicate, out-of-order or disconnected observations', () => {
    const m = new PremiumAlertMonitor()
    m.update([rule], { price: 105, time: 100000 }, 100000, true)
    expect(m.update([rule], { price: 99, time: 99000 }, 100001, true)).toEqual([])
    expect(m.update([rule], { price: 99, time: 100000 }, 100002, true)).toEqual([])
    expect(m.update([rule], { price: 99, time: 101000 }, 130000, true)).toEqual([])
    expect(m.update([rule], { price: 99, time: 131000 }, 131000, true)).toEqual([])
    expect(m.update([rule], { price: 105, time: 132000 }, 132000, false)).toEqual([])
    expect(m.update([rule], { price: 105, time: 133000 }, 133000, true)).toEqual([])
    expect(m.update([rule, { ...rule, id: 'new', price: 102 }], { price: 101, time: 134000 }, 134000, true)).toEqual([])
    expect(m.update([{ ...rule, enabled: false }], { price: 99, time: 135000 }, 135000, true)).toEqual([])
    expect(m.update([rule], { price: 99, time: 136000 }, 136000, true)).toEqual([])
    expect(m.update([rule], { price: 105, time: 160000 }, 160000, true)).toEqual([])
  })
  it('ignores invalid quotes and resets the baseline after editing a level', () => {
    const m = new PremiumAlertMonitor()
    expect(m.update([rule], { price: NaN, time: 1 }, 1, true)).toEqual([])
    expect(m.update([rule], { price: 99, time: 10000 }, 4, true)).toEqual([])
    m.update([rule], { price: 105, time: 1000 }, 1000, true)
    expect(m.update([{ ...rule, price: 106 }], { price: 104, time: 2000 }, 2000, true)).toEqual([])
    m.reset('a')
    expect(m.update([rule], { price: 99, time: 3000 }, 3000, true)).toEqual([])
  })
})
