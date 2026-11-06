# Source strategy selection feedback fix

Authorized continuation: selecting the seven chart templates must reveal useful controls immediately. Retain the existing theme/full chart size, no orders, no invented proprietary entry rules, exact contract/context boundaries.

Root cause: A-ID selection turns research mode off and mounts a closed dock tool. Its source descriptions/notes have no chart reference callback. Template-key changes discard another template draft.

Implementation: add a scoped auto-open token to the existing dock without remounting drafts; structured per-template/per-chart storage with legacy migration; immediate context/explanation plus editable proposed option legs and intrinsic/expiry-P&L SVG preview; explicit matching-future entry/200-point stop references and clearly labeled underlying strike guides, with cleanup. Keep numeric net-P&L axes outside price chart. Source rules remain incomplete and explicitly labeled.

Parallel ownership: existing strategy work thread owns lowercase configuration model/math/tests; parent owns component/editor/preview, chart and dock integration/tests. One final independent review and targeted tests/type/build/served-asset checks. Do not bypass existing browser URL-policy restriction. No new permission round, commits or service/order changes beyond local bundle activation.

Regression checks: every source opens automatically, changing template while closed reopens, closing/reopening preserves edits, same-source selection does not clear drafts, scope isolation, known payoff geometry, invalid/missing premium truth, future line edits/direction and removal on selection/symbol/unmount, no incompatible levels, and existing research choices.


Completed: auto-open and per-template persistence, structured editor/visual math, scoped references and cleanup, saved-chart overlay, targeted negative/failing-before-fix regressions, one independent review,882-test full affected regression suite, types/lint/build and served-entry/asset identity checks. See `docs/validation/2026-10-31-source-strategy-feedback.md` for evidence and remaining source/browser limits.
