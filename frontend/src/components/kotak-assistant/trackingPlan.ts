import { automaticStop, rewardTarget } from './model'
import type { TrackingTrade } from './trackingStore'

export function trackingPlan(row: TrackingTrade) {
  const tick = row.tick && row.tick > 0 ? row.tick : 0.05
  const savedStop = Number.isFinite(row.sl) && row.sl! > 0 && row.sl! < row.entry
  const sl = savedStop ? row.sl! : automaticStop(row.entry, tick)
  const savedTarget = Number.isFinite(row.target) && row.target! > row.entry
  const ratio =
    row.reward_ratio && row.reward_ratio > 0
      ? row.reward_ratio
      : savedTarget && sl
        ? (row.target! - row.entry) / (row.entry - sl)
        : 2
  const target = savedTarget ? row.target! : sl ? rewardTarget(row.entry, sl, ratio, tick) : null
  return {
    tick,
    sl,
    target,
    ratio,
    automatic: row.automatic_sl ?? !savedStop,
    restoredDefault: !savedStop || !savedTarget,
  }
}

export function correctTrackingEntry(row: TrackingTrade, entry: number): TrackingTrade {
  const plan = trackingPlan(row)
  const sl = plan.automatic ? automaticStop(entry, plan.tick) : plan.sl
  const target = sl ? rewardTarget(entry, sl, plan.ratio, plan.tick) : null
  if (!sl || !target) throw new Error('Entry must remain above the tracked SL')
  return {
    ...row,
    entry,
    sl,
    target,
    tick: plan.tick,
    reward_ratio: plan.ratio,
    automatic_sl: plan.automatic,
  }
}
