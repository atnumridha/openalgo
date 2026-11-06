# Gautam Liquidity Concepts Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans, task by task.

**Goal:** Create and validate a separate TradingView indicator from researched public Gautam Jha concepts.
**Architecture:** A tested causal sweep/response/entry engine is reused for Daily and1H/4H/1D references and a mechanical trend-pullback source. Context-only CHoCH/momentum cues stay distinct. Confirmed HTF data uses offset tuples.
**Tech Stack:** Pine v6, existing PineTS runtime, Node test runner, TradingView compiler.
**Spec:** docs/superpowers/specs/2026-10-28-gautam-liquidity-design.md

## Global constraints
Separate from DPA/PK/BB. No invented exact discretionary rules or performance claims. Preserve earlier close-confirmation preference unless user chooses original break. No broker actions, installs, subscriptions or community signup. Source transcripts stay temporary.

## Review focus
- Fresh attempts beyond the original daily boundary, without recycling a spent peak.
- Next-candle-only Daily trigger; no response-bar lookahead or later stale trigger.
- Pending stop/target crossed, entry+exit and simultaneous directional conflicts must not be clean entries/wins.
- HTF pivot/reference availability, target chronology, daily reset, India-session overnight gaps and24/7 BTC.
- Context cues must never masquerade as proven institutional flow or exact author signals.

## Task 1: Source audit and rule engine
Create scripts/tradingview/tests/gautam_liquidity.test.cjs and scripts/tradingview/gautam_liquidity_concepts.pine.
- [ ] Finish selected-source chart checks, document exact rules and proxies.
- [ ] Write actual-Pine failing tests for independent sweep/response/next-bar entry, both modes, mirrored long/short, fresh peaks, freeze, target/stop invalidations and OHLC ambiguity.
- [ ] Run RED, then implement minimal engine and achieve GREEN.
- [ ] Add and verify causal HTF/local target/continuation/context functions with actual-Pine fixtures.

## Task 2: Indicator assembly and chart verification
Create scripts/tradingview/gautam_liquidity_README.md and docs/validation/gautam-liquidity-2026-10-28.md plus evidence directory.
- [ ] Assemble independent rows, clear state/levels, Bull/Bear labels, context and confirmed alerts.
- [ ] Run all Pine suites, independent code review and fix important findings with regressions.
- [ ] Compile and apply separate indicator in existing chart slot on standard BTC1m. Record actual settings, signal counts and evidence without calling them strategy P&L.
- [ ] Save chart layout and deliver files with explicit coverage/limitations.

## Execution ledger
Active user request explicitly expanded research into creation of a strategic indicator. No commit/push requested. Current repository contains unrelated untracked work; only new scoped files are created. Earlier275-item channel inventory is discovery only, not proof of watched coverage.

## Ruling following explicit user steering
Replace prior proposed automatic HTF pivots, numerical trend strength and CHoCH/momentum proxies with manual source-context inputs. Remove min-R/tick buffers and model trade outcomes. Execute automatic daily setup and manually activated event/first-pullback variants only. This avoids presenting invented thresholds as Gautam Jha rules. Tradeoff: discretionary rows need marked levels; they remain WAIT by default. Source interval is strictly1m. See revised spec for the interface and semantics.

## Expanded user research / live correction
User authorized parallel research of most-watched/liked lessons and live trades. Three research agents examine primary channels, selected popular lessons and3live recordings. Body-quality judgment is explicitly part of live DQRS but no universal ratio is stated. Ruling: automatic daily detections become candidates; reviewed entry requires exact response timestamp, and actual trade risk counts remain manual. Cost: indicator cannot autonomously certify the author's qualitative decisions. Added full-assembly tests for approval and risk gates before implementation; RED undeclared rawSd then GREEN35/35. Earlier27-test review found3gap/expired-target defects, all reproduced (4regressions including mirror) RED→GREEN; all93tests passed before latest live amendment.

## Final revision evidence
22sourcevideos reviewed at explicit differing depths;76ranked video/live discoveryrows and17exact engagement samples. Three most-viewed live replays checked; no likes-global-ranking claim. Added source-selected manual Event stop because event lessons provide no universal initialSL. Event context checkbox now explicitly requires causal trap/COC permission for selected direct response. Reviewed output is chart-only; exported alerts are candidate review notices because TradingView alert inputs are saved snapshots. Alert interface test and manualstop regression observed RED then GREEN. Strengthened chartguard assertions against rawcandidate output so unapproved entries cannot mask missing guards. Entire suite99/99 passes. No broker/execution files changed.
