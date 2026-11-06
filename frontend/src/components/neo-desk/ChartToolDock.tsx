import {
  createContext,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

const DockContext = createContext<{
  active: string | null
  select: (id: string | null) => void
} | null>(null)
export function ChartToolDock({ floating, children }: { floating: boolean; children: ReactNode }) {
  const [active, select] = useState<string | null>(null)
  const host = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const dock = host.current,
      parent = dock?.parentElement
    if (!floating || !dock || !parent) return
    const measure = () => {
      if (dock.offsetTop > 0)
        dock.style.setProperty('--chart-tool-max-height', `${dock.offsetTop}px`)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(parent)
    observer.observe(dock)
    return () => observer.disconnect()
  }, [floating])
  return (
    <DockContext.Provider value={{ active, select }}>
      <div
        ref={host}
        aria-label="Chart tools"
        className={
          floating
            ? 'relative flex shrink-0 flex-wrap items-center gap-1 border-t bg-background px-2 py-1 text-xs'
            : 'contents'
        }
      >
        {children}
      </div>
    </DockContext.Provider>
  )
}

/** Expanded tools are positioned outside layout; switching tabs preserves drafts. */
export function ChartToolPanel({
  floating = false,
  label,
  title,
  children,
  defaultOpen = false,
}: {
  floating?: boolean
  label: string
  title: ReactNode
  children: ReactNode
  defaultOpen?: boolean
}) {
  const dock = useContext(DockContext),
    id = useId(),
    button = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLElement>(null)
  const [localOpen, setLocalOpen] = useState(false)
  const open = dock ? dock.active === id : localOpen
  const select = (next: boolean) => {
    if (dock) dock.select(next ? id : null)
    else setLocalOpen(next)
  }
  const close = () => {
    select(false)
    button.current?.focus()
  }
  useEffect(() => {
    if (floating && open) panel.current?.focus()
  }, [floating, open])
  if (!floating)
    return (
      <details open={defaultOpen} className="shrink-0 border-t text-xs" aria-label={label}>
        <summary className="cursor-pointer px-3 py-2 font-medium focus-visible:outline focus-visible:outline-ring">
          {title}
        </summary>
        {children}
      </details>
    )
  return (
    <>
      <Button
        ref={button}
        type="button"
        size="sm"
        variant="ghost"
        aria-expanded={open}
        aria-controls={id}
        aria-haspopup="dialog"
        className={`min-w-0 max-w-full justify-start gap-1.5 px-2 text-xs ${open ? 'bg-muted' : ''}`}
        onClick={() => select(!open)}
      >
        {open ? (
          <ChevronDown aria-hidden="true" className="size-3.5" />
        ) : (
          <ChevronUp aria-hidden="true" className="size-3.5" />
        )}
        <span className="min-w-0 truncate">{title}</span>
      </Button>
      <section
        ref={panel}
        id={id}
        role="dialog"
        aria-label={label}
        hidden={!open}
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation()
            close()
          }
        }}
        className="absolute inset-x-0 bottom-full z-30 overflow-y-auto overscroll-contain border-y bg-card text-card-foreground shadow-xl outline-none"
        style={{ maxHeight: 'min(28rem, var(--chart-tool-max-height, 50dvh))' }}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-card px-3 py-2">
          <strong className="text-sm font-semibold">{label} settings</strong>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-label={`Close ${label}`}
            onClick={close}
            className="gap-1.5 text-xs"
          >
            <X aria-hidden="true" className="size-3.5" />
            Close
          </Button>
        </div>
        {children}
      </section>
    </>
  )
}
