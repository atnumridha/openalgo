import type { StrategySummary } from '@/types/strategy_module'

// Frozen historical reference, 27 September 2026. Source:
// data/research/strategy-ranking-2026-09-27-final/ranking.json (nonduplicate cells).
// 15-minute variants; positive net option outcomes under modeled base costs.
// These are research observations, not live results or a replay of current risk rules.
const evidence: Partial<Record<NonNullable<StrategySummary['scalp_profile']>, {
  wins: number; trades: number; variant: string
}>> = {
  "ema915": {
    "wins": 102,
    "trades": 219,
    "variant": "ema915-r2-hold15"
  },
  "regime50200": {
    "wins": 13,
    "trades": 28,
    "variant": "timing_50_200-hold15"
  },
  "macd200": {
    "wins": 26,
    "trades": 58,
    "variant": "macd-r2-hold15"
  },
  "box15": {
    "wins": 71,
    "trades": 173,
    "variant": "box-1m-hold15"
  },
  "ema5": {
    "wins": 375,
    "trades": 915,
    "variant": "ema5-r2-hold15"
  }
}

export function strategyResearch(profile: StrategySummary['scalp_profile']) {
  const result = profile ? evidence[profile] : undefined
  return result ? { ...result, winPercent: result.wins / result.trades * 100 } : undefined
}

export function orderByResearchWinRate<T extends Pick<StrategySummary, 'scalp_profile'>>(rows: readonly T[]): T[] {
  // Unknown rates sort last; equal rates preserve the original order.
  return [...rows].sort((a, b) =>
    (strategyResearch(b.scalp_profile)?.winPercent ?? -1) -
    (strategyResearch(a.scalp_profile)?.winPercent ?? -1)
  )
}
