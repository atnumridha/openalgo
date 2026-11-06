import { expect, it } from 'vitest'
import {
  SOURCE_STRATEGIES,
  strategyCompatibility,
  optionChartReference,
  proposedFutureTrigger,
  strategyStorageKey,
  readStrategyConfiguration,
  saveStrategyConfiguration,
  proposedOptionLegs,
  optionStructurePreview,
  strategyReferenceLevels,
  type StrategyConfiguration,
} from './chartStrategyConfigurations'
it('keeps source option contracts unresolved', () => {
  expect(SOURCE_STRATEGIES).toHaveLength(7)
  for (const source of SOURCE_STRATEGIES.slice(0, 5))
    expect(source.unconfigured).toEqual(
      expect.arrayContaining([
        'Listed expiry',
        'Exact contracts and ratios',
        'Entry and exit rules',
      ])
    )
})
it('rejects unrelated and option premium charts', () => {
  for (const symbol of ['BTCUSD', 'RELIANCE', 'NIFTY03NOV2623000CE', 'NIFTYNXT50'])
    expect(strategyCompatibility(SOURCE_STRATEGIES[0], symbol, 'NFO').compatible).toBe(false)
  expect(strategyCompatibility(SOURCE_STRATEGIES[5], 'NIFTY', 'NSE_INDEX').kind).toBe(
    'index-context'
  )
  expect(strategyCompatibility(SOURCE_STRATEGIES[6], 'NIFTY24NOV26FUT', 'NFO').compatible).toBe(
    false
  )
  expect(strategyCompatibility(SOURCE_STRATEGIES[6], 'BANKNIFTY24NOV26FUT', 'NFO').compatible).toBe(
    true
  )
})
it('requires matching future price units, direction and tick geometry', () => {
  const base = {
    strategy: SOURCE_STRATEGIES[5],
    symbol: 'NIFTY24NOV26FUT',
    exchange: 'NFO',
    entry: 24000,
    direction: 'long' as const,
    tickSize: 0.05,
  }
  expect(proposedFutureTrigger(base)).toBe(23800)
  expect(proposedFutureTrigger({ ...base, direction: 'short' })).toBe(24200)
  for (const patch of [
    { symbol: 'NIFTY', exchange: 'NSE_INDEX' },
    { tickSize: undefined },
    { tickSize: 0 },
    { tickSize: 0.3 },
    { entry: 24000.01 },
    { entry: 0 },
    { entry: NaN },
    { strategy: SOURCE_STRATEGIES[0] },
  ])
    expect(proposedFutureTrigger({ ...base, ...patch })).toBeNull()
})
it('persists isolated owner, broker, mode and chart scopes; rejects old research IDs', () => {
  const scope = {
    owner: 'alice',
    broker: 'fyers',
    appMode: 'live',
    symbol: 'NIFTY',
    exchange: 'NSE_INDEX',
    interval: '5m',
  }
  const key = strategyStorageKey(scope)!
  const memory = new Map<string, string>()
  const storage = {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => {
      memory.set(key, value)
    },
  }
  saveStrategyConfiguration(storage, key, {
    selectedId: 'A-01',
    entry: '',
    direction: '',
    notes: 'My proposal',
  })
  expect(readStrategyConfiguration(storage, key).selectedId).toBe('A-01')
  for (const patch of [
    { owner: 'bob' },
    { broker: 'other' },
    { appMode: 'analyzer' },
    { symbol: 'BANKNIFTY' },
    { exchange: 'NFO' },
    { interval: '15m' },
  ])
    expect(
      readStrategyConfiguration(storage, strategyStorageKey({ ...scope, ...patch })).selectedId
    ).toBe('')
  expect(strategyStorageKey({ ...scope, owner: undefined })).toBeNull()
  for (const invalid of ['{broken', '{"selectedId":"ema_cross_5m","entry":"23000"}']) {
    memory.set(key, invalid)
    expect(readStrategyConfiguration(storage, key).selectedId).toBe('')
  }
})

