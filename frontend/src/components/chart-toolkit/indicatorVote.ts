import type { TradeSide } from './nineIndicators'

export function indicatorVote(sides: readonly TradeSide[]) {
  const call = sides.filter((side) => side === 'CALL').length
  const put = sides.filter((side) => side === 'PUT').length
  const wait = sides.filter((side) => side === 'WAIT').length
  const max = Math.max(call, put, wait)
  const tied = [call, put, wait].filter((count) => count === max).length > 1
  const side: TradeSide =
    !sides.length || tied || wait === max ? 'WAIT' : call === max ? 'CALL' : 'PUT'
  return { side, call, put, wait, total: sides.length, tied }
}
