import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { getStrategyTemplates, installStrategyTemplate, strategyQueryKeys } from '@/api/strategy_module'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

const catalogKey = ['strategy-module', 'templates'] as const

export function StrategyTemplateLibrary() {
  const [expanded, setExpanded] = useState(false)
  const client = useQueryClient()
  const catalog = useQuery({ queryKey: catalogKey, queryFn: getStrategyTemplates, enabled: expanded })
  const install = useMutation({
    mutationFn: (id: string) => installStrategyTemplate(id),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: catalogKey }),
        client.invalidateQueries({ queryKey: strategyQueryKeys.strategies() }),
      ])
    },
  })
  return (
    <details className="group rounded-xl border bg-muted/10 p-4" onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-semibold">
        <span>Available templates</span>
        <span className="flex items-center gap-2 text-sm font-normal text-muted-foreground">
          Research and earlier strategies · optional
          <ChevronDown aria-hidden="true" className="size-4 transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <p className="mt-3 text-sm text-muted-foreground">
        Keep these uninstalled until you want to test them. Install adds one sandbox strategy and its
        linked Flow using template defaults. Automation stays stopped. Profitability is unproven.
      </p>
      {catalog.isLoading && <p className="mt-3 text-sm">Loading templates…</p>}
      {catalog.error && <p role="alert" className="mt-3 text-sm text-destructive">{catalog.error.message}</p>}
      {install.error && <p role="alert" className="mt-3 text-sm text-destructive">{install.error.message}</p>}
      {install.isSuccess && <output className="mt-3 block text-sm">
        {install.data.created ? 'Installed in sandbox. Automation is stopped.' : 'This template is already installed.'}
      </output>}
      <ul className="mt-4 grid gap-3 lg:grid-cols-2">
        {(catalog.data ?? []).map((template) => (
          <li key={template.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background p-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{template.name}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {template.underlying} · Intraday
                {template.category ? ` · ${template.category}` : ''}
                {template.provenance === 'conventional-inference' ? ' · inferred layout' : ''}
              </p>
            </div>
            {template.installed_strategy_id ? (
              <Button variant="outline" size="sm" asChild>
                <Link aria-label={`Open ${template.name}`} to={`/strategy/${template.installed_strategy_id}`}>Open installed</Link>
              </Button>
            ) : (
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{template.installation_pending ? 'Setup incomplete' : 'Not installed'}</Badge>
                <Button variant="outline" size="sm" aria-label={`Install ${template.name}`}
                  disabled={install.isPending} onClick={() => install.mutate(template.id)}>
                  {install.isPending && install.variables === template.id ? 'Installing…' : template.installation_pending ? 'Finish install' : 'Install'}
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </details>
  )
}
