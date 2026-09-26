import { Handle, Position } from '@xyflow/react'
import { ChartNoAxesCombined } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { OpeningRangeNodeData } from '@/types/flow'

interface Props {
  data: OpeningRangeNodeData
  selected?: boolean
}

export const OpeningRangeNode = memo(({ data, selected }: Props) => (
  <div className={cn('workflow-node min-w-[150px] border-l-cyan-500', selected && 'selected')}>
    <Handle type="target" position={Position.Top} className="!top-0 !-translate-y-1/2" />
    <div className="p-2">
      <div className="flex items-center gap-1.5 text-xs font-medium">
        <ChartNoAxesCombined className="h-3.5 w-3.5 text-cyan-500" />
        Opening Range
      </div>
      <div className="mt-1 rounded bg-muted/50 px-1.5 py-1 text-[10px]">
        {data.symbol || 'Choose symbol'} · {data.rangeMinutes || 15} min
      </div>
    </div>
    <Handle type="source" position={Position.Bottom} className="!bottom-0 !translate-y-1/2" />
  </div>
))

OpeningRangeNode.displayName = 'OpeningRangeNode'
