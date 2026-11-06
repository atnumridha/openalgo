import { webClient } from './client'
import { readDeltaHistory } from '@/components/chart-toolkit/deltaFeed'
import { chartBars } from '@/components/neo-desk/tradingViewStudies'
import type {
  Frame,
  Instrument,
  SavedScreen,
  ScanDataset,
  ScreenDefinition,
} from '@/components/screener/model'
export interface ScreenerUniverse {
  id: string
  label: string
  items: Instrument[]
}
export interface ScreenEvent extends Instrument {
  time: number
  direction: string
  source: string
  observedAt: number
  id?: number
}
export interface DataReply {
  status: 'complete' | 'queued' | 'running'
  datasets: ScanDataset[]
  job_id?: string
  pending?: number
  failed?: number
}
const base = '/screener/api'
export const screenerApi = {
  universes: async (signal?: AbortSignal) =>
    (await webClient.get<{ universes: ScreenerUniverse[] }>(`${base}/universes`, { signal })).data
      .universes,
  screens: async (signal?: AbortSignal) =>
    (await webClient.get<{ screens: SavedScreen[] }>(`${base}/screens`, { signal })).data.screens,
  save: async (definition: ScreenDefinition, existing?: SavedScreen) =>
    (existing
      ? await webClient.put<{ screen: SavedScreen }>(`${base}/screens/${existing.id}`, {
          definition,
          expected_revision: existing.revision,
        })
      : await webClient.post<{ screen: SavedScreen }>(`${base}/screens`, { definition })
    ).data.screen,
  remove: async (id: number) => {
    await webClient.delete(`${base}/screens/${id}`)
  },
  data: async (
    items: Instrument[],
    interval: Frame,
    refresh: boolean,
    mode: 'live' | 'analyzer',
    signal: AbortSignal
  ): Promise<DataReply> =>
    (await webClient.post(`${base}/data`, { items, interval, refresh, mode }, { signal })).data,
  poll: async (id: string, signal: AbortSignal): Promise<DataReply> =>
    (await webClient.get(`${base}/data/${encodeURIComponent(id)}`, { signal })).data,
  cancel: async (id: string) => {
    await webClient.delete(`${base}/data/${encodeURIComponent(id)}`)
  },
  events: async (id: number, signal?: AbortSignal) =>
    (await webClient.get<{ events: ScreenEvent[] }>(`${base}/screens/${id}/events`, { signal }))
      .data.events,
  record: async (
    id: number,
    revision: number,
    mode: 'live' | 'analyzer',
    events: ScreenEvent[],
    signal?: AbortSignal
  ) =>
    (
      await webClient.post<{ events: ScreenEvent[] }>(
        `${base}/screens/${id}/events`,
        { revision, mode, events },
        { signal }
      )
    ).data.events,
}
/** Delta's chart adapter returns legacy IST transport; normalize exactly once to RAW UTC. */
export async function readScreenerDelta(
  item: Instrument,
  interval: Frame,
  signal: AbortSignal
): Promise<ScanDataset> {
  const observedAt = Date.now() / 1000
  try {
    const [history, daily, contract] = await Promise.all([
      readDeltaHistory(item.symbol, interval, undefined, signal),
      interval === '1d'
        ? Promise.resolve(null)
        : readDeltaHistory(item.symbol, '1d', undefined, signal),
      fetch(`https://api.india.delta.exchange/v2/products/${encodeURIComponent(item.symbol)}`, {
        signal,
        credentials: 'omit',
      }).then(async (r) => {
        if (!r.ok) throw Error('Delta contract metadata unavailable')
        const p = await r.json()
        if (!p.success || p.result?.symbol !== item.symbol || !(Number(p.result.tick_size) > 0))
          throw Error('Delta contract metadata unavailable')
        return p.result
      }),
    ])
    return {
      ...item,
      interval,
      source: 'Delta public history',
      observedAt,
      tickSize: Number(contract.tick_size),
      candles: chartBars(history.candles),
      daily: chartBars((daily ?? history).candles),
    }
  } catch (error) {
    if (signal.aborted) throw error
    return {
      ...item,
      interval,
      source: 'Delta public history',
      observedAt,
      candles: [],
      daily: [],
      error: error instanceof Error ? error.message : 'Delta history unavailable',
    }
  }
}
