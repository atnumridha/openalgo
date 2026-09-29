import type { Leg, Strategy } from '@/types/strategy_module'
import {
  computePayoff,
  payoffPriceRange,
  type PayoffResult,
  type ScenarioState,
  type StrategyLeg,
} from './strategyMath'

const PREVIEW_ATM_TIME_VALUE_STEPS = 1.2
const PREVIEW_TIME_VALUE_WIDTH_STEPS = 3
const PREVIEW_DAYS = 7
const PREVIEW_IV = 18

interface UnderlyingScale {
  spot: number
  step: number
  lotSize: number
}

const UNDERLYING_SCALE: Record<string, UnderlyingScale> = {
  NIFTY: { spot: 25000, step: 50, lotSize: 65 },
  BANKNIFTY: { spot: 55000, step: 100, lotSize: 15 },
  SENSEX: { spot: 81000, step: 100, lotSize: 20 },
  GOLDM: { spot: 145000, step: 500, lotSize: 1 },
  CRUDEOILM: { spot: 9100, step: 50, lotSize: 1 },
  SILVERM: { spot: 230000, step: 1000, lotSize: 1 },
  NATGASMINI: { spot: 300, step: 5, lotSize: 1 },
}

export interface StrategyPayoffPreview {
  legs: StrategyLeg[]
  spot: number
  step: number
  remainingYears: number
  daysAtExpiry: number
  scenario: ScenarioState
  payoff: PayoffResult
}

function scaleFor(underlying: string): UnderlyingScale {
  return UNDERLYING_SCALE[underlying.toUpperCase()] ?? { spot: 10000, step: 50, lotSize: 1 }
}

export function strikeOffsetSteps(atmOffset: string | null | undefined, optionType: 'CE' | 'PE'): number {
  const label = (atmOffset || 'ATM').trim().toUpperCase()
  if (label === 'ATM') return 0
  const match = /^(ITM|OTM)([1-5])$/.exec(label)
  if (!match) return 0
  const steps = Number(match[2])
  const otm = match[1] === 'OTM'
  if (optionType === 'CE') return otm ? steps : -steps
  return otm ? -steps : steps
}

function previewPremium(spot: number, strike: number, optionType: 'CE' | 'PE', step: number): number {
  const intrinsic =
    optionType === 'CE' ? Math.max(0, spot - strike) : Math.max(0, strike - spot)
  const width = PREVIEW_TIME_VALUE_WIDTH_STEPS * step
  const decay = Math.exp(-Math.abs(strike - spot) / width)
  return intrinsic + PREVIEW_ATM_TIME_VALUE_STEPS * step * decay
}

function optionLegs(strategy: Strategy): Leg[] {
  return strategy.legs.filter((leg) => leg.segment === 'options' && (leg.option_type === 'CE' || leg.option_type === 'PE'))
}

export function previewStrategyLegs(strategy: Strategy): StrategyLeg[] {
  const { spot, step, lotSize } = scaleFor(strategy.underlying)
  const expiryTs = Math.floor(Date.now() / 1000) + PREVIEW_DAYS * 24 * 60 * 60
  return optionLegs(strategy).map((leg, index) => {
    const optionType = leg.option_type === 'PE' ? 'PE' : 'CE'
    const strike =
      leg.strike_mode === 'strike' && leg.strike != null && leg.strike > 0
        ? leg.strike
        : spot + strikeOffsetSteps(leg.atm_offset, optionType) * step
    return {
      id: String(leg.id ?? index + 1),
      segment: 'OPTION',
      side: leg.position === 'S' ? 'SELL' : 'BUY',
      lots: Math.max(1, leg.lots ?? 1),
      lotSize,
      expiry: '07OCT26',
      strike,
      optionType,
      price: previewPremium(spot, strike, optionType, step),
      iv: PREVIEW_IV,
      active: true,
      symbol: `${strategy.underlying}${strike}${optionType}`,
      expiryTs,
    }
  })
}

export function strategyPayoffPreview(strategy: Strategy, now: Date = new Date()): StrategyPayoffPreview | null {
  const legs = previewStrategyLegs(strategy)
  if (legs.length === 0) return null
  const { spot } = scaleFor(strategy.underlying)
  const remainingYears = PREVIEW_DAYS / 365
  const range = payoffPriceRange(spot, legs, PREVIEW_IV, remainingYears)
  const payoff = computePayoff(legs, spot, PREVIEW_DAYS, 0, range, 240, 0, PREVIEW_IV, now)
  return {
    legs,
    spot,
    step: scaleFor(strategy.underlying).step,
    remainingYears,
    daysAtExpiry: PREVIEW_DAYS,
    scenario: { spot, iv: PREVIEW_IV, daysElapsed: 0, valuationTime: now },
    payoff,
  }
}
