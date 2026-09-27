# Additional historical robustness tests — 26 September 2026

**The positive result did not hold up.** The unchanged breakout control lost money in all four newly tested 2025 periods, including every cost scenario. This batch fails the criteria set before testing. It does not support promoting the strategy to live trading.

This follows the [earlier five-run comparison](filtered-strategy-retest-2026-09-26.md). No production strategy, risk limit or live cost profile was changed for this batch.

## What was tested

The [fixed test plan](plans/2026-09-26-independent-robustness-tests.md) was recorded and hashed before evaluating new results. Rules and implementation are identical to earlier Run #3: `trend_breakout`, 20-bar lookback, 10% stop, 20% target. The plan was not expanded after seeing losses.

- Four periods, each containing the first 60 available shared index/options sessions of its 2025 quarter: **240 previously unevaluated sessions**. These are retrospective checks on additional dates, not prospective paper trading or a final confirmation sample.
- Five-minute underlying signals and actual one-minute option candles. The daily contract universe is selected at 09:20 using observed premiums/volume and prior-session NSE contract definitions, following the earlier dataset procedure.
- Each quarter starts independently with ₹10,000. Within a quarter, equity, peak equity and drawdown protection persist through all 60 sessions. Capital is not reset at the UI's training/later-period boundary.
- Existing risk policy retained: first filled trade has up to ₹1,000 planned risk; all later trades share another ₹1,000 per day; ₹2,000 daily limit; 20% peak-equity drawdown protection; 20% cash buffer.
- Four UI development runs, four exact independent reproductions of their reports, 16 continuous-quarter/cost replays, and four continuous replays of the already-seen 2026 period. Reusing dates under different costs is sensitivity analysis, not additional independent market evidence.

The base cost scenario uses the same numerical current Kotak NFO assumptions as Run #3, applied hypothetically to 2025 prices: ₹0 brokerage per order and 10 basis points adverse slippage per side, plus the configured charges/taxes. This is **not a verified 2025 fee schedule** or a reconstruction of actual broker fills. Only the research draft's descriptive source and date coverage were extended.

## Continuous-quarter results

All P&L figures are net of the configured costs. Each column uses the same rules and risk policy; adverse slippage is applied at both entry and exit.

| Period, 60 sessions each | Base: 10 bps, ₹0/order | 30 bps, ₹0/order | 100 bps, ₹0/order | 30 bps, ₹20/order | Base trades | Base maximum observed drawdown |
|---|---:|---:|---:|---:|---:|---:|
| Q1: 1 Jan–27 Mar 2025 | −₹846.60 | −₹925.41 | −₹1,419.11 | −₹1,013.32 | 8 | 18.31% |
| Q2: 1 Apr–27 Jun 2025 | −₹1,666.22 | −₹1,700.00 | −₹1,812.55 | −₹1,841.60 | 3 | 18.49% |
| Q3: 1 Jul–24 Sep 2025 | −₹1,957.32 | −₹1,991.10 | −₹1,810.04 | −₹1,816.63 | 3 | 19.57% |
| Q4: 1 Oct–29 Dec 2025 | −₹1,465.49 | −₹1,536.78 | −₹1,750.62 | −₹1,772.78 | 5 | 18.77% |
| Sum of four separate experiments | **−₹5,935.63** | **−₹6,153.29** | **−₹6,792.32** | **−₹6,444.33** | **19** | — |

The total is **not one account's annual return**: there were four independent ₹10,000 starts. Higher costs can change lot sizing and which trades pass admission, so net P&L need not worsen monotonically in every individual period. Every scenario was negative here.

## What the UI shows, and why it differs

The UI evaluates 42 training sessions and 18 later sessions as separate accounts, each starting with ₹10,000. These remain useful separate-period diagnostics, but their P&Ls cannot be added to describe continuous trading.

| Saved UI run | Dataset | Training net | Later-period net | Stressed later-period net |
|---|---|---:|---:|---:|
| #8 | 2025 Q1 robustness | −₹846.60 | −₹1,784.81 | −₹1,826.09 |
| #9 | 2025 Q2 robustness | −₹1,666.22 | +₹3,380.55 | +₹3,200.51 |
| #10 | 2025 Q3 robustness | −₹1,957.32 | −₹1,919.03 | −₹1,956.55 |
| #11 | 2025 Q4 robustness | −₹1,465.49 | −₹768.09 | −₹846.84 |

For example, Run #9's later-period profit requires a fresh ₹10,000 account. In the continuous Q2 replay, the earlier losses leave too little drawdown headroom to admit subsequent proposed trades. The continuous result therefore stays at **−₹1,666.22**, not training loss plus later-period profit.

The same check on the previously seen 22 January–23 April 2026 period produces **+₹1,883.90 across 11 trades**, not +₹1,883.90 plus +₹816.19. Its continuous stress results are +₹1,744.11 at 30 bps, +₹1,797.13 at 100 bps, and +₹1,806.32 at 30 bps plus ₹20/order. These are diagnostics on already-seen dates, not fresh validation. Removing its largest winning trade arithmetically leaves +₹480.10 in the base scenario; that subtraction is not an alternative portfolio replay.

## Why this batch lost

The 19 base-case trades include **4 winners and 15 losses**, with 15 stop exits and four target exits. Gross P&L after modeled slippage was already **−₹5,692.50**; explicit fees/taxes add **₹243.13**, giving −₹5,935.63 net. Brokerage alone does not explain the failure. Nine stop exits occurred within five minutes of entry. That suggests entries and fixed stops deserve investigation, but it does not identify a profitable replacement rule.

At each quarter's end, only ₹189.90, ₹153.92, ₹42.68 and ₹128.98 respectively remain above the protected drawdown floor. That is less than the risk of subsequent proposed whole-lot entries. The account can thus stop admitting entries before the formal 20% pause flag is triggered. Relaxing protection would change the strategy's risk, not establish an advantage.

