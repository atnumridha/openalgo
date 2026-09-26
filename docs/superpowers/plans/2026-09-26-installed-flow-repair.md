# Repair the installed trading flows

Approved scope: disable the three orphan cash flows, validate strategy links on
activation/restoration, align candle scheduling with settlement, make repeated
batch starts a safe no-op, use IST time gates, expose history readiness, and
verify the installed UI. Preserve graphs, history, sandbox mode and trading rules.

## Work and verification ledger

1. Lifecycle/readiness: validate ownership, strategy, connection, kind and mode;
   stop linked triggers before strategy deletion; expose actionable readiness.
2. Execution: settled scheduling, IST gates, matching-run no-op, history warm-up.
3. UI/diagnostics: list/editor reasons and destination links, diagnostic updates.
4. Rollout: backed-up idempotent orphan repair, tests, build, restart, UI review.

Pre-flight: lifecycle/readiness output is shared by activation, restoration,
diagnostics and UI. Runtime broker availability must not suppress exit branches.
The approved plan in the conversation is the specification.

Implementation uses branch codex/repair-installed-flows in the existing local
checkout so the explicitly requested local restart loads the reviewed files.
Tests use isolated databases. No change to strategy selection or order sizing.

## Completed verification — 26 September 2026

- Backend: 1,180 passed, 3 skipped across flow, strategy API/lifecycle/scheduler,
  starter workflow and Kotak MCX suites. Frontend: 201 passed. Production build
  passed (existing large-chunk warning remains); `git diff --check` passed.
- Independent review addressed transient lookup handling, per-workflow startup
  quarantine, concurrent link/deletion exclusion, RSI/nested warm-up, and editor
  readiness refresh after save. Failed teardown still prevents deletion.
- Verified no open strategy runs before restart. Backed up the installed DB to
  `db/backups/orphan-flow-repair-20260926T042508796287Z.db` (integrity checked,
  permissions 0600), with adjacent JSON repair audit.
- Applied lifecycle deactivation to flows 4, 5, 6 only. A second inspection
  planned no changes. All 12 graphs/connection selections match the backup;
  execution history remains 508 rows before and after repair.
- Restarted the same app at 127.0.0.1:5001. Nine persisted Flow jobs remain,
  all aligned to second 06; orphan registrations are absent. No open runs.
- Browser checked the complete list: three missing-strategy notices and nine
  Broker expired notices. RELIANCE editor shows Workflow inactive; NATGASMINI
  shows Workflow active, guarded SANDBOX run and reconnect link.
- Kotak remains marked expired. Real feed freshness/warm-up after reconnection
  requires operator authentication and cannot be claimed verified here. The
  existing stream collector and rollover regression suite passes unchanged.
- No live mode, trading thresholds, SENSEX rules or risk limits changed.
