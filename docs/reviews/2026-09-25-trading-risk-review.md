# Trading safety review — 25 September 2026

## Verdict

**Not ready for unattended live trading.** The reviewed paths contain avoidable loss risks. A sandbox trial currently does not exercise the same portfolio admission controls as live mode. Passing tests do not establish profitability or a guaranteed maximum loss.

The earlier claim of a ₹12,000 maximum daily loss, calculated as 12 strategies × ₹1,000, was not supported by the implementation. The configured amounts are local stop triggers, not guaranteed loss ceilings. Re-entry, execution price, costs, and failed or ambiguous exits can exceed them.

Scope: Strategy Module, its Flow entry paths, authorization, portfolio admission, entry/exit dispatch, recovery, tick feed, lifecycle alerts, and installed local configuration. Database inspection was read-only. No real broker calls, orders, live-mode changes, or production fixes were made. The exact OpenAlgo MCP connection was not available in this review, so broker positions, funds, current quotes, and live execution were **not** independently verified. No substitute market feed was used.

## Observed local configuration

- 12 saved strategies; all have live execution disabled and no current run.
- 12 active workflows; their execution nodes select sandbox.
- Installed strategy entries use MARKET orders and MIS; each has ₹1,000 overall and daily stop settings.
- Two historical sandbox runs were recorded; neither remains open. Local history is not broker confirmation or evidence of a successful market-session trial.
- The configured WebSocket server port is 8766, while the strategy feed's default client call selects 8765.

These observations describe the snapshot reviewed, not a continuing monitoring guarantee.

## Findings requiring correction before live use

### 1. P1 — Ambiguous broker responses are classified as rejections

[order_dispatch.py:349](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/order_dispatch.py:349) catches placement exceptions and returns `ok=False`. The engine then [marks an entry rejected](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/engine.py:900) or [releases an exit claim](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/engine.py:1502).

A timeout can happen after a broker accepted an order. Treating it as a definitive rejection can lose track of exposure or permit a duplicate exit. A mocked timeout reproduced the classification. Existing recovery for an exception escaping dispatch or a lost database acknowledgement does not repair this swallowed-exception path.

Required: distinguish rejected from unknown; retain the durable intent and exposure reservation; reconcile against authoritative broker state before retrying or releasing it. Where a broker cannot support exact reconciliation/idempotency, stop new entries and require operator resolution rather than blindly retrying.

### 2. P1 — Sandbox bypasses portfolio admission controls

[portfolio_governor.py:1518](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/portfolio_governor.py:1518) immediately allows sandbox entries without collecting facts or acquiring an admission lease. The pure evaluator has the same bypass at line 648.

Consequently, the paper trial does not validate this governor's position caps, combined risk, cash buffer, cooldown, or portfolio daily-loss lock. Sandbox execution still has its own checks, such as simulated funds and contract validation; those do not replace portfolio policy. A probe confirmed fact collection was never called.

Required: apply the same risk policy to isolated sandbox funds, exposure, and reservations, with only the execution destination changing. Test parity and concurrent-entry limits.

### 3. P1 — A spent strategy daily budget does not block a new batch entry

[engine.py:289](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/engine.py:289) checks time and live enablement before starting, but daily strategy loss is evaluated [after entry on a tick](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/engine.py:2335). The new workflows [call the batch start path](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/flow_executor_service.py:2071).

A simulated strategy with a ₹1,000 daily limit successfully started while its historical daily P&L provider was set to −₹1,500; the provider was not even consulted during start. A later tick can close it again, allowing repeated entry/exit churn and additional losses or charges.

Required: a persistent, session-scoped daily lock checked before every entry, including batch, scheduled, manual, and existing signal runs. Exits must remain available. Missing P&L evidence must block entry rather than bypass the limit.

### 4. P1 — Protective exits depend on the local process

[Entry placement](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/engine.py:812) does not create a broker-held protective stop after a fill. [Stop evaluation](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/engine.py:2243) runs locally and then dispatches an exit; [exit orders are MARKET](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/order_dispatch.py:45).

An app crash, sleeping laptop, power failure, or lost connectivity can prevent that exit. Recovery after restart is useful but does not protect the interval while the app is unavailable.

