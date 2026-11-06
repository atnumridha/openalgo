# Shared Trend Public Backtest Implementation Plan

> **For agentic workers:** Execute the authorized offline research in this session. Steps use checkbox tracking.

**Goal:** Test the selected shared strategy on public Hugging Face and GitHub candles, with reproducible trade ledgers and data limitations.
**Architecture:** Standalone research folder, no application changes. Downloader records pinned revisions/hashes; OHLCV normalization and deterministic event replay produce independent currency results and cost scenarios.
**Tech Stack:** Existing Python environment, pandas, numpy, pyarrow, pytest, matplotlib.
**Spec:** docs/research/shared-trend-breakout-design-2026-10-30.txt

## Global Constraints
- Completed five-minute candles; prior 20-bar channels, EMA20/50, Wilder ADX/DMI14, volume >1.2x prior20 mean; 200-bar warmup.
- Next-bar opens; 2ATR stop, 4ATR target; close-based non-loosening trail after 1R; 24-bar deadline.
- 0.25% trade risk, 0.75% portfolio risk, 1% daily equity loss and 3-loss halt; no leverage or pyramiding.
- Cash stocks long-only, 09:30–14:45 entries, flat 15:15 India; separate quote-currency ledgers.
- Public BTCUSDT is an explicitly labeled Binance proxy; no fabricated Delta/index futures results.

## Review Focus
- Incomplete/gapped data must not fabricate candles or enable immediate signals.
- Simultaneous stock signals must share cash and risk budgets.
- Stop and target same bar must choose stop; gaps incur adverse fills.
- Indicators and fills must not use future data; trailing only applies next bar.
- Costs and funding must affect net equity, sizing and statistics.

## Task 1: Public data and fixed run assumptions
- [x] Download 2025 BTC perpetual candles/funding from pinned HF revision; selected five cash stocks from GitHub release.
- [x] Record source hashes, schema, exact coverage, duplicates, missing bars, and exclusions.
- [x] Fix hypothetical capital: 10,000 USDT and 1,000,000 INR; no leverage. Base all-in illustrative fees: BTC 6bp/side and stocks 5bp/side; adverse slippage 2bp/side. Also zero and double friction scenarios. These are sensitivity assumptions, not verified broker tariffs.
- [x] Freeze Jan–Aug initial / Sep–Dec later evaluation before examining performance; no tuning.

## Task 2: Tested offline replay
Files: workspace/shared-trend-backtest-20261030/engine.py and test_engine.py.
Interfaces: indicators(frame, indian=False); size_units(equity, price, stop_distance, step, fee, slip, available); resolve_bar(side, entry, stop, target, open, high, low); replay(frames, settings, funding).
- [x] Write behavior tests for prior-channel lookahead, next-open entries, long/short stops/gaps, stop-first ambiguity, risk sizing, no stock shorts, cutoff, trailing, portfolio limits and data rejection.
- [x] Run tests and observe missing implementation failures.
- [x] Implement pure research engine and make the tests pass.
- [x] Review source separately and verify targeted research suite. Application suite is outside scope because no app code is changed.

## Task 3: Runs and report
- [x] Execute baseline/zero/double friction and separate chronological periods with unchanged rules.
- [x] Save summary, per-trade and mark-to-market equity CSVs, monthly results, chart, source manifest and readable report.
- [x] Independently reconcile sum of trade net P&L with ending equity and check risk constraints and timestamps.
- [x] Document blocked markets, proxy data, selected-universe bias, costs and data coverage. No live activation.

## Rulings
- The user's request to backtest authorizes this research execution; defer production integration.
- Keep research isolated in a new folder; do not branch, edit runtime files or commit unrelated working-tree changes.
- Compare fixed assumptions before and after costs; no claimed calibration of trading fees.

- Data ruling before performance evaluation: primary 2025 HF crypto source returned HTTP 403 for public blobs. Use the accessible pinned 2020–2024 BTC futures file; BTC test Jan–Nov 2024, later evaluation Sep–Nov 2024. Stock test remains calendar 2025. Verify BTC timezone independently; supplement with official Binance funding archives.

Completion evidence: 21 replay tests passed; independent audit of 18 runs passed. Source files and app configuration are separate; no application code was changed. Results fail the cost-aware test. Final source review performed directly; no agent delegation.
