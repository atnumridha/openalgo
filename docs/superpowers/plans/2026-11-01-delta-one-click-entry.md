# Delta One-Click Entry Plan

User explicitly requests combining review and submission into one entry click. Place Long/Short performs preflight and sends an entry, or shows error and stops. Entries remain maker-only; best bid for buys, best ask for sells. These quotes do not guarantee profit or fills. Existing close/edit/adoption confirmations stay unchanged.

- [x] Use one shared guarded submission path with explicit payload/snapshot; no stale React review-state dependency.
- [x] Synchronous click lock before awaited fresh broker state. Validate current account/symbol/connected/fresh metadata, flat/noorders/no pending, latest quote, quantity/leverage/funds, closed-candle trend/protection. Recompute quantity for selected percentage and autoquote using fresh version; reject invalid latest protection.
- [x] Persist one minimal UUID intent before POST; one action maximum, retain unknown outcome for reconciliation, no auto retry after timeout. Surface errors and stop.
- [x] Tests cover oneclick freshbestbid/ask and attachedSL/target, preflight errors/noPOST, doubleclick guard, rejected/unknown outcomes and existing nonentry review flows. Typecheck/build and independent review.
- [x] Publish frontend indexlast; verify HTTP/browser controls without clicking live financial buttons. Record evidence.
