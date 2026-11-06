# Option SL closing-session fix

Goal: preserve a fully observed shortened closing candle at the verified exchange end time so ATR carries across normal sessions.

Evidence: selected NIFTY03NOV2623300CE minute archive ends at15:39, NFO metadata ends15:40, but15m history ends15:15. Existing production planner reproduces ATR14 unavailable; adding the actual15:30–15:39 closing candle restores the calculation.

- [x] Add failing resampler and history-service tests for complete shortened close, unknown timing, missing/repaired minutes and prices beyond close.
- [x] Pass verified exchange end metadata into canonical minute aggregation; emit the final bucket only when all scheduled source minutes exist. Keep intraday gap rejection and current forming-bar behavior.
- [x] Run relevant backend history tests and frontend planner regressions; replay actual archived option prices before/after.
- [x] Fresh review of touched backend files, then gracefully reload the worker, fetch chart history read-only and verify the UI calculation. No order placement or chart-entry changes.
