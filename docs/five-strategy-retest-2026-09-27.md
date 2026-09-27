# Five-strategy recent-window retest — 27 September 2026

**A complete last-three-months options profitability test could not be completed.** The requested trailing period is 27 June–26 September 2026; observed index sessions run from 29 June through the last completed session on 25 September. The available expired-option minute archive still ends on 21 July. The current upstream revision and its 2026 file checksum are unchanged from the previous download. No option prices were synthesized or filled to hide that gap.

All five frozen research variants were evaluated without parameter optimization: EMA 9/15 with Bank Nifty confirmation, EMA 50/200 with daily regime, MACD/EMA 200, opening-box breakout, and EMA 5 reversal. Maximum hold is 15 minutes. The four index-exit variants use 2R; the box uses a 10-point option-premium stop and 20-point target. These are the earlier research execution rules, not a complete replay of the installed platform's protective premium stops, shared daily loss budget, drawdown governor, funding reservations, or order lifecycle.

## Observed option results: 29 June–21 July, 17 source sessions

Assumed capital ₹25,000, one lot, maximum initial premium plus entry fees ₹20,000. Each strategy is tested independently. Win percentage means positive **net option P&L**, including the modeled costs. It is not the percentage reaching the 2R target.

| Strategy | Priced trades | Base wins | Base win rate | Base net sum | Stress wins | Stress win rate | Stress net sum | Worst stress trade |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EMA 9/15 + Bank Nifty | 16 | 7 | 43.75% | ₹3,857.82 | 5 | 31.25% | ₹2,557.00 | −₹1,921.51 |
| MACD + EMA 200 | 3 | 2 | 66.67% | ₹766.32 | 2 | 66.67% | ₹520.81 | −₹210.07 |
| Opening-box breakout | 5 | 3 | 60.00% | −₹57.03 | 3 | 60.00% | −₹413.21 | −₹741.58 |
| EMA 5 reversal | 48 | 23 | 47.92% | ₹1,402.29 | 19 | 39.58% | −₹2,610.55 | −₹1,257.61 |
| EMA 50/200 + daily regime | 0 | — | N/A | N/A | — | N/A | N/A | N/A |

Base costs use 10 basis points of adverse slippage per side and zero brokerage. Stress uses 30 basis points per side and ₹20 per order. Both include the existing hypothetical exchange, SEBI, GST, stamp duty and STT assumptions. These are fixed cost sensitivities carried forward for comparison, not verified historical contract-note charges. No saved broker fee configuration was changed.

EMA 50/200's six index trades occurred after the option archive cutoff, so it has **no measured option P&L** here. EMA 5 had 52 index attempts in the overlap: one entry was through its stop, and three other signals lacked an eligible observed contract with prior-session listing information; 48 were priced. These exclusions are preserved in the artifacts.

EMA 9/15's largest stressed winner was ₹7,262.48. Without that trade, its stressed sum becomes **−₹4,705.48**. It also exceeded a ₹1,000 actual loss twice. EMA 5 exceeded ₹1,000 twice under stress, and its base profit also disappears without its largest winner. MACD's three trades cannot support a reliable winner ranking. The box's 60% win rate did not produce a profit because the size of wins, losses, timed exits and costs matters.

The sums are totals of independent historical opportunities passing initial affordability, **not returns on a continuously funded ₹25,000 account**. Do not add the rows together as a portfolio result. Capital depletion, shared concurrency and the user's ₹1,000 first-trade / ₹1,000 subsequent-trades / ₹2,000 daily budgets were not simulated by these frozen comparison engines. Therefore these numbers do not establish how the deployed account would have performed.

## Index signal outcomes across the requested period

These use valid observed bars across 64 sessions from 29 June–25 September. They are gross hypothetical index outcomes, **not option accuracy or option profits**.

| Strategy | Positive outcomes / completed trades | Gross index win rate | Mean gross R | Unresolved or rejected attempts |
|---|---:|---:|---:|---:|
| MACD + EMA 200 | 7 / 11 | 63.64% | 0.2147 | 0 |
| EMA 9/15 + Bank Nifty | 20 / 39 | 51.28% | 0.1976 | 0 |
| EMA 50/200 + daily regime | 3 / 6 | 50.00% | −0.0206 | 0 |
| EMA 5 reversal | 95 / 192 | 49.48% | 0.0232 | 1 entry through stop |
| Opening-box breakout | 21 raw signals | N/A | N/A | Exits require option prices |

