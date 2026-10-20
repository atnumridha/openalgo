export interface TrackingTrade {
  id: string
  scope: string
  symbol: string
  exchange: string
  lot: number
  lots: number
  entry: number
  tick?: number
  reward_ratio?: number
  automatic_sl?: boolean
  sl?: number
  target?: number
  created: number
  closed?: number
  exit?: number
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('openalgo-tracking-only', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('trades', { keyPath: 'id' })
    request.onerror = () => reject(new Error('Local tracking database unavailable'))
    request.onsuccess = () => resolve(request.result)
  })
}
export async function loadTracking(scope: string): Promise<TrackingTrade[]> {
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('trades', 'readonly')
      const request = tx.objectStore('trades').getAll()
      tx.oncomplete = () =>
        resolve(
          (request.result as TrackingTrade[])
            .filter((row) => row.scope === scope)
            .sort((a, b) => b.created - a.created)
        )
      tx.onerror = tx.onabort = () => reject(new Error('Unable to load saved tracking trades'))
    })
  } finally {
    db.close()
  }
}

// Restore only missing IDs in one transaction. An older backup must never
// reopen a trade that was already closed or overwrite a corrected fill.
export async function restoreTracking(trades: TrackingTrade[]): Promise<void> {
  const db = await database()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('trades', 'readwrite')
      const store = tx.objectStore('trades')
      for (const trade of trades) {
        const request = store.get(trade.id)
        request.onsuccess = () => {
          if (request.result == null) store.add(trade)
        }
      }
      tx.oncomplete = () => resolve()
      tx.onerror = tx.onabort = () => reject(new Error('Unable to restore tracking backup'))
    })
  } finally {
    db.close()
  }
}
export async function saveTracking(trade: TrackingTrade): Promise<void> {
  const db = await database()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('trades', 'readwrite')
      const store = tx.objectStore('trades')
      const request = store.get(trade.id)
      let conflict = ''
      request.onsuccess = () => {
        const current = request.result as TrackingTrade | undefined
        if (current && (current.scope !== trade.scope || current.closed != null)) {
          conflict =
            'This trade was already closed or changed in another window. Saved records have been reloaded.'
          tx.abort()
          return
        }
        store.put(trade)
      }
      tx.oncomplete = () => resolve()
      tx.onerror = tx.onabort = () => reject(new Error(conflict || 'Unable to save tracking trade'))
    })
  } finally {
    db.close()
  }
}
