# Chart Replay and Fair Value Gaps Implementation Plan

**Goal:** Add synchronized historical replay and labelled Fair Value Gap zones to the existing Kotak scalping charts.

**Architecture:** Freeze completed candles from the existing live chart cache into a shared replay timeline. Keep the raw live model collecting data separately from the displayed prefix. Derive RSI, structure and FVGs from displayed candles only; retain live monitoring and ticket prices outside replay.

**Tech stack:** React, TypeScript, lightweight-charts v5, Vitest and Testing Library. No additional packages or backend changes.

**Scope and constraints:** Existing user approval covers implementation. Preserve manual order availability and server monitoring. Do not submit orders when testing, change credentials, restart the service or deploy unrelated files.

## Work items

- [x] Test and implement `chartReplay.ts`: completed snapshots, common timeline, immutable prefixes and IST date parsing.
- [x] Test and implement `ChartReplayControls.tsx`: date, scrubber, step, playback speed, pause, end and Return to live. Reset on instrument, timeframe, layout or account changes.
- [x] Integrate replay into `ScalpingCharts.tsx` and `KotakAssistantChart.tsx`: separate live and visible arrays; hide future fills and current live levels during replay; keep shared live cache current.
- [x] Test and implement `fairValueGaps.ts`: consecutive three closed candles, bullish/bearish gaps, partial touch and full fill, no future or overnight formation.
- [x] Add FVG toggle and clipped, labelled zones on CE/index/PE; derive them from the replay prefix when replaying.
- [x] Verify chart isolation, RSI, timer, indicators and unchanged live account refresh behavior through focused tests. Review implementation, run assistant tests, TypeScript and scoped lint.
- [x] Copy only chart files and dependencies to the active Kotak checkout; build and atomically activate static assets, preserving old assets. Verify UI replay, FVG and live monitoring without orders or service restart.

## Review focus

- A forming or future candle must never confirm a replay indicator or leak through markers, levels or shared cache.
- Missing history in one pane must produce a useful message instead of asynchronous clocks.
- Live updates during replay must remain available immediately on Return to live.
- Switching scope must stop playback and discard old snapshots.
- FVG overlays must remain in the price pane and follow pan/zoom without covering RSI or chart interaction.

## Verification before activation

- Source assistant suite: 180 tests across 31 files passed. TypeScript build check passed.
- Scoped lint: all nine new model, control, overlay and test files passed. Existing broader chart files retain earlier lint diagnostics.
- Review findings addressed: confirm gaps at close without a tick; use actual chart plot width; anchor labels inside the plot.
- Replay tests verify synchronized panes, date selection without lookahead, play/pause/speed/end, scope reset, future marker filtering, live cache updates and Return to live. FVG tests verify formation/mitigation and history boundaries.

## Activated and verified in the dashboard

- Active checkout assistant suite passed 156 tests before the final label refinement; the final source suite passed 180 tests after it. TypeScript and the production build passed. All 13 scoped source/test files match the active checkout.
- Dashboard and all 29 referenced assets returned HTTP 200. Server PID 74312 remained unchanged; no service restart or broker orders were used. Previous static assets retained and rollback copies saved.
- Browser checks: all three panes replayed the same 13 October timeline; stepping, playback, speed, pause and FVG toggle worked. Hidden zones were empty when the toggle was off. Latest-candle RSI and FVGs recalculated in replay. Return to live removed replay headers and restored current candles.
- Live monitor continued syncing with 18 saved fills today and no additional open positions. The dashboard was left in live chart view.
- Final visual refinement spaces nearby FVG labels 24px apart and retains full bounds/direction in the label tooltip. Screenshot: /tmp/kotak-replay-fvg-verified.jpg.
