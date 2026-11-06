export interface ResearchBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}
export interface ResearchTrade {
  entry_time: number
  side: number
  entry: number
  stop: number
  target: number
  status?: string
  exit?: number
  exit_time?: number
}
export interface ResearchResult {
  values: Record<string, (number | null)[]>
  trades: ResearchTrade[]
  status: string
}
export function compute(
  bars: ResearchBar[],
  settings: { mode?: string; reward?: number },
  ctx: {
    symbol: string
    interval: string
    transformed?: boolean
    universal?: boolean
    continuous?: boolean
    tickSize?: number
    optionSide?: 'CE' | 'PE'
    session?: { start: number; end: number; offset: number } | null
  }
): ResearchResult
export default function register(api: { registerIndicator: (descriptor: unknown) => void }): void
