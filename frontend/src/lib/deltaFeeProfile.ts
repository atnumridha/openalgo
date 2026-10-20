import { type FeeProfile, withProfile } from './cryptoFees'

// One account snapshot only; populated by existing risk reads, with no extra polling.
let snapshot: { scope: string; at: number; profile: FeeProfile } | null = null
export function rememberDeltaFeeProfile(
  scope: string | undefined,
  profile: FeeProfile | undefined
) {
  snapshot = profile
    ? { scope: scope || 'session', at: Date.now(), profile: withProfile(profile) }
    : null
}
export function knownDeltaFeeProfile(scope?: string): FeeProfile | null {
  return snapshot &&
    snapshot.scope === (scope || 'session') &&
    Date.now() - snapshot.at >= 0 &&
    Date.now() - snapshot.at < 20000
    ? snapshot.profile
    : null
}
