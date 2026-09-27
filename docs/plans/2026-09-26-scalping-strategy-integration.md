# Three automated scalping strategies

**Goal:** Install the three tested rule sets as separate saved Strategy Module strategies with linked, initially inactive Flows and existing sandbox/live controls.

**Design:** Reuse the exact pure research signal functions. A server-owned profile identifies the rules, not the display name. An existing Strategy Module Run node requests evaluation every minute. The engine independently obtains completed candles, requires a current signal, records a durable per-candle claim, selects one ITM Nifty call/put and admits it through existing execution/risk gates. Persist index stop/target/deadline with the run before dispatch. A shared scheduler monitors these with the existing pure risk evaluator and managed stop lifecycle, including after restart. Premium protection is an additional operational constraint, so results must not be represented as identical to offline counterfactual returns.

**Constraints:** Stopped and sandbox by default; no real orders during verification. Fixed 2R index target, 15-minute cap, one ITM lot, maximum ₹20,000 premium debit (₹25,000 research capital less buffer). Existing account capital/loss/release controls remain authoritative and may be stricter; this feature does not reset or top up a risk ledger. Missing/stale candles or invalid contracts fail closed. Ordinary strategies preserve existing behavior. No indicator or quote secrets in reports.

**Implementation and checks:**
- [x] Add profile persistence, validation, idempotent owner/broker-bound installer and API. Test round trips, invalid profiles and duplicate installation.
- [x] Add bounded history adapter and execution preparation with exact signal reuse, freshness, current Flow ownership, deduplication and capped premium stop. Test forming/stale/gapped data, bearish contract selection, missing origin and rejected contracts.
- [x] Persist run context before order dispatch; add restart-safe index/time exits using managed stops. Test stop/target/time/missing-context failure paths and unchanged ordinary runs.
- [ ] Add a simple installer panel with the three named setups and explain existing individual sandbox/live controls. Test frontend, build and inspect actual UI.
- [ ] Run related regression tests, resource audit and independent code review; install via UI and confirm three inactive strategies/Flows and no new orders.

**Review focus:** Manual/webhook bypass; disabled automation and mode mismatch; stale signal after slow data fetch; crash between context persistence and dispatch; one failing quote blocking other runs' timed exits; state shared across account modes; source hashes invalidating previous research approvals.

**Completion evidence:** 2,689 related backend tests passed (3 skipped, 1 expected failure), 26 frontend tests passed, production build and independent review passed. Resource audit was static. IDs 13–15 installed using the application service, each stopped with an inactive linked Flow; nine existing controls preserved. Browser visual/interactive verification is pending an authenticated user session. See `docs/scalping-strategies.md`.
