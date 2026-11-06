# NIFTY minimum-500-trade comparison

The user selected Realshyt's testing process and asks for the most profitable single CALL/PUT buying strategy with at least 500 trades. The earlier 80% net-win and average-winner-greater-than-average-loser requirements remain measured. No order placement or chart deployment is part of this experiment. The authorized research scope supplies approval to execute this bounded comparison without another planning question.

## Freeze before outcomes

Sixteen policies: four entries in `workspace/nifty-entry-80/500trade-entry-sources-2026-10-29.txt` times premium stop 5%/10% times target 1.5/2 times initial NET stop risk. No outcome-driven entry, stop, time, trade-count or side tuning. EMA9/21 fresh crossover; prior-20-bar high/low channel fresh breakout; RSI2 extreme reclaim through 10/90 in EMA200 direction; Bollinger20,2 immediate reentry before its middle band. These are researcher adaptations of documented indicator families, not the sources' proven NIFTY strategies.

One-minute underlying completed bars only. EMA seeds with SMA; RSI uses Wilder smoothing and 50 for a flat series. Bollinger uses population standard deviation. Channel excludes current bar. Indicators carry across normal official-session boundaries; reset after missing/invalid/repaired intraday bars. Require the previous signal comparison bar in the same session and segment. No future bars, final daily H/L, or nonexistent spot volume in entry features. Prior20 high/low are recorded as contextual S/R, not used as new filters.

The parent shared execution contract supersedes the research note's optional time/exit suggestions: actual next EXACT minute open 09:45 through 14:30 IST; one held daily-selected ATM CE/PE contract, one historical lot; at most two fills/session; maximum 45 minutes held, flat by 15:15. Signal close during an exit minute can enter the next minute; signals before exit are discarded, never deferred. Intrabar resting premium stops and targets; both touched in a minute is unknown. Adverse stop gaps fill open; favorable target gaps fill limit. Unknown stops further entries that day. Stops round up to the valid tick. No trailing or partial exits.

Reuse verified option replay and fee model: dated STT, exchange/regulatory/GST/stamp fees, INR20 per order, INR0.50/unit/side slippage; stress INR1/unit/side with unchanged signals/orders. Record gross zero-cost results. The 2024–2026 fee model must not be applied to older periods without explicitly auditing dated taxes/fees and lot size.

## Data and qualification

Current source covers 439 selected dates, Oct2024–Jul21 2026. Nearest-expiry ATM pair chosen at09:19 and fixed all day, not dynamic ATM at signal time. Both chronological periods have been used previously; no untouched validation claim.

Run all 16 on (1) original archived prices, labelled diagnostic due to known off-tick prices; (2) strict prices, invalidating every off-tick bar without rounding; and (3) complete paired clean sessions, selected by data QA alone before strategy outcomes. Pre-run QA gives264 clean complete paired sessions, ceiling528 trades at2/day. The clean subset is a data-availability sensitivity, not an unbiased full-period substitute. Keep unknown and no-entry outcomes separately. Never pool alternative configurations to reach500 or suppress unresolved paths from a complete-P&L claim.

Per-policy sample gate: >=500 CLOSED trades. Descriptive net ranking includes all qualifying-count policies; a positive known subtotal with unknowns is conditional, not a verified profitable strategy. Research candidate gate additionally requires zero unresolved outcomes, positive combined/earlier/later net, later stress profit and PF>=1.2 in both chronological periods, with >=100 closed in each period. User goal additionally needs >=80% net wins and average net winner>average net loser in both periods. Data-source disagreement prevents a validated/deployable label even if numerical gates pass.

A newly discovered Zenodo2017–2020 option archive may be independently audited before using any outcomes. If sufficient actual paired options, matching spot, dated lots/fees and QA are established, apply exactly these same16 policies to it as older-period replication. Report an unusable source if those conditions fail; do not alter strategy rules to make it fit.

## Evidence

Save protocol, source/data/code hashes, all trades, all16 summaries, chronology/year/month/side breakdowns, net R, fee/slippage drag, exit reasons, drawdown and uncertainty. Independently reconcile five randomly selected traded dates, actual fills and costs. Verify causal feature prefixes and known failure modes with tests. One independent code/results review before claims. Most profitable means among this explicitly bounded tested set, not across all possible strategies. If none qualify, state that result.
