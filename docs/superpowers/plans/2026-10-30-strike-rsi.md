# Per-contract RSI 14

- Add a scoped calculator using verified broker candles and the existing LiveIndicatorPreview. Keep live preview separate from closed RSI and reject stale/wrong-contract quotes. Test independent CE/PE values, warmup and source freshness.
- Add a background data component. Load all listed contracts progressively with at most two history requests; prioritize the selection and most-traded strikes. Reuse current verified chart history when available, cache by account/mode/contract/timeframe, cancel on scope change, and coalesce quote-driven list updates to once a second. Test concurrency, cancellation and history errors.
- Pass the selected timeframe from the workspace. Show contract-specific RSI with Live/Closed/unavailable labels in both menus and selected badges, preserving volume ranking and automatic selection. Verify chart regressions, types/build and the actual menu.
