# Independent Delta scalping context

The user selected separate 1m entries with a 5m trend filter, independent of the visible chart timeframe. This short design records that approved approach. It is a bounded integration of the current production trend/protection engine, not a new prediction algorithm.

Approaches considered: continue using the visible chart plus its next higher interval (current behavior, unsuitable for the requested quick scalps); or use dedicated 1m/5m execution data (selected by the user). Keep chart indicators, EMA studies and selected timeframe available for viewing.

Fetch fresh public Delta 1m and 5m histories independently of chart studies. Keep observation timestamps fixed, reject mismatched/stale/gapped/invalid data, and use only the latest completed candles. Both existing trend readings must be confirmed and agree for entry; unavailable higher context must fail closed for new entries while verified fast context remains available for existing-position management. Strict entry deadlines are checked again at submission. Refresh at every minute close plus a periodic fallback. No millisecond polling or profit guarantee.

Use the current ATR/structure stop and target, anti-chase checks, maker-only best-quote entry, balance/leverage checks, idempotent entry claim, exchange SL/target, fee-aware trailing, market safety exits, and 30-minute review. Require the scalp target to exceed verified maker-entry plus conservative taker-exit fees and at least a full tick, without assuming a promotional waiver. Keep editable leverage/quantity defaults unchanged.

Give the panel a compact 1m/5m execution label and both trend readings. Use a strategy-specific recovery namespace so a permission saved for an old chart setup cannot arm this new execution mode. New scalp permissions survive display-timeframe changes and resume only after existing account/order/protection reconciliation. Keep symbol/account and cross-tab revocation checks. Existing older-interval plans retain their original chart context for management; their exchange protection stays active.

No live trades or activation during testing. Use tests, the saved historical snapshot and read-only public data. Publish the verified frontend assets; the user controls Auto activation.
