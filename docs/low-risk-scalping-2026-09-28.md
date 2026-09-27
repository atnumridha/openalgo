# ₹300 risk / 3R scalping profile

This profile replaces the earlier ₹1,000 first-trade and ₹1,000 later-trade pools for new managed entries. It is a risk/execution change, not evidence that a strategy is profitable.

| Rule | Meaning |
|---|---|
| Planned price loss per trade | At most ₹300 before charges, using one whole option lot |
| Price target | Three times the actual tick-rounded stop risk; a ₹300 stop targets ₹900 before charges |
| Daily allowance | ₹2,000 of losses after modeled charges; pending/open risk also reserves allowance |
| Consecutive losses | Three completed trades with negative net P&L stop new entries for that trading day |
| Profits | Do not replenish the daily loss allowance; a non-loss breaks a streak before the third loss |
| Once the day stop is reached | A later winning exit, restart, or portfolio-resume action cannot reopen the day |
| Positions already open | Continue to receive protective exits; the three-loss latch is an entry stop |
| Next trading day | Starts a new daily allowance/streak, subject to unresolved exposure and portfolio drawdown checks |
| Drawdown | The existing 20% peak-equity pause remains |
| Cash | The existing 20% cash buffer and whole-lot affordability checks remain |

Charges are kept outside the ₹300/₹900 price-risk example but included in net results and the daily allowance. Gaps, slippage and delayed execution can make actual losses larger than a planned stop. No result is clipped to make it fit a limit.

A loss, loss, then win resets the consecutive-loss count, but the two losses still spend daily allowance. Three ₹300 price losses in succession stop further entries around ₹900 plus charges, even though the full ₹2,000 daily allowance has not been spent.

## Stops and pacing

A single lot retains the technical stop when its price risk fits ₹300. Otherwise the new cash-stop recipe tightens the stop to the largest valid price tick within ₹300. The target is 3× that rounded distance. Tighter stops may reduce the win rate. A 3R target does not mean every winner earns 3R: the holding deadline or another protective exit may close the position earlier. Signals, contract selection, liquidity checks, quote freshness and protective deadlines remain required.

The new recipe removes the old arbitrary three-entry daily cap. Its default post-exit cooldown is five minutes. This permits additional qualifying entries while the shared risk controls allow them; it does not force trades or waive signal checks.

## Research protocol

Research allocation: ₹25,000. Existing saved Sandbox/Live allocations and fee settings are not changed by this study. Current Kotak charges are the user-approved retrospective research assumption, not verified historical charges.

Five non-overlapping development windows use 60 sessions each: January–March, April–June, July–September and October–December 2025, and January 22–April 23 2026. The consumed final period April 24–July 21 2026 is excluded. Reuse of development data makes these comparisons exploratory.

The fixed study compares ML holds of 5/10/15 minutes and cooldowns 0/5/15 minutes. Each holding-time model is trained once per window (15 final development-model fits, plus their chronological cross-validation fits), then its out-of-sample decisions are replayed at each cooldown (45 variants, each base and execution stress). Seed 42,100 trees,3 chronological folds,10 minimum training sessions and 0.5 probability threshold are fixed before looking at outcomes. Runtime cooldown remains 5 minutes; research ranking does not auto-activate a model or change defaults.

## Exploratory results

These are reused development windows, not fresh final or forward validation. Each window trains on its first 42 development sessions and evaluates the last 18. The same scored decisions are reused across cooldowns. Aggregate results below concatenate five independent ₹25,000 window experiments; they are not one continuous funded-account return.

| Hold / cooldown (minutes) | Base trades | Base win % | Base net ₹ | Stress trades | Stress win % | Stress net ₹ |
|---|---:|---:|---:|---:|---:|---:|
| 5 / 0 | 428 | 39.02 | -18,116.76 | 302 | 36.75 | -22,744.62 |
| 5 / 5 | 496 | 39.52 | -11,216.59 | 371 | 36.39 | -20,356.80 |
| 5 / 15 | 570 | 43.86 | -9,231.54 | 484 | 40.70 | -15,700.26 |
| 10 / 0 | 470 | 39.57 | -9,472.45 | 352 | 37.22 | -20,356.08 |
| 10 / 5 | 431 | 41.76 | -12,934.84 | 345 | 39.71 | -16,813.08 |
| 10 / 15 | 477 | 41.30 | -6,247.45 | 419 | 37.23 | -15,396.37 |
| 15 / 0 | 421 | 37.77 | -14,038.94 | 346 | 34.39 | -16,455.39 |
| 15 / 5 | 344 | 36.05 | -18,592.16 | 295 | 32.54 | -21,928.70 |
| 15 / 15 | 367 | 36.24 | -14,155.94 | 276 | 32.25 | -20,659.34 |

