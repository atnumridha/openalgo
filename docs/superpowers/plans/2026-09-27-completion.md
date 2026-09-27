# Complete capital, ML deployment, and data research

Approved scope: user said “add them all” after the pending-work list. Continue the existing research branch and preserve the related uncommitted changes.

## Global constraints

- New strategies stay uninstalled/disabled; no broker orders, activation, or live fee changes.
- New research uses ₹25,000, ₹1,000 first-trade loss allowance, ₹1,000 shared later-trade allowance, ₹2,000 daily allowance, 20% drawdown pause and 20% cash buffer. Keep legacy stored runs reproducible.
- Loss allowances limit planned risk; gaps and costs can exceed them. Report realized breaches honestly.
- Preserve sealed final sessions during development. Freeze selection before a one-shot final evaluation. Never tune using final outcomes.
- Use current Kotak costs retrospectively only with the user's approved research-assumption label.
- No fabricated market/revenue data or forward sessions. Report data restrictions and qualification failures.
- Implement original mathematics, not copied restricted upstream code.
- Publish verified related changes to main and verify the running app, subject to platform approval controls and safe restart conditions.

## Task 1: Consistent capital and full replay

Add validated research capital to configuration, hashes, sizing, ML labels and opportunity affordability, portfolio metrics and analytics. Default new UI experiments to ₹25,000 while stored configurations without capital retain ₹10,000. Reuse the two-bucket risk policy. Expose the selected capital clearly in the UI and results. Cover fee-inclusive sizing, bucket limits, drawdown and backward compatibility with meaningful tests. Files: research replay/ml/jobs/analytics, Research UI/types/API and focused tests. Do not change live BudgetPolicy defaults or database risk settings. Add a reproducible full-portfolio runner for the two Conlan rule signals (5/10/15 minutes) and ML using the same admission/exit engine; clearly distinguish rule adaptation from original one-lot opportunity comparisons.

## Task 2: Frozen ML inference and qualification integration

Implement bounded validated JSON forest inference (no pickle), exact feature parity with research, artifact hashing, immutable model selection and final evaluation without refitting on final sessions. Integrate a disabled installable strategy/Flow adapter using server-observed completed bars and contracts, stale/gap/missing-data rejection, account/ownership binding and existing risk/qualification checks. Model changes invalidate evidence. Permit forward enrollment only after the same frozen model passes historical gates; keep explicit live release approval. Test train/serve parity, malformed trees, future/missing bars, stale artifacts, frozen final and ownership. Do not install/activate anything or submit an order. If prerequisite data or evidence fails, show the exact reason.

## Task 3: Real alternative data and stock universe

Obtain permitted free real multi-stock price history and publication-dated company revenue history, preferring Indian official data if available. Preserve source URLs, hashes, retrieval times, publication semantics and market labels. If necessary use an explicitly labelled separate US stock example with official SEC filing data; it cannot establish NIFTY option profitability. Implement reusable bounded fetch/import/normalization, chronological alternatives/model evaluation and preference portfolio controls. Never infer publication time from period end; exclude incompatible fiscal units/periods and avoid revisions leaking backwards. Test point-in-time handling. Run real-data study and retain reproducible report and ledgers locally, without publishing raw vendor data.

## Task 4: Verification, qualification readiness and publication

Run the new ₹25k full replay and fixed-model chronological study, then one-shot sealed evaluation only for an eligible frozen selected model. Prepare qualification readiness in the UI; actual future sandbox trading requires market sessions and user activation. Inspect all changed UI flows, run focused and broad checks, production build and an independent review. Record outcomes and remaining external prerequisites. Commit the related branch work including built assets; merge/push main through normal permissions. Check active positions/automation before restarting the locally owned app; verify the actual deployed backend/frontend/worker. Keep live settings and new-strategy activation unchanged.

## Predeclared historical selection

Before inspecting the new real-data outcomes, the final-screen selection is restricted to dataset 3 (the most recent development window, ending 2026-04-23). Test 5/10/15-minute ML variants with fixed settings. Eligibility requires at least 20 trades in each base/stress evaluation, positive net results in each, no incomplete outcomes, and no ambiguous exits. Rank eligible variants by stressed net profit, then base profit factor, then shorter holding time. Freeze the exact selected model for one final test through the owner/session consumption ledger. If none qualifies, preserve the untouched final dataset. Do not select an older quarter's model because its different test period looks better. This three-way selection is exploratory and cannot replace prospective forward qualification.

All 45 primary variants (six Conlan rule adaptations and three ML variants on each of datasets 3–7) retain separate scenario ledgers; returns across different windows are not summed into a purported live portfolio. The separate US equity/revenue demonstration cannot qualify a NIFTY model.

## Execution record

- Plan extends prior completed research work; this request authorizes the previously deferred adapter/data/publication work.
- Existing branch is a non-main checkout with related changes; preserve them and stage a baseline snapshot before task commits.
