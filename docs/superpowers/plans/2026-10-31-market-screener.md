# Market Screener and Chart Candlestick Setup Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Add a native analytical Screener page with saved rules, sources/coverage, sound alerts and exact chart handoff, plus selectable candlestick setups on the chart.

**Architecture:** A pure TypeScript rule engine in a dedicated Web Worker reuses existing chart math and candle geometry. Authenticated Flask endpoints supply bounded stored/refreshed histories and owner-scoped saved screens/events. Chart links carry validated instrument, timeframe and pattern identity.

**Tech Stack:** Existing React19, TanStack Query, UI primitives, TypeScript, Web Worker, Flask, SQLAlchemy, Historify and Vitest/pytest; no added dependencies.

**Spec:** docs/superpowers/specs/2026-10-31-market-screener-design.md

## Global Constraints
- Work in existing isolated running checkout /Users/nmandal/.codex/worktrees/neo-native/openalgo on codex/neo-native-kotak; preserve unrelated changes. No commits/pushes.
- Existing appearance and full chart size; no order APIs, broker writes, external notifications or deployment of a scanner daemon.
- Maximum rule depth3 and24 leaves, numeric periods1–500; first-release single selected timeframe, no arbitrary eval.
- Selected visible-screen sound monitoring, at most25 automatically refreshed broker instruments, cached history before bounded network reads.
- Source observation times, owner/mode/revision identity, own sessions/ticks and missing-data truth must be retained.

## Review Focus
- Missing data/volume, stale snapshots or a failed refresh must not pass a comparison or rearm a sound alert.
- Worker replies from an older user/rule/universe/timeframe must never overwrite current rows.
- A neutral ANY/volume rule must not invent LONG/SHORT; explicit saved intent supplies direction.
- Pattern selection changes evidence identity and confirmed overlays; an option bearish observation cannot plot a bought-premium short plan.
- Open-chart links must initialize exact contract/timeframe/pattern with safe defaults and support browser back/forward.

### Task1: Shared candle patterns and rule engine
Files: chart-toolkit/candlePatterns.ts/test.ts, candleProbability.ts/types/test.ts; new screener/model.ts, engine.ts/test.ts, presets.ts, scan.worker.ts.
Interfaces: PatternSelection/recognizePattern(bars,choice); ScreenDefinition, RuleNode, ScanDataset/ScanRow; validateDefinition(value), evaluateScreen(dataset,definition), evaluateBatch(request). Results use match/unknown/no-match and reasons.
- [x] Write/run failing causal pattern-selection, tick/session/evidence identity and rule ALL/ANY/crossing/missing/prefix tests.
- [x] Implement shared pattern-family recognition and bounded rule evaluation using ToolkitEngine, NineIndicatorEngine and existing chart geometry; add explicit intents/presets.
- [x] Add worker request/revision protocol; run focused engine/candle tests and type check.

### Task2: Data coverage and saved-screen API
Files: services/screener.py, database/screener_db.py, blueprints/screener.py, app.py; test/test_screener.py.
Interfaces: GET /screener/api/universes and /screens, POST/PUT/DELETE /screens, POST /data for bounded identities/source choice, GET/POST /screens/<id>/events. Native UTC candle payload carries observation/source/session/tick and coverage; no inferred live freshness.
- [x] Write/run failing stored-history normalization, owner-isolation, validation, update revision, event idempotency and API auth tests.
- [x] Implement owner-scoped definitions/event store, stored catalog/watchlist/NIFTY50 universes, cached/bounded snapshot reads and explicit broker refresh (public Delta handled by existing frontend adapter). Reuse canonical contract metadata/session and configured broker calls.
- [x] Verify routes, errors and limits, with no order functions imported/called.

### Task3: Screener UI and lifecycle
Files: api/screener.ts; components/screener/RuleBuilder.tsx, ResultsTable.tsx, useScreener.ts, alerts.ts/test.ts, ScreenerWorkspace.tsx/test.tsx; pages/Screener.tsx; App.tsx/config/navigation.ts/hooks/usePageTitle.ts/blueprints/react_app.py.
Interfaces: query-scoped data batches feed worker; visible current screen monitoring uses persisted definitions and fresh-match transitions. CSV and watchlist actions use existing APIs.
- [x] Write/run failing component rule editing/preset, save/duplicate/rename/delete, stale/cancelled request, alert baseline/rearm and chart-link tests.
- [x] Implement responsive native page with presets, ALL/ANY groups, bounded rows/paging/search/sort/columns, coverage, source times, load/cancel, sound arming/history and saved screens.
- [x] Add route/navigation, owner/mode reset, worker cleanup/visibility handling and exact CSV escaping; verify UI tests.