Default recipe:15-minute maximum hold,5-minute post-exit cooldown. No research ranking automatically changes runtime settings.

| Development window | Scenario | Trades | Win % | Gross ₹ | Charges ₹ | Net ₹ | Net/trade ₹ | Closed / observed-open max DD % | Three-loss stopped days |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026 Jan–Apr | base | 55 | 32.73 | -4,046.25 | 737.04 | -4,783.29 | -86.97 | 19.13 / 19.13 | 7 |
| 2026 Jan–Apr | stress | 43 | 25.58 | -4,335.50 | 562.15 | -4,897.65 | -113.9 | 19.59 / 19.59 | 7 |
| 2025 Jan–Mar | base | 103 | 35.92 | -2,103.75 | 1,189.44 | -3,293.19 | -31.97 | 16.60 / 16.92 | 12 |
| 2025 Jan–Mar | stress | 84 | 34.52 | -3,390.00 | 963.19 | -4,353.19 | -51.82 | 19.75 / 19.97 | 11 |
| 2025 Apr–Jun | base | 42 | 33.33 | -3,566.25 | 510.39 | -4,076.64 | -97.06 | 18.87 / 19.37 | 5 |
| 2025 Apr–Jun | stress | 44 | 34.09 | -4,293.75 | 526.68 | -4,820.43 | -109.56 | 19.28 / 19.72 | 5 |
| 2025 Jul–Sep | base | 70 | 34.29 | -2,553.75 | 870.40 | -3,424.15 | -48.92 | 18.01 / 19.52 | 8 |
| 2025 Jul–Sep | stress | 57 | 26.32 | -4,031.25 | 670.34 | -4,701.59 | -82.48 | 19.51 / 19.72 | 9 |
| 2025 Oct–Dec | base | 74 | 41.89 | -2,055.00 | 959.89 | -3,014.89 | -40.74 | 19.43 / 19.89 | 5 |
| 2025 Oct–Dec | stress | 67 | 38.81 | -2,291.25 | 864.59 | -3,155.84 | -47.1 | 19.06 / 19.76 | 5 |

Base assumes 10 bps slippage per fill; stress assumes 30 bps and 1.5× fixed brokerage. Zero API brokerage remains zero, while taxes/exchange charges still apply. Those charges use the authorized current Kotak schedule as a retrospective assumption.

### Limit audit

Verified 90 scenario ledgers and 15 fitted development models independently of production replay arithmetic.
- max_planned_gross: 300.0
- max_realized_net_loss: 359.3
- max_trades_in_day: 20
- realized_gross_losses_over 300 across scenario replays: 2892
- realized_net_losses_over_reserved_risk across scenario replays: 20
- incomplete_outcomes across scenario replays: 0
- Scenario/day pairs with realized daily losses above ₹2,000: 0
- Replayed variants share dates, signals and trades; counts across all 90 scenarios are not independent sample sizes.
- Every entry had gross planned risk ≤ ₹300 and an exact gross 3R target. The independent audit checked lot/tick geometry, next-bar entry, fees, net P&L, daily reserves, cooldown, completion sequence, and no entry after the third consecutive net loss.
- Actual loss overruns are retained in the evidence rather than clipped. Planned reserves and stop orders cannot guarantee a maximum realized loss.


## What the results mean

All nine fixed holding/cooldown combinations had negative aggregate net P&L under both base and stressed execution. The least-negative aggregate was 10-minute hold / 15-minute cooldown: −₹6,247.45 base and −₹15,396.37 stress. It is not a profitable winner and was not promoted.

At the unchanged 15-minute/5-minute default,344 base trades won 36.05% and lost ₹18,592.16 across the five separately capitalized windows. Only 24 trades reached the target;178 stopped out,140 hit the holding deadline and 2 closed at session end. Average positive net outcome was ₹337.03, versus ₹274.47 per negative outcome. The target is 3R, but time exits mean realized winners need not earn 3R. Gross P&L was already negative before ₹4,267.16 of charges. Raising trade frequency alone did not fix the signal/exit economics.

