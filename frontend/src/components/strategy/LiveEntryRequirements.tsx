import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { researchKeys, saveLiveEntryPolicy } from '@/api/trading-research'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { LiveEntryPolicy } from '@/types/trading-research'

export default function LiveEntryRequirements({ policy }: { policy?: LiveEntryPolicy }) {
  const queryClient = useQueryClient()
  const [required, setRequired] = useState(policy?.research_required !== false)
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const saved = useMutation({
    mutationFn: saveLiveEntryPolicy,
    onSuccess: () => {
      setReason('')
      setConfirmed(false)
      void queryClient.invalidateQueries({ queryKey: researchKeys.risk })
    },
  })
  const current = saved.data ?? policy
  const changed = Boolean(current && required !== current.research_required)
  return (
    <Card className="mb-5" aria-label="Live entry requirements">
      <CardHeader>
        <CardTitle>Live entry requirements</CardTitle>
        <CardDescription>
          Research qualification can be required or optional for managed live entries. Making it
          optional skips the historical and forward campaign approval check; it does not establish
          profitability or start trading.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm font-medium">
          {current
            ? current.research_required
              ? 'Currently required'
              : 'Currently optional'
            : 'Current requirement unavailable'}
        </p>
        <p className="text-sm text-muted-foreground">
          Per-strategy LIVE approval, session authorization, broker funds, valid signals, protective
          stops, daily loss limits and contract checks still apply. Before changing this setting,
          close live positions and turn off each strategy’s LIVE mode.
        </p>
        <div className="space-y-2">
          <Label htmlFor="live-research-requirement">Research qualification</Label>
          <select
            id="live-research-requirement"
            className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
            value={required ? 'required' : 'optional'}
            disabled={!current || saved.isPending}
            onChange={(event) => {
              setRequired(event.target.value === 'required')
              setConfirmed(false)
            }}
          >
            <option value="required">Required before live entries</option>
            <option value="optional">Optional; keep live approvals and risk checks</option>
          </select>
        </div>
        {changed && (
          <>
            <div className="space-y-2">
              <Label htmlFor="live-research-reason">Review reason</Label>
              <Textarea
                id="live-research-reason"
                value={reason}
                maxLength={1000}
                onChange={(event) => setReason(event.target.value)}
                disabled={saved.isPending}
              />
            </div>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={saved.isPending}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              I understand this changes the research requirement only and does not start live
              trading.
            </label>
          </>
        )}
        <Button
          variant="outline"
          disabled={!changed || !confirmed || reason.trim().length < 3 || saved.isPending}
          onClick={() => {
            if (current)
              saved.mutate({
                research_required: required,
                expected_revision: current.revision,
                reason: reason.trim(),
                confirm: true,
              })
          }}
        >
          {saved.isPending ? 'Saving requirement…' : 'Save entry requirement'}
        </Button>
        {saved.error && (
          <p role="alert" className="text-sm text-destructive">
            {saved.error.message}
          </p>
        )}
        {saved.isSuccess && (
          <output className="block text-sm">
            Entry requirement saved. Live trading has not been started.
          </output>
        )}
      </CardContent>
    </Card>
  )
}