Required: explicitly supported broker-side protection, sized to actual fills and reconciled with local exits so both cannot over-close. Refuse unsupported live setups, detect unprotected quantities, and provide an independent operational watchdog. A broker-held stop still does not guarantee execution at its trigger price.

### 5. P1 — Entry admission lacks quote freshness and spread/liquidity checks

[portfolio_governor.py:909](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/portfolio_governor.py:909) accepts a positive ask, or LTP when ask is absent, without checking quote age, bid/ask spread, or executable depth. A probe accepted a prior-day quote with bid ₹1, ask ₹200, and zero volume/OI. This proves the quote-validation gap, not that every subsequent live authorization check would also pass.

The installed MARKET entries have no executable price cap. A configured stop-distance estimate is therefore not a bound on actual fill-to-exit loss.

Required: fresh, coherent broker evidence; instrument-specific spread and executable-liquidity thresholds; fail closed when required fields are missing; bounded entry prices and cancellation/reconciliation of unfilled quantities. Illiquid MCX options need particular scrutiny.

### 6. P1 — Old candles can be treated as a current signal

[flow_executor_service.py:2184](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/flow_executor_service.py:2184) returns a successful closed-bar result without verifying the expected current exchange candle. [indicator_service.py:519](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/indicator_service.py:519) removes forming bars but does not reject old ones. A probe returned a previous-day candle as the successful latest 5-minute signal bar.

Required: verify expected completed timestamps against the exchange session and interval, sufficient history, coherent 5/15-minute samples, and a consumed-signal identifier. Historical lookback bars should remain allowed, but they must not masquerade as the current trigger.

### 7. P1 — Strategy tick client uses the wrong configured port

[tick_feed.py:973](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/tick_feed.py:973) calls the shared client without endpoint parameters. [websocket_client.py:764](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/websocket_client.py:764) defaults to localhost:8765; this installation is configured for 8766.

REST fallback exists: default inactivity threshold 10 seconds, polling every 2 seconds, fatal stale threshold 60 seconds. Therefore this is degraded protection, not evidence that every stop is disabled. The broker order-update stream is separate and does not prove option price ticks reach the strategy engine.

Required: honor the configured endpoint and validate actual strategy-instrument ticks, fallback transitions, and stale-data exits through the deployed runtime.

### 8. P1 — Portfolio daily loss is not an aggregate emergency loss ceiling

[portfolio_governor.py:1214](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/portfolio_governor.py:1214) sums realized Strategy Module P&L for the user without filtering mode/broker. Open unrealized losses are omitted. The [4% check](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/portfolio_governor.py:763) is an entry gate, not an aggregate mark-to-market exit watchdog, and derives its threshold from currently available cash.

Sandbox profits can mask live losses in this input, sandbox losses can block live entries, and large open losses do not by themselves activate this portfolio gate. Per-strategy tick stops are a separate mechanism.

Required: agreed account/broker/mode scope; a stable session capital basis; realized plus unrealized P&L and costs; a persistent entry lock; and a separately specified, reconciled emergency-exit policy. External/manual positions must not silently disappear from the intended account-level risk view.

### 9. P2 — Losing-streak protection misses individual leg-stop losses

[portfolio_governor.py:1255](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/portfolio_governor.py:1255) counts only `overall_sl` and `daily_loss_limit` stop reasons. A batch whose legs close normally can [finalize as `manual`](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/engine.py:1304), including leg-level stop closures. A probe with three completed losing `manual` runs produced a loss streak of zero.

Required: define the loss unit explicitly and calculate cooldown/streaks from reconciled outcomes, including costs, rather than those two labels alone. Signal-run round trips also need an explicit counting rule.

### 10. P2 — WhatsApp alerts can be silently lost

[whatsapp_alert_service.py:340](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/whatsapp_alert_service.py:340) explicitly drops messages when disconnected. [Lifecycle delivery](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/whatsapp_alert_service.py:439) ignores unsuccessful send results, and [notification work](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/lifecycle_events.py:107) uses an in-memory executor.

