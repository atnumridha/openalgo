import { Check, ChevronsUpDown } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

export interface StrikePickerOption {
  value: string
  moneyness: string
  premium: string
  rsi: string
  volume: string
  oi: string
  spread?: string
  change?: string
  changeTone?: string
}

const columns = 'grid grid-cols-[1.1fr_1.2fr_1fr_1fr_1fr] gap-2 sm:gap-4'
const optionLabel = (option: StrikePickerOption) =>
  `${option.value} · ${option.moneyness} · ${option.premium} · ${option.rsi} · Vol ${option.volume} · OI ${option.oi}${option.spread && option.spread !== '—' ? ` · Spread ${option.spread}` : ''}`

/** Keep the closed control compact; give every metric its own column when open. */
export function StrikePicker({ id, side, value, options, disabled, onValueChange }: {
  id: string
  side: 'CE' | 'PE'
  value: string
  options: StrikePickerOption[]
  disabled: boolean
  onValueChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const trigger=useRef<HTMLButtonElement>(null)
  const [search, setSearch] = useState('')
  const selected = options.find(option => option.value === value)
  const query = search.trim().toLowerCase()
  const visible = open ? options.filter(option => `${option.value} ${option.moneyness}`.toLowerCase().includes(query)) : []
  return (
    <Popover open={open} onOpenChange={next => { setOpen(next); if (!next) setSearch('') }}>
      <PopoverTrigger asChild>
        <Button ref={trigger} id={id} role="combobox" aria-label={`${side} strike`} aria-expanded={open}
          variant="outline" disabled={disabled}
          className="h-auto min-h-11 w-60 max-w-full justify-between gap-2 whitespace-normal px-3 py-1.5 text-left font-normal">
          <span className="min-w-0 space-y-0.5">
            <span className="block text-sm">{selected ? `${selected.value} · ${selected.moneyness}` : 'Choose strike'}</span>
            <span className="block break-words text-xs text-muted-foreground tabular-nums">
              {selected ? <><span className={selected.changeTone}>{selected.premium}{selected.change?` (${selected.change})`:''}</span> · {selected.rsi}</> : 'Premium · RSI'}
            </span>
          </span>
          <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" collisionPadding={12} className="max-h-(--radix-popover-content-available-height) overflow-hidden p-0"
        onCloseAutoFocus={event=>{if(trigger.current?.closest('[hidden]'))event.preventDefault()}}
        style={{ width: 'min(42rem, calc(100vw - 1.5rem))', maxWidth: 'var(--radix-popover-content-available-width)' }}
        container={typeof document === 'undefined' ? null : document.fullscreenElement as HTMLElement | null}>
        {open ? <Command shouldFilter={false} label={`Search ${side} strikes`}>
          <CommandInput aria-label={`Search ${side} strikes`} placeholder="Search strike or ATM / ITM / OTM…"
            value={search} onValueChange={setSearch} />
          <div aria-label="Strike data columns" className={`${columns} shrink-0 border-b px-3 py-2 text-xs font-medium text-muted-foreground`}>
            {['Strike', 'Premium', 'RSI 14', 'Volume', 'OI'].map(label => <span key={label}>{label}</span>)}
          </div>
          <CommandList label={`${side} strike choices`} className="max-h-[min(22rem,45dvh)] scroll-py-1 p-1">
            <CommandEmpty>No matching strike.</CommandEmpty>
            {visible.map(option => {
              const [rsiValue, rsiSource] = option.rsi.replace(/^RSI /, '').split(' ')
              return (
                <CommandItem key={option.value} value={option.value} aria-label={optionLabel(option)}
                  className={`${columns} min-h-12 cursor-pointer items-center rounded-md px-2 py-2 text-xs tabular-nums`}
                  onSelect={() => { setOpen(false); setSearch(''); onValueChange(option.value) }}>
                  <span className="min-w-0 break-words">
                    <span className="flex items-center gap-1 font-medium">{option.value}
                      {option.value === value ? <Check aria-hidden="true" className="size-3 shrink-0" /> : null}
                    </span>
                    <span className="block text-muted-foreground">{option.moneyness}</span>
                  </span>
                  <span className="min-w-0 break-words [overflow-wrap:anywhere]"><span className={`font-medium ${option.changeTone??''}`}>{option.premium}</span>
                    {option.change?<span className={`block font-medium ${option.changeTone??''}`}>{option.change}</span>:null}
                    {option.spread ? <span className="block text-muted-foreground">Spread {option.spread}</span> : null}
                  </span>
                  <span className="min-w-0 break-words"><span className="block">{rsiValue}</span>
                    {rsiSource ? <span className="block text-muted-foreground">{rsiSource}</span> : null}
                  </span>
                  <span className="min-w-0 break-words [overflow-wrap:anywhere]">{option.volume}</span>
                  <span className="min-w-0 break-words [overflow-wrap:anywhere]">{option.oi}</span>
                </CommandItem>
              )
            })}
          </CommandList>
          <p className="shrink-0 border-t px-3 py-2 text-xs text-muted-foreground">
            {visible.length} of {options.length} strikes · most traded first. Volume / OI: CE + PE totals.
          </p>
        </Command> : null}
      </PopoverContent>
    </Popover>
  )
}
