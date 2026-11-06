# Chart-aware options indicators implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Make the two independent option-selling indicators follow the active chart's market without borrowing another market's prices or claimed results.

**Architecture:** Keep the validated NIFTY files as snapshots. Generate separate chart-aware versions using shared routing and configuration. Auto-identify NSE NIFTY/BANKNIFTY and BSE SENSEX index/dated option charts; allow an explicitly bound custom chart and European cash-settled option template. All entries continue to require fresh option data and confirmed one-minute candles.

**Tech Stack:** Pine v6, Python source builder, Node PineTS tests, TradingView editor.

**Spec:** The user's requests in this conversation: other indices and markets, focus on the active chart, independent indicators, clear signals, candle-close confirmation, one enabled at a time.

## Global constraints

- No broker orders. Preserve existing chart studies and NIFTY snapshots.
- Standard one-minute chart; no inferred intrabar execution on higher timeframes.
- NIFTY current-cycle defaults apply only to NIFTY. Other markets require their own cycle, anchors, ATR and volatility inputs. Custom profiles bind to an exact chart/underlying so they cannot leak onto another market.
- Unknown markets or missing data show WAIT/configuration required. Non-NIFTY variants are labelled unvalidated; no transferred win-rate claim.
- Maximum 40 request contexts per script. No new realtime strike requests; fixed historical banks.
- An option chart uses underlying prices for strike selection, its own prices for label placement, and no index-price strike plots.

## Review focus

- Similar tickers and wrong exchanges must not accidentally route to NIFTY.
- Expiry mismatch and reused custom settings must block signals.
- Option premiums must never become the underlying ATM price.
- Missing chart minutes and quote timestamps must not create a later valid-looking stop history.
- New market settings must not retain NIFTY anchors, VIX or pinned ATR.

### Task 1: Chart routing and source assembly

Files: workspace/weekly-options-indicators/build_chart_sources.py; scripts/tradingview/chart_sd_condor_signals.pine; scripts/tradingview/chart_atr_strangle_signals.pine; scripts/tradingview/tests/chart_options_signals.test.cjs.

- [x] Add failing executable Pine tests for routing, option expiry matching, fractional strike rounding and missing underlying prices.
- [x] Implement shared chart routing, explicit custom configuration, underlying requests, parameterized strike banks and context budget. Preserve strategy math and lifecycle from NIFTY sources.
- [x] Run focused tests including NIFTY selection regression, unsupported markets, no-data and sparse-chart cases.

### Task 2: Verify and install

- [x] Compile both generated indicators in TradingView; verify index, matching option and unsupported-chart states. Keep one enabled.
- [x] Run the local Pine suite, inspect a fresh independent review and fix material findings.
- [x] Save chart layout and write operating/verification notes with actual limitations.

## Execution record

Ruling: work in the existing codex/kotak-home-assistant checkout and add separate sources, because this task continues existing untracked indicator work; copying the unrelated research into a new worktree would obscure its provenance. Prior user preference is to proceed without additional planning questions.

Task 1 complete: created separate chart-aware sources and builder; 26 focused PineTS tests pass. Original NIFTY sources unchanged. Synthetic full assembly reproduces the NIFTY snapshots and runs a configured non-NIFTY profile at its own scale.

Review: fresh read-only reviewer found a cross-session gap hole and missing explicit expiry binding on custom option charts. Added failing regression tests, then fixed with underlying source-bar sequence tracking and custom chart expiry binding. Both fixes and the full Pine suite pass: 165/165. No profitability claim follows from these software tests.

TradingView verification: both scripts compiled on NIFTY, retaining their prior selection/reference results. Matching NIFTY option chart retained entry legs/credit and correctly flagged incomplete stop coverage as REVIEW - DATA GAP. SENSEX automatically mapped to BSE:SENSEX and required its own configuration, with no NIFTY legs. The zero/unset expiry display was corrected to Not configured.

Task 2 complete: layout saved and reloaded at https://in.tradingview.com/chart/lyqjV7r1/?symbol=NSE%3ANIFTY. Both chart-aware instances persisted, SD hidden and ATR visible. Final focused 26-case run passed after the display correction. No broker order action taken.
