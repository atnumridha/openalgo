# TradingView Top20 Coverage Implementation Plan

> For agentic workers: use superpowers:executing-plans inline, then one fresh final review.

Goal: cover the20drawings in the supplied cheat sheet without duplicate detectors or labels.
Architecture: existing completed-candle pipeline; new harmonic detector feeds ArchiveMatch geometry; existing widening-range detector gains cylinder classification/geometry; one reference catalog also feeds tooltip/outline eligibility.
Spec: user's linked chart and existing6px labels, dotted arrows, confirmation-only signals, deduplication and no financial execution during tests.
Tech: TypeScript, React, Lightweight Charts, Vitest.

Global constraints: no changes to order entry/exit eligibility or fees; existing candle/shape behavior retained; no future pivots; sources are reference data, not executable instructions.

Approach: reuse existing16families, promote existing Broadening Wedge to Megaphone alias, add Gartley/Cypher and a strictly defined expanding-cylinder geometry. A second indicator would duplicate output and is rejected. Image-only matching lacks numerical rules and is rejected.
Ruling: Livermore sketch has no unique numerical/volume recipe; label explicitly means expanding sloping-range breakout, with three confirmed touches on each boundary. No claim of proven accumulation.
Ruling: Gartley usesB0.618±0.03XA, D0.786±0.03XA, BC0.618–0.786AB, CD1.27–1.618BC, approximately equivalentAB/CD (10%). Cypher usesB0.382–0.618XA, C1.13–1.414XA, D0.786±0.03XC. ConfirmD with two right closed bars before a later reversal close crosses their extreme; no projected labels.

Review focus: ratio denominators; bearish reflection; future pivot leakage; wick-only breakouts; duplication against aliases.

Task1 — detectors and tests
- Write failing mirrored valid/invalid ratio, close confirmation, future stability and geometry tests.
- Implement harmonicChartPatterns.ts; add to existing archivePatternEngine.ts.
- Extend existing widening-range geometry, preserving legacypatternID for Megaphone.
- Verify detector and final-pipeline regressions.

Task2 — integrated reference/help/geometry
- Add20-item source catalog with aliases to existing IDs; expose through existing crypto lookup.
- Add help and source links, plain-language hover meanings and coverage tests.
- Verify outlines and final engine; check fresh publicBTC history without inventing missing live matches.
- Run scoped full chart/trading regressions, TypeScript and build; fresh review; publish frontend index last. No backend restart or live financial actions.

Completed: detectors, shared tooltip/outline metadata and duplicate-name handling; 257 focused tests, TypeScript and build passed. Fresh final review completed. Public BTC audit saved in docs/validation/tradingview-top20-2026-11-01; all prior events prefix-stable. See report.md for source definitions, coverage and actual market sample limits.
