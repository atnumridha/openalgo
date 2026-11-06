# NIFTY Entry Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Test 12 fixed, source-informed NIFTY single-option buying candidates against the user's win-rate and payoff requirements.

**Architecture:** A separate causal index-feature/state module emits entry events. A research runner joins those events to existing option-minute pairs and the already-tested fee/payoff engine. Reports preserve failures and distinguish reused history from fresh validation.

**Tech Stack:** Existing Python/pandas/numpy runtime, unittest, JSON/text reports.

**Spec:** `docs/superpowers/specs/2026-10-29-nifty-entry-research-design.md`

## Global Constraints

- 12 candidates only; no post-result tuning. One long CE/PE, maximum two entries/day, dated one-lot quantities.
- Close-confirmed index events, next option-minute open; 09:45–14:30 entries, 45-minute maximum hold, 15:15 final exit.
- Fees and slippage included in targets and outcomes; independent 80% and payoff gates.
- Both periods reused; no live changes, no fresh-validation or guarantee claims.

## Review Focus

- Completed-bar alignment: no 15-minute future context leaked into five-minute events.
- Missing/repaired opening bars: excluded from session-level noise/range calculations.
- State cancellation/session changes: first touch and three-bar expiration enforced.
- Gap fills and overlapping trades: one position, unknown ends day, stops cannot cap gap losses.
- Summary qualification: both periods must pass; zero trades or unknowns cannot qualify.

### Task 1: Research and data audit

- [x] Gather three primary-source hypotheses and distinguish adaptations.
- [x] Finish bounded local/newer-source coverage audit.
- [x] Freeze design and common exits before running outcomes.

### Task 2: Causal signals

**Files:** Create `workspace/nifty-entry-80/index_entries.py`, `test_index_entries.py`.
**Interfaces:** `aggregate(bars, minutes) -> DataFrame`; `build_context(index_frame, official_dates) -> DataFrame`; `entry_events(context) -> list[dict]`. Five-minute rows carry `timestamp` as bar start and `signal_time` as final minute start; index15 context is joined on completion time.

- [x] Write failing fixtures for full/missing/repaired bars, no future context, prior-only bands, CE/PE mirror signals, cancellation and session reset.
- [x] Run focused unittest and observe missing behavior.
- [x] Implement aggregation, Wilder/EMA features and three independent state machines per exact source/spec rules.
- [x] Run focused tests and full research tests; expect all pass.

### Task 3: Chronological replay and reporting

**Files:** Create `workspace/nifty-entry-80/run_index_entries.py`; output `index-entry-comparison-2026-10-29/`.
**Interfaces:** Consume entry events and `payoff_engine.replay_payoff`; output per-policy results with input/code/protocol hashes, summaries, monthly/side/exit analyses and unknowns.

- [x] Add failing replay integration tests for next-open mapping, independent entry eligibility, gaps, daily trade cap and both-period qualification.
- [x] Implement fixed 12-candidate runner without changing older engines.
- [x] Run tests; run all candidates over the full available valid dataset and rerun after the review correction.
- [x] Reconcile counts/fees/targets, check prefix invariance and read every candidate summary.

### Task 4: Independent review and delivery

- [x] Fresh reviewer audits signal causality, fills, fee model integration, summaries and qualifications.
- [x] Fix material findings with a failing regression test and rerun affected outcomes.
- [x] Write report with exact rules, data limits, comparisons and explicit pass/fail result.
- [x] Prepare plan and results for delivery. No candidate qualifies; evidence gaps are documented and no variant is deployed.

## Execution record

The user requested planning and execution together. Implementation proceeds in the existing separate research workspace, preserving the app and previous experiments. No commit/push or chart installation is required for the research deliverable. Progress is recorded in `workspace/nifty-entry-80/index-entry-progress.txt`.

### Task 5: User-requested Realshyt process audit

The user selected the process in https://realshyt.com/guides/backtest-trading-strategy, not a reproduction of the losing two-line strategy. Preserve every version; add yearly and zero-cost comparisons, target/stop/time exit fractions, average R and break-even rate; trace five reproducibly random days; independently check data where available.

- [x] Add and run independent Decimal cost, tick-grid and metric tests (three new tests; full suite 56 passes).
- [x] Create yearly/zero-cost and five-trade evidence in `index-entry-comparison-2026-10-29/`.
- [x] Run bounded independent data QA: daily NSE-derived metadata agrees substantially, but 7.56% of archived bars have off-tick prices and no independent overlapping minute option feed exists locally.
- [x] Run separate strict tick-validity sensitivity, preserving original output and never silently rounding data.
- [x] Prepare consolidated report with unknowns and unverified execution/data requirements explicit.

Further validation plan: obtain independently checkable minute option prices/quotes; freeze any candidate before collecting a new test period; require at least 50 subsequent paper trades plus the original both-period win/payoff criteria. The current 12 variants qualify neither before nor after data-quality sensitivity. This is a plan, not a scheduled monitor or broker action.
