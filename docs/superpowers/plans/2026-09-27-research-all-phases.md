# Complete the research workflow

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Finish the previously approved research enhancements, with usable optimization and RandomForest workflows, reproducible evidence, and truthful promotion controls.

**Architecture:** Extend the existing research queue, replay, data store and Research page. Reuse the existing portfolio analytics and causal indicator functions. Research never submits an order or changes an installed strategy.

**Tech Stack:** Python, Flask, SQLAlchemy, pandas, optional scikit-learn, React/TypeScript, pytest, Vitest.

**Spec:** User-supplied “Algorithmic Trading Application Review” and its five-phase implementation plan, including subsequent correction to reuse existing metrics/signals rather than introduce parallel systems.

## Global constraints

- Preserve 60 sealed sessions; development feature preparation must not read their prices or labels.
- Limit optimization to 256 candidates and deterministic selection. Keep fixed parameters when varying grid parameters.
- Use chronological expanding folds with purged overlapping labels, never shuffled K-fold evaluation.
- Keep feature construction and prediction independent of validation outcomes; include all eligible prediction rows even when outcomes are unavailable.
- Hash fitted model state, training provenance, predictions and implementation/dependency versions.
- Keep ownership, cancellation, immutable data, freeze/final consumption and forward qualification controls.
- Do not import upstream source code: its freeware license restricts commercial reuse.
- No live activation, broker orders, main-branch publication or account-state changes are authorized by this implementation task.

## Review focus

1. Grid normalization, type aliases and ignored fixed parameters must not change the submitted experiment silently.
2. A missing option outcome must not remove the opportunity from predictions; sealed prices must not affect training.
3. Promotion must preserve the exact selected configuration and provenance; search evidence itself cannot qualify for live.
4. ML unavailable dependencies, cancellation and empty input must produce visible, actionable failures.
5. UI run/report variants must never crash on optimization reports lacking ordinary trade metrics.

## Tasks

- [x] Optimizer/store/API: add failing integration tests for grid bounds, fixed parameters, selection, ownership, cancel and promotion → freeze → final. Fix validation and dispatch; retain provenance and reject incomplete selected results.
- [x] ML: add failing tests for sealed exclusion, missing labels, fold purging, finite inputs, cancellation, actual fitted-model hashes and deterministic predictions. Finish orchestration and optional dependency declaration. Expose validation accuracy separately from trading win rate.
- [x] Research primitives: reuse existing causal features/signals and analytics with focused causal and finite-result tests; expose session-return metrics without inventing a benchmark.
- [x] UI/API: add run-type selector, bounded parameter-grid controls, ML settings, run-specific results and promotion affordance; cover create/inspect/promote/error behavior with tests.
- [x] Lifecycle: verify optimization promotion uses a new ordinary development run and existing freeze/final/qualification gates. Make the ML deployment capability explicit; do not relabel historical schedules as executable live models.
- [x] Verification: run focused tests, backend CI-safe suite, frontend suite, Ruff, lint and production build; inspect the UI, perform independent review and record results.

## Execution record

- Existing branch `feature/research-all-phases` contains related unfinished changes in five files. Continue those changes without switching branches or touching account data.
- Implementation proceeds from the already approved five-phase design in the supplied transcript. A separate clarification is pending on whether a new live ML inference adapter is included; research completion proceeds independently.
- No reply to the ML scope clarification arrived during implementation. Research-only ML was the stated working assumption; live ML inference remains unimplemented and explicitly blocked in the API/UI. This completion does not establish live ML readiness or profitability.
- Independent review found two bounded-work/cancellation issues: grid size validation occurred too late, and opportunity preparation lacked early/per-contract cancellation checks. Added regression tests that failed before each fix and passed after it.
- Browser testing found deterministic-rule controls and promotion wording misleading in ML mode. Corrected the copy/visibility, added a failing UI regression test, then rebuilt and verified the corrected page.
- Final automated verification: backend 3,978 passed, 13 skipped, one expected failure; frontend 2,786 passed in 177 files. Ruff, formatting, frontend lint and production build passed, with existing warnings recorded in the verification report.
- Browser checks exercised the built UI with the actual research API/store/replay/ML worker and synthetic fixtures in isolated databases. See [verification record](../../research-workflow-ui-verification-2026-09-27.md) for the scenario matrix, test-host stall investigation and boundaries.