const optionConfig = (id = 'A-01'): StrategyConfiguration => ({
  selectedId: id,
  entry: '',
  direction: '',
  notes: '',
  anchor: '24000',
  legs: proposedOptionLegs(id),
})
it('provides editable proposed structures with blank premiums and independent leg objects', () => {
  expect(proposedOptionLegs('A-01')).toEqual([
    { optionType: 'PE', offset: '0', quantity: '-1', premium: '' },
    { optionType: 'PE', offset: '-200', quantity: '1', premium: '' },
  ])
  expect(proposedOptionLegs('A-02').map((leg) => [leg.offset, leg.quantity])).toEqual([
    ['-200', '1'],
    ['0', '-2'],
    ['300', '1'],
  ])
  expect(proposedOptionLegs('A-03').map((leg) => [leg.offset, leg.quantity])).toEqual([
    ['0', '1'],
    ['200', '-2'],
    ['400', '1'],
  ])
  expect(proposedOptionLegs('A-04')[2].quantity).toBe('2')
  expect(proposedOptionLegs('A-05').map((leg) => leg.quantity)).toEqual(['-1', '2'])
  for (const id of ['A-01', 'A-02', 'A-03', 'A-04', 'A-05'])
    expect(proposedOptionLegs(id).every((leg) => leg.premium === '')).toBe(true)
  const changed = proposedOptionLegs('A-01')
  changed[0].quantity = '9'
  expect(proposedOptionLegs('A-01')[0].quantity).toBe('-1')
  expect(proposedOptionLegs('A-06')).toEqual([])
  expect(proposedOptionLegs('ema_cross_5m')).toEqual([])
})
it('computes hand-checked spread intrinsic and subtracts premiums only when every premium is explicit', () => {
  const config = optionConfig()
  const raw = optionStructurePreview(SOURCE_STRATEGIES[0], config)
  expect(raw.includesPremiums).toBe(false)
  expect(raw.points.find((p) => p.price === 23800)?.value).toBe(-200)
  expect(raw.points.find((p) => p.price === 24000)?.value).toBe(0)
  expect(raw.reason).toMatch(/intrinsic/i)
  const legs = config.legs!.map((leg, i) => ({ ...leg, premium: i === 0 ? '100' : '40' }))
  const net = optionStructurePreview(SOURCE_STRATEGIES[0], { ...config, legs })
  expect(net.includesPremiums).toBe(true)
  expect(net.points.find((p) => p.price === 23800)?.value).toBe(-140)
  expect(net.points.find((p) => p.price === 24000)?.value).toBe(60)
  for (const premium of ['', ' ', 'abc', '-1', 'Infinity']) {
    const incomplete = optionStructurePreview(SOURCE_STRATEGIES[0], {
      ...config,
      legs: legs.map((leg, i) => ({ ...leg, premium: i === 0 ? premium : leg.premium })),
    })
    expect(incomplete.includesPremiums).toBe(false)
    expect(incomplete.points.find((p) => p.price === 24000)?.value).toBe(0)
  }
  const zero = optionStructurePreview(SOURCE_STRATEGIES[0], {
    ...config,
    legs: legs.map((leg) => ({ ...leg, premium: '0' })),
  })
  expect(zero.includesPremiums).toBe(true)
})
it('computes ratio tails and mirrors CE exposure correctly into PE exposure', () => {
  const config = optionConfig('A-05')
  const call = optionStructurePreview(SOURCE_STRATEGIES[4], config)
  expect(call.points.find((p) => p.price === 24200)?.value).toBe(-200)
  expect(call.points.find((p) => p.price === 24400)?.value).toBe(0)
  const put = optionStructurePreview(SOURCE_STRATEGIES[4], {
    ...config,
    legs: config.legs!.map((leg) => ({
      ...leg,
      optionType: 'PE',
      offset: String(-Number(leg.offset)),
    })),
  })
  expect(put.points.find((p) => p.price === 23800)?.value).toBe(-200)
  expect(put.points.find((p) => p.price === 23600)?.value).toBe(0)
  const ladder = optionStructurePreview(SOURCE_STRATEGIES[2], optionConfig('A-03'))
  expect(ladder.points.find((p) => p.price === 24200)?.value).toBe(200)
  expect(ladder.points.find((p) => p.price === 24800)?.value).toBe(0)
  const plus = optionStructurePreview(SOURCE_STRATEGIES[3], optionConfig('A-04'))
  expect(plus.points.find((p) => p.price === 24800)?.value).toBe(400)
  expect(plus.points.length).toBeLessThanOrEqual(81)
  expect(
    plus.points.every(
      (p, i, a) => Number.isFinite(p.value) && p.price > 0 && (i === 0 || p.price > a[i - 1].price)
    )
  ).toBe(true)
})
it('rejects absent anchors and malformed leg geometry instead of filling working legs', () => {
  const config = optionConfig()
  const invalid = [
    { anchor: '' },
    { anchor: '0' },
    { anchor: 'Infinity' },
    { legs: undefined },
    { legs: [] },
    { legs: Array(7).fill(config.legs![0]) },
    ...['0', '1.5', '11', '-11', 'abc'].map((quantity) => ({
      legs: [{ ...config.legs![0], quantity }],
    })),
    { legs: [{ ...config.legs![0], offset: '' }] },
    { legs: [{ ...config.legs![0], offset: '-24000' }] },
    { legs: [{ ...config.legs![0], offset: 'NaN' }] },
  ]
  for (const patch of invalid) {
    const result = optionStructurePreview(SOURCE_STRATEGIES[0], { ...config, ...patch })
    expect(result.points).toEqual([])
    expect(result.strikes).toEqual([])
    expect(result.reason.length).toBeGreaterThan(0)
  }
  expect(optionStructurePreview(SOURCE_STRATEGIES[5], config).points).toEqual([])
})
it('returns price guides only in compatible instrument units and guards futures references', () => {
  const strategy = SOURCE_STRATEGIES[0],
    configuration = optionConfig()
  const guides = strategyReferenceLevels({
    strategy,
    configuration,
    symbol: 'NIFTY',
    exchange: 'NSE_INDEX',
  })
  expect(guides.map((line) => line.price)).toEqual([24000, 23800])
  expect(guides.every((line) => line.title.includes('Proposed') && line.color)).toBe(true)
  for (const [symbol, exchange] of [
    ['BTCUSD', 'DELTA'],
    ['BANKNIFTY', 'NSE_INDEX'],
    ['NIFTY03NOV2623000PE', 'NFO'],
  ])
    expect(strategyReferenceLevels({ strategy, configuration, symbol, exchange })).toEqual([])
  const future = {
    strategy: SOURCE_STRATEGIES[5],
    configuration: {
      ...configuration,
      selectedId: 'A-06',
      entry: '24000',
      direction: 'long' as const,
    },
    symbol: 'NIFTY24NOV26FUT',
    exchange: 'NFO',
    tickSize: 0.05,
  }
  expect(strategyReferenceLevels(future).map((line) => [line.price, line.title])).toEqual([
    [24000, 'Entry reference'],
    [23800, '200-point stop reference'],
  ])
  expect(
    strategyReferenceLevels({
      ...future,
      configuration: { ...future.configuration, direction: 'short' },
    }).map((line) => line.price)
  ).toEqual([24000, 24200])
  for (const patch of [
    { tickSize: undefined },
    { tickSize: 0.3 },
    { symbol: 'NIFTY', exchange: 'NSE_INDEX' },
    { symbol: 'BANKNIFTY24NOV26FUT' },
    { configuration: { ...future.configuration, entry: '' } },
    { configuration: { ...future.configuration, direction: '' as const } },
  ])
    expect(strategyReferenceLevels({ ...future, ...patch })).toEqual([])
})
it('migrates legacy drafts and safely retains bounded optional draft fields', () => {
  const base = { selectedId: 'A-01', entry: '', direction: '', notes: 'old' }
  const read = (data: unknown) =>
    readStrategyConfiguration({ getItem: () => JSON.stringify(data) }, 'test')
  expect(read(base)).toEqual(base)
  const valid = {
    ...base,
    anchor: '24000',
    expiry: 'user proposed expiry',
    legs: proposedOptionLegs('A-01'),
  }
  expect(read(valid)).toEqual(valid)
  const malformed = read({
    ...base,
    anchor: 20,
    expiry: [],
    legs: [{ optionType: 'XX', quantity: '1', offset: '0', premium: '' }],
  })
  expect(malformed).toEqual(base)
  expect(read({ ...base, legs: Array(7).fill(valid.legs[0]) })).toEqual(base)
  expect(read({ ...base, anchor: '9'.repeat(41), expiry: 'x'.repeat(81) })).toEqual(base)
})

