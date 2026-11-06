import { useEffect, useMemo, useRef, useState } from 'react'
import {
  kotakAssistantApi,
  type DeskMode,
  type Leg,
  type OrderTicket,
  type Preview,
  type Snapshot,
  type Plan,
  type CashPlan,
  type SetupResult,
} from '@/api/kotakAssistant'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { errorMessage, money, rewardTarget, automaticStop, draftEntry } from './model'
import { type DraftLevels, LEVEL_COLORS } from './PriceLevels'
import { feeDay, ticketCosts } from './feeEstimates'
import { TicketCosts } from './TicketCosts'

export function useTradingTicket({
  leg,
  desk,
  mode,
  refresh,
  onDraftChange,
  defaultRatio = '2',
  onRatioChange,
  onPreviewChange,
  selectedPlan,
  previewDelay = 300,
}: {
  leg: Leg | null
  desk?: Snapshot
  mode: DeskMode
  refresh: () => void
  onDraftChange?: (draft: DraftLevels) => void
  defaultRatio?: string
  onRatioChange?: (ratio: string) => void
  onPreviewChange?: (preview: Preview | null) => void
  selectedPlan?: Plan | null
  previewDelay?: number
}) {
  const [lots, setLots] = useState('1'),
    [entry, setEntry] = useState(''),
    [manualSL, setManualSL] = useState<string | null>(null),
    [volatilityDistance, setVolatilityDistance] = useState<number | undefined>(undefined),
    [customTarget, setCustomTarget] = useState('')
  const [entrySource, setEntrySource] = useState('')
  const entryEdited = useRef(false)
  const [adoption, setAdoption] = useState<{
    setup: SetupResult
    symbol: string
    plan?: Plan
  } | null>(null)
  const adoptedSetup = adoption?.symbol === leg?.symbol ? adoption?.setup : null
  const [cashRisk, setCashRisk] = useState(false)
  const [lossBudget, setLossBudget] = useState('500')
  const [cashMultiple, setCashMultiple] = useState('3')
  const [cashResult, setCashResult] = useState<{ key: string; plan: CashPlan } | null>(null)
  const [cashError, setCashError] = useState('')
  const cashInput = {
    entry: Number(entry),
    quantity: Number(lots) * (leg?.lotsize || 0),
    tick: leg?.tick_size || 0,
    exchange: desk?.exchange || '',
    loss_budget: Number(lossBudget),
    target_multiple: Number(cashMultiple),
    lot: leg?.lotsize || 0,
  }
  const cashKey = JSON.stringify([cashInput, desk?.scope, desk?.settings])
  const cashPlan = cashRisk && cashResult?.key === cashKey ? cashResult.plan : null
  const [rewardMultiple, setRewardMultiple] = useState(defaultRatio)
  const stopEstimate = automaticStop(Number(entry), leg?.tick_size || 0, volatilityDistance)
  const sl = cashRisk
    ? cashPlan?.fits
      ? String(cashPlan.sl)
      : ''
    : manualSL !== null
      ? manualSL
      : stopEstimate == null
        ? ''
        : String(stopEstimate)
  const setSL = (value: string) => setManualSL(value)
  const changeEntry = (value: string) => {
    entryEdited.current = true
    setEntrySource('Manual entry')
    setEntry(value)
  }
  const calculated = rewardTarget(
    Number(entry),
    Number(sl),
    Number(rewardMultiple),
    leg?.tick_size || 0
  )
  const target = cashRisk
    ? cashPlan?.fits
      ? String(cashPlan.target)
      : ''
    : rewardMultiple === 'custom'
      ? customTarget
      : calculated == null
        ? ''
        : String(calculated)
  const setTarget = (value: string) => {
    setRewardMultiple('custom')
    setCustomTarget(value)
  }
  const [autoTarget, setAutoTarget] = useState(true),
    [autoRisk, setAutoRisk] = useState(false),
    [autoInvalidation, setAutoInvalidation] = useState(false),
    [trail, setTrail] = useState(false),
    [activation, setActivation] = useState(''),
    [retention, setRetention] = useState('0.5')
  const [storedPreview, setPreview] = useState<Preview | null>(null),
    [message, setMessage] = useState('Select a strike and enter an SL and target'),
    [busy, setBusy] = useState(false),
    [clock, setClock] = useState(Date.now() / 1000)
  const [previewOrderKey, setPreviewOrderKey] = useState('')
  const generation = useRef(0),
    inflight = useRef(false),
    pending = useRef<{ mode: DeskMode; ticket: string; key: string } | null>(null),
    autoFilled = useRef('')
  const draftContext = useRef(`${mode}:${desk?.scope || ''}`)
  useEffect(() => {
    const t = setInterval(() => setClock(Date.now() / 1000), 1000)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    const initial = draftEntry(leg)
    setEntry(initial.price == null ? '' : String(initial.price))
    setEntrySource(
      initial.price == null
        ? ''
        : initial.source === 'ask'
          ? 'Entry from ask'
          : 'Entry from last traded price · indicative'
    )
    setManualSL(null)
    setCashRisk(false)
    setCashResult(null)
    const context = `${mode}:${desk?.scope || ''}`
    const sameContext = draftContext.current === context
    setAdoption((current) => (sameContext && current?.symbol === leg?.symbol ? current : null))
    draftContext.current = context
    setVolatilityDistance(undefined)
    entryEdited.current = false
    setCustomTarget('')
    setRewardMultiple(defaultRatio)
    setPreview(null)
    autoFilled.current = ''
    generation.current++
    pending.current = null
  }, [leg?.symbol, mode, desk?.scope])
  const adoptSetup = (setup: SetupResult, option: Leg | null = leg) => {
    if (inflight.current || pending.current) {
      setMessage('Resolve the previous entry outcome before adopting another setup')
      return
    }
    if (
      !option ||
      setup.read_only ||
      setup.eligible === false ||
      !['ready', 'triggered'].includes(setup.stage) ||
      (setup.expires != null && setup.expires <= Date.now() / 1000)
    )
      return
    const recommended =
      desk?.recommendation?.symbol === option.symbol ? desk.recommendation.plan : undefined
    const plan =
      (option.symbol === leg?.symbol
        ? selectedPlan === undefined
          ? desk?.selected_plan
          : selectedPlan || undefined
        : undefined) || recommended
    setAdoption({ setup, symbol: option.symbol, plan })
  }
  useEffect(() => {
    if (!adoption || adoption.symbol !== leg?.symbol) return
    const initial = draftEntry(leg)
    const plan = adoption.plan
    setEntry(plan ? String(plan.entry) : initial.price == null ? '' : String(initial.price))
    setEntrySource(
      'Setup adopted · option premium from ' + (plan ? 'volatility plan' : initial.source)
    )
    entryEdited.current = true
    setManualSL(null)
    setVolatilityDistance(plan && plan.entry > plan.sl ? plan.entry - plan.sl : undefined)
    setRewardMultiple(defaultRatio)
    setAutoTarget(true)
    if (adoption.setup.strategy !== 'trend') setAutoInvalidation(false)
    setCashRisk(adoption.setup.strategy !== 'trend')
    setLossBudget('500')
    setCashMultiple('3')
    setCashResult(null)
    setCashError('')
    autoFilled.current = leg.symbol
    setPreview(null)
    generation.current++
    pending.current = null
  }, [adoption, leg?.symbol])
  useEffect(() => {
    if (!cashRisk) return
    setCashError('')
    if (
      ![
        cashInput.entry,
        cashInput.quantity,
        cashInput.tick,
        cashInput.loss_budget,
        cashInput.target_multiple,
        cashInput.lot,
      ].every((value) => Number.isFinite(value) && value > 0) ||
      !Number.isInteger(cashInput.quantity) ||
      cashInput.quantity % cashInput.lot !== 0 ||
      !['NFO', 'BFO'].includes(cashInput.exchange)
    ) {
      setCashError('Enter a positive premium, whole lots and a valid net loss budget')
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const plan = await kotakAssistantApi.cashPlan(cashInput)
        if (!cancelled) setCashResult({ key: cashKey, plan })
      } catch (error) {
        if (!cancelled) setCashError(errorMessage(error))
      }
    }, 150)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [cashRisk, cashKey])
  useEffect(() => {
    if (!leg || autoFilled.current === leg.symbol) return
    const recommendation =
      desk?.recommendation?.symbol === leg.symbol ? desk.recommendation.plan : undefined
    const p =
      selectedPlan === undefined
        ? desk?.selected_plan || recommendation
        : selectedPlan || recommendation
    if (p) {
      if (!entryEdited.current) {
        setEntry(String(p.entry))
        setEntrySource('Entry from volatility plan')
      }
      if (p.entry > p.sl && p.sl > 0) setVolatilityDistance(p.entry - p.sl)
      if (rewardMultiple !== 'custom') setCustomTarget(String(p.target))
      autoFilled.current = leg.symbol
    }
  }, [desk?.selected_plan, desk?.recommendation, selectedPlan, leg])
  useEffect(() => {
    const initial = draftEntry(leg)
    if (
      !entryEdited.current &&
      !entry &&
      initial.price != null &&
      autoFilled.current !== leg?.symbol
    ) {
      setEntry(String(initial.price))
      setEntrySource(
        initial.source === 'ask' ? 'Entry from ask' : 'Entry from last traded price · indicative'
      )
    }
  }, [entry, leg?.ask, leg?.ltp, leg?.symbol])
  useEffect(() => {
    if (['1.5', '2', '3', '4', '5', '6'].includes(rewardMultiple)) onRatioChange?.(rewardMultiple)
  }, [rewardMultiple, onRatioChange])
  const order = useMemo<OrderTicket | null>(
    () =>
      leg
        ? {
            symbol: leg.symbol,
            ...(adoptedSetup
              ? {
                  strategy:
                    adoptedSetup.strategy === 'trend'
                      ? ('trend' as const)
                      : ('opening_reversal' as const),
                  strategy_version: adoptedSetup.version,
                  ...(cashRisk
                    ? {
                        risk_policy: {
                          kind: 'cash_budget' as const,
                          loss_budget: Number(lossBudget),
                          target_multiple: Number(cashMultiple),
                          net_target: Number(lossBudget) * Number(cashMultiple),
                        },
                      }
                    : {
                        risk_policy: {
                          kind: 'structural_premium' as const,
                          planned_sl: Number(sl),
                          planned_target: Number(target),
                        },
                      }),
                }
              : {}),
            manual_entry: true,
            exchange: desk?.exchange || '',
            product: 'MIS',
            quantity: Number(lots) * leg.lotsize,
            entry: Number(entry),
            sl: Number(sl),
            target: Number(target),
            auto_target: autoTarget,
            auto_risk: autoRisk,
            auto_invalidation: autoInvalidation,
            trailing: trail,
            profit_activation: Number(activation),
            retention: Number(retention),
            underlying: desk?.underlying,
            index_invalidation: cashRisk
              ? undefined
              : (adoptedSetup?.invalidation ?? desk?.analysis.invalidation),
            setup_id:
              adoptedSetup?.setup_id ||
              (desk?.recommendation?.symbol === leg.symbol ? desk.analysis.setup_id : undefined),
          }
        : null,
    [
      leg,
      desk?.exchange,
      desk?.underlying,
      desk?.analysis.invalidation,
      desk?.analysis.setup_id,
      desk?.recommendation?.symbol,
      lots,
      entry,
      sl,
      target,
      autoTarget,
      autoRisk,
      autoInvalidation,
      trail,
      activation,
      retention,
      adoptedSetup,
      cashRisk,
      lossBudget,
      cashMultiple,
    ]
  )
  const entryBlock =
    desk?.day?.halt ||
    ((desk?.day?.entry_limits?.entries ?? 0) >= 3
      ? 'Daily entry limit reached · 3 entries. Stop trading for today'
      : undefined)
  const key = JSON.stringify(order)
  const settingsKey = JSON.stringify(desk?.settings)
  const identity = `${mode}:${desk?.scope || ''}:${settingsKey}:${key}`
  const latestIdentity = useRef(identity)
  latestIdentity.current = identity
  const validOrder =
    !!order &&
    !!leg &&
    ['NFO', 'BFO'].includes(order.exchange) &&
    Number.isInteger(order.quantity) &&
    order.quantity > 0 &&
    leg.lotsize > 0 &&
    order.quantity % leg.lotsize === 0 &&
    leg.tick_size > 0 &&
    [order.entry, order.sl, order.target].every(
      (price) =>
        Number.isFinite(price) &&
        Math.abs(price - Math.round(price / leg.tick_size) * leg.tick_size) < 1e-7
    ) &&
    0 < order.sl &&
    order.sl < order.entry &&
    order.entry < order.target
  const preview =
    previewOrderKey === identity && storedPreview?.mode === mode ? storedPreview : null
  useEffect(() => {
    onPreviewChange?.(preview)
  }, [preview, onPreviewChange])
  useEffect(() => {
    if (leg)
      onDraftChange?.({
        symbol: leg.symbol,
        mode,
        entry: Number(entry),
        sl: Number(sl),
        target: Number(target),
      })
  }, [leg?.symbol, mode, entry, sl, target, onDraftChange])
  useEffect(() => {
    const gen = ++generation.current
    setPreview(null)
    if (entryBlock) {
      setMessage(entryBlock)
      return
    }
    if (!order || !order.entry || !order.sl || !order.target || !order.quantity) {
      setMessage('Select an option and complete the entry, SL and target')
      return
    }
    setMessage('Manual entry · broker checks run on Buy')
    let stopped = false,
      reading = false
    const load = async () => {
      if (stopped || reading || inflight.current || pending.current) return
      reading = true
      try {
        const p = await kotakAssistantApi.preview(mode, order)
        if (!stopped && generation.current === gen && !inflight.current && !pending.current) {
          setPreviewOrderKey(identity)
          setPreview(p)
          setMessage('')
        }
      } catch (e) {
        if (!stopped && generation.current === gen && !inflight.current && !pending.current) {
          setPreview(null)
          const reason = errorMessage(e)
          setMessage(
            reason === 'Trade operation already in progress; wait for reconciliation'
              ? 'Broker busy · retrying checks automatically'
              : reason
          )
        }
      } finally {
        reading = false
      }
    }
    // Stagger the two panes; each preview uses the same account-operation lease.
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      await load()
      if (!stopped) timer = setTimeout(poll, 3000)
    }
    timer = setTimeout(poll, previewDelay)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [identity, settingsKey, entryBlock, previewDelay])
  const buy = async () => {
    if (inflight.current || entryBlock || !validOrder || !order) return
    if (pending.current && pending.current.key !== identity) {
      setMessage('Previous entry outcome is unresolved; check positions before changing the order')
      return
    }
    const submittedIdentity = identity
    inflight.current = true
    setBusy(true)
    try {
      let intent = pending.current
      if (!intent) {
        const p =
          preview && preview.expires >= Date.now() / 1000
            ? preview
            : await kotakAssistantApi.preview(mode, order)
        if (latestIdentity.current !== submittedIdentity) {
          throw new Error('Order changed while checking; click Buy again with the displayed ticket')
        }
        if (p.mode !== mode || p.expires < Date.now() / 1000 || !p.ticket || !p.plan.fits) {
          throw new Error('Broker checks expired or failed; click Buy to check again')
        }
        intent = { mode, ticket: p.ticket, key: submittedIdentity }
        pending.current = intent
      }
      const trade = await kotakAssistantApi.enter(intent.mode, intent.ticket)
      setMessage(`${trade.status}: ${trade.reason}`)
      pending.current = null
      setPreview(null)
      refresh()
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status && [400, 401, 403, 409].includes(status)) pending.current = null
      setMessage(errorMessage(e) + ' · Refresh positions before another entry')
      refresh()
    } finally {
      inflight.current = false
      setBusy(false)
    }
  }
  const canBuy =
    !entryBlock && !busy && (!pending.current || pending.current.key === identity) && validOrder
  const currentPreview = preview && preview.expires >= clock ? preview : null
  const statusMessage = busy
    ? 'Checking and submitting order…'
    : entryBlock ||
      message ||
      (currentPreview
        ? 'Ready · broker checks passed'
        : preview
          ? 'Manual entry · refresh broker checks on Buy'
          : 'Manual entry · broker checks run on Buy')
  const costEstimate =
    Number.isInteger(Number(lots)) && Number(lots) > 0
      ? ticketCosts(
          order,
          desk?.exchange || '',
          desk?.settings.brokerage ?? 10,
          desk?.settings.slippage ?? 0,
          feeDay(clock * 1000)
        )
      : null
  return {
    leg,
    adoptSetup,
    adoptedSetup,
    cashRisk,
    lossBudget,
    setLossBudget,
    cashMultiple,
    setCashMultiple,
    cashPlan,
    cashStatus:
      cashError ||
      (cashPlan
        ? cashPlan.fits
          ? 'Cash budget includes estimated charges and slippage for the total quantity'
          : cashPlan.reason
        : cashRisk
          ? 'Calculating cash risk for the total quantity…'
          : ''),
    useManualRisk: () => {
      setCashRisk(false)
      setAdoption(null)
      setManualSL(null)
      setRewardMultiple(defaultRatio)
    },
    desk,
    mode,
    lots,
    setLots,
    entry,
    changeEntry,
    sl,
    setSL,
    target,
    setTarget,
    entrySource,
    manualSL,
    setManualSL,
    volatilityDistance,
    rewardMultiple,
    setRewardMultiple,
    calculated,
    autoTarget,
    setAutoTarget,
    autoRisk,
    setAutoRisk,
    autoInvalidation,
    setAutoInvalidation,
    trail,
    setTrail,
    activation,
    setActivation,
    retention,
    setRetention,
    preview: currentPreview,
    message,
    statusMessage,
    costEstimate,
    busy,
    clock,
    entryBlock,
    buy,
    order,
    canBuy,
  }
}

