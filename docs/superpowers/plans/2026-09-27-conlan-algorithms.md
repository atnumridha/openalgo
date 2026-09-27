# Repository algorithm coverage and disabled strategy additions

Approved scope: test the algorithms from Chris Conlan's `algorithmic-trading-with-python` on existing user data, implement missing methods, and keep additions disabled. Reference revision: `ebe01087c7d9172db72bc3c9adc1eee5e882ac49`. Implement the mathematical ideas independently; do not redistribute the upstream freeware source.

## Decisions

- Implement the SMA(5)-SMA(34) zero-cross and sample-standard-deviation Bollinger(20,2) signals exactly. Separately label their NIFTY option adaptation: CE/PE, signal-candle stop, 2R target, next-minute execution, 5/10/15-minute horizon. A bearish stock exit is not the same as buying a put.
- Add these two as optional Strategy templates, uninstalled by default; installing creates a stopped, sandbox, unscheduled strategy and inactive Flow. Preserve existing strategies.
- Provide rolling-Sharpe portfolio preference, white-noise and bootstrapped-return preference controls as offline algorithms. Only evaluate meaningful multiasset selection when independent underlying histories exist.
- Add CUSUM, causal calendar-lag features, configurable triple barriers, event uniqueness, revenue-release-aware feature preparation, chronological ML diagnostics, and missing analytics. Do not manufacture alternative revenue data.
- Use existing real market archives and imported development sessions. Exclude all protected final sessions before features, labels, and scoring. Existing development data has been studied before; it is not a fresh blind holdout.
- Use ₹25,000 as the option-study affordability scenario, with 20% cash buffer. Report one-lot opportunity outcomes separately from portfolio returns. Existing live capital and risk limits do not change.
- User approved current saved Kotak charges extended over research dates as a labelled assumption. Preserve the saved fee schedule. Record source hashes, seed, settings, costs, exclusions, and full trade ledgers.
- UI RandomForest gets an explicit 5/10/15-minute label/execution limit and session-balanced overlapping-event weights. Preserve legacy caller defaults; bind new behavior to configuration/version hashes.

## Execution ledger

- [x] Implement and test independent algorithm primitives, controls, and release-aware alternative-data adapter.
- [x] Integrate disabled optional signal templates and verify safe installation.
- [x] Integrate bounded ML horizon, uniqueness weights, feature importance and calibration diagnostics.
- [x] Add reproducible offline runner and run the real-data comparisons and controls.
- [x] Present complete results, coverage, cost assumption, and untestable inputs in a report.
- [x] Run focused/backend/frontend checks and fresh code review; verify the UI where changed.

## Completion evidence

- `data/research/conlan-algorithms-2026-09-27-verified/results.json`: six option variants, fifteen chronological ML runs, six CUSUM/barrier cases, 200 seeded preference controls, nine grid settings, and CMF coverage on seven imported datasets. Protected final sessions evaluated: zero. Saved live fees unchanged.
- Independent reviewer found and verified fixes for initial SMA sign, missing intraday barrier bars, older-period revenue revisions, and five-session confidence intervals. Grid candidate trade/equity ledgers added and recomputed results exactly matched the original study.
- Full backend run: 3,993 passed / 13 skipped / 1 expected failure; frontend: 2,786 passed. Additional revenue pipeline check brings the focused primitive suite to 12 passing. Focused final Research UI suite: 25 passing. Build and targeted lint passed.
- Isolated browser run #9: selected five-minute holding time and 50 trees, completed through actual Research queue/worker, rendered calibration/importance, preserved research-only restriction. Synthetic UI numbers are excluded from investment results.
- Report: `docs/conlan-algorithm-results-2026-09-27.md`, with chart and complete comparisons. No new strategy installed, automation activated, or live setting changed. Backend was not restarted.

Scope distinctions: the two-index portfolio is a labelled proxy for the source stock-universe example; no timestamped company revenue dataset was supplied. The alternative-data pipeline is implemented and unit tested but has no empirical accuracy claim. The existing technical ML model remains research-only; the source repository contains no broker/live inference adapter. Option opportunity studies use ₹25k affordability, whereas canonical ML replay keeps its existing ₹10k policy; these results are not a single continuous portfolio.

No order submission, live settings mutation, activation, or publication is part of this task.
