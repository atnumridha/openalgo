import type {
  VideoBar,
  VideoGuideOptions,
  VideoGuideResult,
  VideoStrategy,
  VideoStrategyId,
  VideoSelection,
  VideoEvent,
} from './videoStrategyTypes'
export const VIDEO_STRATEGIES: readonly VideoStrategy[]
export function videoStrategyGuide(
  bars: readonly VideoBar[],
  options: VideoGuideOptions
): VideoGuideResult
export function chooseVideoSetup(
  result: VideoGuideResult,
  selectedId?: VideoStrategyId | ''
): VideoSelection

export function activeVideoSetups(result: VideoGuideResult): VideoEvent[]
export function videoSilverWindow(opened: number, closed: number, seconds: number): boolean
