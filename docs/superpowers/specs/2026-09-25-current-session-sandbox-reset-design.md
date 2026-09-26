# Current-Session Sandbox Reset Design

## Purpose and scope

Let the signed-in operator repeat today's strategy tests without using OpenAlgo's
existing `/sandbox/reset`, which clears all sandbox history and configuration.
"Today" is the Strategy Module's current trading session, beginning at
`SESSION_EXPIRY_TIME` (03:00 IST by default), not calendar midnight. The reset
targets only this user's Strategy Module runs with `mode=sandbox` that started
in that session, their attributable sandbox orders and trades, and their
dependent run records. It never selects by date alone or touches a live run.

The user has also authorized one execution of this reset after implementation,
provided the preflight passes. Building the control must not itself reset data.

## Operator workflow

The Strategies page has a separate **Reset today's sandbox tests** action. A
read-only preview reports session bounds, run/order/trade counts, total verified
realised P&L to reverse, current simulated funds and projected funds. It also
lists any blockers. The confirmation names the operation and makes clear that
saved strategies, workflows, market history, configuration, older test sessions,
and live trading remain unchanged. The existing all-data reset remains separate.

The POST takes the preview's opaque version/nonce and requires normal session
authentication and CSRF protection. It re-evaluates all facts under the reset
lock; a stale preview fails instead of resetting a changed set. A successful
response returns counts, reversed P&L, resulting funds, and an audit ID. The UI
refreshes strategy history, funds, and P&L. Repeating the action after an empty
reset is a no-op, not a second funds credit or debit.

## Admission and attribution

The reset serializes against new sandbox strategy entries for the user. It is
refused while any affected run is open, while any sandbox order is pending, or
while any sandbox position/holding involved in the affected trades is non-flat.
It also refuses if a prior-session run spans the boundary, a Flow execution is
currently dispatching a linked order, or another reset is in progress. The
operator first stops/settles those activities; the reset never places or
cancels an order to achieve flatness.

Only strategy orders with verified sandbox order IDs are selected. Each selected
trade must be linked to one selected order, and each fill must agree with the
Strategy Module's recorded quantity, price, and realised P&L to the cent.
Unattributed or mixed manual/Flow trading in the same netted instrument blocks
the reset where it makes the starting position or P&L ambiguous. Missing or
inconsistent evidence fails closed. The preview never estimates a cash
adjustment from LTP, unrealised marks, or the strategy run summary alone.

## Funds and risk accounting

The fund adjustment reverses only the selected runs' **verified realised P&L**:
`new_available_balance = old_available_balance - selected_realised_pnl`.
The same signed reversal applies to total and today's realised P&L and to total
P&L, while preserving pre-session capital and unrelated sandbox activity.
This is correct only after all selected margins are released and positions are
flat; otherwise the reset is refused. A negative selected P&L credits its loss
back; a positive selected P&L removes the profit. The API shows both figures.

Sandbox session-risk summaries and reservations derived solely from selected
runs are reset consistently; no live risk state is modified. Existing duplicate
completed-candle claims and webhook idempotency remain, so resetting history
does not authorize replay of the same signal. The operator may start or receive
new sandbox signals after the reset, subject to current market and risk checks.

## Records, durability, and failure handling

Before mutation, create a recoverable snapshot of affected rows and both
databases, and a durable reset audit entry recording user, session, selected
IDs, counts, reversed P&L, pre/post fund values, and outcome. Do not include
credentials or webhook secrets in the audit or UI. The snapshot and audit are
outside the active run-history queries, so the operator sees a fresh test while
the previous result remains recoverable for incident review.

Deleting the active run rows also removes their run-scoped orders, checkpoints,
events, and shadow comparison rows. Linked sandbox orders/trades are removed;
unrelated and older records are preserved. Any run-reference table without a
foreign-key cascade is handled explicitly. The operation is idempotent by audit
ID and uses a short admission lock. Because the sandbox and strategy databases
may be separate, their changes are not claimed atomic without verification.
Use a durable operation state and compensating restore (or an equivalent
database-supported atomic mechanism); if either side fails, block further
entries and report recovery required rather than expose a partly reset balance.

No automatic strategy/workflow restart is part of reset. Their saved active
configuration remains, and the operator can run another test once the reset
returns success. WhatsApp, broker connections, collected market candles, and
live orders/positions are unchanged.

## Verification

Tests cover session boundary and user isolation; live-mode exclusion; open
runs, pending orders, and non-flat positions; fill/P&L mismatch; mixed manual
trading; repeat/no-op behavior; concurrent signal admission; stale preview;
cross-database failure and recovery; linked comparison/event cleanup; exact
fund reversal for both profit and loss; preservation of older history and
configuration; and CSRF/ownership checks. Frontend tests cover preview,
confirmation, blockers, and refreshed balances.

Before executing today's authorized reset, take a fresh backup, verify the
exact signed-in user's affected rows and zero open exposure, run the preview,
and record its projected balance. Execute once through the new guarded path,
then verify the post-reset UI, fund ledger, empty current-session run list,
intact older history, and ability to start a new sandbox test. If any preflight
fails, do not clear today's data and report the blocker.
