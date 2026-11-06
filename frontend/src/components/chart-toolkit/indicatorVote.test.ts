import { expect, it } from 'vitest'
import { indicatorVote } from './indicatorVote'

it('picks the largest independent CALL count, with equal weight per indicator', () => {
  expect(
    indicatorVote(['CALL', 'CALL', 'CALL', 'CALL', 'PUT', 'PUT', 'PUT', 'WAIT', 'WAIT'])
  ).toEqual({ side: 'CALL', call: 4, put: 3, wait: 2, total: 9, tied: false })
})
it('picks PUT and WAIT when their respective counts are largest', () => {
  expect(indicatorVote(['PUT', 'PUT', 'CALL', 'WAIT']).side).toBe('PUT')
  expect(indicatorVote(['WAIT', 'WAIT', 'CALL', 'PUT']).side).toBe('WAIT')
})
it('returns WAIT for ties and absent readings', () => {
  expect(indicatorVote(['CALL', 'PUT', 'WAIT'])).toMatchObject({ side: 'WAIT', tied: true })
  expect(indicatorVote(['CALL', 'CALL', 'PUT', 'PUT', 'WAIT'])).toMatchObject({
    side: 'WAIT',
    tied: true,
  })
  expect(indicatorVote([])).toMatchObject({ side: 'WAIT', total: 0 })
})
