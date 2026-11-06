import { forwardRef, useEffect, useId } from 'react'
import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from 'lucide-react'
import { toast } from 'sonner'

function describeNotice(notice: string) {
  if (
    /^(Order not sent:|Rejected:|Cannot safely|Entry paused:|Position changed\.|Order changed\.|Balance changed\.|Trend plan changed\.)/.test(
      notice
    )
  )
    return {
      kind: 'error' as const,
      title: 'Order not placed',
      Icon: OctagonXIcon,
      style: 'border-rose-500/60 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    }
  if (/^(Pending:|Outcome unknown\.)/.test(notice))
    return {
      kind: 'warning' as const,
      title: 'Confirmation pending',
      Icon: TriangleAlertIcon,
      style: 'border-amber-500/60 bg-amber-500/10 text-amber-800 dark:text-amber-200',
    }
  if (/^(Checking current|Placing )/.test(notice))
    return {
      kind: 'loading' as const,
      title: notice.startsWith('Placing ') ? 'Sending order' : 'Checking order',
      Icon: Loader2Icon,
      style: 'border-sky-500/60 bg-sky-500/10 text-sky-800 dark:text-sky-200',
    }
  if (notice.includes('Broker acknowledgement, not a fill.'))
    return {
      kind: 'success' as const,
      title: 'Order accepted',
      Icon: CircleCheckIcon,
      style: 'border-emerald-500/60 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200',
    }
  return {
    kind: 'info' as const,
    title: 'Update',
    Icon: InfoIcon,
    style: 'border-border bg-muted text-foreground',
  }
}

/** A durable inline result plus one replaceable popup; acknowledgement never implies a fill. */
export const DeltaOrderNotice = forwardRef<
  HTMLDivElement,
  { notice: string; quietSuccess?: boolean }
>(function DeltaOrderNotice({ notice, quietSuccess = false }, ref) {
  const id = useId()
  const { kind, title, Icon, style } = describeNotice(notice)
  useEffect(() => {
    if (kind === 'success' && quietSuccess) {
      toast.dismiss(id)
      return
    }
    if (kind === 'info') return
    const options = {
      id,
      description: notice,
      closeButton: true,
      duration: Infinity,
    }
    toast[kind](title, options)
  }, [id, notice, kind, title, quietSuccess])
  useEffect(
    () => () => {
      toast.dismiss(id)
    },
    [id]
  )
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role={kind === 'error' ? 'alert' : 'status'}
      aria-atomic="true"
      className={`rounded border p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring ${style}`}
    >
      <div className="mb-1 flex items-center gap-2 font-semibold">
        <Icon
          aria-hidden="true"
          className={`size-4 shrink-0 ${kind === 'loading' ? 'animate-spin motion-reduce:animate-none' : ''}`}
        />
        <span>{title}</span>
      </div>
      <p className="break-words">{notice}</p>
    </div>
  )
})
