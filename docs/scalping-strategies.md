# Automated scalping strategies

Open **Strategies** and use the **Scalping strategies** cards. The highlighted research shortlist is EMA50/200 + daily regime, EMA9/15 + Bank Nifty confirmation, and the opening-box breakout. Yesterday’s EMA9/15, MACD + EMA200, and 5 EMA reversal strategies remain saved for comparison testing. **Add all 3** creates missing strategies and their linked Flows once. New strategies start stopped, in sandbox mode. Repeating installation preserves existing settings and does not activate trading.

## Start, inspect, stop

1. Connect your saved Kotak account for current candles, quotes and contracts. Enable the shared capital profile with verified costs in Research.
2. Choose **Start sandbox** on one strategy. It waits for a qualifying completed-candle signal; starting does not force a trade. Results and logs explain waiting, data failures and admission refusals.
3. **Stop automation** blocks further entries, requests closure of its managed position, and waits for flatness before reporting disabled.
4. To use live execution, stop automation, enable live for that strategy, complete the existing live-session authorization and any research qualification/release checks required by the account's **Live entry requirements**, then choose **Start live**. Research remains required by default; its explicit optional setting does not replace LIVE approval, session authorization or risk checks. Turning on the live flag alone does not authorize an entry.

The global header mode does not override each strategy's selected execution mode. All saved strategies share account limits; they do not each receive a separate capital allocation. Running them together can cause later signals to be refused because another position has reserved the available funds or risk.

The strategy detail page shows trade status and automation status separately. A **stopped** trade can still have **Automation: Monitoring**, ready to evaluate the next signal. Use **Stop automation**, confirm **Stop automation & close positions**, and wait for **Automation: Disabled** before changing mode. **Stop & Close Positions** closes the current run; it does not disable future signal monitoring. Closing or close-failed states keep mode changes blocked and show the reconciliation reason.

The same Start flow applies to generic linked signal receivers. **Start live** validates the linked Flow and enables monitoring; it does not submit an immediate manual entry. An inactive Flow with no open run may have all its managed entry and exit nodes switched together. Missing, ambiguous, shared, malformed or broker-mismatched links are refused; LIVE monitoring also refuses Flows containing unmanaged broker-order nodes. Stop is available in either mode, including when an older saved LIVE flag differs from the Flow's mode.

## Rules and exits

Signals reuse the historical research implementations on completed candles. EMA9/15 requires both indices to agree. MACD uses its EMA200/support-resistance setup. The 5 EMA setup combines five-minute bearish and fifteen-minute bullish non-touch alerts with subsequent one-minute breaks. Missing warmup history, incomplete candles, stale signals or stale quotes prevent entry.

| Setup | Option selection | Profit target and stop |
| --- | --- | --- |
| EMA50/200 + daily regime | One ATM Nifty option lot, expiry 0–7 days away | 2R index target, signal index stop, plus protective option stop |
| EMA9/15, MACD + EMA200, 5 EMA reversal | One ITM Nifty option lot, expiry 1–7 days away | 2R index target, signal index stop, plus protective option stop |
| Opening-box breakout | One ATM Nifty option lot, expiry 0–7 days away | Option premium +20 points target / −10 points stop from the actual fill |

EMA50/200 uses a completed five-minute crossover and strictly prior-session daily trend and volatility filters. It requires at least 272 completed daily observations, including the previous trading session, and uses Kotak's daily history interval. The opening-box strategy waits for all 15 opening one-minute bars and evaluates the first qualifying break through 09:45. The two new candidates also require at least ten lots of volume in the option's latest completed five-minute candle. Missing data produces no entry.

All five have a holding deadline 15 minutes after the signal. Entries must leave room for that window before 15:20. Index 2R does not promise a 2R option-premium return. The box has no index-based exit; its option stop, option target and deadline manage closure. Premium targets are persisted with the run so recovery without a checkpoint preserves the box's take-profit.

The index-exit profiles also have a protective premium stop: no more than INR800 gross planned loss per lot and no more than 20% of entry premium, rounded down to a 0.05 point increment. The box's gross planned loss is 10 points times its lot size. Actual fills, fees and gaps can produce larger losses. The account governor and shared loss ledger decide whether a trade fits. All exits use the existing managed order lifecycle; deadline closure intent does not require a fresh quote.

## Capital and evidence

INR25,000 is the research assumption. These presets cap the initial premium at INR20,000, leaving a nominal 20% research buffer. They **do not change the existing INR10,000 shared capital policy or replenish its ledger**. The account policy can therefore reject a trade below the preset's premium ceiling. Its first-trade INR1,000, combined later-trade INR1,000 and daily INR2,000 planned-loss allowances remain in force when enabled. A funded account balance is not automatically an increased policy allocation.

None of these setups is proven profitable or automatically qualified for live release. The automated premium stop is an additional constraint beyond the offline index-exit studies. Current master-contract selection, broker data, shared account admission and live fills can also differ from historical eligible-option selection. The historical ranking is not a backtest of the complete deployed order path or a portfolio simulation. Use prospective sandbox evidence for this implementation.

