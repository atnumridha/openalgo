# Delta account summary and XAUTUSD

User requested live balance, P&L after fees, displayed fees, and XAUTUSD. Extend the existing Delta-only manual chart panel without financial mutations.

- Read verified USD wallet balance/available balance from Delta without subtracting charged fees twice.
- Show mark-based gross open-position P&L, provable entry fees, estimated maker exit fees including GST, and estimated net. Keep incomplete fee attribution unavailable rather than inventing a value.
- Keep 5x default, maker-only entries/exits, strict reviewed balance sizing, product-specific ceilings, stale-source guards and non-Delta hiding.
- Add XAUTUSD to quick market choices and route history/search/live data through generic Delta adapters.
- Verify backend accounting and frontend rendering with tests, compile/build, publish index last and reload backend using existing supervisor. Inspect live chart without placing trades.

User steering added reviewed trend management: default best maker quote; persisted owned entry plans create separate maker-only SL/target after a full fill. Chart-open CSRF POST sync performs at most one idempotent child mutation per request. Confirmed opposing trends cancel the owned pending entry or request a maker-only exit. Fee-aware breakeven/trailing tightens stops only; unknown fees pause trailing. No promise of small loss/profit or immediate maker fill. No GET financial mutations, foreign-order management, unsafe unknown-outcome retries, or automatic live entry submission. Initial levels use verified closed bars, confirmed support/resistance, ATR and at least 1.5 reward/risk. Timeframe/source mismatch pauses management; submitted broker protections remain active.