Required: a durable outbox, bounded retry and expiry, deduplication, visible delivery/failure status, and escalation for critical exit failures. Delayed notifications must show their original timestamp and must never be represented as current trade signals. Notification failure must not block an exit.

### 11. P2 — Commodity live entry hours conflict with the workflows

[portfolio_governor.py:655](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/portfolio_governor.py:655) applies 09:20–15:00 intraday and 14:45 option cutoffs without an exchange-specific session. The commodity workflows allow later MCX evaluation. This fails closed rather than causing an extra entry, but switching live would not behave like the advertised evening sandbox schedule.

Required: one exchange-aware session policy shared by scheduling, entry admission, stale-bar validation, expiry restrictions, and square-off, including special sessions and holidays.

## Strategy quality is not yet established

[starter_workflows.py:46](/Users/atanumridha/Documents/AlgoTrading/openalgo/services/strategy_module/starter_workflows.py:46) uses the same two-condition bullish graph for all six SENSEX/MCX additions: latest 5-minute close above the previous high and latest 15-minute close above the previous close. The two differently named SENSEX workflows do not implement distinct trend versus breakout/retest algorithms. They can produce correlated signals; more named workflows is not more diversification.

No profitability conclusion follows from these rules or from unit tests. Before considering live trading, validate distinct strategy behaviour, costs, spreads, realistic fills, missed fills, drawdown, correlated exposure, and out-of-sample results. One or two sandbox days is operational observation, not sufficient evidence of a durable profitable edge. Adding AI or a quantum-labelled component would not fix the execution and risk-control defects above.

## Existing useful protections

The reviewed system has explicit per-strategy live enablement, session authorization checks, durable order intents, partial-fill and order-event handling, recovery/reconciliation paths, separate live/sandbox dispatch, and stale-feed exit attempts. Relevant regression tests pass. These are useful foundations; they do not close the specific gaps above.

## Verification evidence

The final combined run completed **327 tests: 321 existing tests plus 6 isolated diagnostic probes**, all passing, in 3.53 seconds. The probes pass because they reproduce current unsafe behaviour; they are not evidence that it was fixed.

Existing suites: engine, portfolio governor, live authorization, order dispatch, recovery, scheduler, tick feed, and lifecycle alerts.

Diagnostic probes were held outside the application tree at `/private/tmp/openalgo-risk-review.GQp4yc/test_review_probes.py`. They use test databases and mocked services, and demonstrate sandbox bypass, post-budget re-entry, inadequate quote validation, stale signal bars, ambiguous timeout rejection, and missed losing streaks. No actual broker placement was invoked. The temporary file may be removed by the operating system; the findings and reproduction details above are the durable review record.

## Acceptance gates before any live trial

1. Correct the P1 findings and add regression tests that require safe outcomes, including simultaneous entries, partial fills, broker-accepted/time-out responses, restart, duplicate/out-of-order events, stale data, and failed exits.
2. Exercise identical risk policy in sandbox. Demonstrate that a spent budget blocks all new entry paths across restart while exits still work.
3. Prove current contract resolution, broker-pinned data, and exchange-aware session handling for each instrument family. Verify the configured price stream, not only order connectivity.
4. Demonstrate broker-supported protective-order lifecycle and reconciliation, including app/internet interruption. Do not create a second exit before resolving an uncertain first exit.
5. Demonstrate WhatsApp failure visibility and recovery. Keep operational alerts independent from order safety.
6. Validate strategy behaviour and realistic after-cost performance. Only then consider a separately authorized, tightly limited live trial; passing these gates cannot promise zero losses.

NSE's [risk disclosure](https://nsearchives.nseindia.com/content/circulars/cmtr4468.htm) explains that liquidity, fast price movement, and network problems can prevent execution or defeat intended stop/limit protection. That is residual market risk, distinct from the avoidable software gaps identified here.

## Implementation and installed-app check — 25 September 2026

This section records follow-up work against the findings above; it does not erase the original reproduction evidence. The dirty checkout has not been committed. The installed app was restarted once at 10:54 IST after a successful frontend build, and the authenticated Strategies and Positions pages were inspected. The local server reported ready on port 5001, recovered both previously open sandbox strategy runs, and remained in Analyze Mode with live automation authorization inactive.

