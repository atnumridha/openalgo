import type { BookInstrument, BookRisk, BookSettings, BookSide } from './types'
import { finite } from './math'
export function calculateBookRisk(
  plan: { entry: number; stop: number; target: number; side: BookSide },
  settings: Pick<
    BookSettings,
    'equity' | 'riskPercent' | 'fixedCost' | 'perUnitCost' | 'slippagePrice'
  >,
  instrument?: BookInstrument
): BookRisk {
  const distance = Math.abs(plan.entry - plan.stop),
    reward = plan.side === 'long' ? plan.target - plan.entry : plan.entry - plan.target
  const r: BookRisk = {
    priceRisk: distance,
    priceReward: reward,
    rr: reward / distance,
    unavailableReasons: [],
    notes: [
      'Affordability, margin and existing portfolio exposure have not been established.',
      'Quantity uses the selected explicit unit definition; lot size is presentation only.',
    ],
  }
  const reasons = r.unavailableReasons
  if (
    [plan.entry, plan.stop, plan.target].some((price) => !finite(price) || price <= 0) ||
    !finite(distance) ||
    distance <= 0 ||
    !finite(reward) ||
    reward <= 0 ||
    (plan.side === 'long' ? plan.stop >= plan.entry : plan.stop <= plan.entry)
  )
    reasons.push('Invalid price-level geometry')
  if (!finite(settings.equity) || settings.equity <= 0) reasons.push('Account equity is unset')
  if (!finite(settings.riskPercent) || settings.riskPercent <= 0)
    reasons.push('Risk percent must be positive')
  if (!instrument) reasons.push('Validated instrument units are unavailable')
  if (
    !instrument ||
    !['underlying', 'contract', 'option-premium'].includes(instrument.unitDefinition)
  )
    reasons.push('Explicit linear product unit definition is unavailable')
  if (instrument && instrument.kind !== 'linear')
    reasons.push(
      'Inverse, nonlinear or untradable index products do not support linear monetary sizing'
    )
  if (instrument?.unitDefinition === 'option-premium' && instrument.chartPriceKind !== 'premium')
    reasons.push('Option sizing requires this option premium chart')
  if (!instrument?.accountCurrency) reasons.push('Account currency is unavailable')
  if (!instrument?.quoteCurrency) reasons.push('Quote currency is unavailable')
  const x =
    instrument?.accountCurrency &&
    instrument.quoteCurrency &&
    instrument.accountCurrency === instrument.quoteCurrency
      ? 1
      : instrument?.conversionRate
  if (!finite(x) || x <= 0) reasons.push('Required currency conversion is unavailable')
  const v = instrument?.valuePerPriceUnit,
    step = instrument?.quantityStep
  if (!finite(v) || v <= 0) reasons.push('Verified value per price unit is unavailable')
  if (!finite(step) || step <= 0) reasons.push('Quantity step is unavailable')
  if (
    [settings.fixedCost, settings.perUnitCost, settings.slippagePrice].some(
      (n) => !finite(n) || n < 0
    )
  )
    reasons.push('Costs and slippage must be nonnegative and finite')
  if (reasons.length) return r
  const budget = (settings.equity * settings.riskPercent) / 100 - settings.fixedCost
  r.budget = budget
  if (budget <= 0) {
    reasons.push('Costs exhaust the risk budget')
    return r
  }
  const lossPerUnit = (distance + settings.slippagePrice) * v! * x! + settings.perUnitCost
  r.lossPerUnit = lossPerUnit
  const quantity = Number(
    (Math.floor(budget / (lossPerUnit * step!) + 1e-12) * step!).toPrecision(14)
  )
  if (quantity < step!) {
    reasons.push('Risk budget cannot fund one quantity step')
    return r
  }
  r.quantity = quantity
  if (finite(instrument?.lotSize) && instrument.lotSize > 0) r.lots = quantity / instrument.lotSize
  r.estimatedRiskCash = quantity * lossPerUnit + settings.fixedCost
  r.estimatedRewardCash =
    quantity * (reward * v! * x! - settings.perUnitCost - settings.slippagePrice * v! * x!) -
    settings.fixedCost
  return r
}
