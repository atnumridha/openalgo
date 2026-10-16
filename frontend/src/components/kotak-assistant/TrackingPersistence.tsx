import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { ManualTrackingController } from './ManualTracking'
import { parseTrackingBackup, serializeTrackingBackup } from './trackingBackup'
import { errorMessage } from './model'

export function TrackingPersistence({ controller }: { controller: ManualTrackingController }) {
  const input = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState('')
  const backup = () => {
    const blob = new Blob([serializeTrackingBackup(controller.scope, controller.rows)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `kotak-tracking-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <div className="space-y-2 rounded-md bg-muted/30 p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">
            {controller.ready
              ? `${controller.rows.length} manual tracking records saved · Restored on reopening`
              : 'Loading saved manual records…'}
          </p>
          <p>
            Entry, lots, SL, target and closes survive app or server restarts in this browser. Live
            prices resume when the feed reconnects.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!controller.ready || controller.busy || !controller.rows.length}
            onClick={backup}
          >
            Backup tracking
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!controller.ready || controller.busy}
            onClick={() => input.current?.click()}
          >
            Restore tracking
          </Button>
          <input
            ref={input}
            className="hidden"
            type="file"
            accept="application/json,.json"
            aria-label="Restore tracking file"
            onChange={async (event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (!file) return
              try {
                if (file.size > 5_000_000) throw new Error('Tracking backup is too large')
                const trades = parseTrackingBackup(controller.scope, await file.text())
                await controller.restore(trades)
                setMessage('Backup restored. Existing records were kept unchanged.')
              } catch (e) {
                setMessage(errorMessage(e))
              }
            }}
          />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Use a backup when changing browser or clearing browser data.
      </p>
      {message && <output className="block text-sm">{message}</output>}
    </div>
  )
}
