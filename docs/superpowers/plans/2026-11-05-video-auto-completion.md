# Automatic video strategy completion implementation plan

> For agentic workers: use superpowers:executing-plans inline, with a fresh final review.

**Goal:** complete automatic chart detection for six missing methods in OpenAlgo/OpenAlgoAll and clearly resolve KRM research.
**Architecture:** existing pure JS engine plus actual Pine parity; existing guide/layer consumers; small default matches list.
**Tech stack:** JS/TypeScript, React, Pine v6, Vitest, Node/PineTS.
**Spec:** docs/superpowers/specs/2026-11-05-video-auto-completion-design.md

## Constraints and review focus

Guidance only, no broker/Auto modifications; causal completed candles; no guessed KRM; preserve unrelated dirty work. Same numeric rules both engines. New York DST/holidays and session boundaries, same-bar ambiguity, conflicting methods, frozen sources and existing single-plan drawings are review focus.

### Task 1 — engine completion
Files: live frontend/src/components/chart-toolkit/videoStrategyGuide.js, videoStrategyTypes.ts, videoStrategyGuide.test.ts; primary scripts/tradingview/validation/video-strategy-completion-fixtures.json.
- [x] Write six mirrored fixture tests, source metadata/support tests, prefix and window boundaries; observe RED.
- [x] Implement six methods using existing create/lifecycle with explicit variant metadata; add automatic confirmed matches selector.
- [x] Observe green engine checks; retain KRM source limitation only if no reproducible primary rules established.

### Task 2 — Pine parity
Files: primary scripts/tradingview/openalgo_combined_indicator.pine and tests/openalgo_video_strategy.test.cjs.
- [x] Add shared-fixture actual-Pine prefix parity for kinds9–14; observe RED.
- [x] Port recipes, New York clock/window expiry and metadata/support predicates, extend Auto across all supported methods.
- [x] Run full Pine suite and inspect source/drawing compatibility.

### Task 3 — automatic guidance and delivery
Files: live frontend/src/components/neo-desk/VideoStrategyGuide.tsx and tests; primary Pine table, README, validation report.
- [x] Write visible auto-scan/matches/direction/local-rule tests; observe RED.
- [x] Show supported count, confirmed matching methods, direction/next condition without manual selection; preserve optional all catalogue.
- [x] Focused frontend checks and build; fresh read-only review; fix Important/Critical via RED→GREEN; deploy/verify both UIs as accessible.
- [x] Save source/hash/screenshots/status/limitations. No broad staging/commit/cleanup in dirty concurrent workspaces.
