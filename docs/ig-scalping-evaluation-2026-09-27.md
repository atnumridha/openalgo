# IG scalping strategy evaluation — 27 September 2026

**None of the tested NIFTY adaptations demonstrated a profitable after-cost result.** All 15 variants with trades had negative average option P&L under both cost scenarios. Six RSI variants had no qualifying signals under the registered interpretation, so their accuracy is undefined. No rules or parameters were changed after observing these outcomes.

The study uses **1 January 2025–23 April 2026**, ₹25,000 initial capital, a 20% buffer and one eligible ITM NIFTY option lot. Primary comparisons use five-minute candles, a 2R index target and a maximum 15-minute hold. These are reused exploratory data; no protected 24 April–21 July 2026 outcomes were evaluated. This is not fresh out-of-sample confirmation.

## Primary option results

Win rate means the proportion of initially affordable trades whose option P&L is positive **after modeled fees and slippage**. It does not mean a full 2R target was reached.

| Setup | Base affordable trades | Base win rate | Mean base P&L/trade | Stress affordable trades | Stress win rate | Mean stress P&L/trade |
|---|---:|---:|---:|---:|---:|---:|
| Stochastic | 429 | 45.69% | ₹-14.52 | 428 | 40.89% | ₹-104.05 |
| MA5/20/200 | 692 | 41.91% | ₹-70.59 | 691 | 36.32% | ₹-158.83 |
| Parabolic SAR | 908 | 41.85% | ₹-63.04 | 908 | 37.56% | ₹-152.34 |
| RSI | 0 | N/A | N/A | 0 | N/A | N/A |

Stochastic was the least negative primary setup. Its observed base mean was not reliably positive: the 95% interval spans a loss and a gain. The stressed mean intervals for all three traded primary setups are below zero under the declared cost model. These conditional intervals do not account for trying many strategy families over earlier research.

| Setup | Base win-rate 95% interval | Base mean P&L 95% interval | Stress mean P&L 95% interval |
|---|---:|---:|---:|
| Stochastic | 41.63% to 49.54% | ₹-83.40 to ₹52.39 | ₹-173.84 to ₹-37.07 |
| MA5/20/200 | 38.43% to 45.58% | ₹-130.15 to ₹4.68 | ₹-218.45 to ₹-83.57 |
| Parabolic SAR | 38.31% to 45.31% | ₹-128.10 to ₹11.50 | ₹-217.42 to ₹-78.57 |
| RSI | N/A | N/A | N/A |

Intervals use 2,000 moving blocks of five active trading days with seed 42, conditional on available/affordable opportunities. Shorter holding limits and the three-minute variants are correlated sensitivity checks, not independent confirmations.

## Why a 2R target did not produce a profitable system

| Setup | Completed index outcomes | Index-positive rate | Full 2R hits | Time exits | Stop exits | Indicator exits |
|---|---:|---:|---:|---:|---:|---:|
| Stochastic | 452 | 46.02% | 39 (8.63%) | 263 | 117 | 33 |
| MA5/20/200 | 725 | 48.14% | 31 (4.28%) | 570 | 124 | 0 |
| Parabolic SAR | 951 | 46.06% | 15 (1.58%) | 843 | 81 | 12 |
| RSI | 0 | N/A | 0 (N/A) | 0 | 0 | 0 |

Most trades ended at the time limit, rather than at the full target. A target of 2R is therefore not the realized average payoff. An index move also does not translate into the same option return: the simulation uses actual historical option prices, adverse execution assumptions and fees. Wider five-bar or SAR stops often make the target distant relative to a 15-minute horizon. This is an interpretation of the exit counts, not a separately tested causal intervention.

## RSI: no measurable accuracy

The registered RSI interpretation requires recovery above 30 while SMA20/50/100 all have positive three-bar slopes, or rejection below 70 with all three slopes negative. On five-minute data there were 365 upward and 370 downward threshold crossings before the trend gate; none passed all three slopes. On three-minute data there were 576 and 568 crossings; again none passed.

The article describes the trend qualitatively, and its chart examples do not make that phrase a reproducible threshold. This strict interpretation is too restrictive on the tested NIFTY data. **Zero qualifying trades is not a 0% win rate and does not establish that every RSI variant fails.** A looser trend definition would be a separate hypothesis, not a correction selected to improve these results.

