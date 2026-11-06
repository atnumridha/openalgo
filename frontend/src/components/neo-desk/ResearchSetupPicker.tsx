import { useState } from 'react'
import { ChevronsUpDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Command, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { PIYUSH_MODES } from './PiyushResearchLayer'

export function ResearchSetupPicker({value,onChange}:{value:string;onChange:(mode:string)=>void}){
 const [open,setOpen]=useState(false)
 return <Popover open={open} onOpenChange={setOpen}>
  <PopoverTrigger asChild><Button role="combobox" aria-label="Setup" aria-expanded={open} variant="outline" size="sm" className="h-8 min-w-56 justify-between gap-2 text-xs font-normal">
   {PIYUSH_MODES.find(([mode])=>mode===value)?.[1]??'Choose setup'}<ChevronsUpDown className="size-3" aria-hidden="true"/>
  </Button></PopoverTrigger>
  <PopoverContent align="start" className="w-80 max-w-[calc(100vw-1.5rem)] p-0" container={document.fullscreenElement as HTMLElement|null}>
   <Command><CommandInput aria-label="Find research setup" placeholder="Find setup…"/>
    <CommandList label="Research setup choices">{PIYUSH_MODES.map(([mode,label])=><CommandItem key={mode} value={mode} keywords={[label]}
      aria-selected={mode===value} onSelect={()=>{onChange(mode);setOpen(false)}}>{label}</CommandItem>)}</CommandList>
   </Command>
  </PopoverContent>
 </Popover>
}
