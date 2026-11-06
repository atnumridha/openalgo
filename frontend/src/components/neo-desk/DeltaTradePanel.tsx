import { deltaBrokerGuide } from './tradeGuidanceAdapters'
import type { GuideBrokerContext } from './tradeGuidance'
import { DeltaBackendAuto } from './DeltaBackendAuto'
import {
  autoRecoveryKey,
  autoRecoveryAuthorized,
  readAutoRecovery,
  saveAutoRecovery,
  clearAutoRecovery,
  recoveryPauseReason,
} from './deltaRecovery'
import { readDeltaTradeDefaults, saveDeltaTradeDefaults } from './deltaTradeDefaults'
import { DELTA_SCALP_STRATEGY, scalpTargetPauseReason } from './deltaScalpRisk'
import { useEffect, useMemo, useRef, useState } from 'react'
import { claimDeltaAutoEntry, withDeltaAutoEntryLock } from './deltaAutoEntry'
import { deltaChartApi, type DeltaChartAction, type DeltaChartState } from '@/api/deltaChart'
import { calculateDeltaContracts, scalpRiskLimitedContracts, type BalanceFraction } from './deltaSizing'
import { publishTradeAlert, tradeFillAlerts, nextTradeAlertSnapshot } from './deltaTradeAlerts'
import { DeltaTradeAlerts } from './DeltaTradeAlertList'
import { readySound } from '@/lib/trading/alertDelivery'
import { DeltaTradeTimer } from './DeltaTradeTimer'
import { DeltaOrderNotice } from './DeltaOrderNotice'
import { DELTA_USD_INR, formatDeltaINR } from './deltaMoney'
import { revalueDeltaDisplay, useDeltaMark } from './deltaLiveValuation'
import {
  buildDeltaProtection,
  deltaProtectionPauseReason,
  type DeltaRiskContext,
} from './deltaRisk'
import { buildDeltaAdoption, useDeltaAutoManagement } from './deltaAutoManagement'

type PendingIntent = {
  request_id: string
  symbol: string
  account: string
  action?: DeltaChartAction['action']
}
const intentKey = (intent: Pick<PendingIntent, 'account' | 'symbol'>) =>
  `delta-chart:intent:v1:${encodeURIComponent(intent.account)}:${encodeURIComponent(intent.symbol)}`
function readIntent(context: Pick<PendingIntent, 'account' | 'symbol'>): PendingIntent | null {
  const raw = sessionStorage.getItem(intentKey(context))
  if (raw === null) return null
  const item: unknown = JSON.parse(raw)
  if (
    !item ||
    typeof item !== 'object' ||
    !('request_id' in item) ||
    typeof item.request_id !== 'string' ||
    !item.request_id ||
    !('symbol' in item) ||
    item.symbol !== context.symbol ||
    !('account' in item) ||
    item.account !== context.account
  )
    throw new Error('Invalid saved live intent')
  return {
    request_id: item.request_id,
    symbol: context.symbol,
    account: context.account,
    ...('action' in item &&
    ['entry', 'close', 'protect', 'edit', 'cancel', 'adopt'].includes(String(item.action))
      ? { action: item.action as DeltaChartAction['action'] }
      : {}),
  }
}
function clearIntent(intent: PendingIntent) {
  const stored = readIntent(intent)
  if (stored?.request_id === intent.request_id) sessionStorage.removeItem(intentKey(intent))
}

export interface DeltaTradePanelProps {
  symbol: string
  enabled: boolean
  riskContext?: DeltaRiskContext | null
  chartRiskContext?: DeltaRiskContext | null
  executionMode?: typeof DELTA_SCALP_STRATEGY
  onState?: (state: DeltaChartState | null) => void
  onGuidance?: (context: GuideBrokerContext | null) => void
  editProposal?: { order_id: string; price: number; nonce: number } | null
  onProposalHandled?: () => void
  closeProposal?: { nonce: number } | null
  onCloseProposalHandled?: () => void
}
const inputClass = 'w-full rounded border border-border bg-background px-2 py-1 text-xs'
const buttonClass = 'rounded border border-border px-2 py-1 text-xs disabled:opacity-40'
const positive = (value: string) => Number.isFinite(Number(value)) && Number(value) > 0
const editableOrder = (order: DeltaChartState['orders'][number]) =>
  order.type === 'limit_order' ||
  (order.type === 'market_order' && order.kind === 'sl' && order.reduce_only)
const validPrice = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0
const money = (value: number | null | undefined) =>
  value == null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 12 })

const usdMoney = (value: number | null | undefined) =>
  value == null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 4 })

function validMetadata(current: DeltaChartState | null, symbol: string) {
  return (
    !!current?.product &&
    current.product.symbol === symbol &&
    Number.isFinite(current.product.tick_size) &&
    current.product.tick_size > 0 &&
    Number.isFinite(current.product.contract_value) &&
    current.product.contract_value > 0 &&
    Number.isFinite(current.product.max_leverage) &&
    current.product.max_leverage >= 1 &&
    Array.isArray(current.orders) &&
    current.orders.every(
      (order) =>
        order &&
        typeof order.id === 'string' &&
        order.id.length > 0 &&
        ['buy', 'sell'].includes(order.side) &&
        ['entry', 'sl', 'target'].includes(order.kind) &&
        typeof order.version === 'string' &&
        order.version.length > 0 &&
        typeof order.state === 'string' &&
        Number.isFinite(order.size) &&
        order.size > 0 &&
        Number.isFinite(order.unfilled) &&
        order.unfilled >= 0 &&
        (order.price === null || (Number.isFinite(order.price) && order.price > 0))
    ) &&
    Array.isArray(current.fills)
  )
}

