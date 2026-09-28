# Fixed risk and signal-aware startup

The pasted start results exposed a routing error: the nine earlier option templates are stored as batch strategies, but each has a conditional Flow. Start all and individual Start treated them as standalone batches and requested immediate entries. Linked strategies now enable signal monitoring. The normal Flow evaluates the setup before requesting a run. A missing lookup, invalid link or recognizably malformed numeric reference cannot fall back to a manual entry. Standalone batches preserve their existing behavior. Non-scalp linked strategies cannot use a live UI start to bypass their Flow.

## Requested risk settings

- Sandbox allocation: ₹50,000, applied through the reviewed allocation operation after deployment and flatness checks. Live allocation remains unchanged.
- Current policy `fixed-300-v3`: ₹300 planned **gross price-stop loss** per trade. Estimated charges and slippage are reserved separately.
- Fixed ₹2,000 daily allowance includes completed net losses and reserved open risk. Profits do not replenish it. Neither allowance scales with capital or halves at 5% drawdown.
- Preserve one simultaneous position, the stop after three consecutive completed net losses, the 8% portfolio drawdown pause, the cash buffer and reconciliation controls.
- Preserve the original technical stop; skip an unaffordable whole lot. Do not manufacture a tighter stop to obtain a trade.
- Profit protection remains ₹100 at ₹300 gross peak, ₹300 at ₹600, ₹600 at ₹900, and at most ₹300 planned giveback thereafter, without a hard profit ceiling. Actual fills can gap through stops.

Policy transition requires no pending/open risk exposure and complete close evidence. It changes no capital, peak gap, prior trade results or latched stops, and records an audit review. Allocation review is mode-specific and retains historical losses. ₹50,000 is accepted for Sandbox only. Existing equity-v2 and earlier research policies retain their historical arithmetic. New generic research uses a separate fixed-risk v6 recipe; existing v3/v4/v5 profit protection remains readable, and the forward option-candle structure remains distinct from generic research geometry.

## Remaining entry restrictions

At the observed master-contract sizes, the earlier 20-point templates imply ₹1,300 before charges for NIFTY (65 units) and ₹400 for SENSEX (20 units), both above ₹300. They can monitor signals but cannot enter with that saved stop. The seven scalp profiles instead derive the option stop from completed option candles and check affordability at each signal.

MCX contract price-to-value conversion is not implemented end-to-end by the shared capital budget. Those strategies remain blocked from entry and now say so. Do not set a guessed multiplier merely to clear the error. MCX histories were also still accumulating during the UI inspection.

Frozen ML deployment and qualification currently require ₹25,000. The new ₹50,000 Sandbox allocation applies to deterministic strategies; it does not qualify the frozen ML models or approve live deployment. The allocation UI states this restriction.

## Why the 12:15 chart did not trigger

The supplied chart is Nifty Midcap Select at 15 minutes; no installed strategy targets that index. The EMA9/15 strategy uses NIFTY 5-minute candles plus Bank Nifty confirmation. The monitor's recorded evaluation of the 12:15 candle showed no qualifying direction: NIFTY normalized slopes were approximately -0.0048 and -0.0357 ATR/bar, and Bank Nifty slopes -0.0139 and -0.0341, short of the -0.10 threshold for puts. The bearish touch/body pattern also failed. The scheduler was running, with zero open managed runs and all 16 workflows in Sandbox. The 12:16 observation was already beyond the fresh-entry age limit; no valid signal was reported in that recorded evaluation. This is observed runtime evidence, not a claim that a trade should have been profitable.

## Verification

Regression checks cover signal-aware single/bulk starts, unavailable/malformed/foreign linkage, live-start refusal, fixed limits at multiple capital levels, independent Sandbox allocation, policy migration, retained loss stops, cost reservations, frozen recipe compatibility, research/ML replay and the profit ratchet. The UI control sends a Sandbox-only ₹50,000 allocation review and shows monitoring separately from a trade.

Resource audit: existing ORM sessions and account/automation leases are reused; no new engine, thread, cache or network client was introduced. Reviewed transaction/context-manager exception cleanup and existing request session teardown statically. No resource leak was observed or claimed to be measured.

Final automated verification: 6,722 backend tests passed, with 31 skipped and one expected failure. The full suite retains the previously reproduced baseline's 10 failures and 11 teardown errors (rate-limiter legacy mocks, optional Telegram test dependencies and sandbox-restricted process inspection). All 2,800 frontend tests passed; the final three-page regression rerun passed 61 tests. TypeScript and the production frontend build passed, with the existing bundle-size warning. `git diff --check` passed. A separate review found no unresolved issue in the fixed-risk or signal-start changes.

## Applied UI verification

After the first implementation commit was merged to main, the local stack was restarted with zero open managed runs, zero pending/open risk reservations and zero live-enabled strategies. The Research UI saved the requested Sandbox allocation through its reviewed operation and displayed ₹50,000 capital, ₹300 price-stop limit, ₹2,000 daily allowance and zero reserved risk. Live capital remained ₹10,000. The monitor displayed `fixed-300-v3`, the running scheduler, 16 Sandbox monitors and zero live strategies. Start all (sandbox) returned Monitoring for all 16; the four MCX rows explicitly reported their unsupported contract-value conversion. No immediate manual run was created by this action.

The subsequent NIFTY 50 5-minute screenshot matched the installed EMA strategy. At the recorded evaluation of the candle closing 12:25, NIFTY EMA9 was 22,834.523310, below EMA15 at 22,835.648358. Three-bar slopes were +0.086298 and +0.030179 ATR/bar, both below the +0.10 call threshold. The call's EMA touch/body/close condition passed, but the qualifying candle-pattern test and Bank Nifty confirmation failed. Bank slopes were +0.030618 and -0.001404 ATR/bar. No put pattern qualified either. The recorded 12:28 check was already 186 seconds after candle close; this does not prove the first evaluation was late. Signal rules rejected entry before option sizing and capital checks.

UI testing also caught obsolete equity-risk wording in the shortlist and an incorrect including-costs label beside ₹300. These were updated to the fixed gross price-stop rule; charges remain separately reserved and count toward daily losses.
