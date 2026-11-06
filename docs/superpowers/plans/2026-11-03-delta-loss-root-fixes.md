# Delta loss root-cause fixes

> For agentic workers: use superpowers:subagent-driven-development with bounded ownership and tests before implementation. User explicitly requests fixes to the audited losses and realistic trend SLs. No loss halt is authorized.

**Goal:** Correct structural-stop clipping, repeated setup reuse, and hidden protection failures; improve staged structural profit protection without promising profitability.

**Architecture:** Keep TradingService and broker-owned market SL authoritative. Pure strategy rules produce fresh completed-candle setups. Durable backend setup claims prevent reuse. Management failures become visible status and persistent alerts. Position stops never widen.

**User ruling:** Auto stays enabled; do not add daily or consecutive-loss halts. Existing ₹20 planned risk and maker-entry / market-exit rules remain. If a structural SL cannot fit one contract under the risk budget, skip rather than clip SL inside invalidation.

## Tasks
- [x] Reproduce EMA SL clipped at 1.5ATR inside support/pullback; replace with true buffered invalidation. Require a completed fresh EMA pullback-and-continuation trigger, aligned higher trend/slope. Preserve generic pattern observations as optional. Add stable setup identity and mirrored tests for chop, stale pullback, fake continuation, structural stop, tick/fee sizing.
- [x] Let structural trailing reduce risk before a full ₹10 lock is feasible. Profit stage first covers actual fees and tick profit when possible; no fixed-rupee forced close or stop widening. Keep own-timeframe closed-candle/ATR buffer, ₹20 initial risk, and visible reason for waiting.
- [x] Propagate blocked/pending management responses into backend status/events and persistent UI alerts. Never overwrite these with generic managing. Verify protection even when strategy candles fail. Add durable setup deduplication across restart/Off/On; require a new completed post-exit setup rather than reusing an unchanged EMA regime.
- [x] Audit all ten backend entries using exact historical candles available before each decision; compare proposed SL with actual price invalidation and classify why rejected/accepted by revised policy. Report filtered winners and losers together; do not tune to this sample or call replay profitable evidence.
- [x] Focused regressions, independent review, hash-checked publication/retained assets and verified graceful restart. Do not arm Auto or place trades as tests. Keep user-authorized running state unchanged.

## Post-release sizing preference
User approved risk-capped automatic quantity; up to 100% balance sizing is allowed below INR2,000. Live fixed-four-lot configuration still awaits user UI handoff after automatic review rejected the Auto toggle. Do not claim the preference is active before verification.
