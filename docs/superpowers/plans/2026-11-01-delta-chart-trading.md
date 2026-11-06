# Delta India chart trading implementation plan

> For agentic workers: use subagent-driven-development for the independent gateway, panel and chart layer tasks, then verify their integration.

**Goal:** Trade and manage Delta India perpetual positions from the existing live chart, with 5x default leverage and contract-specific limits up to 200x.

**Architecture:** An authenticated, CSRF-protected Flask gateway owns credentials, fresh preflight, contract validation and a durable mutation ledger. A compact React panel polls broker snapshots; a lightweight-charts layer draws acknowledged orders and prepares drag edits for explicit submission.

**Tech stack:** Flask, SQLite, HMAC-SHA256, React, TanStack Query, Lightweight Charts.

## Constraints

- Existing Kotak login and chart research features remain usable.
- Production API origin is fixed to api.india.delta.exchange. Credentials never enter chart state or logs.
- User actions send real orders; development verifies read-only production data and mocked mutations only.
- Whole contracts, tick-aligned prices, broker leverage limits and reduce-only position exits are validated server-side.
- Timeout means pending reconciliation, never automatic resubmission.
- Replay/history and stale/mismatched snapshots cannot drive trading lines or actions.
- Chart entry/SL/target order lines show broker evidence; drag produces a proposal, not an acknowledged change.

## Tasks and ownership

- [x] Gateway: services/delta_chart/, blueprints/delta_chart.py, test/test_delta_chart*.py. Test owner/session/CSRF boundaries, signed requests, parameter validation, limits, reduced closes, idempotency and unknown outcomes.
- [x] Panel: frontend/src/api/deltaChart.ts, components/neo-desk/DeltaTradePanel.tsx and tests. Test default 5x, caps, review, stale state, symbol switch and pending action behavior.
- [x] Layer: frontend/src/components/chart-toolkit/DeltaOrderLayer.ts and tests. Test acknowledged lines, tick snapping, proposals and cleanup.
- [x] Integration: app.py and NeoMarketChart.tsx. Test live Delta gating, history isolation and cleanup; preserve all existing chart levels/patterns.
- [x] Verification: focused backend/frontend tests, TypeScript, production build, read-only local endpoint and browser inspection. Publish assets atomically and reload Flask workers only after checks pass.

## Review focus

1. Account or symbol changes invalidate a prepared order and any chart lines.
2. Delayed HTTP responses never cause duplicate exchange actions.
3. Exits and protective orders cannot reverse a position.
4. A partial or failed account read disables trading instead of presenting an empty account.
5. Leverage changes are submitted only as part of an explicit reviewed entry action.

Authenticated production verification remains blocked by the Delta API-key IP whitelist; see docs/validation/delta-chart-2026-11-01/report.md.
