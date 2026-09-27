# Groww algorithmic families and cumulative ranking: frozen protocol

Source: https://groww.in/blog/algorithmic-trading-strategies, read 27 September 2026. Seven broad families, not seven fully specified executable strategies. Rules below are declared adaptations, not assertions about exact article profitability. User asks to test them and rank all previous studies.

## New scalping tests

Freeze four families on completed five-minute NIFTY bars, each at 5/10/15-minute maximum hold, 2R underlying-index target. Primary hold 15 minutes; shorter holds are sensitivity tests. Indicators carry across sessions. Require three consecutive five-minute intervals after gaps; 200 observations for trend rules, 20 for z-score. Exclude special session 2025-10-21. Direction CE buys calls; PE buys puts, never short options.

1. `mean_z20`: close re-enters above -2 from a previous z-score <=-2, with a bullish candle, buys CE; re-enters below +2 from >=+2 with a bearish candle buys PE. Z-score uses rolling 20 closes and population standard deviation. Flat windows produce no signal.
2. `mean_daily10`: first close crossing below 90% of the prior completed 20-day simple mean buys CE; above 110% buys PE. Compare previous five-minute close to the SAME known daily mean. This tests the article's literal 10% example on NIFTY; no trades is a valid result, not a failed implementation.
3. `trend_50_200`: EMA50 crosses above/below EMA200, CE/PE respectively. Round EMA difference to eight decimals for equality, as prior EMA studies. These periods are five-minute bars, a scalping adaptation of the article's longer trend examples.
4. `timing_50_200`: same crossover, admitted only when prior completed daily close is above SMA200 for CE or below for PE, AND prior 20-day close-return volatility is no greater than its trailing 252-observation median. This is a technical regime filter, not a VIX or macro-data test. Daily inputs join strictly earlier dates, never the current day's close.

Stop at signal candle low/high, next minute open entry, actual entry-to-stop distance defines 2R; refuse entry through stop; shared risk replay uses adverse gaps, stop-first ambiguous bars, time exits. Three non-overlapping index entries/day, deadline <=15:25. Missing/unaffordable option observations consume index slots. Development period 2025-01-01 through 2026-04-23 only; do not evaluate protected 2026-04-24 through 2026-07-21 outcomes. Daily warmup can use earlier years, but daily rows after development cutoff must be removed before feature calculation.

Reuse unchanged Groww Supertrend/Tradejini observed ATM selection and option execution: prior NSE listing <=7 days old, expiry 0–7 days, nearest eligible observed strike, completed five-minute quote >=10 lots, actual historical lot size, one lot, no cheaper fallback. Complete positive-volume raw option minutes; buy at signal boundary open, exit at next option open following closed index exit candle. Capital ₹25,000, entry premium plus fees <=₹20,000. Base 10bp adverse slippage and zero brokerage, stress 30bp and ₹20/order plus configured taxes/charges. These are independent initial-affordability opportunities, not a compounding account or enforcement of ₹1,000/₹2,000 risk limits. Report breaches. No prices invented, parameter tuning after outcomes, orders or activation.

## Other families

Index rebalancing: small separate long-equity event study of ALL Nifty50 additions in the official 21-Feb-2025 and 22-Aug-2025 notices (JIOFIN, ZOMATO/current ETERNAL; INDIGO, MAXHEALTH). Enter next trading day's open after announcement, exit close on last session before effective inclusion (27-Mar and 29-Sep). Equal ₹10,000 funding caps per stock within a ₹25,000 campaign, integer shares; separate fresh campaigns, no compounding. Fetch raw Yahoo daily OHLC and corporate actions for bounded event windows, archive response and hashes. Abort affected event if missing data or corporate actions cannot be handled. Compare with NIFTY same-date open/close return. Report gross and illustrative round-trip 30bp/60bp cost sensitivities, not Kotak equity fee quotes. Four trades/two correlated events cannot validate or rank a scalping system. No shorting removed names.

Arbitrage requires synchronized executable prices and size for both legs plus fees/borrow/latency; current one-index minute archive cannot prove it. Record missing-data audit instead of simulated profits. VWAP/TWAP are execution methods; one whole option lot cannot be split into multiple legal child orders. Record this feasibility result separately; index spot volume is not a usable execution-volume profile. Reuse existing canonical verified ML/portfolio experiments with their original capital and hold/risk assumptions; do not relabel copies as fresh trials.

## Ranking frozen before new outcomes

Catalog every canonical tested scalping cell with option outcomes, including zero-trade cells as unranked. Use corrected/verified evidence; exclude superseded copies and deduplicate reused StockGro 1-minute/all EMA baseline. Rank traded cells descriptively by stress mean net option P&L, then base mean, then count. Display sample size, net win rate, stress and base means, period stability and confidence/risk limitations. This is a development ranking across heterogeneous protocols, NOT a controlled head-to-head, a statistical proof or independent validation. Also report each family's predeclared primary separately; do not silently promote the best of many variants to primary. Best research candidate is the highest stress-ranked eligible scalp; live-qualified selection requires independent positive evidence and enforced portfolio limits, so descriptive rank alone cannot qualify it.

Include earlier ₹10,000 portfolio/ML experiments, prediction-only evaluations and untestable order-flow/execution/arbitrage families in separate evidence sections, never pool those P&Ls with ₹25,000 opportunities. State old calendar/ITM-vs-ATM/admission differences and repeated reuse of development history. Preserve sealed outcomes and prior artifacts.

## Implementation and verification

1. Add new signal module and synthetic tests first: mirrored thresholds, no flat-window signals, EMA warmup, strict past daily join, future-prefix invariance, missing-bar gate. Do not change old hashed modules.
2. Add offline runner and independent verifier: recreate signals from raw minutes/daily closes; independently requery ATM selections, paths, fill prices and costs; check all cells and provenance hashes. Run relevant regression tests.
3. Run bounded event data download and independently reconcile per-stock and campaign arithmetic.
4. Build reproducible JSON/CSV and Markdown full ranking, evidence links and exclusions. Test rank/deduplication/zero-trade handling. Fresh read-only review covers lookahead, parameter fishing, lot size/costs, comparability, unsupported profit claims and provenance. No unrelated edits, commit, push, live/sandbox enablement.

Pre-outcome data ruling: the initial run aborted during feature validation, before any signals/options were evaluated. Yahoo daily history has 31 missing-close rows before the cutoff, most recently 2026-01-15. Exclude nonfinite/nonpositive daily closes and record their dates; do not fill prices. Rolling windows count valid observed daily closes. Preserve the aborted manifest in the preflight-failed directory.
