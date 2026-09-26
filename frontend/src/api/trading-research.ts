import type {
  CostSchedule,
  ResearchDataset,
  ResearchOverview,
  ResearchRun,
  ResearchRunRequest,
  TradingRisk,
} from '@/types/trading-research'
import { webClient } from './client'

const BASE = '/strategy/api/research'

export const researchKeys = {
  overview: ['trading-research', 'overview'] as const,
  run: (id: number | null) => ['trading-research', 'run', id] as const,
  risk: ['trading-research', 'risk'] as const,
}

export async function getResearch(): Promise<ResearchOverview> {
  return (await webClient.get<{ data: ResearchOverview }>(BASE)).data.data
}

export async function importResearchDataset(
  payload: Record<string, unknown>
): Promise<ResearchDataset> {
  return (await webClient.post<{ data: ResearchDataset }>(`${BASE}/datasets`, payload)).data.data
}

export async function createResearchRun(payload: ResearchRunRequest): Promise<ResearchRun> {
  return (await webClient.post<{ data: ResearchRun }>(`${BASE}/runs`, payload)).data.data
}

export async function getResearchRun(id: number): Promise<ResearchRun> {
  return (await webClient.get<{ data: ResearchRun }>(`${BASE}/runs/${id}`)).data.data
}

export async function researchRunAction(
  id: number,
  action: 'cancel' | 'freeze' | 'final-test'
): Promise<ResearchRun> {
  return (await webClient.post<{ data: ResearchRun }>(`${BASE}/runs/${id}/${action}`, {})).data.data
}

export async function getTradingRisk(): Promise<TradingRisk> {
  return (await webClient.get<{ data: TradingRisk }>('/strategy/api/risk')).data.data
}

export async function saveRiskCosts(costs: CostSchedule): Promise<unknown> {
  return (await webClient.put('/strategy/api/risk/costs', costs)).data.data
}

export async function resumeTradingRisk(payload: {
  mode: 'sandbox' | 'live'
  reason: string
  reconciled: true
}): Promise<unknown> {
  return (await webClient.post('/strategy/api/risk/resume', payload)).data.data
}