| Finding | Current evidence | Boundary |
| --- | --- | --- |
| 1. Unknown broker write | Accepted/rejected/unknown outcomes and reconciliation guard; 208 focused tests after independent review. | A keyless ambiguous broker order still needs operator reconciliation. |
| 2, 5, 8, 11. Admission and market/session facts | Sandbox and live use scoped admission, fresh quote/depth, durable session capital, and venue-aware windows; 222 focused passes, 1 skip. | Process-local admission only; external/manual P&L and costs are not a verified account-wide ceiling. |
| 3, 9. Re-entry after daily loss | Every entry rechecks durable session loss; nested flip admission and five exception cleanup paths were fixed; 271 focused passes including 24 residual probes. | This is an entry lock, not a guarantee that an existing position cannot lose more than the threshold. |
| 4. Protective stop | All Strategy Module live entries remain blocked when broker-held protection is unverified; uncovered quantities emit critical audit events. | No verified broker-held stop lifecycle. Live entry is **not ready**. |
| 6, 7. Current Flow bars and feed | Current completed bars, durable per-bar claims, and configured WebSocket endpoint were tested; 995 focused passes, 3 skips. | Installed MCX Flows currently lack an accepted MCX historical-candle source; six older NIFTY/cash Flows use unsupported node types. |
| 10. WhatsApp critical alerts | Audit+outbox is atomic for new critical events; bounded reclaim/retry/expiry, historical message label, owner-scoped delivery-status UI; 457 focused backend and 43 focused frontend passes, independent review accepted. | Existing audit events were not backfilled; upstream acceptance is not human receipt, and a crash after acceptance may produce a duplicate. |

The full backend suite remains red: **5,389 passed, 147 failed, 14 errors, 25 skipped, 1 xfailed** at the pre-final-outbox integrated run. Its failures are concentrated in older strategy QA suites plus several unrelated modules. The full frontend suite passed **2,710/2,710** after disabling Node's experimental global webstorage in the test runtime; the production frontend build passed. These results and the live-protection gap prevent any claim of full readiness or proven profitability.

The installed Strategies page showed twelve intraday sandbox-only strategies after restart. Four were stopped with negative *last-run snapshots* (not cumulative broker-confirmed account P&L): NIFTY Breakout and Retest −₹1,014, SILVERM Momentum and Breakout −₹187.50, NIFTY Long-Option Momentum −₹39, and NIFTY 5/15-Minute Trend −₹32.50. Their audit trails showed `daily_loss_limit` stops; the SILVERM run recorded a −₹4,385 intrarun trough against a ₹1,000 configured trigger before closing at −₹187.50. The last-run figures are not maximum-loss guarantees. NIFTY Long-Option and NIFTY Trend each had a repeat start after an earlier daily-loss stop in the pre-restart runtime; the new entry lock is intended to refuse those repeats, but no live order was used to validate it.

Two MCX sandbox runs (NATGASMINI and CRUDEOILM) recovered and remained running; their unrealized P&L changes with prices. At the 11:00 IST UI check, CRUDEOILM showed −₹121.50 unrealized, not a fixed realized loss. The Positions page displayed two nonzero MCX quantities after restart. This page is not independent broker confirmation or proof of protective exits. The other stopped strategies were not restarted.

Installed Flow execution is **not healthy** despite the twelve scheduled rows. Workflows 1–6 contain unsupported `strategySignal` (workflow 6 also `openingRange`) and fail validation; their legacy `closedBarsOnly` setting is not enforced by the current indicator executor. Workflows 9–12 (MCX) fail at the first historical 5-minute bar request because this installed Kotak adapter does not provide MCX history; they do not reach the order node. The local Historify database has no rows for these four MCX contracts, so merely changing the Flow source is not a repair. SENSEX workflows 7–8 completed their observed run. Do not silently map the old exit-signal nodes to the start-only Strategy Module node or substitute an unverified MCX data source. The repeated failures need a deliberate Flow graph repair and verified MCX candle provider before those workflows can be treated as active signals.
