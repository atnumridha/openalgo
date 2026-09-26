import { Handle, Position } from '@xyflow/react'
import { PlayCircle } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { StrategySignalNodeData } from '@/types/flow'

interface Props {
  data: StrategySignalNodeData
  selected?: boolean
}

export const StrategySignalNode = memo(({ data, selected }: Props) => (
  <div className={cn('workflow-node min-w-[150px] border-l-emerald-500', selected && 'selected')}>
    <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
    <div className="p-2">
      <div className="flex items-center gap-1.5 text-xs font-medium">
        <PlayCircle className="h-3.5 w-3.5 text-emerald-500" />
        Strategy Signal
      </div>
      <div className="mt-1 rounded bg-muted/50 px-1.5 py-1 text-[10px]">
        #{data.strategyId || '—'} · {data.action || 'choose action'} · {data.mode || 'choose mode'}
      </div>
    </div>
    <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
  </div>
))

StrategySignalNode.displayName = 'StrategySignalNode'
