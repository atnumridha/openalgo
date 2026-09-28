# Managed strategy execution corrections

The seven installed scalp profiles now share an option-premium execution plan. Signal indicators remain unchanged. This corrects conflicting execution rules; it does not establish a profitable trading edge.

## What changed

- New entries use `one-lot-option-structure-runner-v5`: one tick below the lowest low of three contiguous completed one-minute option candles ending at the signal. Missing, stale, forming, inconsistent or crossed structure cannot establish a stop. Genuine wider stops are rejected when unaffordable rather than tightened to fit a budget.
- The absolute stop survives entry-price changes, fills and restarts. Any higher earned profit floor is retained. A 3R premium planning objective replaces the conflicting fixed INR900/index-target admission calculation. It is not an executable target or a forecast; the runner has no hard profit ceiling.
- The existing gross-profit ratchet remains: protection starts at INR300, locks INR100, and subsequently permits at most INR300 planned giveback. Fees, gaps, slippage and execution availability can change actual results.
- Admission reserves loss at the same bounded price sent in the LIMIT order. The previous builder dropped that cap and would fail final live dispatch. Effective order type and limit are now stored in the durable intent.
- Admission and final submission check the executable bid against the unchanged stop. Signal age is checked after quote work. Working entry remainders expire after the 55-second signal window; the five-second observer requests cancellation and reconciled closure, including partial/late fills. This is not an atomic exchange guarantee against a price move after submission.
- Account ownership is established before validating old or malformed active-run history. Another owner's missing broker or prior-session run cannot poison this account's facts; its own invalid evidence still blocks entry.
- Automation Review shows the recorded contract, premium, absolute stop, gross planned loss, candles and 3R objective. Setup failures and governor rejections remain visible after later no-signal checks. A recorded plan is explicitly not an admission or fill.

## Protection retained

Actual funds, dated costs, whole lots, loss allowances, cash buffer, one-position limit, drawdown controls, three-consecutive-loss pause, exit ownership, broker-held stop verification, qualification and explicit live authorization still apply. The arbitrary INR20,000 premium ceiling is removed only for the new managed recipe; funding and all-in planned risk remain authoritative.

Saved allocations were INR10,000 before rollout. Under the existing `equity-1pct-v2` policy this means INR100 planned all-in loss per trade and INR300 daily, subject to tighter remaining allowance/drawdown conditions. INR300 per trade and INR2,000 daily are policy ceilings, not the effective limits at that allocation. This change does not silently increase allocation or disable those controls.

## Verification and scope

Tests exercise all seven profiles with affordable and unaffordable whole-lot fixtures using real cost arithmetic and the durable budget, malformed history, quote movement, signal expiry, owner isolation, fills, recovery, profit-floor preservation and legacy versions. Synthetic fixtures demonstrate admission correctness, not historical accuracy or expected returns.

Browser checks use an isolated fixture with a separate session cookie; no production order or kill switch was exercised. Independent review found two quote-timing issues that were corrected and cleared before publication.

Frozen historical/ML recipes retain v4. The new recipe is forward-only and requires new prospective Sandbox evidence before a matching live release. Existing reports must not be presented as v5 results. A valid signal may still be rejected for legitimate risk, data, liquidity or qualification reasons.


A broad verification attempt stalled in native SQLite connection-close mutexes. It was stopped; its isolated test databases were preserved before a clean rerun. Duplicate Flow records left by the interrupted fixture caused two intermediate retry failures. A fully fresh run also exposed that the API deletion tests had never created or isolated their Flow schema; that fixture now owns a throwaway Flow database. This involved only `*-test.db` files in the isolated checkout, never the production account.

Final verification: **2,472 backend tests passed**, one existing expected failure for an unrelated legacy LIMIT-price configuration; three SQLAlchemy identity-map warnings. **49 UI tests passed**; TypeScript/Vite production build and isolated browser inspection passed.
