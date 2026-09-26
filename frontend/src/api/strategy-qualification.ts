import type { QualificationCampaign, QualificationOverview } from '@/types/strategy-qualification'
import { webClient } from './client'

const BASE = '/strategy/api/qualification'
type Response<T> = { status: 'success'; data: T } | { status: 'error'; message: string }

function unwrap<T>(response: Response<T>): T {
  if (response.status !== 'success')
    throw new Error(response.message || 'Qualification request failed.')
  return response.data
}

export const qualificationKeys = {
  overview: ['strategy-qualification', 'overview'] as const,
  campaign: (id: number | null) => ['strategy-qualification', 'campaign', id] as const,
}

export async function getQualification(): Promise<QualificationOverview> {
  return unwrap((await webClient.get<Response<QualificationOverview>>(BASE)).data)
}

export async function getQualificationCampaign(id: number): Promise<QualificationCampaign> {
  return unwrap(
    (await webClient.get<Response<QualificationCampaign>>(`${BASE}/campaigns/${id}`)).data
  )
}

export async function createQualificationCampaign(payload: {
  strategy_id: number
  final_run_id: number
}): Promise<QualificationCampaign> {
  return unwrap(
    (await webClient.post<Response<QualificationCampaign>>(`${BASE}/campaigns`, payload)).data
  )
}

export type QualificationAction =
  | {
      action: 'reconcile'
      payload: {
        reason: string
        costs_confirmed: true
        expected_revision: number
        evidence_digest: string
      }
    }
  | {
      action: 'approve'
      payload: {
        reason: string
        acknowledged: true
        expected_revision: number
        evidence_digest: string
      }
    }
  | { action: 'revoke'; payload: { reason: string } }

export async function reviewQualificationCampaign(
  id: number,
  review: QualificationAction
): Promise<QualificationCampaign> {
  return unwrap(
    (
      await webClient.post<Response<QualificationCampaign>>(
        `${BASE}/campaigns/${id}/${review.action}`,
        review.payload
      )
    ).data
  )
}
