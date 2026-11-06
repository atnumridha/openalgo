# Delta Market Exits Implementation Plan

User explicitly approved market exits on2026-11-01; supersedes prior all-maker exits policy. Entries remain maker-only. Close/X opens user review; confirmed submission uses exact-position reduce-only market. Triggered SL uses reduce-only stop-market, mark trigger. TP remains maker. No real trade is placed as a test.

- [x] Backend: test close/stop market payloads, retain maker-entry and target guards, preserve idempotency/position ownership. Permit safe stop-market price edits. Migrate owned maker stop only after replacement market stop ACK, preserving protection during unknown outcomes.
- [x] Fee contract: expose verified taker metadata, generic estimated exit fee/basis; estimate position net using taker including GST, retain genuine maker estimate for target and compatibility. Missing taker means unknown net.
- [x] UI: review marketclose without limitquote gate; display marketclose/SL and maker entry/TP clearly. Preserve review and send safeguards. Genericfee drives positionnet and trailing.
- [x] Chart/display: draggable stop-market trigger only, market close X wording, per-order fee estimate SL=taker TP=maker; fresh public mark revalues both estimates without changing paid costs or financial snapshots.
- [x] Verify focused backend/frontend suites, typecheck/build, independent review. Inspect live state read-only before deployment; no test financial action. Publish frontend indexlast, clean backend restart only after checking active controllers/plans and open protection. Verify HTTPartifact, live readonlystate and browser.
