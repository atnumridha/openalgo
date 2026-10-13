import { webClient } from './client'
export interface NeoDeskView {
  profile: string
  activation: string
  mode: string
  status: string
  can_edit: boolean
  run_id: number | null
  entries_today: number
  day_net_estimate: string
  protection: Record<string, unknown>
  presets: Array<{ profile: string; label: string; research_only?: boolean }>
  runner: { running: boolean }
  owned?: { run_id: number | null; legs: Array<Record<string, unknown>> }
  observed_at?: string
}
export const neoDeskApi = {
  state: async (): Promise<NeoDeskView> => (await webClient.get('/neodesk/api/state')).data,
  command: async (action: string, confirmLive = false): Promise<NeoDeskView> =>
    (
      await webClient.post('/neodesk/api/execution/' + action, {
        request_id: crypto.randomUUID(),
        confirm_live: confirmLive,
      })
    ).data,
  settings: async (profile: string): Promise<NeoDeskView> =>
    (await webClient.post('/neodesk/api/settings', { profile })).data,
}
