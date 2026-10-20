# Multi-market chart strategy research

Research date: 17 October 2026. Protocol: `chart-combinations-v1`.

This offline study searches for an 80% **net** win rate while also requiring
positive expectancy, adequate samples and resilience to higher execution costs.
It does not connect signals to orders or change the running trading applications.
The first completed study found no qualifying strategy.

## Run and artifacts

From the repository root, with the existing Python environment:

```sh
LOG_FORMAT='%(message)s' uv run python -m scripts.research.multi_market.run
```

Outputs are under `workspace/backtests/multi-market-20261017/`:

- `report.html`: readable methodology, coverage, results and limitations.
- `results.json`: metrics, sources, code fingerprints and data provenance.
- `*-development.csv`: all 600 configurations per market.
- `*-selection.json`: selection saved before final-period evaluation.
- `*-final-trades.csv`: individual final-period outcomes, including unresolved exposure.
- `data/`: frozen input snapshots and dated contract metadata with checksums.

Existing snapshots are reused only after checksum verification. To conduct a
different study, explicitly version its dates, protocol and output location;
do not silently replace the data or tune settings against the final period.

## Strategy families and selection

Five original, explicitly specified combinations use trend pullbacks,
breakout/retests, Bollinger reclaims, prior-range sweep/reclaims and a regime
combination. The sources explain their constituent concepts; they do not validate
these combinations or the chosen thresholds. Exact predicates are in
`scripts/research/multi_market/engine.py`. Research sources are recorded in the
report and the [implementation plan](../superpowers/plans/2026-10-17-multi-market-strategy-research.md).

For each market, the fixed grid uses 5/15-minute entries, base/selective filters,
1/1.5/2.5 ATR stops, 0.5/1/1.5/2/3R targets and 30/120-minute maximum holding
periods: 600 configurations, 2,400 overall. Signals use completed candles and
enter at the following minute's open. At most three entries per IST day and one
position at a time are permitted. These are independent research rules, not the
live terminal's existing dollar-profit trailing policy.

Observed dates split 60% development, 20% validation and 20% final test.
Development selection requires at least 30 trades, positive expectancy,
profit factor >=1.1 and no unresolved exposures. Only the top ten enter validation;
validation requires at least 15 trades and the same profitability checks.
If selection fails, the report explicitly labels its example diagnostic-only.
Final results never determine a new set of parameters.

The final research screen requires at least 100 final trades, 80% net wins,
positive expectancy, profit factor >=1.2, positive stressed-cost P&L, no unresolved
exposures in either execution scenario and at least 60 observed dates overall.
Historical dates can overlap earlier exploratory work, so this is chronological
validation rather than a pristine prospective holdout. Wilson intervals are
descriptive and do not account for serial dependence or multiple testing.

## Costs and coverage limits

BTCUSD is simulated at 0.001 BTC, with taker fees of 0.05% per side plus 18% GST,
0.01% adverse slippage per side and a disclosed funding reserve of 0.01% of entry
notional for each crossed eight-hour funding boundary. This reserve is not actual
historical funding. The stress run doubles fees and slippage. There is no margin,
liquidation or order-book simulation, and no assumed promotional fee waiver.

The 180-day snapshot contains 180 BTCUSD dates, 125 NIFTY dates and only nine
dates each for BANKNIFTY and SENSEX. Incomplete/repaired candles are excluded;
unexpected gaps reset indicator warm-up. Missing exposure data creates an
unresolved outcome, never a fabricated profitable exit. An actual earlier stop
or target before the gap remains usable. Stops take precedence when minute OHLC
cannot determine which of stop and target occurred first.

Indian underlying results are **index points, not option P&L**. Base slippage is
one point per side, stressed to two. Normal sessions only are accepted, with exits
by 15:15. Session dates come from observed history; an independent holiday calendar
was not available. Missing bars and the short BANKNIFTY/SENSEX coverage severely
limit usable signals. More history retrieval was attempted but unavailable.

The separate long-option diagnostic requires dated expiry/strike/lot metadata,
actual positive-volume premium candles and the existing dated Kotak fee estimator
with zero brokerage. No selected final entry had sufficient such coverage in this
study, so no option-profitability claim is possible. The metadata from a different
date is not substituted. Longer verified histories and prospective observations
are needed before attempting a live qualification.

## Verification and resource ownership

The focused suite is `test/research/test_multi_market_research.py`. It covers
causality, gaps, session boundaries, execution ambiguity, short symmetry, costs,
daily entry limits, selection, impossible timing and executable premium inputs.
Shared pure position-risk decisions are reused from `services/risk/`.

Both SQLite source readers open read-only connections inside explicit closing
contexts. Files use scoped reads/writes; no database mutation, execution API,
background service, timer, WebSocket or persistent worker is added. The fixed
grid and signal caches bound the search. Output artifacts intentionally persist
for audit and reproducibility; the foreground research process exits on completion.

This study is separate from the [Delta chart strategy ports](crypto-strategy-sources.md).
