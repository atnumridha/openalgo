import { FIELDS, OPS, type Operand, type RuleGroup, type RuleNode } from './model'
import { CANDLE_PATTERNS, type PatternSelection } from '../chart-toolkit/candlePatterns'
import { Button } from '@/components/ui/button'
const input = 'rounded-md border border-input bg-background px-2 py-1.5 text-sm'
const uid = () => crypto.randomUUID()
const count = (n: RuleNode): number =>
  n.type === 'condition' ? 1 : n.children.reduce((s, c) => s + count(c), 0)
function OperandEditor({
  label,
  value,
  onChange,
}: {
  label: string
  value: Operand
  onChange: (v: Operand) => void
}) {
  const field = typeof value === 'number' ? null : value
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="grid gap-1 text-xs">
        {label} operand
        <select
          className={input}
          aria-label={`${label} operand`}
          value={field ? 'field' : 'number'}
          onChange={(e) =>
            onChange(e.target.value === 'number' ? 0 : { field: 'close', offset: 0 })
          }
        >
          <option value="field">Field</option>
          <option value="number">Number</option>
        </select>
      </label>
      {field ? (
        <>
          <label className="grid gap-1 text-xs">
            {label} field
            <select
              className={input}
              aria-label={`${label} field`}
              value={field.field}
              onChange={(e) => onChange({ ...field, field: e.target.value as typeof field.field })}
            >
              {FIELDS.map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs">
            {label} bar
            <select
              className={input}
              aria-label={`${label} bar`}
              value={field.offset ?? 0}
              onChange={(e) => onChange({ ...field, offset: Number(e.target.value) as 0 | 1 })}
            >
              <option value="0">Last completed</option>
              <option value="1">Previous completed</option>
            </select>
          </label>
          {['ema', 'sma', 'relative_volume', 'highest_high', 'lowest_low'].includes(
            field.field
          ) && (
            <label className="grid gap-1 text-xs">
              {label} period
              <input
                className={`${input} w-20`}
                aria-label={`${label} period`}
                type="number"
                min={1}
                max={500}
                value={field.period ?? 20}
                onChange={(e) =>
                  onChange({
                    ...field,
                    period: Math.max(1, Math.min(500, Number(e.target.value) || 1)),
                  })
                }
              />
            </label>
          )}
          {field.field === 'candle_pattern' && (
            <label className="grid gap-1 text-xs">
              {label} pattern
              <select
                className={input}
                aria-label={`${label} pattern`}
                value={field.pattern ?? 'all'}
                onChange={(e) =>
                  onChange({ ...field, pattern: e.target.value as PatternSelection })
                }
              >
                {CANDLE_PATTERNS.map(([key, name]) => (
                  <option key={key} value={key}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </>
      ) : (
        <label className="grid gap-1 text-xs">
          {label} number
          <input
            className={`${input} w-28`}
            aria-label={`${label} number`}
            type="number"
            step="any"
            value={value as number}
            onChange={(e) => onChange(Number(e.target.value))}
          />
        </label>
      )}
    </div>
  )
}
export function RuleBuilder({
  rule,
  onChange,
}: {
  rule: RuleGroup
  onChange: (rule: RuleGroup) => void
}) {
  const leaves = count(rule)
  function group(node: RuleGroup, change: (n: RuleGroup) => void, depth: number) {
    const replace = (index: number, next: RuleNode) =>
      change({ ...node, children: node.children.map((child, i) => (i === index ? next : child)) })
    return (
      <fieldset className="space-y-3 rounded-lg border p-3">
        <legend className="px-1 text-xs text-muted-foreground">
          {depth === 1 ? 'Rules · completed candles only' : `Nested group ${depth}`}
        </legend>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm">
            Group logic{' '}
            <select
              className={input}
              aria-label="Group logic"
              value={node.op}
              onChange={(e) => change({ ...node, op: e.target.value as 'all' | 'any' })}
            >
              <option value="all">ALL conditions</option>
              <option value="any">ANY condition</option>
            </select>
          </label>
          <label className="text-xs">
            <input
              type="checkbox"
              checked={node.enabled !== false}
              onChange={(e) => change({ ...node, enabled: e.target.checked })}
            />{' '}
            Enabled group
          </label>
        </div>
        {node.children.map((child, index) => (
          <div key={child.id} className="space-y-2 rounded-md border p-2">
            {child.type === 'group' ? (
              group(child, (n) => replace(index, n), depth + 1)
            ) : (
              <>
                <label className="text-xs">
                  <input
                    type="checkbox"
                    aria-label={`Enable condition ${index + 1}`}
                    checked={child.enabled !== false}
                    onChange={(e) => replace(index, { ...child, enabled: e.target.checked })}
                  />{' '}
                  Enabled condition {index + 1}
                </label>
                <div className="flex flex-wrap items-end gap-3">
                  <OperandEditor
                    label="Left"
                    value={child.left}
                    onChange={(left) => replace(index, { ...child, left })}
                  />
                  <label className="grid gap-1 text-xs">
                    Comparison
                    <select
                      className={input}
                      aria-label="Comparison"
                      value={child.op}
                      onChange={(e) =>
                        replace(index, {
                          ...child,
                          op: e.target.value as typeof child.op,
                          ...(e.target.value === 'within_pct'
                            ? { tolerance: child.tolerance ?? 1 }
                            : {}),
                        })
                      }
                    >
                      {OPS.map(([key, name]) => (
                        <option key={key} value={key}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <OperandEditor
                    label="Right"
                    value={child.right}
                    onChange={(right) => replace(index, { ...child, right })}
                  />
                  {child.op === 'within_pct' && (
                    <label className="grid gap-1 text-xs">
                      Tolerance %
                      <input
                        className={`${input} w-24`}
                        aria-label="Tolerance percent"
                        type="number"
                        min={0}
                        step="any"
                        value={child.tolerance ?? 1}
                        onChange={(e) =>
                          replace(index, { ...child, tolerance: Number(e.target.value) })
                        }
                      />
                    </label>
                  )}
                </div>
              </>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={leaves + count(child) > 24}
                onClick={() => {
                  const clone = (n: RuleNode): RuleNode =>
                    n.type === 'condition'
                      ? { ...n, id: uid() }
                      : { ...n, id: uid(), children: n.children.map(clone) }
                  change({ ...node, children: [...node.children, clone(child)] })
                }}
              >
                Copy
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={node.children.length === 1}
                onClick={() =>
                  change({ ...node, children: node.children.filter((_, i) => i !== index) })
                }
              >
                Remove
              </Button>
            </div>
          </div>
        ))}
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={leaves >= 24}
            onClick={() =>
              change({
                ...node,
                children: [
                  ...node.children,
                  { type: 'condition', id: uid(), left: { field: 'close' }, op: 'gt', right: 0 },
                ],
              })
            }
          >
            Add condition
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={depth >= 3 || leaves >= 24}
            onClick={() =>
              change({
                ...node,
                children: [
                  ...node.children,
                  {
                    type: 'group',
                    id: uid(),
                    op: 'all',
                    children: [
                      {
                        type: 'condition',
                        id: uid(),
                        left: { field: 'close' },
                        op: 'gt',
                        right: 0,
                      },
                    ],
                  },
                ],
              })
            }
          >
            Add group
          </Button>
          <span className="self-center text-xs text-muted-foreground">
            {leaves}/24 conditions · maximum 3 levels
          </span>
        </div>
      </fieldset>
    )
  }
  return group(rule, onChange, 1)
}