There are also substantial coverage constraints. Across the four base replays, 982 opportunities are rejected for a missing next option bar, 307 for unaffordable whole lots, and 120 for budget/drawdown limits. The limited imported contract universe and original selector are not a full-market execution model. The finding applies to this tested implementation and universe; it is not a claim that every breakout strategy must lose.

## Predefined criteria and uncertainty

| Criterion recorded before new results | Observed | Outcome |
|---|---|---|
| Positive aggregate base P&L | −₹5,935.63 | Fail |
| At least three profitable quarters | 0 of 4 | Fail |
| Positive aggregate 30 bps + ₹20/order P&L | −₹6,444.33 | Fail |
| At least 40 completed base trades | 19 | Fail |
| Complete outcomes in every scenario | Yes | Pass |
| No ambiguous exits | Zero | Pass |
| Positive 5th-percentile block-resampled sum | −₹9,520.83 | Fail |

The 10,000 seeded resamples draw 48 nonoverlapping five-session P&L blocks from these same 240 dates. Their 5th/50th/95th percentiles are **−₹9,520.83 / −₹5,790.12 / −₹2,771.83**. This is a conditional diagnostic of the observed P&Ls, including inactive periods. It does not rerun risk-dependent order admission, create new market evidence or estimate a calibrated probability of future profitability. The small number of trades limits inference further.

Repeatedly selecting combinations that look good in historical tests can introduce severe selection/overfitting bias; see [Novy-Marx, Backtesting Strategies Based on Multiple Signals](https://www.nber.org/papers/w21329). Accordingly this failed batch ends without extra parameter searching or consuming the final holdout.

## Data quality and verification

- All four datasets were imported and all four development jobs queued through the Research UI. Runs #8–#11 completed, their displayed reports were inspected, and independent evaluation reproduced each full stored report exactly.
- The same rules, numeric costs, dataset/configuration fingerprints and implementation fingerprint were checked. The test plan's SHA-256 still matches the preregistered value.
- Each dataset contains 60 new 2025 sessions plus the same 60 reserved sessions of 24 April–21 July 2026 to fit the existing workflow. The session-use ledger records all 240 new dates as development; **zero reserved dates have been evaluated**. Reserved prices were not passed to any outcome replay.
- Historical NSE lot sizes were checked; Q1 includes 25- and 75-unit contracts and later 2025 quarters use 75. Each import stayed below 100,000 rows and 20 MB; no limit was raised.
- One zero-volume minute, `NIFTY24APR2523550CE` at 14:54 IST on 17 April 2025, was omitted and recorded. No selected replay position required it; all scenarios have complete outcomes and zero ambiguous exits. This does not erase the rejected-entry coverage limitation above.
- Source data: existing Kotak Neo five-minute underlying history and public rissin/Upstox minute options, cross-checked with official NSE archives. Third-party redistribution rights remain unverified; data stays in private local exploratory analysis.
- Saved live costs are unchanged, all nine saved strategies remain stopped, and the Strategy Module order count remains zero. No version was frozen, released or activated.
- Only offline preparation/analysis and documentation were added in this batch. Production code and implementation fingerprint are unchanged; no app restart or deployment occurred. This is historical performance verification, not a new claim that the full repository test suite is green; the earlier report retains its unit-test results and outstanding unrelated failures.
- Offline files use context-managed reads/writes, gzip and DuckDB handles; SQLAlchemy sessions are context managed and engines disposed in `finally`. Preparation caches timestamp formatting once instead of repeating it for each date. No new persistent service, process or connection was introduced.

## Evidence and reproduction

Local evidence is under `data/research/robustness-2026-09-26/` (ignored by Git):

- `frozen-spec.json`, `session-selection.json`, `initial-state.json`
- `validation.json`, `contract-selection.csv`, `rejected-option-bars.csv`
- `nifty-2025-q1-robustness.json` through `nifty-2025-q4-robustness.json`
- `ui-run-8.json` through `ui-run-11.json`
- `robustness-results.json`, `existing-2026-diagnostics.json`
- `prepare_quarters.py`, `analyze_quarters.py`, `existing_diagnostics.py`

From the repository root, reproduce the stored UI reports and the 16 continuous scenarios without creating additional UI jobs:

```sh
.venv/bin/python data/research/robustness-2026-09-26/analyze_quarters.py
```

The script intentionally fails if the frozen implementation/configuration, recorded date usage, saved live-cost profile or trading state has changed. A deterministic reproduction establishes reproducibility, not a new independent profitability result.

Implementation fingerprint: `1b32efb798bdb2aaa0ffda32d368aaf382d371fbd48ab338ac907ce6ed4f54d4`.
Plan SHA-256: `5c8c1bb088e04bd03f8a42151318b8edfc5e817700fd24f3431862e32ea754d4`.

| Dataset | Content SHA-256 |
|---|---|
| Q1 | `cad1212493e274f2c30fd12c89ba2ab492fc565f0b1f6660d6639873671054f7` |
| Q2 | `a507c1d770f6cf51d0cdf3ffb189e22343f7b0902a5f9c4cbdbff214ddc36d7b` |
| Q3 | `3dafcb4f746d63f78ad9694b8c058ecdfb245b464482b2be36e90843a06a2a39` |
| Q4 | `41d9291976631cdc89c94157ca05dddab2b282fe7d96700969ca3f8e1c9183fd` |

Decision: reject the claim that the current candidate has demonstrated robust profitability. Further research needs adequate executable-contract coverage and a separately specified hypothesis, followed by genuinely new evaluation and prospective Sandbox observations. These results do not justify a live-profit claim.
