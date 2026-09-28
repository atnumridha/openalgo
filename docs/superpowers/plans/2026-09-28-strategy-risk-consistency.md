# Managed scalping risk consistency

**Goal:** Correct all open execution-rule findings from the strategy review without forcing trades or weakening protection.

**Architecture:** Version the seven managed scalp profiles' execution recipe independently of frozen research and ML recipes. Derive a long option's absolute stop from the three contiguous completed one-minute option candles ending at the signal, one tick below their lowest low. Persist its evidence. Treat 3R as a planning objective, not a hard take-profit; keep the existing INR300-start profit ratchet. Use the same absolute stop in admission, fills, broker protection and recovery.

**Tech stack:** Existing Python/SQLAlchemy risk runtime, React monitor, pytest/Vitest.

## Constraints and rulings

- User authorized fixing the reviewed issues with proper risk management. No unlimited-risk mode, forced order, live opt-in, or budget reset. Existing allocations and percentage/absolute loss controls remain unchanged. "Forget budget" is not treated as permission to disable protective loss limits.
- Remove the arbitrary INR20,000 premium ceiling only for the new structure recipe; actual funds, cash buffer, whole lot and all-in loss checks remain authoritative.
- Prior entry/exit versions and historical reports remain reproducible. The new recipe is initially forward-execution only; generic historical/ML configuration must not silently claim to reproduce its option-structure rule.
- Genuine wider structure is rejected; never shrink a stop to fit the budget. Missing/stale option candles, spread/depth and contract evidence fail closed.
- Retain three-loss pause, one-position control, daily and drawdown limits, exit ownership, qualification and explicit live authorization. Preserve all seven Sandbox activations and nine uninstalled templates.
- No real broker orders or production kill-switch clicks during verification.

## Review focus

1. Stale, missing, duplicate, forming, future and previous-session candles cannot establish a stop.
2. Admission uses the adverse entry cap and absolute stop; a changed quote or fill must not move the original stop down.
3. Identical geometry must receive the same reward-risk verdict for all seven profiles; a runner objective is never a guaranteed return or a hard target.
4. Other owners' old/malformed runs cannot contaminate account facts; own invalid evidence still blocks entry.
5. Restart preserves the original absolute stop and any higher earned profit floor; old recipes retain old behavior.

## Tasks

- [x] Add failing option-structure and reward-objective tests, owner-scope regressions, and absolute-stop fill/recovery tests.
- [x] Implement pure validated structure geometry and its managed recipe; integrate causal broker history and immutable stop evidence.
- [x] Correct admission, account scoping, state/risk adapter/recovery propagation; retain all independent loss/funding gates.
- [x] Expose stop/objective/entry-rejection evidence on the monitor; distinguish signal waiting from rejected setup.
- [x] Test all seven profiles through affordable/over-budget scenarios and old-recipe regressions; independent final review, relevant UI checks/build.
- [ ] Publish to main, verify services/current scheduled checks and unchanged account/activation settings; report evidence and limitations.

## Execution ledger

- Baseline 908a8b98f. Reused clean isolated checkout, branch codex/strategy-risk-consistency.
- Existing Flow SQLite lock correction is already published; it is included in regression checks, not redesigned.

- Ruling: use the authenticated account's executable quote at admission and retain that exact cap in LIMIT orders. Inspection found the previous order builder dropped it and final dispatch rejected MARKET. Persist the effective type/price in the order intent.
- Ruling: final quote must still have bid above the absolute stop. Recheck signal freshness after quote I/O in both modes. The five-second deadline observer expires outstanding entry remainders older than 55 seconds through the existing cancel/close/reconcile path; a submitted order can still race a fill and is never presumed flat.
- Regression evidence: geometry/owner tests first 19 failures then 22 pass; adapter/recovery 130 pass; reserved cap/monitor nine failing tests then 159 pass; final quote/expiry eight failures then 147 focused pass; post-quote age regression observed failing before remediation.
- Genuine narrow fixture passes real dated-cost/durable-budget admission for all seven profiles at INR10,000; genuine wide fixture is rejected unchanged for all seven. Prices are synthetic test cases, not profitability evidence.
- Browser QA used an isolated database and distinct cookie on port 5077. Verified option contract, absolute stop, gross loss, 3R planning label, expanded candles and rejection evidence. No production order or kill-switch action.
- Independent final review found crossed-stop and post-quote Sandbox freshness gaps; both corrected. Reviewer confirmed no remaining P1/P2 findings.
- Legacy research/ML retains v4; v5 is forward-only. Source binding invalidates prior live releases on code changes. Portfolio allocations and strategy activation settings are intentionally unchanged.

- Final backend regression: 2,472 passed, one pre-existing expected failure, three SQLAlchemy identity-map warnings (59.84s). UI: 49 tests passed, production TypeScript/Vite build passed. Biome has no errors (one existing informational template-literal suggestion).
