# Dashboard live indicator values

User request: update the nine-indicator dashboard immediately as market data arrives. Preserve the already chosen candle-close confirmation rule and each indicator's independent conditions.

## Design

Use the existing shared broker stream for index price updates. Calculate provisional numeric values from the currently forming candle, visibly labelled Live. Keep confirmed directions, event times and the overall vote based on verified closed broker candles. Never convert a cached forming bar into a confirmed one just because time elapsed. Refresh history at candle boundaries, with a bounded fallback; no millisecond HTTP polling. Show connection/freshness and distinguish last signal change from live value updates.

IV, PCR, OI and volume-based MFI must retain their own valid source and freshness requirements. Improve their refresh where supported, without relabelling cached fields as ticks or inventing volume. State the actual update cadence. Broker cadence limits apply; a 1 ms clock is not new market data.

## Implementation

1. Snapshot the actual running frontend into `workspace/dashboard-live-signals/frontend`, record hashes, and preserve unrelated edits.
2. Add behavior tests for immediate price previews, unchanged confirmed votes, stale/reconnected/wrong-symbol ticks, missing candles, and automatic post-close history refresh. Implement a scoped live preview helper/hook and integrate it in the dashboard.
3. Update the table to distinguish provisional values and confirmed signal times. Investigate option stream fields and use safe bounded refresh for unsupported sources. Test source independence and freshness.
4. Run relevant tests, the full frontend suite, TypeScript and a production build. Obtain an independent review; address any issues.
5. Install only changed sources and built assets after checking baseline hashes. Back up overwritten files, preserve old hashed assets and publish the new index last. Verify the running dashboard. No backend restart or broker orders.

## Review focus

- A tick must not change the confirmed side, event time or vote.
- Cached values from another user, symbol, timeframe or connection must not become live values.
- Missing OHLC/volume history must not be fabricated; incomplete candles wait for broker reconciliation.
- Tick delivery must not trigger unbounded REST calls, and failed history requests must not promote cached bars.
- Options-source timestamps and cross-leg validation must remain intact.