export function DeltaTradePanel({
  symbol,
  enabled,
  onState,
  onGuidance,
  editProposal,
  onProposalHandled,
  riskContext,
  chartRiskContext,
  executionMode,
  closeProposal,
  onCloseProposalHandled,
}: DeltaTradePanelProps) {
  const [snapshot, setSnapshot] = useState<DeltaChartState | null>(null)
  const [error, setError] = useState('')
  const [now, setNow] = useState(Date.now())
  const [manualSide, setManualSide] = useState<'buy' | 'sell'>('buy')
  const [manualQuantity, setQuantity] = useState(() => readDeltaTradeDefaults().manualQuantity)
  const [defaultsNotice, setDefaultsNotice] = useState('')
  const confirmedDirection =
    riskContext === undefined
      ? 'up'
      : riskContext?.symbol === symbol
        ? riskContext.direction
        : 'unavailable'
  const entrySide = confirmedDirection === 'down' ? 'sell' : 'buy'
  const hasEntryDirection = confirmedDirection === 'up' || confirmedDirection === 'down'
  const [balanceFraction, setBalanceFraction] = useState<BalanceFraction | null>(
    () => readDeltaTradeDefaults().balanceFraction
  )
  const [reviewBudget, setReviewBudget] = useState<number | null>(null)
  const [adoptionMark, setAdoptionMark] = useState<number | null>(null)
  const [leverage, setLeverage] = useState(() => readDeltaTradeDefaults().leverage)
  const [stop, setStop] = useState('')
  const [target, setTarget] = useState('')
  const [editId, setEditId] = useState('')
  const [editPrice, setEditPrice] = useState('')
  const [review, setReview] = useState<DeltaChartAction | null>(null)
  const reviewElement = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const element = reviewElement.current
    if (!review || !element) return
    element.closest('details')?.setAttribute('open', '')
    element.scrollIntoView?.({ block: 'nearest' })
    element.focus({ preventScroll: true })
  }, [review?.request_id])
  const [sending, setSending] = useState(false)
  const entryClickLock = useRef(false)
  const entryMounted = useRef(true)
  useEffect(() => {
    entryMounted.current = true
    return () => {
      entryMounted.current = false
    }
  }, [])
  const [storageChecked, setStorageChecked] = useState('')
  const [storageFailed, setStorageFailed] = useState(false)
  const [notice, setNotice] = useState('')
  const entryNotice = useRef(false)
  const entryFeedback = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!entryNotice.current || !notice || notice.startsWith('Checking current')) return
    entryFeedback.current?.scrollIntoView?.({ block: 'nearest' })
    entryFeedback.current?.focus({ preventScroll: true })
  }, [notice])
  const [entryTimerPlacement, setEntryTimerPlacement] = useState<{
    account: string
    symbol: string
    key: string
    startedAt: number
  } | null>(null)
  const [pendingRequest, setPendingRequest] = useState<PendingIntent | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [connecting, setConnecting] = useState(false)
  const handledCloseProposal = useRef<number | null>(null)
  const handledEditProposal = useRef<number | null>(null)
  const context = useRef({ symbol, enabled })
  context.current = { symbol, enabled }
  const callback = useRef(onState)
  callback.current = onState
  const pinnedAccount = useRef<string | null>(null)
  const current = enabled && snapshot?.symbol === symbol ? snapshot : null
  const entryScope = useRef({ key: '', version: 0 })
  const pinnedRiskScope = useRef<{ symbol: string; seconds: number } | null>(null)
  if (riskContext?.symbol === symbol)
    pinnedRiskScope.current = { symbol, seconds: riskContext.intervalSeconds }
  const recoverySeconds = executionMode
    ? 60
    : riskContext?.symbol === symbol
      ? riskContext.intervalSeconds
      : pinnedRiskScope.current?.symbol === symbol
        ? pinnedRiskScope.current.seconds
        : undefined
  const recoveryAccount = current?.account ?? pinnedAccount.current
  const scopeKey = `${enabled}:${symbol}:${recoveryAccount ?? ''}:${recoverySeconds ?? ''}:${executionMode ?? ''}`
  if (entryScope.current.key !== scopeKey)
    entryScope.current = { key: scopeKey, version: entryScope.current.version + 1 }
  const [autoArm, setAutoArm] = useState<{ scope: string; token: string } | null>(null)
  const [autoMessage, setAutoMessage] = useState('')
  const [recoveryPending, setRecoveryPending] = useState(false)
  const backendAutomation = current?.automation?.owner === 'backend' ? current.automation : null
  const browserAutoEnabled = !!autoArm && autoArm.scope === scopeKey && enabled && !backendAutomation
  const autoEnabled = !!backendAutomation?.enabled || browserAutoEnabled
  const autoPermit = useRef('')
  autoPermit.current = browserAutoEnabled && autoArm ? autoArm.token : ''
  const recoveryAttempted = useRef(new Set<string>())
  const autoLoopBusy = useRef(false)
  const stopAuto = (clearSaved = true) => {
    autoPermit.current = ''
    recoveryAttempted.current.add(scopeKey)
    const cleared =
      !clearSaved ||
      !recoveryAccount ||
      !recoverySeconds ||
      clearAutoRecovery(recoveryAccount, symbol, recoverySeconds, executionMode)
    setAutoArm(null)
    setRecoveryPending(false)
    setAutoMessage(
      cleared
        ? ''
        : 'Stopped here, but saved Auto permission could not be cleared. Close other charts and disable browser storage recovery before reloading.'
    )
  }
  useEffect(() => {
    stopAuto(false)
    recoveryAttempted.current.delete(scopeKey)
  }, [scopeKey])
  useEffect(() => {
    if (backendAutomation || !current?.account || !riskContext) return
    const onStorage = (event: StorageEvent) => {
      if (
        event.key !== null &&
        event.key !==
          autoRecoveryKey(current.account, symbol, riskContext.intervalSeconds, executionMode)
      )
        return
      if (
        !autoArm ||
        !autoRecoveryAuthorized(
          current.account,
          symbol,
          riskContext.intervalSeconds,
          autoArm.token,
          executionMode
        )
      ) {
        stopAuto(false)
        setAutoMessage('Auto stopped by another chart. Turn On to start again.')
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [current?.account, symbol, riskContext?.intervalSeconds, autoArm, executionMode])
  const entryContext = useRef({ current, riskContext })
  entryContext.current = { current, riskContext }
  const fresh = !!current && now / 1000 - current.asof <= 10 && now / 1000 - current.asof >= -5
  const metadataValid = validMetadata(current, symbol)
  const valid =
    !!current?.connected &&
    !!current.account &&
    current.environment === 'india_prod' &&
    metadataValid &&
    fresh &&
    !error
  const unknownOrder =
    metadataValid &&
    current?.orders.some(
      (order) =>
        !['open', 'pending', 'closed', 'cancelled', 'canceled', 'filled'].includes(order.state)
    )
  const pending = !!pendingRequest || !!current?.pending?.length || !!unknownOrder
  const currentStorageKey = current?.account ? intentKey(current) : ''
  const legacyPlan =
    executionMode &&
    current?.managed_plans?.find(
      (plan) =>
        !['completed', 'cancelled', 'rejected'].includes(plan.status) &&
        plan.interval_seconds !== 60
    )
  const managementRiskContext = legacyPlan
    ? chartRiskContext?.symbol === symbol &&
      chartRiskContext.intervalSeconds === legacyPlan.interval_seconds
      ? chartRiskContext
      : null
    : (riskContext ?? null)
  const autoManagement = useDeltaAutoManagement(
    enabled && !backendAutomation &&
      valid &&
      storageChecked === currentStorageKey &&
      !storageFailed &&
      !sending &&
      !pending &&
      review?.action !== 'close' &&
      review?.action !== 'adopt',
    current,
    managementRiskContext
  )
  const canAct =
    valid &&
    storageChecked === currentStorageKey &&
    !storageFailed &&
    !sending &&
    !pending &&
    !autoManagement.busy
  const markTick = useDeltaMark(symbol, enabled && valid)
  const displayState = useMemo(
    () => (current ? revalueDeltaDisplay(current, markTick, now) : null),
    [current, markTick, now]
  )
  const alertSnapshot = useRef<DeltaChartState | null>(null)
  useEffect(() => {
    if (!valid || !current) return
    for (const event of tradeFillAlerts(alertSnapshot.current, current)) publishTradeAlert(event)
    alertSnapshot.current = nextTradeAlertSnapshot(alertSnapshot.current, current)
  }, [current, valid])
  const streamedValuation = displayState !== current
  const cap = metadataValid
    ? Math.max(1, Math.min(200, Math.floor(current!.product.max_leverage)))
    : 5
  const entryPrice = (side: 'buy' | 'sell') =>
    side === 'buy' ? current?.ticker?.bid : current?.ticker?.ask
  const canReviewClose = valid && !sending && !!current?.position?.version
  const quotePrices = [current?.ticker?.bid, current?.ticker?.ask, current?.ticker?.mark].filter(
    validPrice
  )
  const sizingPrice = quotePrices.length ? Math.max(...quotePrices) : NaN
  const selectedLeverage = Math.min(leverage, cap)
  const sizingAvailable =
    valid &&
    calculateDeltaContracts(
      current?.sizing,
      0.25,
      1,
      current?.product?.contract_value || 0,
      selectedLeverage
    ) !== null
  const canSize = sizingAvailable && validPrice(sizingPrice)
  const marginSizedContracts =
    balanceFraction && canSize
      ? calculateDeltaContracts(
          current?.sizing,
          balanceFraction,
          sizingPrice,
          current!.product.contract_value,
          selectedLeverage
        )
      : null
  const sizingProtection = riskContext?.entryExpiresAt !== undefined && validPrice(entryPrice(entrySide))
    ? buildDeltaProtection(riskContext, entrySide, entryPrice(entrySide)!, current?.product.tick_size || 0, Date.now()/1000, 'manual') : null
  const sizedContracts = sizingProtection && current
    ? scalpRiskLimitedContracts(marginSizedContracts, entryPrice(entrySide)!, sizingProtection.stop, current.product.contract_value, current.sizing)
    : marginSizedContracts
  const quantity = balanceFraction === null ? manualQuantity : String(sizedContracts ?? 0)
  const fundsRequired =
    sizingAvailable &&
    validPrice(sizingPrice) &&
    Number.isSafeInteger(Number(quantity)) &&
    Number(quantity) >= 0
      ? Number(quantity) *
        sizingPrice *
        current!.product.contract_value *
        (1 / selectedLeverage +
          current!.sizing!.maker_fee_rate * (1 + current!.sizing!.fee_tax_rate))
      : null
  const validEntry = Number.isSafeInteger(Number(quantity)) && Number(quantity) > 0
  const managedRequested = riskContext !== undefined
  const rawProtectionPlan =
    riskContext?.symbol === symbol && validPrice(entryPrice(entrySide))
      ? buildDeltaProtection(
          riskContext,
          entrySide,
          entryPrice(entrySide)!,
          current?.product?.tick_size || 0
        )
      : null
  const scalpFeePause =
    executionMode && rawProtectionPlan && validPrice(entryPrice(entrySide))
      ? scalpTargetPauseReason(
          entrySide,
          entryPrice(entrySide)!,
          rawProtectionPlan.target,
          current?.product.tick_size || 0,
          current?.sizing
        )
      : null
  const protectionPlan = scalpFeePause ? null : rawProtectionPlan
  const entryPauseReason =
    scalpFeePause ||
    (riskContext?.symbol === symbol && validPrice(entryPrice(entrySide))
      ? deltaProtectionPauseReason(
          riskContext,
          entrySide,
          entryPrice(entrySide)!,
          current?.product?.tick_size || 0
        )
      : null)
  const entryExposureReason =
    current?.position && current.position.size !== 0
      ? 'close the existing position before opening a new entry.'
      : metadataValid && current?.orders.some((order) => ['open', 'pending'].includes(order.state))
        ? 'cancel existing open orders before opening a new entry.'
        : null
  const protectionPauseReason =
    riskContext?.direction === 'up' && entrySide === 'sell'
      ? 'Trend is up. Short is paused; choose Long or wait for a confirmed downtrend.'
      : riskContext?.direction === 'down' && entrySide === 'buy'
        ? 'Trend is down. Long is paused; choose Short or wait for a confirmed uptrend.'
        : riskContext?.entryAligned === false
          ? riskContext.trendReason ||
            'The two chart timeframes disagree. Waiting for the same direction.'
          : riskContext?.direction === 'sideways'
            ? riskContext.trendReason || 'No confirmed trend yet. Entry is paused.'
            : entryPauseReason ||
              'Waiting for a confirmed trend with enough room for the SL and target.'
  const entryDisabledReason = sending
    ? 'sending the reviewed broker request.'
    : pending
      ? 'a broker request is pending reconciliation.'
      : autoManagement.busy
        ? 'automatic protection is being checked with the broker.'
        : error
          ? 'broker data could not be refreshed. Wait for a fresh snapshot.'
          : !current
            ? 'waiting for live broker data.'
            : !current.connected
              ? 'Delta is disconnected. Connect to continue.'
              : !fresh
                ? 'broker data is stale. Wait for a fresh snapshot.'
                : !valid
                  ? 'the broker snapshot is not valid for trading.'
                  : storageFailed
                    ? 'this browser cannot safely save live request tracking.'
                    : storageChecked !== currentStorageKey
                      ? 'checking saved broker requests.'
                      : entryExposureReason
                        ? entryExposureReason
                        : !validEntry
                          ? balanceFraction !== null && sizedContracts === 0
                            ? 'the balance is too small at this leverage.'
                            : 'enter a positive whole number of lots.'
                          : !validPrice(entryPrice(entrySide))
                            ? 'a valid best quote or manual limit price is required.'
                            : managedRequested && !protectionPlan
                              ? protectionPauseReason
                              : null
  const guideCallback = useRef(onGuidance)
  guideCallback.current = onGuidance
  useEffect(() => {
    const side = autoEnabled ? entrySide : manualSide
    const price = entryPrice(side)
    const plan = riskContext?.symbol === symbol && validPrice(price)
      ? buildDeltaProtection(riskContext, side, price, current?.product.tick_size || 0, Date.now() / 1000, 'manual') : null
    guideCallback.current?.(deltaBrokerGuide(current, {
      quantity: Number(quantity), side, plan, sourceTime: riskContext?.sourceTime ?? 0, source: autoEnabled ? 'auto' : 'manual',
    }))
  }, [current, quantity, entrySide, manualSide, autoEnabled, riskContext, symbol])
  useEffect(() => () => guideCallback.current?.(null), [symbol])
  const coin = symbol.endsWith('USD') ? symbol.slice(0, -3) : symbol
  const selectedCoinQuantity =
    quantity.trim() &&
    Number.isSafeInteger(Number(quantity)) &&
    Number(quantity) >= 0 &&
    current?.product
      ? Number(quantity) * current.product.contract_value
      : null

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    setSnapshot(null)
    setError('')
    setReview(null)
    setStop('')
    setTarget('')
    setEditId('')
    setEditPrice('')
    const defaults = readDeltaTradeDefaults()
    setLeverage(defaults.leverage)
    setBalanceFraction(defaults.balanceFraction)
    setQuantity(defaults.manualQuantity)
    setDefaultsNotice('')
    setEntryTimerPlacement(null)
    pinnedAccount.current = null
    callback.current?.(null)
    if (!enabled) return
    const poll = async () => {
      try {
        const state = await deltaChartApi.state(symbol, controller.signal)
        if (!alive) return
        if (state.symbol !== symbol) throw new Error('Symbol mismatch. Trading paused.')
        if (pinnedAccount.current && pinnedAccount.current !== state.account)
          throw new Error('Account changed. Reload before trading.')
        if (state.connected && state.account) pinnedAccount.current = state.account
        setSnapshot(state)
        setError('')
        setNow(Date.now())
      } catch {
        if (!alive) return
        setSnapshot(null)
        setReview(null)
        setError('Connection or account check failed. Trading paused.')
        callback.current?.(null)
      } finally {
        if (alive) timer = setTimeout(poll, 2000)
      }
    }
    void poll()
    return () => {
      alive = false
      clearTimeout(timer)
      controller.abort()
      callback.current?.(null)
    }
  }, [symbol, enabled])
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    callback.current?.(valid ? displayState : null)
  }, [displayState, valid])

  useEffect(() => {
    if (!valid || !current) return
    try {
      const stored = readIntent(current)
      const candidate =
        stored ||
        (pendingRequest?.account === current.account && pendingRequest.symbol === current.symbol
          ? pendingRequest
          : null)
      const receipt =
        candidate &&
        current.receipts?.find(
          (item) =>
            item.request_id === candidate.request_id &&
            (item.status === 'confirmed' || item.status === 'rejected')
        )
      if (candidate && receipt) {
        clearIntent(candidate)
        setPendingRequest((previous) =>
          previous?.request_id === candidate.request_id ? null : previous
        )
        if (receipt.status === 'confirmed' && candidate.action === 'entry') {
          entryNotice.current = true
          publishTradeAlert({
            id: `order:${candidate.request_id}`,
            account: current.account,
            symbol: current.symbol,
            title: 'Order placed',
            message: `${current.symbol} · Delta accepted the entry order. Check live fills for execution.`,
            at: current.asof,
          })
        }
        setNotice(
          receipt.status === 'confirmed'
            ? `${receipt.message}. Broker acknowledgement, not a fill. Check position and fills.`
            : `Rejected: ${receipt.message}`
        )
      } else if (stored) {
        setPendingRequest((previous) =>
          previous?.request_id === stored.request_id ? previous : stored
        )
      }
      setStorageChecked(intentKey(current))
      setStorageFailed(false)
    } catch {
      setStorageFailed(true)
      setNotice('Cannot safely record or restore live intent. Trading paused.')
    }
  }, [current, valid, pendingRequest])

  const prepare = (action: Omit<DeltaChartAction, 'request_id' | 'symbol' | 'account'>) => {
    if (
      !current ||
      (action.action === 'close' ? !canReviewClose : !canAct) ||
      (action.action === 'entry' && entryDisabledReason)
    )
      return
    if (
      (action.action === 'close' || action.action === 'protect' || action.action === 'adopt') &&
      !current.position?.version
    )
      return
    entryNotice.current = false
    setNotice('')
    setAdoptionMark(action.action === 'adopt' ? (current.position?.mark ?? null) : null)
    setReviewBudget(
      action.balance_fraction && current.sizing
        ? action.balance_fraction * current.sizing.available_balance
        : null
    )
    setReview({
      ...action,
      ...(action.action === 'close' || action.action === 'protect' || action.action === 'adopt'
        ? { position_version: current.position?.version }
        : {}),
      request_id: crypto.randomUUID(),
      symbol,
      account: current.account,
    })
  }
  const beginClose = () => {
    if (!current?.position) return
    stopAuto()
    prepare({
      action: 'close',
      size: Math.abs(current.position.size),
      side: current.position.size > 0 ? 'sell' : 'buy',
      order_type: 'market_order',
    })
  }
  useEffect(() => {
    if (!closeProposal || handledCloseProposal.current === closeProposal.nonce || !canReviewClose)
      return
    handledCloseProposal.current = closeProposal.nonce
    beginClose()
    onCloseProposalHandled?.()
  }, [closeProposal?.nonce, canReviewClose, current?.position?.version])
  useEffect(() => {
    if (!editProposal || handledEditProposal.current === editProposal.nonce || !canAct || !current)
      return
    handledEditProposal.current = editProposal.nonce
    const order = current.orders.find((item) => item.id === editProposal.order_id)
    if (
      order &&
      editableOrder(order) &&
      Number.isFinite(editProposal.price) &&
      editProposal.price > 0
    ) {
      setEditId(order.id)
      setEditPrice(String(editProposal.price))
      setReview({
        request_id: crypto.randomUUID(),
        symbol,
        account: current.account,
        action: 'edit',
        order_id: order.id,
        version: order.version,
        price: editProposal.price,
      })
    }
    onProposalHandled?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editProposal?.nonce, canAct, current])

  async function send() {
    if (
      !canAct ||
      !review ||
      !current ||
      review.symbol !== symbol ||
      review.account !== current.account
    )
      return
    if (review.action === 'entry' && entryExposureReason) {
      setReview(null)
      setNotice(`Entry paused: ${entryExposureReason}`)
      return
    }
    if (
      (review.action === 'close' || review.action === 'protect' || review.action === 'adopt') &&
      (!review.position_version || review.position_version !== current.position?.version)
    ) {
      setReview(null)
      setNotice('Position changed. Review the current position again.')
      return
    }
    if (
      review.order_id &&
      current.orders.find((order) => order.id === review.order_id)?.version !== review.version
    ) {
      setReview(null)
      setNotice('Order changed. Review its latest price again.')
      return
    }
    if (
      review.balance_fraction &&
      (!sizingAvailable ||
        !review.sizing_version ||
        review.sizing_version !== current.sizing?.version)
    ) {
      setReview(null)
      setNotice('Balance changed. Review the quantity again.')
      return
    }
    if (review.auto_protection && review.action !== 'adopt') {
      const latest =
        riskContext?.symbol === symbol && review.side && review.price
          ? buildDeltaProtection(riskContext, review.side, review.price, current.product.tick_size)
          : null
      if (
        !latest ||
        latest.source_time !== review.auto_protection.source_time ||
        latest.stop !== review.auto_protection.stop ||
        latest.target !== review.auto_protection.target
      ) {
        setReview(null)
        setNotice('Trend plan changed. Review this entry again.')
        return
      }
    }
    if (review.action === 'adopt') {
      const latest = buildDeltaAdoption(current, managementRiskContext, adoptionMark ?? undefined)
      if (
        !latest ||
        !review.auto_protection ||
        latest.protection.source_time !== review.auto_protection.source_time ||
        latest.protection.stop !== review.auto_protection.stop ||
        latest.protection.target !== review.auto_protection.target ||
        JSON.stringify(latest.existingStop) !== JSON.stringify(review.existing_stop) ||
        JSON.stringify(latest.existingTarget) !== JSON.stringify(review.existing_target)
      ) {
        setReview(null)
        setNotice('Position or existing protection changed. Review automatic SL again.')
        return
      }
    }
    await submitAction(review)
  }

  async function submitAction(submitted: DeltaChartAction) {
    const intent: PendingIntent = {
      request_id: submitted.request_id,
      symbol: submitted.symbol,
      account: submitted.account,
      action: submitted.action,
    }
    try {
      const existing = readIntent(intent)
      if (existing) {
        setPendingRequest(existing)
        setNotice('Pending: An earlier request is awaiting confirmation. Do not resubmit.')
        setReview(null)
        return
      }
      sessionStorage.setItem(intentKey(intent), JSON.stringify(intent))
      if (readIntent(intent)?.request_id !== intent.request_id)
        throw new Error('Intent write failed')
    } catch {
      setStorageFailed(true)
      setNotice('Cannot safely record live intent. Order was not sent. Trading paused.')
      return
    }
    setPendingRequest(intent)
    setSending(true)
    setReview(null)
    try {
      const result = await deltaChartApi.action(submitted)
      if (
        result.request_id === submitted.request_id &&
        (result.status === 'confirmed' || result.status === 'rejected')
      ) {
        clearIntent(intent)
        setPendingRequest((previous) =>
          previous?.request_id === intent.request_id ? null : previous
        )
      } else if (result.status !== 'pending') {
        throw new Error('Unmatched broker acknowledgement')
      }
      if (result.status === 'pending')
        setPendingRequest({
          request_id: submitted.request_id,
          symbol: submitted.symbol,
          account: submitted.account,
        })
      if (context.current.symbol !== submitted.symbol || !context.current.enabled) return
      if (result.status === 'confirmed' && submitted.action === 'entry') {
        publishTradeAlert({
          id: `order:${submitted.request_id}`,
          account: submitted.account,
          symbol: submitted.symbol,
          title: 'Order placed',
          message: `${submitted.symbol} · ${submitted.side === 'buy' ? 'Long' : 'Short'} ${submitted.size} lots. Delta accepted the maker-only order; waiting for fill.`,
          at: Date.now() / 1000,
        })
        const placed =
          typeof result.placed_at === 'number' &&
          Number.isFinite(result.placed_at) &&
          result.placed_at > 0 &&
          result.placed_at <= Date.now() / 1000 + 1
            ? result.placed_at
            : Date.now() / 1000
        setEntryTimerPlacement({
          account: submitted.account,
          symbol: submitted.symbol,
          key: `entry:${submitted.request_id}`,
          startedAt: placed,
        })
      }
      if (result.status === 'confirmed')
        setNotice(
          submitted.action === 'adopt'
            ? `${result.message}. Existing protection remains until its replacement is acknowledged.`
            : `${result.message}. Broker acknowledgement, not a fill. Check position and fills.`
        )
      else if (result.status === 'rejected') setNotice(`Rejected: ${result.message}`)
      else {
        setPendingRequest({
          request_id: submitted.request_id,
          symbol: submitted.symbol,
          account: submitted.account,
        })
        setNotice(`Pending: ${result.message}. Do not resubmit. Request ${submitted.request_id}`)
      }
    } catch {
      setPendingRequest({
        request_id: submitted.request_id,
        symbol: submitted.symbol,
        account: submitted.account,
      })
      if (context.current.symbol === submitted.symbol && context.current.enabled) {
        setNotice(
          `Outcome unknown. Do not resubmit. Check broker orders. Request ${submitted.request_id}`
        )
      }
    } finally {
      setSending(false)
    }
  }
  function automaticAuthorized(token: string) {
    const latest = entryContext.current
    return (
      autoPermit.current === token &&
      !!latest.current?.account &&
      !!latest.riskContext &&
      autoRecoveryAuthorized(
        latest.current.account,
        symbol,
        latest.riskContext.intervalSeconds,
        token,
        executionMode
      )
    )
  }
  async function placeEntry(
    automatic?: { token: string; source: number },
    manualOverride?: 'buy' | 'sell'
  ) {
    if (automatic && !automaticAuthorized(automatic.token)) return
    if (entryClickLock.current || !canAct || entryExposureReason || !current) return
    entryClickLock.current = true
    setSending(true)
    entryNotice.current = true
    setNotice('Checking current broker data and best maker price…')
    const requestScope = entryScope.current.version
    const account = current.account,
      requestedSymbol = symbol,
      side = manualOverride ?? entrySide
    const leverageValue = selectedLeverage,
      fraction = balanceFraction,
      manualLots = Number(quantity)
    try {
      const freshState = await deltaChartApi.state(requestedSymbol)
      const latest = entryContext.current
      if (
        automatic &&
        (!automaticAuthorized(automatic.token) ||
          latest.riskContext?.sourceTime !== automatic.source)
      )
        throw new Error('Automatic entry stopped or the signal candle changed. No order was sent.')
      const clock = Date.now() / 1000
      if (
        !entryMounted.current ||
        entryScope.current.version !== requestScope ||
        !context.current.enabled ||
        context.current.symbol !== requestedSymbol ||
        latest.current?.account !== account ||
        freshState.symbol !== requestedSymbol ||
        freshState.account !== account
      )
        throw new Error('The symbol or account changed. Check the current chart.')
      if (
        !freshState.connected ||
        freshState.environment !== 'india_prod' ||
        !validMetadata(freshState, requestedSymbol) ||
        !Number.isFinite(freshState.asof) ||
        clock - freshState.asof > 10 ||
        clock - freshState.asof < -5
      )
        throw new Error('Fresh valid broker data is unavailable.')
      if (freshState.position && freshState.position.size !== 0)
        throw new Error('Close the existing position before opening a new entry.')
      if (
        freshState.orders.some(
          (order) => !['closed', 'cancelled', 'canceled', 'filled'].includes(order.state)
        ) ||
        freshState.pending?.length
      )
        throw new Error('Resolve existing broker orders or requests before a new entry.')
      if (
        automatic &&
        freshState.managed_plans?.some(
          (plan) =>
            !['completed', 'cancelled', 'rejected'].includes(plan.status) ||
            (plan.interval_seconds === latest.riskContext?.intervalSeconds &&
              plan.source_time >= automatic.source)
        )
      )
        throw new Error(
          'Another managed trade exists or this candle already has a trade. Waiting for a new eligible candle.'
        )
      const best = side === 'buy' ? freshState.ticker?.bid : freshState.ticker?.ask
      if (!validPrice(best)) throw new Error('The current best maker quote is unavailable.')
      const ticks = best / freshState.product.tick_size
      if (Math.abs(ticks - Math.round(ticks)) > 1e-7)
        throw new Error('The best quote does not match the current tick size.')
      if (leverageValue > Math.min(200, Math.floor(freshState.product.max_leverage)))
        throw new Error('The contract leverage limit changed. Select leverage again.')
      const costPrice = Math.max(
        ...[best, freshState.ticker.mark, freshState.ticker.bid, freshState.ticker.ask].filter(
          validPrice
        )
      )
      let lots =
        fraction === null
          ? manualLots
          : calculateDeltaContracts(
              freshState.sizing,
              fraction,
              costPrice,
              freshState.product.contract_value,
              leverageValue
            )
      if (lots === null || !Number.isSafeInteger(lots) || lots <= 0)
        throw new Error('The current balance cannot fund the selected whole lots.')
      const affordableLots = calculateDeltaContracts(
        freshState.sizing,
        1,
        costPrice,
        freshState.product.contract_value,
        leverageValue
      )
      if (affordableLots !== null && lots > affordableLots)
        throw new Error(
          'The selected lots exceed the current available balance including fees and reserve.'
        )
      const risk = latest.riskContext
      const plan =
        risk?.symbol === requestedSymbol
          ? buildDeltaProtection(
              risk,
              side,
              best,
              freshState.product.tick_size,
              Date.now() / 1000,
              manualOverride ? 'manual' : 'entry'
            )
          : null
      if ((manualOverride || risk !== undefined) && !plan)
        throw new Error(
          deltaProtectionPauseReason(risk ?? null, side, best, freshState.product.tick_size) ||
            'Automatic protection could not be verified for this entry.'
        )
      if (plan && risk?.entryExpiresAt !== undefined) {
        const limited = scalpRiskLimitedContracts(lots, best, plan.stop, freshState.product.contract_value, freshState.sizing)
        if (limited === null || limited < 1) throw new Error('One lot exceeds the ₹20 planned-loss limit including fees. Waiting for a smaller-risk setup.')
        if (fraction === null && lots > limited) throw new Error('Selected lots exceed the ₹20 planned-loss limit including fees. Reduce lots.')
        lots = limited
      }
      const scalpFees =
        executionMode && plan
          ? scalpTargetPauseReason(
              side,
              best,
              plan.target,
              freshState.product.tick_size,
              freshState.sizing
            )
          : null
      if (scalpFees) throw new Error(scalpFees)
      const body: DeltaChartAction = {
        request_id: crypto.randomUUID(),
        symbol: requestedSymbol,
        account,
        action: 'entry',
        ...(manualOverride ? { entry_mode: 'manual' as const, ...(backendAutomation ? {target_mode: 'trend' as const} : {}) } : {}),
        side,
        size: lots,
        order_type: 'limit_order',
        price: best,
        leverage: leverageValue,
        ...(plan ? { auto_protection: plan } : {}),
        ...(fraction !== null
          ? { balance_fraction: fraction, sizing_version: freshState.sizing!.version }
          : {}),
      }
      setSnapshot(freshState)
      setNotice(
        `Placing ${side === 'buy' ? 'Long' : 'Short'}: ${lots} lots at ${money(best)} · maker-only.`
      )
      if (automatic && !automaticAuthorized(automatic.token))
        throw new Error('Auto permission was revoked. No order was sent.')
      await submitAction(body)
    } catch (failure) {
      if (context.current.symbol === requestedSymbol && context.current.enabled)
        setNotice(
          `Order not sent: ${failure instanceof Error ? failure.message : 'Preflight failed. Try again only after checking the error.'}`
        )
    } finally {
      entryClickLock.current = false
      setSending(false)
    }
  }
  const backendHandoff = useRef(new Set<string>())
  useEffect(() => {
    if (!backendAutomation || !current?.account || !valid || !enabled) return
    const key = `${current.account}:${symbol}`
    if (backendAutomation.generation) {
      clearAutoRecovery(current.account, symbol, 60, executionMode)
      setAutoArm(null)
      setRecoveryPending(false)
      return
    }
    if (backendHandoff.current.has(key)) return
    backendHandoff.current.add(key)
    try {
      const saved = readAutoRecovery(current.account, symbol, 60, executionMode)
      if (!saved) return
      autoPermit.current = ''
      setAutoArm(null)
      setRecoveryPending(false)
      void deltaChartApi.automation({
        account: current.account, symbol, enabled: true,
        leverage: saved.settings.leverage,
        balance_fraction: saved.settings.balanceFraction,
        manual_quantity: Number(saved.settings.manualQuantity),
      }).then(result => {
        if (result.status !== 'confirmed' || result.automation.account !== current.account) return
        clearAutoRecovery(current.account, symbol, 60, executionMode)
        setSnapshot(previous => previous?.account === current.account ? {...previous, automation: result.automation} : previous)
      }).catch(() => setNotice('Backend Auto hand-off is awaiting confirmation. Read the live backend status before changing Auto.'))
    } catch {
      setNotice('Saved Auto settings could not be verified. Backend remains Off; select Auto On after reviewing its settings.')
    }
  }, [backendAutomation, current?.account, enabled, valid, symbol, executionMode])
  useEffect(() => {
    if (!backendAutomation?.enabled) return
    setLeverage(backendAutomation.leverage)
    setBalanceFraction(backendAutomation.balance_fraction as BalanceFraction | null)
    setQuantity(String(backendAutomation.manual_quantity))
  }, [backendAutomation?.generation, backendAutomation?.enabled])
  const autoManagedPlan = current?.managed_plans?.some(
    (plan) => !['completed', 'cancelled', 'rejected'].includes(plan.status)
  )
  useEffect(() => {
    if (
      backendAutomation ||
      autoEnabled ||
      !enabled ||
      !valid ||
      !current ||
      pending ||
      storageFailed ||
      storageChecked !== currentStorageKey ||
      riskContext?.symbol !== symbol ||
      recoveryAttempted.current.has(scopeKey)
    )
      return
    try {
      const saved = readAutoRecovery(
        current.account,
        symbol,
        riskContext.intervalSeconds,
        executionMode
      )
      if (!saved) {
        recoveryAttempted.current.add(scopeKey)
        return
      }
      setRecoveryPending(true)
      const pause = recoveryPauseReason(current, riskContext.intervalSeconds)
      if (pause) {
        setAutoMessage(`Recovery paused: ${pause}`)
        return
      }
      recoveryAttempted.current.add(scopeKey)
      setLeverage(saved.settings.leverage)
      setBalanceFraction(saved.settings.balanceFraction)
      setQuantity(saved.settings.manualQuantity)
      setAutoMessage('Recovered · Delta orders and protection reconciled.')
      const token = saved.generation
      setRecoveryPending(false)
      autoPermit.current = token
      setAutoArm({ scope: scopeKey, token })
    } catch {
      recoveryAttempted.current.add(scopeKey)
      setRecoveryPending(true)
      setAutoMessage(
        'Recovery paused: saved settings could not be verified. Turn Off to cancel recovery.'
      )
    }
  }, [
    autoEnabled,
    enabled,
    valid,
    current,
    pending,
    storageFailed,
    storageChecked,
    currentStorageKey,
    riskContext,
    symbol,
    scopeKey,
  ])
  useEffect(() => {
    if (
      backendAutomation ||
      !browserAutoEnabled ||
      !autoArm ||
      !canAct ||
      entryExposureReason ||
      autoManagedPlan ||
      review ||
      !validEntry ||
      !protectionPlan ||
      !riskContext ||
      riskContext.symbol !== symbol
    )
      return
    if (
      current?.managed_plans?.some(
        (plan) =>
          plan.interval_seconds === riskContext.intervalSeconds &&
          plan.source_time >= riskContext.sourceTime
      )
    ) {
      setAutoMessage('This signal already has a trade. Waiting for a new candle.')
      return
    }
    if (autoLoopBusy.current) return
    autoLoopBusy.current = true
    const token = autoArm.token
    void withDeltaAutoEntryLock(current!.account, symbol, async () => {
      if (!automaticAuthorized(token)) {
        stopAuto(false)
        setAutoMessage('Auto permission changed. No order was sent.')
        return
      }
      try {
        if (
          !claimDeltaAutoEntry(
            localStorage,
            current!.account,
            symbol,
            riskContext.intervalSeconds,
            riskContext.sourceTime
          )
        ) {
          setAutoMessage('This candle was already checked. Waiting for a new candle.')
          return
        }
      } catch {
        stopAuto()
        setAutoMessage('Auto stopped: safe request tracking is unavailable.')
        return
      }
      setAutoMessage('Checking the latest eligible setup…')
      await placeEntry({ token, source: riskContext.sourceTime })
    })
      .then((acquired) => {
        if (!acquired && autoPermit.current === token)
          setAutoMessage('Another chart is checking this account. Waiting…')
      })
      .catch(() => {
        if (autoPermit.current === token) {
          stopAuto(false)
          setAutoMessage('Auto paused: this browser could not lock the entry safely.')
        }
      })
      .finally(() => {
        autoLoopBusy.current = false
      })
  }, [
    autoEnabled,
    autoArm,
    canAct,
    entryExposureReason,
    autoManagedPlan,
    review,
    validEntry,
    protectionPlan?.source_time,
    protectionPlan?.stop,
    protectionPlan?.target,
    current?.asof,
    riskContext,
    quantity,
    selectedLeverage,
    symbol,
  ])
  if (!enabled) return null
  const editOrder = metadataValid ? current?.orders.find((order) => order.id === editId) : undefined
  const adoptionPlan =
    riskContext !== undefined ? buildDeltaAdoption(current, managementRiskContext) : null
  const hasManagedPosition = current?.managed_plans?.some(
    (plan) => !['completed', 'cancelled', 'rejected', 'blocked'].includes(plan.status)
  )
  const hasBlockedPlan = current?.managed_plans?.some((plan) => plan.status === 'blocked')
  const restoredEntryTimer =
    current?.managed_plans?.reduce<{ key: string; startedAt: number } | null>((latest, plan) => {
      if (
        !plan.entry_order_id ||
        typeof plan.entry_request_id !== 'string' ||
        !plan.entry_request_id ||
        typeof (plan.first_fill_at ?? plan.placed_at) !== 'number' ||
        !Number.isFinite(plan.first_fill_at ?? plan.placed_at) ||
        (plan.first_fill_at ?? plan.placed_at)! <= 0 ||
        (plan.first_fill_at ?? plan.placed_at)! > Date.now() / 1000 + 1
      )
        return latest
      return !latest || (plan.first_fill_at ?? plan.placed_at)! > latest.startedAt
        ? {
            key: `entry:${plan.entry_request_id}${plan.first_fill_at ? ':filled' : ''}`,
            startedAt: (plan.first_fill_at ?? plan.placed_at)!,
          }
        : latest
    }, null) ?? null
  const acknowledgedEntryTimer =
    entryTimerPlacement?.account === current?.account && entryTimerPlacement?.symbol === symbol
      ? entryTimerPlacement
      : null
  const timerPlacement =
    acknowledgedEntryTimer &&
    (!restoredEntryTimer || acknowledgedEntryTimer.startedAt >= restoredEntryTimer.startedAt)
      ? acknowledgedEntryTimer
      : restoredEntryTimer
  const accounting =
    valid &&
    displayState?.accounting?.currency === 'USD' &&
    ['verified', 'incomplete', 'flat', 'unavailable'].includes(displayState.accounting.fee_status)
      ? displayState.accounting
      : null
  const finiteAmount = (value: unknown): value is number =>
    typeof value === 'number' && Number.isFinite(value)
  const accountAmount = (value: unknown) =>
    finiteAmount(value) ? `USD ${money(value)} (${formatDeltaINR(value)})` : '—'
  const estimatedExitFee =
    accounting?.exit_fee_basis === 'taker' ? accounting.estimated_exit_fee : null
  const netPnl =
    (accounting?.fee_status === 'verified' || accounting?.fee_status === 'flat') &&
    finiteAmount(accounting.position_gross_pnl) &&
    finiteAmount(accounting.position_entry_fees) &&
    finiteAmount(estimatedExitFee) &&
    finiteAmount(accounting.position_net_after_fees)
      ? accounting.position_net_after_fees
      : null
  const pnlClass = (value: unknown) =>
    finiteAmount(value) && value !== 0
      ? value > 0
        ? 'text-emerald-500'
        : 'text-rose-500'
      : 'text-muted-foreground'
  const livePlan = Array.isArray(current?.managed_plans) ? current.managed_plans.find((plan) => plan && !['completed', 'cancelled', 'rejected'].includes(plan.status)) : undefined
  const restingEntry = Array.isArray(current?.orders) ? current.orders.find((order) => order && order.kind === 'entry' && ['open', 'pending'].includes(order.state)) : undefined
  const executionStatus = !valid ? 'Waiting for fresh broker data.'
    : sending ? 'Sending request · waiting for Delta acknowledgement.'
    : pending ? 'Reconciling request · new entries paused.'
    : current?.position && current.position.size !== 0
      ? livePlan?.status === 'closing' ? 'Exiting · waiting for Delta fill and a flat position.'
        : `Position open · ${livePlan?.message || 'tracking live P&L and protection.'}`
    : restingEntry ? `Maker order ${restingEntry.id} resting · ${restingEntry.unfilled} lots waiting for a fill. New entries paused.`
    : livePlan ? `Reconciliation · ${livePlan.message}`
    : 'No open trade · checking the next eligible EMA setup.'
  return (
    <details
      open
      className="w-full max-w-[280px] shrink-0 rounded border border-border bg-card text-xs"
      aria-label="Delta live trading"
      onPointerDownCapture={() => readySound()}
      onKeyDownCapture={() => readySound()}
    >
      <summary className="cursor-pointer px-3 py-2 font-medium">Delta · {symbol}</summary>
      <div className="max-h-[65vh] space-y-3 overflow-y-auto border-t border-border p-3 lg:max-h-[75vh]">
        <p role="status">
          {error ||
            (!current
              ? 'Connecting…'
              : !current.connected
                ? 'Disconnected'
                : !fresh
                  ? 'Stale broker data. Trading paused.'
                  : valid
                    ? storageChecked === currentStorageKey
                      ? 'Live · India'
                      : 'Checking saved requests…'
                    : 'Trading paused.')}
        </p>
        {valid && current && (
          <>
            <p className="text-muted-foreground">
              Updated{' '}
              {new Date(current.asof * 1000).toLocaleTimeString(undefined, {
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })}{' '}
              · broker leverage {current.leverage == null ? '—' : `${current.leverage}×`} · account
              polling ~2s after each response
            </p>
            <p className="text-muted-foreground">Drag an order line to review a price change.</p>
            <p className="text-muted-foreground">Fixed conversion $1 = ₹{DELTA_USD_INR}</p>
          </>
        )}
        {current?.account && <DeltaTradeAlerts account={current.account} symbol={symbol} />}
        {valid && displayState?.position && (
          <p aria-label="P&L data freshness" className="text-muted-foreground">
            {streamedValuation && markTick
              ? `P&L: live mark · ${Math.max(0, now - markTick.receivedAt)} ms since received. Delta publishes marks about every 2s.`
              : 'P&L: broker snapshot · waiting for a fresh mark message.'}
          </p>
        )}
        {notice && !entryNotice.current && <DeltaOrderNotice notice={notice} />}
        {pending && (
          <p role="alert">
            Pending broker outcome. New actions paused; reconcile orders before submitting again.
          </p>
        )}
        {Array.isArray(current?.pending) &&
          current.pending.map((item) => <p key={item.request_id}>{item.message}</p>)}
        {current && !current.connected && (
          <form
            className="space-y-2"
            onSubmit={async (event) => {
              event.preventDefault()
              if (connecting) return
              const key = apiKey
              const secret = apiSecret
              setApiKey('')
              setApiSecret('')
              setConnecting(true)
              try {
                const result = await deltaChartApi.connection(key, secret)
                setNotice(result.message || 'Connection saved. Checking broker…')
              } catch {
                setNotice('Connection failed. Check your Delta India credentials.')
              } finally {
                setConnecting(false)
              }
            }}
          >
            <p>{current.message || 'Connect Delta India. Credentials stay on the server.'}</p>
            <label className="block">
              API key
              <input
                aria-label="Delta API key"
                autoComplete="off"
                type="password"
                className={inputClass}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </label>
            <label className="block">
              API secret
              <input
                aria-label="Delta API secret"
                autoComplete="off"
                type="password"
                className={inputClass}
                value={apiSecret}
                onChange={(event) => setApiSecret(event.target.value)}
              />
            </label>
            <button className={buttonClass} disabled={connecting || !apiKey || !apiSecret}>
              Connect Delta
            </button>
          </form>
        )}
        <div className="sticky top-0 z-10 space-y-1 rounded border border-border bg-card p-2">
          <p role="status" aria-label="Live execution status">{executionStatus}</p>
          {valid && displayState?.position && <>
            <p aria-label="Live profit after fees" className={`font-semibold tabular-nums ${pnlClass(netPnl)}`}>Net after fees: {formatDeltaINR(netPnl)}</p>
            <p aria-label="Live fee deductions" className="text-muted-foreground">Entry fee {formatDeltaINR(accounting?.position_entry_fees)} · Exit fee estimate {formatDeltaINR(estimatedExitFee)}</p>
          </>}
          <button
            className="w-full rounded bg-rose-700 py-2 font-medium text-white disabled:opacity-40"
            disabled={!canReviewClose}
            onClick={beginClose}
          >
            Close position
          </button>
          <p className="text-muted-foreground">
            {current?.position ? 'Market exit · taker fees and slippage apply' : 'No open position'}
          </p>
          {current?.position && !canAct && (
            <p role="status">Close submission paused: {entryDisabledReason}</p>
          )}
          {riskContext !== undefined && current?.position && (
            <>
              <button
                className={buttonClass + ' w-full'}
                disabled={!canAct || !adoptionPlan || !!hasManagedPosition}
                onClick={() =>
                  adoptionPlan &&
                  prepare({
                    action: 'adopt',
                    side: current.position!.size > 0 ? 'buy' : 'sell',
                    auto_protection: adoptionPlan.protection,
                    existing_stop: adoptionPlan.existingStop,
                    existing_target: adoptionPlan.existingTarget,
                  })
                }
              >
                {hasBlockedPlan
                  ? 'Review updated position protection'
                  : 'Review automatic SL for this position'}
              </button>
              {hasBlockedPlan && !hasManagedPosition && (
                <p className="text-muted-foreground">
                  The broker protection changed. Review it again to resume automatic checks.
                </p>
              )}
              {!adoptionPlan && !hasManagedPosition && (
                <p className="text-muted-foreground">
                  Waiting for a valid position protection plan and clear existing SL/target.
                </p>
              )}
            </>
          )}
        </div>
        {backendAutomation && current ? <DeltaBackendAuto
          automation={backendAutomation} account={current.account} symbol={symbol} valid={valid} observedAt={current.asof}
          leverage={selectedLeverage} balanceFraction={balanceFraction} manualQuantity={manualQuantity}
          onChanged={automation => setSnapshot(previous => previous?.account === current.account ? {...previous,automation} : previous)}
        /> : <>
        <div className="rounded border border-border p-2 space-y-1">
          <label className="flex items-center justify-between font-medium">
            Auto trading
            <button
              type="button"
              role="switch"
              aria-label="Auto trading"
              aria-checked={autoEnabled || recoveryPending}
              disabled={
                !autoEnabled &&
                !recoveryPending &&
                (!valid ||
                  storageFailed ||
                  storageChecked !== currentStorageKey ||
                  riskContext?.symbol !== symbol)
              }
              onClick={() => {
                if (autoEnabled || recoveryPending) stopAuto()
                else {
                  const token = crypto.randomUUID()
                  if (
                    !current ||
                    !riskContext ||
                    !saveAutoRecovery({
                      version: 1,
                      ...(executionMode ? { strategy: executionMode } : {}),
                      generation: token,
                      account: current.account,
                      symbol,
                      seconds: riskContext.intervalSeconds,
                      settings: {
                        leverage: selectedLeverage,
                        balanceFraction,
                        manualQuantity: balanceFraction === null ? manualQuantity : '1',
                      },
                    })
                  ) {
                    setAutoMessage('Auto not started: recovery settings could not be saved.')
                    return
                  }
                  recoveryAttempted.current.add(scopeKey)
                  autoPermit.current = token
                  setAutoMessage('Watching for an eligible trend…')
                  setAutoArm({ scope: scopeKey, token })
                }
              }}
              className={`rounded px-3 py-1 text-white disabled:opacity-40 ${autoEnabled ? 'bg-emerald-600' : 'bg-slate-600'}`}
            >
              {recoveryPending ? 'Paused · turn Off' : autoEnabled ? 'On' : 'Off'}
            </button>
          </label>
          {executionMode && (
            <div aria-label="Scalping timeframes" className="space-y-1">
              <p className="font-medium">Scalping · 1m entry / 5m trend</p>
              <p>{riskContext?.trendSummary || 'Checking fresh 1m and 5m candles…'}</p>
              <p className="text-muted-foreground">
                Chart timeframe is for viewing. Targets must cover estimated fees.
              </p>
            </div>
          )}
          <p className="text-muted-foreground">
            Auto entry → SL/target → trailing → exit. Keep this chart open. Off stops new entries;
            open trades keep protection. Resume after reload follows verified Delta reconciliation.
            Turn Off to change sizing.
          </p>
          <p role="status" aria-label="Auto trading status" className="text-muted-foreground">
            {!autoEnabled
              ? autoMessage || 'Off · no automatic entries.'
              : sending
                ? 'Checking / placing…'
                : !valid
                  ? 'Paused · waiting for fresh Delta data.'
                  : pending
                    ? 'Waiting for broker confirmation.'
                    : current?.position
                      ? 'Managing the open trade and its protection.'
                      : entryExposureReason || autoManagedPlan
                        ? 'Waiting for the current orders and protection to finish.'
                        : !validEntry
                          ? 'Waiting for enough balance for a whole lot.'
                          : !protectionPlan
                            ? protectionPauseReason
                            : autoMessage || 'Watching for an eligible trend…'}
          </p>
        </div>

        </>}
        <section aria-label="Manual order" className="rounded border border-border p-2 space-y-2">
          <h3 className="font-medium">Manual order</h3>
          <p className="text-muted-foreground">
            You choose the direction. Trend and sharp-move filters are skipped. Maker-only pricing,
            balance checks, SL, target and trailing stay on.
          </p>
          <label className="block">
            Direction
            <select
              aria-label="Manual direction"
              disabled={!canAct || autoEnabled || recoveryPending}
              value={manualSide}
              onChange={(e) => setManualSide(e.target.value as 'buy' | 'sell')}
              className={inputClass}
            >
              <option value="buy">Long · best bid</option>
              <option value="sell">Short · best offer</option>
            </select>
          </label>
          <p>
            {quantity} lots · {selectedLeverage}× · maker-only · sizing below
          </p>
          {(autoEnabled || recoveryPending) && (
            <p role="status" className="text-amber-500">
              Turn Auto off to place a manual order.
            </p>
          )}
          <button
            type="button"
            className={`w-full rounded py-2 text-white disabled:opacity-40 ${manualSide === 'buy' ? 'bg-emerald-600' : 'bg-rose-600'}`}
            disabled={
              autoEnabled || recoveryPending || !canAct || !!entryExposureReason || !validEntry
            }
            onClick={() => void placeEntry(undefined, manualSide)}
          >
            Place manual {manualSide === 'buy' ? 'Long' : 'Short'}
          </button>
        </section>

        <fieldset disabled={!valid || autoEnabled || recoveryPending} className="space-y-2">
          <legend className="mb-1 font-medium">New live order</legend>
          <div className="flex items-center justify-between">
            <span className="rounded bg-muted px-2 py-1">Maker-only</span>
            <span className="rounded bg-muted px-2 py-1">GTC</span>
          </div>
          <label className="block">
            Quantity (lots)
            <input
              aria-label="Quantity (lots)"
              type="number"
              min="1"
              step="1"
              value={quantity}
              onChange={(event) => {
                setDefaultsNotice('')
                setBalanceFraction(null)
                setQuantity(event.target.value)
              }}
              className={inputClass}
            />
          </label>
          <div className="flex gap-1" aria-label="Available balance sizing">
            {([0.1, 0.25, 0.5, 0.75, 1] as const).map((fraction) => (
              <button
                key={fraction}
                className={buttonClass}
                aria-pressed={balanceFraction === fraction}
                disabled={!canAct || !canSize}
                onClick={() => {
                  setBalanceFraction(fraction)
                  setDefaultsNotice('')
                }}
              >
                {fraction * 100}%
              </button>
            ))}
          </div>
          {sizingAvailable ? (
            <p className="text-muted-foreground">
              Available margin: USD {usdMoney(current?.sizing?.available_balance)}
            </p>
          ) : (
            <p className="text-muted-foreground">Balance unavailable</p>
          )}
          {sizingAvailable && !canSize && <p>Enter a limit price to size from balance.</p>}
          {balanceFraction !== null && sizedContracts === 0 && (
            <p>Balance too small at this leverage</p>
          )}
          <p className="text-muted-foreground">
            1 lot = {money(current?.product?.contract_value)} {coin} · selected total{' '}
            {money(selectedCoinQuantity)} {coin}
          </p>
          <p>
            Best Bid {money(current?.ticker?.bid)} · Best Offer {money(current?.ticker?.ask)}
          </p>
          <p
            className="text-muted-foreground"
            title="Fresh best bid for Long, best offer for Short. Maker-only orders may wait to fill; profit is not guaranteed."
          >
            Auto price · Long at bid / Short at offer
          </p>
          <label className="block">
            Leverage <strong>{selectedLeverage}×</strong>
            <input
              aria-label="Leverage"
              type="range"
              min="1"
              max="200"
              step="1"
              value={selectedLeverage}
              onChange={(event) => {
                setLeverage(Math.min(cap, Number(event.target.value)))
                setDefaultsNotice('')
              }}
              className="w-full accent-primary"
            />
          </label>
          <div className="flex justify-between text-muted-foreground">
            <span>1×</span>
            <span>200×</span>
          </div>
          {cap < 200 && <p className="text-muted-foreground">Contract limit: {cap}×</p>}
          <p className="text-muted-foreground">Funds required: USD {usdMoney(fundsRequired)}</p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className={buttonClass}
              disabled={!valid || !validEntry}
              onClick={() => {
                const saved = saveDeltaTradeDefaults({
                  leverage: selectedLeverage,
                  balanceFraction,
                  manualQuantity: balanceFraction === null ? manualQuantity : '1',
                })
                setDefaultsNotice(
                  saved
                    ? 'Defaults saved for future charts.'
                    : 'Could not save defaults in this browser.'
                )
              }}
            >
              Save defaults
            </button>
            <span
              role="status"
              aria-label="Trading defaults status"
              className="text-muted-foreground"
            >
              {defaultsNotice}
            </span>
          </div>

          {riskContext !== undefined && (
            <div className="space-y-1 rounded border border-border p-2">
              <p className="font-medium">
                {executionMode
                  ? 'Automatic scalp SL / target'
                  : 'Required SL / target from chart trend'}
              </p>
              {protectionPlan ? (
                <>
                  <p>
                    Managed SL {money(protectionPlan.stop)} · target {money(protectionPlan.target)}
                  </p>
                  <p className="text-muted-foreground">
                    Tighten SL after fee-aware profit; cancel an unfilled entry or close on opposite
                    trend.
                  </p>
                </>
              ) : null}
            </div>
          )}

          {!backendAutomation && <p>One click checks, then places or shows an error.</p>}
          {notice && entryNotice.current && (
            <DeltaOrderNotice ref={entryFeedback} notice={notice} quietSuccess />
          )}
          {!backendAutomation && entryDisabledReason && (
            <p role="status" aria-label="Entry pause reason">
              Entry paused: {entryDisabledReason}
            </p>
          )}

          {!backendAutomation && <button
            className={`w-full rounded py-2 font-medium text-white disabled:opacity-40 ${!hasEntryDirection ? 'bg-slate-600' : entrySide === 'buy' ? 'bg-emerald-600' : 'bg-rose-600'}`}
            disabled={autoEnabled || !hasEntryDirection || !canAct || !!entryExposureReason}
            onClick={() => void placeEntry()}
          >
            {sending && entryClickLock.current
              ? 'Checking / placing…'
              : autoEnabled
                ? 'Auto trading on'
                : hasEntryDirection
                  ? `Place ${entrySide === 'buy' ? 'Long' : 'Short'}`
                  : 'Waiting for trend'}
          </button>}

          {current?.position && (
            <div className="space-y-2 border-t border-border pt-2">
              <p className="font-medium">Position protection · market SL / maker target</p>
              <label className="block">
                SL trigger price
                <input
                  aria-label="Stop price"
                  type="number"
                  min="0"
                  step={current?.product?.tick_size || 'any'}
                  value={stop}
                  onChange={(event) => setStop(event.target.value)}
                  className={inputClass}
                />
              </label>
              <button
                className={buttonClass}
                disabled={!canAct || !current.position.version || !positive(stop)}
                onClick={() => prepare({ action: 'protect', stop: Number(stop) })}
              >
                Add market SL
              </button>
              <p className="text-muted-foreground">
                Triggered SL exits at market; taker fees and slippage apply.
              </p>
              <label className="block">
                Target limit price
                <input
                  aria-label="Target price"
                  type="number"
                  min="0"
                  step={current?.product?.tick_size || 'any'}
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                  className={inputClass}
                />
              </label>
              <button
                className={buttonClass}
                disabled={!canAct || !current.position.version || !positive(target)}
                onClick={() => prepare({ action: 'protect', target: Number(target) })}
              >
                Add maker target
              </button>
            </div>
          )}
        </fieldset>
        {accounting && (
          <section
            aria-label="Delta account summary"
            className="space-y-2 rounded border border-border bg-muted/20 p-2"
          >
            <p className="font-medium">Live Delta account</p>
            <dl className="space-y-1">
              <div className="flex justify-between gap-2">
                <dt>Balance</dt>
                <dd className="tabular-nums">{accountAmount(accounting.balance)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>Available</dt>
                <dd className="tabular-nums">{accountAmount(accounting.available_balance)}</dd>
              </div>
              {(current?.position || accounting.fee_status === 'flat') && (
                <>
                  <div className="flex justify-between gap-2 border-t border-border pt-1">
                    <dt>Live P&amp;L (before fees)</dt>
                    <dd className={`tabular-nums ${pnlClass(accounting.position_gross_pnl)}`}>
                      {formatDeltaINR(accounting.position_gross_pnl)}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt title="Already charged on fills. Changes only when the position receives another fill.">
                      Entry fees paid
                    </dt>
                    <dd className="tabular-nums">
                      {formatDeltaINR(accounting.position_entry_fees)}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt title="Estimated market exit fee at the latest mark, including GST. Actual fee is known after the exit fills.">
                      Est. closing fees{accounting.exit_fee_basis === 'taker' ? ' (taker)' : ''}
                    </dt>
                    <dd className="tabular-nums">{formatDeltaINR(estimatedExitFee)}</dd>
                  </div>
                  <div className="flex justify-between gap-2 border-t border-border pt-1 font-semibold">
                    <dt>Est. net P&amp;L after fees</dt>
                    <dd className={`text-sm tabular-nums ${pnlClass(netPnl)}`}>
                      {formatDeltaINR(netPnl)}
                    </dd>
                  </div>
                </>
              )}
            </dl>
            <p className="text-muted-foreground">
              Fees include GST. Paid entry fees stay fixed until another fill. Closing fee varies
              with mark; actual cost is known after exit. Balance already reflects charged fees.
            </p>
            <p className="text-muted-foreground">
              {backendAutomation
                ? 'Scalp risk limit ₹20 including fees. Profit threshold: USD 0.15 net (₹12.75). Smart trailing reduces structural risk before that threshold. After that threshold, a structural stop covers actual fees and a tick of profit when structure allows, then protects ₹10 when structure allows. SL trails behind completed candles and ATR and only tightens. Trend mode has no fixed ₹10 giveback exit or 2R profit cap. Stop levels can slip at execution.'
                : 'Scalp risk limit ₹20 including fees. Smart trailing activates at ₹15 net and protects ₹10; then trails with up to ₹10 planned giveback from the observed peak. Stop levels can slip at execution.'}
            </p>
            {current?.managed_plans?.filter(p => p.status === 'active' && p.smart_profit_tracking).map(p => (
              <p key={p.id} className="text-muted-foreground">Smart profit tracking on · highest observed net {typeof p.peak_net_inr === 'number' ? `₹${p.peak_net_inr.toFixed(2)}` : 'waiting for a verified fill snapshot'} · SL only tightens.</p>
            ))}
            {typeof accounting.message === 'string' && accounting.message && (
              <p className="text-muted-foreground">{accounting.message}</p>
            )}
          </section>
        )}
        {valid && current && (
          <DeltaTradeTimer
            account={current.account}
            symbol={symbol}
            autoStartKey={timerPlacement?.key}
            startedAt={timerPlacement?.startedAt}
          />
        )}
        {(riskContext !== undefined || current?.managed_plans?.length) && (
          <div className="space-y-1 rounded border border-border p-2">
            <p>
              Automatic checks while this live chart is open; exchange SL/target stay active. SL
              tightens after price covers verified fees plus a half-ATR price buffer; it never
              widens.
            </p>
            {current?.managed_plans?.map((plan) => (
              <p key={plan.id}>
                {plan.side === 'buy' ? 'Long' : 'Short'} · {plan.status} · SL {money(plan.stop)} ·
                target {money(plan.target)}
                {plan.message ? ` · ${plan.message}` : ''}
              </p>
            ))}
            {current?.managed_plans?.some(
              (plan) =>
                managementRiskContext?.intervalSeconds !== plan.interval_seconds &&
                !['blocked', 'completed', 'cancelled', 'rejected'].includes(plan.status)
            ) && <p>Automatic checks paused: return to the plan's chart interval.</p>}
            {autoManagement.message && <p role="status">{autoManagement.message}</p>}
          </div>
        )}
        {valid && current?.position && (
          <div className="space-y-1">
            <p>
              {current.position.size > 0 ? 'Long' : 'Short'} · {Math.abs(current.position.size)}{' '}
              contracts · entry {money(current.position.entry)}
            </p>
            {!accounting && (
              <p>Gross unrealized P&amp;L (INR): {formatDeltaINR(displayState?.position?.pnl)}</p>
            )}
            <p>
              Mark {money(displayState?.position?.mark)} · liquidation{' '}
              {money(current.position.liquidation)}
            </p>
          </div>
        )}

        {valid && current && (
          <div className="space-y-2">
            <p className="font-medium">Broker orders ({current.orders.length})</p>
            {current.orders.map((order) => (
              <div key={order.id} className="space-y-1 border-t border-border pt-1">
                <p>
                  {order.side} {order.unfilled}/{order.size} ·{' '}
                  {order.kind === 'entry' && order.reduce_only ? 'exit' : order.kind} ·{' '}
                  {money(order.price)} ·{' '}
                  {order.type === 'market_order'
                    ? 'market / taker'
                    : order.post_only
                      ? 'maker'
                      : 'not maker'}{' '}
                  · {order.state}
                </p>
                <div className="flex gap-2">
                  <button
                    className={buttonClass}
                    disabled={!canAct || order.price == null || !editableOrder(order)}
                    onClick={() => {
                      setEditId(order.id)
                      setEditPrice(String(order.price))
                    }}
                  >
                    Edit {order.id}
                  </button>
                  <button
                    className={buttonClass}
                    disabled={!canAct}
                    onClick={() =>
                      prepare({ action: 'cancel', order_id: order.id, version: order.version })
                    }
                  >
                    Cancel {order.id}
                  </button>
                </div>
              </div>
            ))}
            {editOrder && (
              <div className="space-y-1">
                <label className="block">
                  Order price
                  <input
                    aria-label="Order price"
                    type="number"
                    min="0"
                    step={current.product.tick_size}
                    className={inputClass}
                    value={editPrice}
                    onChange={(event) => setEditPrice(event.target.value)}
                  />
                </label>
                <button
                  className={buttonClass}
                  disabled={!canAct || !positive(editPrice) || !editableOrder(editOrder)}
                  onClick={() =>
                    prepare({
                      action: 'edit',
                      order_id: editOrder.id,
                      version: editOrder.version,
                      price: Number(editPrice),
                    })
                  }
                >
                  Review price edit
                </button>
              </div>
            )}
            <p className="font-medium">Recent fills</p>
            {current.fills.length ? (
              current.fills.slice(0, 5).map((fill) => (
                <p key={fill.id}>
                  {fill.side} {fill.size} @ {money(fill.price)}
                </p>
              ))
            ) : (
              <p>No recent fills</p>
            )}
          </div>
        )}
        {review && (
          <div
            ref={reviewElement}
            tabIndex={-1}
            role="dialog"
            aria-label="Review live order"
            className="space-y-2 rounded border border-amber-500 p-2"
          >
            <p className="font-medium">Review live order · {review.symbol}</p>
            <p>
              Delta India · {review.action} · {review.side}{' '}
              {review.size ? `${review.size} lots` : ''}
            </p>
            {review.action === 'close' ? (
              <p>Market exit · taker fees and slippage apply</p>
            ) : review.stop ||
              (review.action === 'edit' &&
                current?.orders.find((order) => order.id === review.order_id)?.kind === 'sl') ? (
              <p>Market SL · taker fees and slippage apply</p>
            ) : (
              <p>Maker-only entry / target · waits to fill.</p>
            )}
            {review.order_id && <p>Order {review.order_id}</p>}
            {review.price && <p>Price {money(review.price)}</p>}
            {review.leverage && <p>Leverage {review.leverage}×</p>}
            {review.balance_fraction && reviewBudget !== null && (
              <p>
                {review.balance_fraction * 100}% balance budget: USD {money(reviewBudget)}
              </p>
            )}
            {review.action === 'adopt' && (
              <div className="space-y-1">
                <p>Registers automatic protection; creates no new entry.</p>
                <p>
                  Existing SL stays active until the full-size market SL replacement is
                  acknowledged.
                </p>
                {review.existing_stop && <p>Replace SL {review.existing_stop.id}</p>}
                {review.existing_target && <p>Replace target {review.existing_target.id}</p>}
              </div>
            )}
            {review.auto_protection && (
              <div className="space-y-1 border-t border-border pt-1">
                <p>
                  Managed SL {money(review.auto_protection.stop)} · target{' '}
                  {money(review.auto_protection.target)}
                </p>
                <p>{review.auto_protection.reason}</p>
                <p>
                  Market SL and maker-only target are managed as entry fills are verified. Market
                  exits incur taker fees and slippage.
                </p>
                <p>
                  Tighten SL after fee-aware profit; cancel an unfilled entry or close on opposite
                  trend.
                </p>
                <p>
                  Automatic checks while this live chart is open; exchange SL/target stay active. SL
                  tightens after price covers verified fees plus a half-ATR price buffer; it never
                  widens.
                </p>
              </div>
            )}
            {review.stop && <p>SL trigger {money(review.stop)}</p>}
            {review.target && <p>Target limit {money(review.target)}</p>}
            <p>Live funds. Entries and targets remain maker-only; market exits can slip.</p>
            {!canAct && <p role="status">Submission paused: {entryDisabledReason}</p>}
            <button className={buttonClass} disabled={!canAct} onClick={() => void send()}>
              {review.action === 'adopt' ? 'Register automatic protection' : 'Send live order'}
            </button>{' '}
            <button className={buttonClass} onClick={() => setReview(null)}>
              Back
            </button>
          </div>
        )}
      </div>
    </details>
  )
}
