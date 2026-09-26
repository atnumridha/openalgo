# Allocated capital profile

The Strategy Research page at `/strategy/research` includes an explicit **Save costs and enable capital profile** action. This enables the profile for that signed-in user's managed Strategy Module entries across strategies and broker connections. Research experiments alone do not enable it. Stop and reconcile existing Strategy Module runs before first activation; the API refuses activation while a run is recorded as current. Accounts that have not enabled the profile retain their existing Strategy Module policies. Direct broker orders, arbitrary Python strategies and ordinary Flow order nodes do not pass through this profile; use the managed Strategy Module start/signal path.

The profile allocates ₹10,000. Its session boundary is the existing Strategy Module boundary (03:00 Asia/Kolkata), shared across exchanges. The first filled position lifecycle gets a maximum ₹1,000 planned loss, including modeled charges and slippage. All later lifecycles share another ₹1,000. Profits cannot refill either allowance; unused first-trade allowance cannot transfer. Daily planned loss is limited to ₹2,000. Partial fills belong to the same position reference. A proven unsent or zero-fill rejected/cancelled entry does not consume a trade; unknown broker outcomes retain their reservation.

A 20% decline from peak allocated net equity persists a pause across restarts and subsequent sessions. Open positions are marked after estimated liquidation costs. New entries must also fit the remaining drawdown headroom. A profitable open position can raise equity but cannot finance a new position with unrealized proceeds. Working partial BUY orders retain their full cash commitment. The profile keeps a 20% cash buffer and permits at most one index and one MCX position, two derivatives total. Quotes, lot sizes, broker cash, managed position quantities and order evidence must agree.

This version accepts single-leg intraday long options. NFO/BFO quantities use exchange units. MCX entry requires explicit verified monetary multiplier metadata and currently supports only multiplier 1; the present resolver does not provide that verification, so unsupported commodity entries are refused. Research import can model explicitly supplied multipliers, but that does not qualify a live contract.

These are planned-risk controls, not a guarantee of maximum realized loss. Gaps, rejected exits, missing liquidity, outages or slippage can exceed a stop. The engine continues to use its existing managed exits and protective-order machinery. Bucket loss and drawdown breaches trigger those exits, including after fills. Admissions fail closed when allocation evidence cannot be read. Failed accounting must not prevent a protective exit.

## Cost evidence and reconciliation

Provide the dated cost schedule described in [Strategy Research](trading-research.md). Missing costs are unknown, never silently zero. Saving a schedule records an operator assumption; the system does not authenticate tax rates or broker contract notes. Each admitted trade keeps its schedule snapshot. Later fee edits do not rewrite historical trades.

The separate risk ledger retains evidence even when strategy run history is removed. Cash, peak equity and loss pools remain separate for Sandbox and live modes; broker connections cannot create extra allowances. A Sandbox balance reset does not reset the allocated capital ledger. No deposit/withdrawal adjustment or contract-note reconciliation import is supplied in this version.

Concurrent price and fill updates use conditional snapshots and bounded refresh/retry. Persistent contention pauses the account. Monitoring reconciles active positions only; late fill callbacks can still update an exact closed/cancelled position reference. Unknown working orders must be resolved through the existing broker/order reconciliation path.

An operator can resume a drawdown pause only after every managed exposure is flat/resolved, with a review reason and explicit reconciliation acknowledgement. This writes an audit record and reanchors the peak to current allocated equity. It does not refill today's loss pools or replenish capital.

## Qualification and operation

The profile's live admission gate requires a currently qualified and explicitly approved campaign for the exact strategy and Flow. [Strategy Research](trading-research.md#forward-qualification) documents automatic prospective evidence collection, conservative execution/cost valuation, qualification thresholds and reconciliation. Approvals bind the reviewed evidence, rules, source, account and broker authentication; they expire after seven days and can be revoked. Protective exits remain available when qualification fails. Sandbox costs are estimates reviewed by the operator, not broker-charged fees. Implementing this workflow does not demonstrate profitability; real historical and forward observations are still needed for each deployment.

Apply the ordinary application migrations, then restart the application to load the new APIs and UI. The migration is `upgrade/migrate_trading_research.py` and is included as required in `upgrade/migrate_all.py`. Run the separate research worker using the commands in [Strategy Research](trading-research.md). This development task did not restart the application, enable an account profile or send broker orders.

| Authenticated endpoint | Purpose |
|---|---|
| `GET /strategy/api/risk` | Enabled status, allocation policy, costs and both mode budgets |
| `PUT /strategy/api/risk/costs` | Validate/save costs and explicitly enable the account profile |
| `POST /strategy/api/risk/resume` | Review a flat account with mode, reason and reconciliation acknowledgement |
