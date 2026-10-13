import { webClient } from './client'
export interface NeoDeskView {
  profile: string
  activation: string
  mode: string
  originating_mode?: string
  management?: { ready: boolean; message: string | null }
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
  protection: async (tradeId: number, changes: Record<string, unknown>) =>
    (await webClient.post('/neodesk/api/position/protection', { trade_id: tradeId, changes })).data,
  close: async (tradeId: number) =>
    (
      await webClient.post('/neodesk/api/position/close', {
        trade_id: tradeId,
        confirmed: true,
        request_id: crypto.randomUUID(),
      })
    ).data,
  chart: async (
    instrument: string,
    interval: string
  ): Promise<{ overlays: Array<{ label: string; price: string; run_id: number }> }> =>
    (await webClient.get('/neodesk/api/chart', { params: { instrument, interval } })).data,
  settings: async (profile: string): Promise<NeoDeskView> =>
    (await webClient.post('/neodesk/api/settings', { profile })).data,
}
