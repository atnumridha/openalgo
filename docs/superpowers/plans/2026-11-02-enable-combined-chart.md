# Combined chart activation implementation plan

> **For agentic workers:** Use superpowers:executing-plans for this activation and chart integration.

**Goal:** Enable the existing combined Kotak/Flattrade service and expose its manual order ticket and owned-position controls beside the existing chart.

**Architecture:** Keep the current Neo chart and its indicators. Mount a compact broker panel for Indian index/options charts, reuse the account-scoped combined API/ticket/position components, and plot only selected-account levels matching the chart's exact symbol and exchange. Use existing isolated broker processes and private signed worker configuration.

**Tech Stack:** React 19, TanStack Query, Lightweight Charts, Flask, SQLite, existing Pi/Kotak adapters.

**Spec:** ../../validation/flattrade-chart-integration-2026-11-02/review.md and the existing 2026-10-20 combined terminal design. User approved the combined route with “allow combined” on 2 November 2026.

## Global constraints

- No live test order or automatic entry; broker selection must never submit.
- Keep the active Kotak login/database and isolated Flattrade login/database separate.
- Broker failures and missing logins stay visible. No other-broker fallback.
- Preserve existing chart pattern, EMA, pivot, volume and RSI behavior.
- Keep the existing daily entry/risk policy visible; exits stay available when entries are blocked.
- Existing SL and exit actions manage only controller-owned positions. Pending-entry cancellation uses the controller's coordinated full-exit operation, preserving partial-fill handling.
- Flattrade targets remain server-monitored plan levels; no claim of broker-native TP or target dragging in this activation.

## Review focus

- Broker/symbol changes during refresh or preview must invalidate the old ticket and remove mismatched levels.
- Selecting an index must not draw option-premium levels on the index scale.
- A disconnected Flattrade account must not display a synthetic zero balance or become ready through Kotak data.
- A pending entry with zero fills must remain visible with a cancel-entry action.
- Activation must retain the worker's actual local login identity, even when the central UI username differs.

### Task 1: Compact account-scoped chart panel

Files: new `frontend/src/components/combined-terminal/CombinedChartPanel.tsx` and tests; modify `NeoMarketChart.tsx` to mount panel and exact-match price lines; export the existing owned-position row for reuse.

- [x] Write and run failing tests for broker selection, exact contract routing, index/option scale isolation, disconnected status and no order on mount/selection.
- [x] Implement a collapsible panel, selected-account funds, visible entry limits, manual ticket, owned exits/SL changes and recent symbol-matched orders/fills.
- [x] Add clear “Cancel entry / close remainder” wording for managed pending entries.
- [x] Run the new and existing combined UI suites and relevant Neo chart tests.

### Task 2: Private combined service activation

Files: existing ignored private worker/registry files and `.env` configuration; no secrets in tracked source.

- [x] Back up private configuration; verify distinct databases, ports, worker identity and signing files.
- [x] Configure the active Kotak instance as its fixed local worker and the combined coordinator. Register the existing isolated Flattrade worker using its actual local login user.
- [x] Activate the existing local services through their launchers; enable manual Flattrade mutations only within the user-authorized combined setup.
- [x] Inspect status, books and session readiness only. If Flattrade requires login, open its normal local sign-in page and retain explicit disconnected state until authenticated.

### Task 3: Verification and rollout

- [x] Run focused offline backend/UI tests, TypeScript/build validation and diff checks.
- [x] Review changes for account ownership, stale data, duplicate submission and unintended auto-entry behavior.
- [x] Verify the combined panel and enabled configuration through the browser; return a factual readiness status for each broker.
- [x] Save deployment/test evidence and explain any remaining Flattrade sign-in requirement.

## Execution record

The existing `codex/neo-native-kotak` linked worktree serves the application. Reuse it and preserve its pre-existing changes; no branch-wide commit or reset. Apply only scoped changes and keep private deployment backups. Route approval is already supplied; proceed in this session without another permission question.

Validation: 109 UI and 98 backend tests passed; TypeScript and production build passed. Read-only Kotak verification succeeded; Flattrade daily Pi sign-in remains a user step. Evidence: ../../validation/flattrade-chart-integration-2026-11-02/activation.md.