- [All-strategy ranking](strategy-ranking-2026-09-27.md)
- [Three-strategy research comparison](ema-scalping-evaluation-2026-09-26.md)
- [Four-hour range test: negative Nifty adaptation](fourhour-range-evaluation-2026-09-26.md)
- [Fabio order-flow audit: missing data and rules](fabio-orderflow-evaluation-2026-09-26.md)

## Verification on 26 September 2026

The related backend regression run passed **2,689 tests**, with three skips and one expected failure. This includes the three signal detectors, Flow behavior, account admission, stop/recovery lifecycle and qualification controls. The new concurrent-edit, mode/epoch change, index reward/premium risk, quote-free deadline and final stale-signal checks passed. One existing recovery identity-map warning remains. **26 frontend tests passed** and the production build succeeded; its existing large-chunk warning remains.

Independent code review reported no remaining integration blockers. Resource review was static: new DB reads use context-managed sessions/connections, the periodic monitor removes its scoped session in `finally`, existing bounded history caches are reused, frames are local and row-bounded, and no new per-request executors, network pools or permanent registries were added. No prolonged load/leak measurement was performed.

Installed local strategy/Flow IDs are **13, 14 and 15**. All three were checked as stopped, sandbox-selected and inactive, preserving the nine existing automation settings. Verification placed no orders. A private database backup was saved before installation. Signed-in browser verification remains pending because the available browser requires login; component tests are not a substitute for that check.

## Shortlist update on 27 September 2026

Added EMA50/200 + daily regime (strategy/Flow 16) and opening-box breakout (17). Retained yesterday's EMA9/15 (13), MACD + EMA200 (14), and 5 EMA reversal (15) unchanged for testing. The main page highlights the three research candidates; all five remain saved, stopped and sandbox-only.

Removed only the nine older template strategies and their exclusive Flows: IDs 1, 2, 3, 7, 8, 9, 10, 11, 12. Their scheduler jobs were removed with the scheduler paused. The unrelated inactive cash Flows 4–6 remain unchanged. Before maintenance, an owner-only SQLite backup and manifest were saved under `workspace/local-backups/shortlist-20260927T064716Z/`; this directory is ignored by Git. Full retained-row and unrelated-Flow hashes matched the backup both before and after app restart. No managed orders or runs were created.

Verification: **2,625 backend tests passed**, with three skips, one expected failure and the existing recovery identity-map warning. **40 frontend tests passed**; the production build succeeded with its existing chunk-size warning. Independent review identified and verified a fix for preserving the box's profit target after restart without a checkpoint. The running browser showed all five saved strategies, the correct three shortlist cards, yesterday's two comparison presets, and the box's 10-point stop / 20-point target. The app and offline worker both reported ready after restart. No automation or live trading was activated; prospective trading performance remains unproven.

### Optional installation of the earlier templates

The nine earlier templates remain **uninstalled**, following the user's latest instruction. Expand **Available templates** on the Strategies page and choose **Install** beside a specific template. This adds only that strategy and its linked Flow, using the template's default rules, pinned to the saved broker connection. Both start stopped in sandbox mode. Repeating installation does not create duplicates or overwrite existing settings. An incomplete Flow installation can be finished by retrying.

The library lists the three NIFTY, two SENSEX, and four commodity presets. Viewing it does not install or activate anything. The current five saved strategies and the highlighted top three remain unchanged. Earlier customized configurations and historical logs are still preserved in the local backup; installing from the library uses factory template defaults rather than restoring those historical rows.

Library verification: 52 backend tests and 28 frontend tests passed, and the production build succeeded. In the running browser, all nine entries displayed **Not installed** with individual Install buttons. Full database-row hashes confirmed that the current five strategies and all existing Flows remained unchanged after restart and viewing the library. No managed orders or active Flows were created.

### Display order by historical win rate

The current five are displayed from highest to lowest historical **net option win percentage**, using the saved **15-minute** research variants and modeled base costs:

| Strategy | Net wins / priced affordable trades | Historical win % |
| --- | ---: | ---: |
| EMA9/15 + Bank Nifty | 102 / 219 | 46.58% |
| EMA50/200 + daily regime | 13 / 28 | 46.43% |
| MACD + EMA200 | 26 / 58 | 44.83% |
| Opening-box breakout | 71 / 173 | 41.04% |
| 5 EMA reversal | 375 / 915 | 40.98% |

Source: the nonduplicate cells in `data/research/strategy-ranking-2026-09-27-final/ranking.json`, with provenance and integer win/trade counts preserved in `frontend/src/lib/strategyResearch.ts`. MACD uses `macd-r2-hold15`, matching its configured maximum hold; its better-ranked 10-minute variant is not substituted. Rates describe historical research observations, not current sandbox/live performance or a replay of the deployed risk rules. Samples and execution assumptions differ. Unknown rates remain unranked after these five. The three highlighted candidates retain their membership and are also ordered by win percentage within the shortlist.
