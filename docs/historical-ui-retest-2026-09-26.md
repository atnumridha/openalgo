# Historical UI retest — 26 September 2026

**Run #2 completed through the browser UI. The tested rules lost money in both development partitions and do not demonstrate profitability.** Dataset import, job execution and saved-result viewing worked. No strategy parameters were changed after examining this result.

> Follow-up: original one-minute prices show that one recorded training loss hit its target before its stop; two other training trades remain ambiguous within one minute. The saved values below are the conservative five-minute model outputs. The three OOS losses still hit their stops first. See [loss diagnosis](historical-loss-analysis-2026-09-26.md).

## What was tested

- Dataset #2: **NIFTY 2026 Jan-Jul | 5m weekly options | 120 sessions | UI screening**. The UI imported 98,847 bars covering 22 January–21 July 2026.
- Underlying: directly downloaded Kotak NIFTY five-minute candles. Options: complete five-minute groups from the [public rissin/Upstox archive](https://huggingface.co/datasets/rissin/nse-options-intraday).
- Contract universe: nearest nonexpired expiry listed in the previous session's NSE archive; opening ATM strike rounded to 50, plus/minus 100 in 50-point steps, calls and puts. These are limited strikes, not the entire option chain.
- All 693 imported contracts use **65-unit lots**, checked against prior-session and same-session NSE UDiFF records. All 89,850 selected option bars stayed within the corresponding NSE daily price range. One zero-volume bar was excluded. No prices or index volume were invented.
- Rules: **Trend and breakout**, 20-bar lookback, 10% stop, 20% target, seed 42, next-bar execution.
- Capital and limits: ₹10,000, 20% cash buffer, ₹1,000 first-trade planned-loss allowance, another ₹1,000 pooled across later trades, ₹2,000 daily allowance and 20% peak-equity drawdown control. Whole lots only.
- Fees: the existing September-verified Kotak NFO assumptions applied as an explicitly labelled historical scenario, with 10 bps adverse slippage per side. They are **not asserted to be the actual charges applicable on every January–July date**. Only the research form draft was changed; saved live-profile costs remained 26 September–10 October 2026.

## Results after modeled costs

| Evaluation | Dates | Sessions | Trades | Net P&L | Ending equity | Maximum drawdown | Win rate |
|---|---|---:|---:|---:|---:|---:|---:|
| Training | 22 Jan–24 Mar 2026 | 42 | 5 | **−₹922.72** | ₹9,077.28 | 19.89% | 20% |
| Exploratory out-of-sample | 25 Mar–23 Apr 2026 | 18 | 3 | **−₹1,412.10** | ₹8,587.90 | 14.12% | 0% |
| Execution stress | Same 18 OOS sessions | 18 | 3 | **−₹1,439.59** | ₹8,560.41 | 14.40% | 0% |

Each partition starts independently with ₹10,000. These are not one continuously compounded account, and the stress row is not an additional independent sample. Stress uses 30 bps slippage per side and 1.5 times brokerage; configured brokerage is zero.

All position outcomes were complete. Training profit factor was 0.5906; OOS profit factor was zero. OOS's 200 exploratory session-block resamples ranged from −₹4,236.30 at the 5th percentile to ₹0 at the 95th. Three OOS trades are too few for a reliable estimate of future performance.

Across training plus OOS, **157 opportunities could not afford a whole lot**, 144 lacked the required next option bar, 70 were refused by budget/drawdown admission and 23 were after the entry cutoff. Missing-bar rejections also reflect the deliberately bounded strike universe; they do not all mean the bulk source lacked a market quote. The result therefore measures this specific strategy, capital and imported universe.

## UI checks

1. Uploaded the JSON through the Dataset file picker; the UI confirmed 98,847 validated bars and selected the new dataset.
2. Set and verified the test-only fee scenario, dates, unchanged rules and seed in the browser.
3. Clicked **Run development test**; verified **Run #2 → completed**, its metrics, recorded configuration and trade table.
4. Selected the VWAP candidate and attempted a test. The UI correctly refused it: “VWAP candidate requires observed underlying volume on every bar; index volume cannot be invented”. No replacement volume was supplied.
5. Reloaded the page. Saved profile costs still showed the original September–October dates; Run #2 remained available in Results.
6. Independently recalculated the stored experiment in a read-only process. Its complete report matched exactly. Dataset, configuration and implementation hashes matched.

**The final 60 sessions, 24 April–21 July 2026, remain unconsumed.** The session-use ledger has no uses for those dates. No version was frozen, no release approved, no forward campaign started and no broker orders were sent by this test.

The third-party dataset labels its license `other` and leaves provider rights unresolved. This local exploratory test does not validate redistribution rights, spreads, market depth, tick-valid execution or live profitability.

## Evidence

- UI: **Strategies → Research → Results → View run 2**; left open after testing.
- Dataset fingerprint: `002c5bf408c0e2b6e5cc47fa7426e5bf1cd576dcba347cfd4f94d437f86c304f`.
- Configuration fingerprint: `afe38b527a4215de9cce5d739d9dc3be723e8776875f0bcf2bc645fff22c4855`.
- Engine implementation fingerprint: `8b10d0c5feec7cbe307a33a4bef3cf9c9b1db889cf33b4f579bbd5d2b444f607`.
- Local evidence: `data/research/recent-ui-test-2026-09-26/`, including immutable import JSON, fixed date/contract selection, NSE metadata hashes, `run-2.json`, `run-verification.json`, and training/OOS/stress trade CSVs.

No application code, trading rules or saved risk settings were modified for this retest.
