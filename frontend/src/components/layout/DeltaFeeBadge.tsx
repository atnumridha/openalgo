import { useDeltaDisplayCurrency } from '@/hooks/useDeltaDisplayCurrency'
import { deltaMoney } from '@/lib/deltaCurrency'
import { useEffect, useState } from 'react'
import { type RiskOverview, riskApi } from '@/api/risk'
import { tradingApi } from '@/api/trading'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useLivePrice } from '@/hooks/useLivePrice'
import { usePageVisibility } from '@/hooks/usePageVisibility'
import { totalNetAfterFees, withProfile } from '@/lib/cryptoFees'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import type { Position } from '@/types/trading'

const NO_POSITIONS: Position[] = []
const FEES_URL =
  'https://www.delta.exchange/support/solutions?categoryId=80000464973&folderId=80000726075&articleId=80001188064'

function pct(value: unknown): string | null {
  if (value == null || value === '') return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return `${Number(n.toFixed(4))}%`
}

/**
 * The fee schedule as the badge states it.
 *
 * `/leverage/api/risk` sends every `_pct` field already in percent (0.05 is
 * 0.05%), so it is shown as sent. Scaling it again is what put 5.00% on a
 * 0.05% fee.
 */
export function deltaFeeText(
  fees: Partial<RiskOverview['fees']> | null | undefined
): string | null {
  if (!fees) return null
  const maker = pct(fees.maker_pct)
  const taker = pct(fees.taker_pct)
  if (maker == null && taker == null) return null
  const gst = pct(fees.gst_pct)
  return `Maker ${maker ?? '-'} · Taker ${taker ?? '-'}${gst ? ` plus ${gst} GST` : ''}`
}

/**
 * Delta Exchange net P&L after fees, as one compact pill in the navbar.
 *
 * The figure is the Positions page's Net P&L total: the same rows, priced by
 * the same live-price hook, summed by the same function. The fee schedule and
 * the rupee equivalent open on click, so the pill stays one line tall like
 * every other control in the bar. It shows from 2xl only: below that the nine
 * labelled nav items already fill the 1280px container (issue #1507), and the
 * Positions page carries the same figure.
 */
export default function DeltaFeeBadge() {
  const { apiKey, user } = useAuthStore()
  const { isVisible } = usePageVisibility()
  const isDelta = user?.broker === 'deltaexchange'
  const [positions, setPositions] = useState<Position[] | null>(null)
  const [risk, setRisk] = useState<RiskOverview | null>(null)
  const [displayCurrency, setDisplayCurrency] = useDeltaDisplayCurrency(user?.username)

  const { data: livePositions } = useLivePrice(positions ?? NO_POSITIONS, {
    enabled: isDelta && (positions?.length ?? 0) > 0,
    useMultiQuotesFallback: true,
    staleThreshold: 5000,
    multiQuotesRefreshInterval: 30000,
    pauseWhenHidden: true,
  })

  useEffect(() => {
    if (!apiKey || !isDelta || !isVisible) return
    const key = apiKey
    let mounted = true

    async function fetchOnce() {
      const [posResp, riskResp] = await Promise.allSettled([
        tradingApi.getPositions(key),
        riskApi.getOverview(),
      ])
      if (!mounted) return
      if (
        posResp.status === 'fulfilled' &&
        posResp.value?.status === 'success' &&
        Array.isArray(posResp.value.data)
      ) {
        setPositions(posResp.value.data)
      } else {
        setPositions(null)
      }
      if (riskResp.status === 'fulfilled') setRisk(riskResp.value)
    }

    void fetchOnce()
    const timer = setInterval(() => void fetchOnce(), 5000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  }, [apiKey, isDelta, isVisible])

  if (!isDelta) return null

  const netUsd =
    positions == null ? null : totalNetAfterFees(livePositions, withProfile(risk?.fee_profile))
  const feesText = deltaFeeText(risk?.fees)
  const open = (positions ?? []).filter((p) => Number(p.quantity) !== 0).length

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="hidden 2xl:inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-xs transition-colors hover:bg-muted"
          aria-label="Net P&L after fees. Show Delta fee details"
        >
          <span className="text-muted-foreground">Net</span>
          <span
            className={cn(
              'font-mono font-semibold tabular-nums',
              netUsd != null && netUsd > 0 && 'text-green-600',
              netUsd != null && netUsd < 0 && 'text-red-600'
            )}
            data-testid="delta-net-pnl"
          >
            {netUsd == null ? '-' : deltaMoney(netUsd, displayCurrency)}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 space-y-2 text-sm">
        <div className="font-medium">Delta Exchange, after fees</div>
        <label className="flex items-center justify-between">
          Display currency
          <select
            aria-label="Delta display currency"
            value={displayCurrency}
            onChange={(e) => setDisplayCurrency(e.target.value === 'USD' ? 'USD' : 'INR')}
            className="rounded border bg-background px-2 py-1"
          >
            <option value="INR">INR ₹</option>
            <option value="USD">USD $</option>
          </select>
        </label>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Net P&L</span>
          <span className="font-mono font-semibold">
            {netUsd == null ? '-' : deltaMoney(netUsd, displayCurrency)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Open positions</span>
          <span className="font-mono">{positions == null ? '-' : open}</span>
        </div>
        <p className="text-xs text-muted-foreground">
          Net is after the fees paid, the fee to close now and funding, the same total the Positions
          page shows.
        </p>
        <p className="text-xs text-muted-foreground">
          Delta India: US$1 = ₹85 (fixed). Currency follows the Positions amount selector.
        </p>
        {feesText && (
          <div className="text-xs text-muted-foreground" data-testid="delta-fee-rates">
            Futures fees: {feesText}
          </div>
        )}
        <a
          href={FEES_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-primary underline"
        >
          Delta fee schedule
        </a>
      </PopoverContent>
    </Popover>
  )
}
