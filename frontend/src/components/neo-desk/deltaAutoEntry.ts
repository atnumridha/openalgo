/** Reserve a closed candle before automatic preflight. Never retries the same candle. */
export function claimDeltaAutoEntry(
  storage: Storage,
  account: string,
  symbol: string,
  seconds: number,
  source: number
): boolean {
  if (
    !account ||
    !symbol ||
    !Number.isInteger(seconds) ||
    seconds <= 0 ||
    !Number.isFinite(source) ||
    source <= 0
  )
    throw Error('Invalid automatic entry context')
  const key = `delta-chart:auto-entry:v1:${encodeURIComponent(account)}:${encodeURIComponent(symbol)}:${seconds}`
  const old = storage.getItem(key)
  if (old !== null) {
    const prior = JSON.parse(old)
    if (!Number.isFinite(prior?.source) || prior.source <= 0)
      throw Error('Invalid automatic entry record')
    if (prior.source >= source) return false
  }
  const record = JSON.stringify({ source })
  storage.setItem(key, record)
  if (storage.getItem(key) !== record) throw Error('Automatic entry tracking could not be saved')
  return true
}

/** Browser-owned lock is released on reload/crash; the durable candle reservation remains. */
export async function withDeltaAutoEntryLock(
  account: string,
  symbol: string,
  run: () => Promise<void>
): Promise<boolean> {
  if (!navigator.locks?.request)
    throw Error('This browser cannot coordinate automatic entries safely')
  return navigator.locks.request(
    `delta-auto:${encodeURIComponent(account)}:${encodeURIComponent(symbol)}`,
    { ifAvailable: true },
    async (lock) => {
      if (!lock) return false
      await run()
      return true
    }
  )
}