### Task4: Chart candlestick setup and validated handoff
Files: components/screener/chartTarget.ts/test.ts; NeoTradingViewWorkspace.tsx/test.tsx, NeoMarketChart.tsx/test.tsx, candleProbabilityTypes.ts/Panel as needed.
Interfaces: parseChartTarget(search), chartTargetUrl(row,screen); URL fields symbol/exchange/interval/study/pattern whitelist. Controlled or internal PatternSelection reaches analyzeCandles.
- [x] Write/run failing exact-contract initialization, invalid target, URL back/forward, selected-family filtering, historical evidence reset and CE/PE/crypto risk-reference tests.
- [x] Implement chart pattern selector and shared setup filtering; preserve chart height and all existing behavior when no target exists.
- [x] Verify targeted chart/screener integration tests and complete affected chart suites.

### Task5: Release verification and review
- [x] Run backend feature/contract/risk tests, complete screener/chart frontend suites, type check and production build; inspect output.
- [x] Obtain one fresh read-only whole-change source review and fix important findings with RED→GREEN regressions and a green suite.
- [x] Activate the local service/build and verify health, authenticated routes and matching served bundles. Respect prior browser access restriction.
- [x] Record scope, source/visual limits and verification in docs/validation/2026-10-31-market-screener.md.

## Ledger
Ruling: The user selected the recommended first release and added chart pattern setup. Existing authorization covers inline implementation; no further plan/permission round is required.
Ruling: Reuse the existing isolated running checkout. Existing dependencies and the earlier794-test chart baseline are available; run targeted baseline checks before changes.
Ruling: The design-system search matched a dense financial dashboard style but suggested an unrelated marketing-page layout; retain the app's established UI tokens, typography and navigation instead of introducing a theme.
Pre-flight: Tasks1/3/4 share validated ScreenDefinition/PatternSelection and chart target values; Task2 persists and validates the same schema, with backend payload limits independently enforced. Data timestamps are raw UTC; do not reuse the chart's legacy IST-shifted transport boundary for screener payloads.


### Progress and authorized parallel execution
The user explicitly requested multiple threads. Created three local work threads using the same running checkout with disjoint ownership: backend/data persistence, screener UI/alerts, and seven chart strategy configuration templates. Parent owns shared engine/patterns/chart integration and release verification. This supersedes the earlier inline-only executor choice; no separate worktrees or commits.

Task1: pattern selection/new families31 tests passed; screener rule engine9 tests passed before the additional future-session regression. Shared helpers reused/exported rather than duplicating chart EMA or adjacency formulas.
Task4: chart family filtering/integration and exact screener handoff tests passed (39 chart/target checks and20 workspace checks). No NIFTY request precedes a linked exact premium. The existing chart adapter's target callback required an input-prop rename, now verified.
Ruling: Additional seven strategy configurations are in scope, per forwarded request and the user's clarification that it is additional. They remain templates with source claims labelled and missing rules explicit; unknown IDs never reach the five-mode research engine.


### Final implementation and verification
All five tasks implemented. Three work threads completed their disjoint work; parent integrated and obtained one independent whole-change review. Important findings were fixed with failing-then-passing regression tests. Final affected suites:869 frontend tests/66 files and100 backend tests, type check and production build all exit0. CPU benchmark500×600 candles:575ms excluding data loading. Source/provider and browser-interaction limits are documented in `docs/validation/2026-10-31-market-screener.md`.

Ruling: Official current NIFTY50 membership is not connected. Expose downloaded histories/watchlists and the two supported public crypto symbols without claiming full-market membership or coverage. Seven source configurations remain explicitly unconfigured where exact rules were absent; no orders or automated strategy activation.

Ruling: Alert monitoring refreshes real history once per minute, including longer timeframes, because a once-per-timeframe schedule would contradict the90-second observation freshness limit and miss exchange-aligned hourly closes. Confirmed-bar evaluation and the25-instrument limit remain in force.

The user's existing local application is the delivery target; keep the existing branch/worktree and uncommitted changes in place. No merge, new commit, push, dependency installation or additional permission round is needed.
