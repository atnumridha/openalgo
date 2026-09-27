# Independent account replay evidence

This directory tracks the simulation scripts, registered assumptions, aggregate results, verification receipt, and account chart from 27 September 2026. See [the report](../../../docs/independent-live-like-simulation-2026-09-27.md) for interpretation.

Raw market archives, prepared minute-price bundles, and the per-account trade/equity/skip ledgers remain local and are not published here. The verification receipt describes the complete local run, not a fresh audit that can run using only these aggregate files. Reproduction requires the prepared `data/research/hundred-trades-2026-09-27/ready/` bundle and its supporting signal files, under the sources' permitted research terms.

`simulate.py` uses a fixed opportunity pool and independent accounts, plus a separate combined-account diagnostic. `cost_sensitivity.py` isolates higher slippage. `test_simulate.py` checks synthetic mechanics only. `verify.py` audits complete local ledgers. `report.py` renders the report and chart from those local outputs. The scripts refuse to overwrite completed results; preserve existing evidence when preparing another run.

No broker orders are submitted by these scripts. Historical results do not qualify any strategy for live trading.
