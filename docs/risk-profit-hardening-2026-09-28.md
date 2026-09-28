# Equity risk and momentum profit protection — 28 September 2026

The new managed-entry recipe is `one-lot-technical-profit-trail-v3`, bound to `equity-1pct-v2`. It preserves a whole lot's technical stop and skips the entry when its estimated loss cannot fit the budget. Older fixed-cash and profit-v2 recipes remain available for exact historical replay and existing-position recovery. Old artifacts do not qualify a new recipe for live release.

| Control | New rule |
| --- | --- |
| Planned trade loss | Lesser of 1% of current allocated equity and ₹300, including estimated fees and slippage |
| Daily loss allowance | Lesser of 3% of persisted session-opening equity and ₹2,000 |
| Loss accounting | Losses consume the allowance; wins do not refill it |
| Consecutive losses | Three completed net losses block entries for the rest of the session |
| Drawdown | Halve trade risk at 5% from peak net equity; pause at 8% until reviewed |
| Exposure | One pending/open managed position per account and execution mode |
| Stop sizing | Technical stop first, rounded away from entry; skip if a whole lot exceeds budget |

At ₹10,000 opening/current equity this initially means ₹100 all-in trade risk and ₹300 daily allowance. At ₹25,000 it initially means ₹250 and ₹750. These are allocated strategy budgets, not broker balances. Existing allocations are preserved. Session-opening equity is stored under the same database lock as admission, survives restart, and cannot be enlarged by funding the account mid-session. Accounts with unresolved old exposure do not silently migrate. Exits and reconciliation remain available when entries are blocked.

## Momentum profits

| Best executable gross profit | Planned gross stop floor |
| --- | --- |
| ₹300 | Estimated fee/slippage-aware break-even, when attainable |
| ₹600 | ₹300 or the higher fee-aware break-even level |
| ₹1,000 | ₹900 |
| ₹1,500 | ₹1,200 |
| ₹1,800 | ₹1,500 |
| Higher | Continue ₹300 behind the peak, never lower than the earned ₹900 floor |

There is no fixed take-profit cap. Existing 5/10/15-minute research holding deadlines and managed strategy deadlines still apply. Profit-floor amounts are before charges; gaps, slippage and unfilled stop-limit orders can result in less realized profit. The rule is a stop instruction, not a guaranteed return.

New managed entries require fresh bid/ask prices and depth for the whole lot. The app advances profit stops from executable bid evidence, not a higher last-traded price. Unavailable/stale/unusable executable quotes cannot create an earned floor; the run requests a protective exit through existing ownership and cancellation/reconciliation handling.

Kotak broker stops now advance through the same existing order. A durable intent precedes dispatch; exact broker trigger, instrument and remaining quantity must be observed before verification. Unknown or rejected modifications remain pending for reconciliation and are not blindly resent. App exits retain existing stop ownership/cancel reconciliation. Restart restores both a pending modification that is verified during recovery and an already-verified broker floor whose app checkpoint lagged. OpenAlgo, its worker and the price feed are still required for future advances.

## Historical comparison

Thirty exploratory replays reuse the same five frozen development signal schedules, with independent ₹25,000 starting accounts, 15-minute holds and 5-minute cooldown. No refits or threshold search. Protected final sessions were excluded. Prior profit-v2 trade sequences and totals reproduced exactly. Current Kotak fees are the previously authorized retrospective research assumption.

| Rules / costs | Trades | Net wins | Win rate | Combined net P&L | Worst window drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| Old profit-v2 / base | 380 | 157 | 41.32% | −₹16,955.74 | 19.84% |
| New technical-v3 / base | 37 | 12 | 32.43% | −₹2,555.90 | 5.55% |
| Old profit-v2 / stressed | 287 | 111 | 38.68% | −₹21,670.78 | 19.84% |
| New technical-v3 / stressed | 37 | 13 | 35.14% | −₹2,019.23 | 4.38% |

New-policy risk refusals were 2,343 with base costs and 2,345 with stressed costs. Fees can change which opportunities are admitted, so the stressed result is not the same trades repriced. These totals combine five independent windows, not one continuous portfolio. Lower losses came with far fewer trades and do not establish an improved profitable edge.

A research-only 2×ATR trail, allowed only to tighten the new floor after ₹600 gross profit, gave identical results: no admitted trade reached its activation threshold. It was not promoted. The ₹1,000/₹1,500 live-rule behavior is tested deterministically, but this historical sample supplies no activation evidence. Candle opens/closes cannot reproduce intrabar quote paths, depth, broker response delays or fills.

Evidence: [comparison manifest](../data/research/risk-profit-comparison-2026-09-28/manifest.json), [interpretation](../data/research/risk-profit-comparison-2026-09-28/README.md), and [reproduction helper](../data/research/risk-profit-verification-2026-09-28/run_comparison.py). Source fingerprint: `9494de1aa42864e47fdfb4bef14eec189487dbfd3e01e94c27a8e880e4eccbc3`.

## Verification and operational scope

Independent review caught and confirmed the verified-broker-stop/checkpoint crash window. A failing regression was added, fixed, and independently rechecked; recovery keeps any higher existing app floor. No other actionable review findings remained. Broker calls were faked; no real orders were sent.

Browser verification used the production build on an isolated local host with synthetic ledger records and no order routes. It confirmed all-in limits, fixed daily allowance, a three-loss session block, 5% risk reduction, 8% pause explanation, technical-stop skips and the ₹1,000 → ₹900 rule. The installed authenticated UI requires operator login; fixture verification is not a live-broker trial.

These shared limits apply to managed Strategy Module entries with the capital profile enabled. Existing standalone Flow rules and activation states are preserved. Live trading still requires fresh qualification, review and session authorization. Profitability remains unproven.

Verification completed: **4,267 backend tests passed**, 16 skipped, one expected failure, seven existing warnings; **61 affected frontend tests passed**. TypeScript/Vite production build and scoped Python Ruff checks passed. Existing bundle-size warnings remain.

Published as `1d3d8b6ad` on `main`. The installed app and research worker restarted ready. All 494 served assets matched the production build; the deployed research-source fingerprint matches the study. The two idle existing risk accounts migrated to the new policy without changing their ₹10,000 allocations: each currently allows ₹100 planned all-in risk and ₹300 daily loss allowance. Before/after snapshots confirmed unchanged strategies, Flow activation, fee hashes, capital/peak/pause values, zero managed orders, zero risk trades and 60 previously consumed final sessions. All five saved strategies remain stopped/live-disabled. The installed browser requires login, so authenticated UI verification remains the isolated-host result described above.
