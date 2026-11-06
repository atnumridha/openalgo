import { expect, it, vi } from 'vitest'
import { relatedPatternMarkers } from './RelatedPatternLayer'
import type { Bar } from './model'
vi.mock('./archiveCandlesA', () => ({ recognizeArchiveCandlesA: () => [] }))
vi.mock('./archiveCandlesB', () => ({ recognizeArchiveCandlesB: () => [] }))
vi.mock('./archiveInstitutionalPatterns', () => ({ recognizeInstitutionalPatterns: () => [] }))
vi.mock('./archiveChartPatterns', () => ({
  recognizeArchiveChartPatterns: () => [],
  parabolicSAR: () => [],
}))
vi.mock('./extendedCandlePatterns', () => ({
  recognizeExtendedCandles: (bars: Bar[]) => [
    { side: 'CALL', name: `Hammer ${bars.length}`, pattern: 'hammer', extreme: 90 },
    { side: 'NEUTRAL', name: 'Doji', pattern: 'doji', extreme: 100 },
  ],
}))
vi.mock('./chartShapePatterns', () => ({
  recognizeChartShapes: () => [
    { side: 'PUT', name: 'Double Top', pattern: 'double-top', extreme: 110 },
  ],
}))
const bars: Bar[] = [0, 60, 120, 600].map((time) => ({
  time,
  open: 100,
  high: 110,
  low: 90,
  close: 101,
  volume: 1,
}))
it('separates choices and uses simple colored labels', () => {
  const markers = relatedPatternMarkers(bars, 'candles', 60, 0, 600)
  expect(markers[0]).toMatchObject({ text: 'Hammer 1', textColor: '#34d399' })
  expect(markers[1]).toMatchObject({ text: 'Doji', textColor: '#cbd5e1' })
  expect(markers.some((m) => m.text.includes('Double'))).toBe(false)
  expect(relatedPatternMarkers(bars, 'shapes', 60, 0, 600)[0]).toMatchObject({
    text: 'Double Top',
    textColor: '#f87171',
  })
})
it('uses prior bars only, resets gaps and respects visible times', () => {
  const markers = relatedPatternMarkers(bars, 'candles', 60, 120, 600)
  expect(markers.filter((m) => m.textColor === '#34d399').map((m) => m.text)).toEqual([
    'Hammer 3',
    'Hammer 1',
  ])
  expect(markers.map((m) => m.time)).toEqual([120, 120, 600, 600])
  expect(relatedPatternMarkers(bars, 'off', 60, 0, 600)).toEqual([])
})
it('does not stack repeated names and confirmation stages on the same candle', async () => {
  const { markersForArchiveEvents } = await import('./RelatedPatternLayer')
  const match = {
    time: 60,
    side: 'CALL' as const,
    name: 'Bullish Marubozu',
    pattern: 'extended-marubozu',
    extreme: 90,
    confirmed: false,
  }
  const events = [
    match,
    {
      ...match,
      name: 'Marubozu confirmed',
      pattern: 'confirmed-extended-marubozu',
      confirmed: true,
    },
    {
      ...match,
      name: 'Marubozu confirmed at demand',
      pattern: 'zone-extended-marubozu',
      confirmed: true,
    },
    {
      ...match,
      name: 'Engulfing confirmed',
      pattern: 'confirmed-guide-engulfing',
      confirmed: true,
    },
  ]
  expect(markersForArchiveEvents(events, bars, 0, 600, false)).toEqual([
    expect.objectContaining({
      time: 60,
      text: 'Marubozu confirmed at demand',
      textColor: '#34d399',
      pointer: true,
    }),
  ])
  const opposite = {
    ...match,
    side: 'PUT' as const,
    name: 'Shooting Star confirmed',
    confirmed: true,
  }
  expect(
    markersForArchiveEvents([...events, opposite], bars, 0, 600, false).map((m) => m.textColor)
  ).toEqual(['#34d399', '#f87171'])
})
it('keeps labels clear of nearby candle wicks while pointing to their own candle', async () => {
  const { markersForArchiveEvents } = await import('./RelatedPatternLayer')
  const nearby = bars.map((b, i) => ({ ...b, high: i === 2 ? 150 : 110, low: i === 2 ? 50 : 90 }))
  const markers = markersForArchiveEvents(
    [
      {
        time: 60,
        side: 'CALL',
        name: 'Hammer confirmed',
        pattern: 'hammer',
        extreme: 90,
        confirmed: true,
      },
      {
        time: 60,
        side: 'PUT',
        name: 'Shooting Star confirmed',
        pattern: 'star',
        extreme: 110,
        confirmed: true,
      },
    ],
    nearby,
    0,
    600
  )
  expect(markers.find((m) => !m.above)).toMatchObject({
    price: 90,
    labelPrice: 50,
    tooltip: expect.stringContaining('Price may rise'),
  })
  expect(markers.find((m) => m.above)).toMatchObject({
    price: 110,
    labelPrice: 150,
    tooltip: expect.stringContaining('Price may fall'),
  })
})