## Source fidelity and explicit adaptations

The [IG article](https://www.ig.com/en/trading-strategies/four-simple-scalping-trading-strategies-190131) and the indicator labels in its four chart images were inspected. It illustrates different markets; this study uses NIFTY signals and purchased Indian options. It does not validate the specific illustrated trades or reproduce CFD execution.

- Stochastic uses the displayed 14/5/3 settings, interpreted as a 14-bar raw oscillator, five-bar K smoothing and three-bar D, with MA50/200 for trend. The smoothing interpretation and quantified trend/extreme entry filter are declared assumptions.
- MA uses simple 5/20/200 averages. The source’s long crossover and short price-below-fast-average rules are asymmetric; that difference is retained.
- SAR uses start/increment 0.02 and cap 0.2. The seed and reversal convention are explicit in the plan.
- RSI uses 14 periods with 20/50/100 averages; the exact slope gate is an adaptation.

Other additions: five-bar signal stops for stochastic/MA/RSI, SAR-dot stops for SAR, a 2R index target, three entries/day, no index-position overlap, a full horizon ending by 15:25 and 5/10/15-minute caps. Stochastic and SAR can exit earlier on their stated indicator conditions. Stops/targets have priority within a minute, with stop first if both are touched. Entry uses the next minute open; option exit uses the minute open after the index exit is detected. Thus execution can occur one minute after the signal-based deadline.

## Capital, costs and large losses

Contracts are chosen using prior-session NSE listing/lot evidence and a completed five-minute option quote. Only ITM options with expiry 1–7 days away and observed quote volume of at least 10 lots qualify. Three-minute triggers can use a quote up to four minutes old. Affordability is checked after selection; no cheaper replacement is searched for. Entry premium plus entry fees must fit ₹20,000.

Base costs use 10bp adverse slippage per side, zero brokerage and the configured exchange, SEBI, GST, stamp and STT formulas. Stress uses 30bp per side and ₹20 brokerage per order. These are hypothetical fee assumptions applied to historical prices, not verified historic broker bills or recorded bid/ask spreads.

| Setup | Worst base trade | Base losses exceeding ₹1,000 | Sum of independent base outcomes | Sum of independent stress outcomes |
|---|---:|---:|---:|---:|
| Stochastic | ₹-4,075.76 | 44 | ₹-6,229.40 | ₹-44,534.26 |
| MA5/20/200 | ₹-4,134.30 | 84 | ₹-48,849.37 | ₹-109,753.63 |
| Parabolic SAR | ₹-5,113.75 | 126 | ₹-57,240.19 | ₹-138,324.46 |
| RSI | N/A | 0 | N/A | N/A |

**These sums are not account returns.** Every opportunity is assessed against the same initial capital allowance. The study does not compound equity, enforce the shared first-trade/later-trade/daily loss buckets, or add the deployed premium stop. Index scheduling also does not reserve capital through the extra minute of option-exit delay. The large losses show why these figures cannot be represented as results of the live risk-managed platform.

## All predeclared variants

| Setup | Candle minutes | Maximum hold | Affordable trades base/stress | Base win rate | Base mean | Stress mean |
|---|---:|---:|---:|---:|---:|---:|
| Stochastic | 5 | 5 | 440/439 | 42.05% | ₹-53.75 | ₹-143.16 |
| Stochastic | 5 | 10 | 433/432 | 44.57% | ₹-47.55 | ₹-137.08 |
| Stochastic | 5 | 15 | 429/428 | 45.69% | ₹-14.52 | ₹-104.05 |
| Stochastic | 3 | 5 | 672/671 | 43.90% | ₹-72.54 | ₹-160.91 |
| Stochastic | 3 | 10 | 663/662 | 42.84% | ₹-61.31 | ₹-150.28 |
| Stochastic | 3 | 15 | 658/657 | 40.73% | ₹-83.65 | ₹-172.91 |
| MA5/20/200 | 5 | 5 | 712/711 | 41.57% | ₹-67.93 | ₹-156.11 |
| MA5/20/200 | 5 | 10 | 708/707 | 41.24% | ₹-75.44 | ₹-163.34 |
| MA5/20/200 | 5 | 15 | 692/691 | 41.91% | ₹-70.59 | ₹-158.83 |
| MA5/20/200 | 3 | 5 | 870/870 | 43.79% | ₹-23.50 | ₹-112.30 |
| MA5/20/200 | 3 | 10 | 869/869 | 44.07% | ₹-31.07 | ₹-119.78 |
| MA5/20/200 | 3 | 15 | 866/866 | 42.15% | ₹-34.78 | ₹-123.51 |
| Parabolic SAR | 5 | 5 | 909/909 | 43.67% | ₹-23.95 | ₹-113.38 |
| Parabolic SAR | 5 | 10 | 909/909 | 42.35% | ₹-29.55 | ₹-118.96 |
| Parabolic SAR | 5 | 15 | 908/908 | 41.85% | ₹-63.04 | ₹-152.34 |
| RSI | 5 | 5 | 0/0 | N/A | N/A | N/A |
| RSI | 5 | 10 | 0/0 | N/A | N/A | N/A |
| RSI | 5 | 15 | 0/0 | N/A | N/A | N/A |
| RSI | 3 | 5 | 0/0 | N/A | N/A | N/A |
| RSI | 3 | 10 | 0/0 | N/A | N/A | N/A |
| RSI | 3 | 15 | 0/0 | N/A | N/A | N/A |

## Coverage and exclusions

Input screening retained 120,683 valid minute candles across 323 observed sessions from 121,054 raw rows, rejecting 371 invalid/out-of-session observations. Complete-bucket aggregation produced 24,094 five-minute and 40,192 three-minute candles. Partial buckets are discarded; missing prices are never filled. Indicators count observed bars and carry history overnight, but entries wait for three consecutive intervals after a gap or session boundary. The dataset is not asserted complete for every exchange session.

| Primary setup | Raw signals | Index attempts/completed | Excluded late / overlap / daily cap | Missing option evidence | Unaffordable base/stress |
|---|---:|---:|---:|---:|---:|
| Stochastic | 549 | 452/452 | 36 / 0 / 61 | 12 | 11/12 |
| MA5/20/200 | 1086 | 726/725 | 56 / 34 / 270 | 15 | 18/19 |
| Parabolic SAR | 1899 | 951/951 | 82 / 0 / 866 | 17 | 26/26 |
| RSI | 0 | 0/0 | 0 / 0 / 0 | 0 | 0/0 |

The primary MA study has one refused entry through its stop. All remaining primary index attempts resolve; primary stochastic and MA each have two stop/target-ambiguous bars treated stop-first, SAR has none. Stress affordability can exclude an additional trade because entry cost rises. Full unresolved/exclusion lists and quarterly results remain in each variant folder.

## Reproduction and verification

Artifacts: `data/research/ig-scalping-2026-09-27/`, including the frozen experiment registration, raw-input/code/plan hashes, signal/exit tables, index ledgers, option selections, base/stress outcomes, exclusions and confidence intervals. The frozen plan is [here](plans/2026-09-27-ig-scalping-evaluation.md).

**34 targeted tests passed**: 11 new IG tests and 23 existing signal/execution/option-selection/cost tests. Ruff passed for the four new Python files. The independent verifier imported no application signal, risk or fee helper: it matched 192,858 indicator rows for stochastic/MA/RSI, reconstructed 11,249 index exits and checked 22,066 base/stress option fill-and-fee calculations. SAR’s explicit recurrence, seed/reversal behavior and future-prefix invariance were checked with deterministic unit vectors. All source and plan hashes matched; protected sessions evaluated: 0. Eleven unresolved/refused index attempts are preserved across the correlated variants. PyArrow emitted environment CPU-cache permission warnings; verification exited successfully.

```sh
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/research_ig_scalping.py \
  --output data/research/ig-scalping-new-run
UV_CACHE_DIR=/tmp/openalgo-uv-cache uv run --no-sync python scripts/verify_ig_scalping.py \
  data/research/ig-scalping-2026-09-27
```

Resource review was static: context-managed files and DuckDB, 512MB DuckDB limit/two threads, one strategy/timeframe option batch at a time, local study-sized frames and no broker/app database calls. No prolonged leak/load measurement was performed. No live strategy settings or orders were changed by this study.
