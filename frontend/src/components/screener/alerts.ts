import { instrumentKey, type ScanRow } from './model'
/** Unknown observations never count as exits. Each newly covered symbol starts silently. */
export class MatchMonitor {
  private matching = new Map<string, boolean>()
  reset() {
    this.matching.clear()
  }
  update(rows: ScanRow[]): ScanRow[] {
    const events: ScanRow[] = []
    for (const row of rows) {
      if (!row.fresh || row.state === 'unavailable' || row.time === null) continue
      const key = instrumentKey(row),
        previous = this.matching.get(key)
      if (previous === false && row.state === 'match') events.push(row)
      this.matching.set(key, row.state === 'match')
    }
    return events
  }
}
