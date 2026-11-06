import type { Strategy51Settings } from './types'
/** Presentation only: retain the saved choices, restoring them when clean view is off. */
export function strategy51VisibleStudies(
  studies: string[],
  settings: Strategy51Settings
): string[] {
  return settings.cleanChart && studies.includes('strategies-51-guide')
    ? studies.filter((id) => id === 'strategies-51-guide' || id === 'volume')
    : studies
}