export type TradingTicketController = ReturnType<typeof useTradingTicket>
export function TradingTicket(props: Parameters<typeof useTradingTicket>[0]) {
  const controller = useTradingTicket(props)
  return <TradingTicketView controller={controller} />
}

export function TradingTicketView({ controller }: { controller: TradingTicketController }) {
  const {
    leg,
    desk,
    mode,
    lots,
    setLots,
    entry,
    changeEntry,
    sl,
    setSL,
    target,
    setTarget,
    entrySource,
    manualSL,
    setManualSL,
    volatilityDistance,
    rewardMultiple,
    setRewardMultiple,
    calculated,
    autoTarget,
    setAutoTarget,
    autoRisk,
    setAutoRisk,
    autoInvalidation,
    setAutoInvalidation,
    trail,
    setTrail,
    activation,
    setActivation,
    retention,
    setRetention,
    statusMessage,
    busy,
    buy,
    canBuy,
    costEstimate,
    cashRisk,
    lossBudget,
    setLossBudget,
    cashMultiple,
    setCashMultiple,
    cashStatus,
    useManualRisk,
    adoptedSetup,
  } = controller
  return (
    <Card className="gap-0 py-0">
      <CardContent className="p-4 space-y-3">
        <div>
          <h3 className="font-semibold">Order ticket</h3>
          <p className="text-sm text-muted-foreground">
            {leg?.symbol || 'Select CE or PE in the strike ladder'} ·{' '}
            {mode === 'live' ? 'Real Kotak order' : 'Paper order'} · MIS
          </p>
        </div>
        <p className="text-xs text-muted-foreground">Option premium in ₹</p>
        <div className="grid grid-cols-2 gap-3">
          {[
            ['Lots', lots, setLots],
            ['Entry limit ₹', entry, changeEntry],
            ['Stop loss trigger ₹', sl, setSL],
            ['Profit target ₹', target, setTarget],
          ].map(([label, value, setter]) => (
            <label key={String(label)} className="text-xs font-medium">
              {String(label)}
              <Input
                className="mt-1 h-10 border-l-[3px] text-base tabular-nums"
                style={{
                  borderLeftColor:
                    label === 'Lots'
                      ? undefined
                      : label === 'Entry limit ₹'
                        ? LEVEL_COLORS.entry
                        : label === 'Stop loss trigger ₹'
                          ? LEVEL_COLORS.stop
                          : LEVEL_COLORS.target,
                }}
                type="number"
                min="0"
                step={label === 'Lots' ? '1' : leg?.tick_size || '.05'}
                value={String(value)}
                onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                disabled={
                  busy ||
                  (cashRisk && (label === 'Stop loss trigger ₹' || label === 'Profit target ₹'))
                }
              />
            </label>
          ))}
        </div>
        {entrySource && <p className="text-xs text-muted-foreground">{entrySource}</p>}
        {adoptedSetup && (
          <p className="text-xs text-muted-foreground">
            Adopted {adoptedSetup.strategy === 'trend' ? 'trend' : 'opening reversal'} · v
            {adoptedSetup.version}
            {cashRisk
              ? ' · cash policy sets the premium stop and target'
              : ` · index invalidation ${adoptedSetup.invalidation?.toLocaleString('en-IN') || '—'}`}
          </p>
        )}
        {cashRisk && (
          <div
            className="space-y-2 rounded-md border bg-muted/20 p-3 text-xs"
            aria-label="Cash risk policy"
          >
            <label className="block font-medium">
              Net loss budget ₹
              <Input
                className="mt-1 h-9"
                type="number"
                min="0"
                step="50"
                value={lossBudget}
                disabled={busy}
                onChange={(event) => setLossBudget(event.target.value)}
              />
            </label>
            <p className="tabular-nums">
              Net target {money(Number(lossBudget) * Number(cashMultiple))} · {cashMultiple}× budget
            </p>
            <p className="text-muted-foreground">
              Total for {Number(lots) * (leg?.lotsize || 0)} units; estimated fees and slippage
              included.
            </p>
            <p aria-live="polite">{cashStatus}</p>
            <button type="button" className="underline" onClick={useManualRisk} disabled={busy}>
              Use manual premium risk
            </button>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-1 text-xs text-muted-foreground">
          <span>
            {cashRisk
              ? 'Cash budget SL · total net risk'
              : manualSL !== null
                ? 'Manual stop loss'
                : volatilityDistance
                  ? 'Automatic SL · option volatility'
                  : 'Automatic SL · 10% premium buffer'}
          </span>
          {!cashRisk && manualSL !== null && (
            <button
              type="button"
              className="underline"
              onClick={() => setManualSL(null)}
              disabled={busy}
            >
              Use automatic SL
            </button>
          )}
        </div>
        <div className="space-y-2" role="group" aria-label="Risk reward ratio">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="font-medium">Risk : reward</span>
            <span className="text-muted-foreground">
              {cashRisk
                ? 'Net target after estimated charges'
                : rewardMultiple === 'custom'
                  ? 'Custom target'
                  : 'Before charges'}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[1.5, 2, 3, 4, 5, 6].map((r) => {
              const value = rewardTarget(Number(entry), Number(sl), r, leg?.tick_size || 0)
              return (
                <Button
                  key={r}
                  type="button"
                  aria-label={`Risk reward 1:${r}`}
                  aria-pressed={(cashRisk ? cashMultiple : rewardMultiple) === String(r)}
                  variant={
                    (cashRisk ? cashMultiple : rewardMultiple) === String(r)
                      ? 'secondary'
                      : 'outline'
                  }
                  className="h-auto flex-col gap-0.5 px-1 py-2"
                  disabled={busy}
                  onClick={() =>
                    cashRisk ? setCashMultiple(String(r)) : setRewardMultiple(String(r))
                  }
                >
                  <span>1:{r}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {cashRisk
                      ? money(Number(lossBudget) * r)
                      : value == null
                        ? 'Set SL'
                        : money(value)}
                  </span>
                </Button>
              )
            })}
          </div>
          {calculated != null ||
          (Number(target) > Number(entry) && Number(sl) > 0 && Number(sl) < Number(entry)) ? (
            <div className="flex flex-wrap justify-between gap-2 text-xs">
              <span>
                Risk{' '}
                <strong className="tabular-nums">
                  {money((Number(entry) - Number(sl)) * Number(lots) * (leg?.lotsize || 0))}
                </strong>
              </span>
              <span>
                Potential profit{' '}
                <strong className="tabular-nums">
                  {money((Number(target) - Number(entry)) * Number(lots) * (leg?.lotsize || 0))}
                </strong>
              </span>
              <span className="basis-full text-muted-foreground">
                Gross for {Number(lots) * (leg?.lotsize || 0)} units. Fees and slippage reduce the
                net reward/risk shown in the broker preview.
              </span>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Select a priced option to fill SL and target automatically. No valid price is
              available yet.
            </p>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoTarget}
            onChange={(e) => setAutoTarget(e.target.checked)}
            disabled={busy}
          />
          Automatic target exit
        </label>
        <p className="text-xs text-muted-foreground">
          {autoTarget
            ? 'Target exit monitored by the server.'
            : 'Target requires manual Exit full.'}{' '}
          Stop loss attaches after fills.
        </p>
        <details className="rounded-md border px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium">
            More exit rules
            {[autoRisk, autoInvalidation, trail].some(Boolean)
              ? ` · ${[autoRisk, autoInvalidation, trail].filter(Boolean).length} enabled`
              : ''}
          </summary>
          <div className="mt-3 space-y-3">
            <div className="grid gap-3 text-sm">
              {[
                ['Exit on account limit', autoRisk, setAutoRisk],
                ['Exit on index invalidation', autoInvalidation, setAutoInvalidation],
                ['Protect winning profit', trail, setTrail],
              ].map(([label, value, setter]) => (
                <label key={String(label)} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(value)}
                    onChange={(e) => (setter as (v: boolean) => void)(e.target.checked)}
                    disabled={
                      busy ||
                      (label === 'Exit on index invalidation' &&
                        (cashRisk || !desk?.analysis.invalidation))
                    }
                  />
                  {String(label)}
                </label>
              ))}
            </div>
            {trail && (
              <div className="grid grid-cols-2 gap-3">
                <label className="text-sm">
                  Activate at net profit ₹
                  <Input
                    type="number"
                    value={activation}
                    onChange={(e) => setActivation(e.target.value)}
                  />
                </label>
                <label className="text-sm">
                  Retain fraction of peak (0–1)
                  <Input
                    type="number"
                    min="0"
                    max="1"
                    step=".05"
                    value={retention}
                    onChange={(e) => setRetention(e.target.value)}
                  />
                </label>
              </div>
            )}
          </div>
        </details>
        <TicketCosts estimate={costEstimate} brokerage={desk?.settings.brokerage ?? 10} />
        <Button
          className="w-full bg-emerald-600 text-white hover:bg-emerald-700"
          size="lg"
          disabled={!canBuy}
          onClick={buy}
        >
          {busy
            ? 'Submitting…'
            : `Buy ${lots} lot${Number(lots) === 1 ? '' : 's'} · ${Number(lots) * (leg?.lotsize || 0)} units ${mode === 'live' ? 'LIVE' : 'PAPER'}`}
        </Button>
        <p role="status" className="text-xs text-muted-foreground">
          {statusMessage}
        </p>
        <p className="text-xs text-muted-foreground">
          Unfilled entry cancels after 5 seconds · SELL stop on fills · square-off{' '}
          {desk?.settings.cutoff || '15:15'} IST
        </p>
      </CardContent>
    </Card>
  )
}

export function ChartBuyControls({
  controller,
  side = controller.leg?.symbol.endsWith('PE') ? 'PE' : 'CE',
  activate,
}: {
  controller: TradingTicketController
  side?: 'CE' | 'PE'
  activate?: () => void
}) {
  const {
    leg,
    mode,
    lots,
    setLots,
    entry,
    sl,
    target,
    busy,
    canBuy,
    buy,
    statusMessage,
    autoTarget,
    rewardMultiple,
    setRewardMultiple,
  } = controller
  return (
    <div className="space-y-2 border-t bg-muted/20 p-3" aria-label={`${side} chart order controls`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">Target R:R</span>
        <div className="flex gap-1" role="group" aria-label={`${side} target risk reward`}>
          {['1.5', '2', '3', '4', '5', '6'].map((ratio) => (
            <Button
              key={ratio}
              size="sm"
              variant={
                (controller.cashRisk ? controller.cashMultiple : rewardMultiple) === ratio
                  ? 'secondary'
                  : 'outline'
              }
              aria-pressed={
                (controller.cashRisk ? controller.cashMultiple : rewardMultiple) === ratio
              }
              disabled={busy}
              className="h-8 px-2 text-xs tabular-nums"
              onClick={() => {
                activate?.()
                if (controller.cashRisk) controller.setCashMultiple(ratio)
                else setRewardMultiple(ratio)
              }}
            >
              1:{ratio}
            </Button>
          ))}
          {rewardMultiple === 'custom' && <span className="self-center text-xs">Custom</span>}
        </div>
      </div>
      {controller.cashRisk && (
        <p className="text-xs tabular-nums">
          Total net risk budget {money(Number(controller.lossBudget))} · net target{' '}
          {money(Number(controller.lossBudget) * Number(controller.cashMultiple))}
          <span className="block text-muted-foreground">{controller.cashStatus}</span>
        </p>
      )}
      <div className="grid grid-cols-3 gap-2 text-xs tabular-nums">
        <div>
          <span className="text-muted-foreground">Entry</span>
          <strong className="block text-blue-400">
            {Number(entry) > 0 ? money(Number(entry)) : '—'}
          </strong>
        </div>
        <div>
          <span className="text-muted-foreground">SL</span>
          <strong className="block text-red-400">{Number(sl) > 0 ? money(Number(sl)) : '—'}</strong>
        </div>
        <div>
          <span className="text-muted-foreground">Target</span>
          <strong className="block text-emerald-400">
            {Number(target) > 0 ? money(Number(target)) : '—'}
          </strong>
        </div>
      </div>
      <TicketCosts
        estimate={controller.costEstimate}
        brokerage={controller.desk?.settings.brokerage ?? 10}
      />
      <div className="flex items-end gap-2">
        <label className="w-20 shrink-0 text-xs font-medium">
          {side} lots
          <Input
            type="number"
            min="1"
            step="1"
            value={lots}
            disabled={busy}
            onChange={(e) => {
              activate?.()
              setLots(e.target.value)
            }}
            className="mt-1 h-10 text-base"
          />
        </label>
        <Button
          className="h-10 min-w-0 flex-1 bg-emerald-600 text-white hover:bg-emerald-700"
          aria-label={`Buy ${side} · ${lots} lot${Number(lots) === 1 ? '' : 's'} · ${mode === 'live' ? 'LIVE' : 'PAPER'}`}
          disabled={!canBuy}
          onClick={() => {
            activate?.()
            void buy()
          }}
        >
          {busy ? 'Submitting…' : `Buy ${side} · ${mode === 'live' ? 'LIVE' : 'PAPER'}`}
        </Button>
      </div>
      <div className="flex flex-wrap justify-between gap-1 text-xs text-muted-foreground">
        <span>{Number(lots) * (leg?.lotsize || 0)} units</span>
        <span>{autoTarget ? 'Auto target on' : 'Manual target'} · SL on fills</span>
        <span>Unfilled entry cancels after 5s</span>
      </div>
      <p role="status" className="text-xs text-muted-foreground">
        {statusMessage}
      </p>
    </div>
  )
}
