import { Handle, Position } from '@xyflow/react'
import { PlayCircle } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { StrategyModuleRunNodeData } from '@/types/flow'

interface Props {
  data: StrategyModuleRunNodeData
  selected?: boolean
}

export const StrategyModuleRunNode = memo(({ data, selected }: Props) => (
  <div className={cn('workflow-node min-w-[150px] border-l-emerald-500', selected && 'selected')}>
    <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
    <div className="p-2">
      <div className="mb-1.5 flex items-center gap-1.5">
        <div className="flex h-5 w-5 items-center justify-center rounded bg-emerald-500/20 text-emerald-500">
          <PlayCircle className="h-3 w-3" />
        </div>
        <div>
          <div className="text-xs font-medium leading-tight">Strategy Module</div>
          <div className="text-[9px] text-muted-foreground">guarded run</div>
        </div>
      </div>
      <div className="rounded bg-muted/50 px-1.5 py-1 text-[10px]">
        Strategy #{data.strategyId || '—'} · {(data.mode || 'sandbox').toUpperCase()}
      </div>
    </div>
    <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
  </div>
))

StrategyModuleRunNode.displayName = 'StrategyModuleRunNode'