it('resolves only matching NFO options to an underlying strike and listed expiry context', () => {
  expect(optionChartReference(SOURCE_STRATEGIES[0], 'NIFTY03NOV2623050CE', 'NFO')).toEqual({
    strike: 23050,
    expiry: '03NOV26',
  })
  expect(optionChartReference(SOURCE_STRATEGIES[0], 'NIFTY03NOV2623050PE', 'NFO')).toEqual({
    strike: 23050,
    expiry: '03NOV26',
  })
  for (const [symbol, exchange] of [
    ['BANKNIFTY03NOV2645000CE', 'NFO'],
    ['NIFTY03NOV2623050CE', 'NSE'],
    ['BTCUSD', 'DELTA'],
    ['NIFTY99ABC2623050CE', 'NFO'],
  ])
    expect(optionChartReference(SOURCE_STRATEGIES[0], symbol, exchange)).toBeNull()
  expect(optionChartReference(SOURCE_STRATEGIES[5], 'NIFTY03NOV2623050CE', 'NFO')).toBeNull()
  expect(
    strategyReferenceLevels({
      strategy: SOURCE_STRATEGIES[0],
      configuration: optionConfig(),
      symbol: 'NIFTY03NOV2623050CE',
      exchange: 'NFO',
    })
  ).toEqual([])
})
