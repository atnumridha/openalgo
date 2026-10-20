import { describe, expect, it } from 'vitest'
import { executionStage, parseExecutionLog } from './strategyExecution'

const line = (value: unknown) => JSON.stringify(value)

describe('strategy execution evidence', () => {
  it('does not turn activation or a suggested LONG plan into an executed trade', () => {
    const report = parseExecutionLog(
      [
        line({
          mode: 'live',
          ready: true,
          status: 'Live activation accepted; checking account and trade risk',
        }),
        line({
          mode: 'live',
          status: 'monitoring',
          execution_enabled: false,
          entry_wait: ['Auto top-up is ON'],
          position: null,
          decision: { action: 'LONG', reason: 'Agreement', selected_plan: { quantity: 1 } },
          daily: { net: '0' },
        }),
      ].join('\n')
    )!
    expect(executionStage(report)).toBe('Monitoring only')
    expect(report.position).toBeNull()
    expect(report.reasons).toEqual(['Auto top-up is ON'])
    expect(report.dailyNet).toBe(0)
  })

  it('distinguishes pending, partial fills and fully filled entries', () => {
    const position = {
      entry_id: 123,
      qty: 2,
      filled: 0,
      open_qty: 0,
      entry_open: true,
      side: 'buy',
    }
    const report = (p: object) =>
      parseExecutionLog(
        line({ mode: 'live', status: 'running', execution_enabled: true, position: p })
      )!
    expect(executionStage(report(position))).toBe('Entry pending · no fill')
    expect(executionStage(report({ ...position, filled: 1, open_qty: 1 }))).toBe(
      'Partially filled · position open'
    )
    expect(executionStage(report({ ...position, filled: 2, open_qty: 2 }))).toBe(
      'Trade executed · position open'
    )
    expect(executionStage(report({ ...position, filled: 2, open_qty: 0, entry_open: false }))).toBe(
      'Position closed · reconciling'
    )
  })

  it('does not inherit a position or enabled flag across mode changes and errors', () => {
    const report = parseExecutionLog(
      [
        line({
          mode: 'live',
          execution_enabled: true,
          position: { filled: 1, open_qty: 1, qty: 1 },
        }),
        line({ mode: 'paper', status: 'started' }),
        line({
          mode: 'paper',
          status: 'public data unavailable; entries suspended',
          error_type: 'HTTPError',
        }),
      ].join('\n')
    )!
    expect(report.mode).toBe('paper')
    expect(report.position).toBeNull()
    expect(report.executionEnabled).toBeNull()
    expect(executionStage(report)).toBe('Entries paused')
  })

  it('retains unresolved exposure on error and keeps paper fills explicitly simulated', () => {
    const live = parseExecutionLog(
      [
        line({
          mode: 'live',
          execution_enabled: true,
          position: { filled: 1, open_qty: 1, qty: 1 },
        }),
        line({
          mode: 'live',
          status: 'entries paused; exchange protection retained',
          error_type: 'ExchangeError',
        }),
      ].join('\n')
    )!
    expect(executionStage(live)).toBe('Entries paused · check exposure')
    expect(live.executionEnabled).toBeNull()
    const paper = parseExecutionLog(
      line({ mode: 'paper', status: 'scanning', position: { side: -1, quantity: 2, entry: 83000 } })
    )!
    expect(executionStage(paper)).toBe('Simulated position open')
    expect(paper.position?.side).toBe('SHORT')
  })

  it('handles stop reports, missing/malformed logs and refuses non-finite financial values', () => {
    expect(parseExecutionLog('traceback\n{"mode":')).toBeNull()
    const report = parseExecutionLog(
      [
        line({ mode: 'live', ready: true }),
        line({
          mode: 'live',
          status: 'stopped',
          position: null,
          unresolved_intents: 0,
          daily: { net: 'Infinity' },
        }),
      ].join('\n')
    )!
    expect(executionStage(report)).toBe('Stopped')
    expect(report.dailyNet).toBeNull()
    expect(report.positionKnown).toBe(true)
  })
})