Only 3 of 39 EMA 9/15 index trades reached the target; 28 closed at the time limit. The corresponding counts are 1 target/10 timed exits for MACD, 1 target/2 timed exits for EMA 50/200, and 17 targets/122 timed exits for EMA 5. A small positive timed exit counts as a win but is not a 2R win.

## Data audit and preserved strict-session check

Fresh read-only Kotak downloads supplied NIFTY one-minute and Bank Nifty five-minute candles from 1 June for warmup. Existing screened Kotak NIFTY five-minute bars and Yahoo daily closes supplied the remaining context. Scoring starts after 27 June. Daily regime features use strictly earlier daily dates. Indicators and contract selections do not use future outcomes; contracts require prior-session listing and lot-size metadata and completed quotes with sufficient volume.

Cleaning rejects invalid OHLC, nonfinite/nonpositive prices, duplicate/conflicting timestamps, misaligned candles and observations outside regular hours. Gaps are not interpolated. Five-minute option selection bars come from the earlier archive converter, which requires five distinct valid minutes. Execution rejects missing, invalid or zero-volume required option minutes. Signals use closed bars and subsequent execution; the same minute touching both stop and target is resolved adversely. At most three entries per day and no overlapping positions are allowed within each strategy's frozen research simulation.

The first audit required every session to contain all 375 NIFTY minutes and all 75 NIFTY/Bank Nifty five-minute bars. Only **20 of 64** observed sessions met that test; the last was 19 August. Much of the rejected history is missing late-session candles. Independent single-day re-fetches for 30 June and 25 September reproduced the omissions. On 25 September, for example, NIFTY lacks minutes 15:16–15:27 and 15:29; Bank Nifty lacks 15:15 and 15:20 five-minute starts.

The strict result is retained. A documented coverage amendment then retained valid bars from all dates and allowed the existing execution engine to reject incomplete paths. No indicators, entries, exits, holding times or cost assumptions were tuned. The two cleaning approaches are not independent experiments, and their difference is not evidence of an improved strategy.

Strict-session option subset: nine dates within 29 June–17 July. EMA 9/15: 6 priced trades, 50% base wins, ₹4,802.66 base / ₹4,305.11 stress sum. MACD: 1 trade, 100% wins, ₹322.46 / ₹223.30. Box: 5 trades, 60% wins, −₹57.03 / −₹413.21. EMA 5: 27 trades, 44.44% base wins, −₹866.12 / −₹3,134.31. EMA 50/200: no trades. These smaller samples show why calling the current sources a complete clean three-month dataset would be misleading.

The newly examined June–July outcomes overlap dates previously reserved from the earlier studies. Those dates are now exposed and must not be described as an untouched holdout in future research. This retest does not grant live qualification or alter any qualification record.

## Verification and reproduction

71 focused execution tests passed. Independent artifact checks verified recorded input/source SHA-256 values, trade counts, win counts, net arithmetic, affordability, daily entry caps, all five adapters' signal parity and 15 causal prefix comparisons. All 72 selected option paths fit within their same-day NSE daily high/low envelopes and agree with the daily lot size. That daily comparison does not prove each minute is correct or each modeled fill executable.

Artifacts are under `data/research/last-three-months-2026-09-27/`: original downloads, source update check, strict results and manifests, `valid-bars/results.json`, per-strategy trade records, selected contract paths, `verification.json`, and `valid-bars/nse-daily-reconciliation.json`. Completed experiment files are preserved. `download_recent.py` acquires read-only source data; `run_study.py` and `run_valid_bars.py` implement the two documented coverage policies; `verify_study.py` rechecks both saved outputs. Run with the repository `.venv/bin/python`. Runners refuse to overwrite completed results.

Sources: [Kotak historical API documentation](https://github.com/Kotak-Neo/Kotak-Neo/blob/main/docs/market-data-apis/historical-data.md), [public NIFTY options archive](https://huggingface.co/datasets/rissin/nse-options-intraday). The missing requirement remains observed expired-option intraday prices for **22 July–25 September 2026**, plus a replay of the installed portfolio and protection rules. No trading strategy was activated by this research.
