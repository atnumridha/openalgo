# Scalping profit protection implementation plan

> For agentic workers: use superpowers:executing-plans for this bounded follow-on.

**Goal:** Keep the initial planned gross loss at or below ₹300, protect earned gains, and allow profits beyond ₹900 within the existing holding deadline.

**Architecture:** A versioned pure profit evaluator shared by managed option ticks, replay and ML labels. New entries use a new recipe; persisted prior recipes retain fixed exits. Fee assumptions and tick size are bound before dispatch and restored with the run.

**Stack:** Python risk core, Strategy Module, research worker, React UI.

**Spec:** Latest user request and the explicit rules below.

## Constraints

- At ₹300 gross peak, ratchet to estimated break-even including modeled fees and sell slippage.
- At ₹600 gross peak, ratchet to peak minus ₹300 gross, never below the estimated break-even stop.
- ₹900 is an objective, not a hard exit; keep trailing above it.
- Initial stop remains technical distance capped at ₹300, rounded toward entry. No stop widening.
- Preserve ₹2,000 shared daily net-loss allowance, three consecutive net losses stop, existing deadlines, capital, live approval and activation states.
- Historical trailing uses observable opens and closes, with adverse low checked before the closing update. Do not infer the high/low order. Report this candle approximation.
- No promise of profit or guaranteed stop fill; gaps and actual charges can exceed assumptions.

## Review focus

- Old recipes must reproduce fixed targets.
- A restart must retain the fee binding and highest price/ratcheted stop.
- A price gap through the stop executes at the available price.
- Fees exceeding an accrued gain must not manufacture a profitable fill.
- Trailed stops must not corrupt the original planned-risk audit.

## Work

- [x] Write failing pure tests for break-even, trailing beyond ₹900, reversal, gaps and old-recipe behavior; implement `services/risk/profit_exit.py`.
- [x] Bind new recipe in replay/labels/entry plans and verify matched exits with deterministic candles; preserve old recipes and original risk.
- [x] Persist cost/tick context in managed entries, leg state and recovery; test actual runtime evaluator after checkpoint reconstruction.
- [x] Update explanatory UI text; test affected UI, typecheck and build.
- [x] Compare frozen development signals with prior exits; retain every result and no protected final sessions.
- [x] Run regression suite, independent review, publish and verify local stack without activating strategies.

## Execution record

Pure tests failed before implementation and passed after it. Runtime/replay integration tests failed before wiring and passed afterward. Independent review found a broker/app stop recovery mismatch; its explicit regression failed, then passed after separating durable broker protection from the app ratchet. Rising protection is app-managed; broker modification on every tick is outside this bounded change and is not claimed. Final publication/UI evidence is in the release report.