Maximum realized price loss across the replay variants was ₹345 before ₹14.30 of charges, producing the worst net loss ₹359.30. Maximum daily sum of net losses was ₹1,996.06. Every planned price stop stayed ≤ ₹300; fills were not clipped to that amount. Therefore the implementation cannot promise an absolute ₹300 realized-loss ceiling.

The five existing named rule strategies use the new exit controls for new managed entries, but their displayed historical win percentages remain from earlier rules. This 90-scenario study evaluates the ML family; it does not replace those five strategies' old performance numbers with newly measured percentages.

## Verification and evidence

- Broad backend: 4,143 passed, 16 skipped, 1 expected failure. Seven existing warnings disclosed in test output.
- Full frontend before the final small UI fix: 2,786 passed across 177 files. Final amended Research component: 26 passed, then final card/List/Research checks: 53 passed; TypeScript and Vite production build passed. Generated assets independently verified: 316 hashes. Existing Vite chunk-size warning remains; source diff whitespace check passed (a generated template retains existing whitespace).
- Independent whole-branch review approved after fixing completion/session attribution, optimization pacing identity, and persisted ML restart geometry. See `docs/low-risk-code-review-2026-09-28.md`.
- Isolated browser tests: three Sandbox losses block the day; loss/loss/win/loss leaves streak 1 without refunding daily allowance; restart preserves the stop; next trading day resets allowance/streak while preserving equity; unresolved legacy exposure is clearly labeled; target field remains 3× stop.
- Independent arithmetic audit checked all 90 saved scenarios, input/output/model/configuration hashes, exact dates, one-lot geometry, fees, equity, cooldown and day stops. No incomplete outcomes or unavailable models. Fifteen completed models plus 45 cross-validation estimators belong to the successful run. An earlier attempt stopped at an analytics-import configuration error after initial fitting; it saved no scenario result and did not change selection settings. The successful retry used synthetic isolated configuration, without live credentials or database access.
- Live/forward qualification is still required. No strategy/model was installed or activated by this work; existing activation and allocation settings are preserved.

Local evidence (ignored by Git): `data/research/lowrisk-2026-09-28-fixed-study-v2/manifest.json`, `data/research/lowrisk-2026-09-28-audit.json`, `data/research/lowrisk-2026-09-28-inputs/` and `data/research/lowrisk-2026-09-28-audit-tools/`.

## Decisions and limits

The one-lot stop is tightened to fit ₹300 when the old technical stop is wider. Keeping the earlier stop would reject the prior latest-window ML trades, whose minimum-lot stop risks exceeded ₹300. Tightening makes trading possible but can lower win rate, as the exploratory results demonstrate.

Five-minute cooldown remains the default. The 0/15-minute comparisons are exploratory and do not auto-promote. A future explicitly chosen cooldown may be used only after its own exact configuration passes qualification/review/session authorization; shorter cooldown can increase turnover and costs.

Managed Strategy Module entries share these limits. Unmanaged/manual orders and independent flows do not acquire this protection merely because the UI displays it. Legacy exposure retains its recorded exits; incomplete historical completion evidence requires reconciliation before policy transition.

## Local release verification

The local app and research worker restarted successfully after read-only checks showed zero open managed runs, zero managed orders and zero risk trades. The running Research page shows ₹300/3R/shared ₹2,000, separate streak 0 and zero reserved risk in both modes. Both stored accounts now use `shared-300-3r-v1`; allocations remain ₹10,000 each. The ₹25,000 allocation is used for research only.

Pre/post snapshots match for capital, fee hashes, saved strategies, Flow activation, orders and consumed final sessions. All five saved strategies remain stopped/live-disabled, with their preexisting Sandbox Flows unchanged. The running checkout's source hash matches the successful immutable study. Broker Positions UI returned `Failed to fetch positions` on initial read and refresh; its displayed zero is not verified broker exposure. No live trading test was attempted. The actual UI check also identified older 2R descriptions on the top cards; their final correction was independently reviewed and verified in the running UI: all three show the ₹300/3R current recipe and explicitly earlier-rule percentages. The layout was also checked visually.
