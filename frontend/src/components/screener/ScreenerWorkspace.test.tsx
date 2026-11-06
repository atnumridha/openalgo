import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RuleBuilder } from './RuleBuilder'
import { ResultsTable, csvRows } from './ResultsTable'
import { makePresets } from './presets'
import type { ScanRow } from './model'
vi.mock('./chartTarget', () => ({
  chartTargetUrl: (r: { symbol: string }) => `/trading?symbol=${r.symbol}`,
}))
describe('screener editing and results', () => {
  it('edits ALL/ANY and previous bar operands through visible controls', () => {
    const definition = makePresets()[0],
      change = vi.fn()
    render(<RuleBuilder rule={definition.rule} onChange={change} />)
    fireEvent.change(screen.getByLabelText('Group logic'), { target: { value: 'any' } })
    expect(change.mock.calls[0][0].op).toBe('any')
    fireEvent.change(screen.getByLabelText('Left bar'), { target: { value: '1' } })
    expect(change.mock.calls[1][0].children[0].left.offset).toBe(1)
  })
  it('escapes CSV values and presents exact chart links', () => {
    const row: ScanRow = {
      symbol: 'A,"B',
      exchange: 'NSE',
      state: 'match',
      fresh: true,
      time: 10,
      observedAt: 20,
      source: 'Stored',
      reason: 'a,b',
      direction: 'MATCH',
      values: { close: 100 },
    }
    expect(csvRows([row], ['symbol', 'reason'])).toContain('"A,""B","a,b"')
    render(
      <ResultsTable rows={[row]} definition={makePresets()[0]} watchlists={[]} onAdd={vi.fn()} />
    )
    expect(screen.getByRole('link', { name: 'Open chart' })).toHaveAttribute(
      'href',
      '/trading?symbol=A,"B'
    )
    expect(screen.getByText('1 matching')).toBeInTheDocument()
  })
})
it('exports signed session price change and explicit stale coverage', () => {
  const row: ScanRow = {
    symbol: 'ABC',
    exchange: 'NSE',
    state: 'match',
    fresh: false,
    time: 10,
    observedAt: 20,
    source: 'Stored',
    reason: 'Rule',
    direction: 'MATCH',
    values: { close: 110, session_change_pct: 10 },
  }
  expect(csvRows([row], ['session_change', 'freshness'])).toContain('"10","Stale snapshot"')
})
