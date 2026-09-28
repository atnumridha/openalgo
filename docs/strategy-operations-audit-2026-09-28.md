# Strategy operations audit — 28 September 2026

Snapshot: 14:45 IST. This is an operational audit of the retained execution,
strategy-event, checkpoint and sandbox records, not an assessment of strategy
profitability. All times below are IST. Strategy database timestamps were
converted from UTC; sandbox trade timestamps and application logs already use IST.

## Actual trading and the reset

The earlier NIFTY Bollinger 20/2 sandbox round trip entered at 12:30:20 and exited
at 12:37:23 with **₹269.75 realized P&L**. The sandbox session reset at 14:33:12
removed those fills from the active tables and returned the funds to the reset
baseline. The `sandbox_session_reset` audit event preserves the removed orders,
trades and realized result. A zero current realized figure after the reset is
therefore not the result for the entire morning.

After the reset:

- The 14:35:21 Bollinger run had an unfilled entry cancelled at 14:36:04, with
  stop reason `scheduler` recorded. No fill occurred for that order.
- The 14:40:21 Bollinger run bought 65 NIFTY29SEP2622750CE at ₹109.70.
  Its 14:45:03 checkpoint marked ₹112.35 and **₹172.25 unrealized P&L**.
  This is a point-in-time mark, not a closed-trade result.

The sample is too small to support conclusions about profitability. Current
sandbox funds/positions can also lag strategy checkpoints, so an unchanged
entry-price mark must not be interpreted as a measured zero result.

## Why many strategies did not enter

| Evidence | Affected strategies | Interpretation |
| --- | --- | --- |
| 22 generic per-trade-risk refusals, 11:31:13–12:25:25 | NIFTY 5 EMA: 3; NIFTY receivers 20, 21, 22: 4 each; SENSEX receiver 23: 4; receiver 24: 3 | Valid risk refusals. A qualifying signal is not permission to exceed the configured limit. |
| Three explicit refusals at 12:30:13–14: ₹1,300 planned stop versus ₹300 per-trade allowance | NIFTY receivers 20–22 | Valid risk refusals; modeled charges/slippage raised estimated loss to approximately ₹1,331. |
| Two explicit refusals at 13:30:13: ₹400 planned stop versus ₹300 allowance | SENSEX receivers 23–24 | Valid risk refusals; estimated loss including modeled costs was ₹443.30. |
| Portfolio position-limit refusals at 12:30:20 and 13:05:18 | NIFTY SMA 5/34 | Two refused signals. Subsequent “signal expired” evaluations are repeat observations, not additional missed signals. |
| Four contract-metadata refusals at 11:53:52–53 | GOLDM, CRUDEOILM, SILVERM, NATGASMINI | Missing execution valuation metadata. |
| Six explicit unsupported MCX conversion refusals, 13:20:13–14:15:06 | CRUDEOILM: 5; SILVERM: 1 | The MCX execution/risk path was deliberately blocked because contract-value conversion was unsupported. |
| Five cost-schedule exchange mismatches, 11:34:01–11:45:24 | SENSEX receiver 23: 3; receiver 24: 2 | Configuration/data compatibility problem, separate from ordinary signal filtering. |
| Two quote failures at 12:30:24 | SENSEX receivers 23–24 | Data retrieval failure; their 14:40 evaluations later fetched data successfully. |

The first three rows total **27 risk-size refusals**. Many other evaluations
completed normally and reported no fresh qualifying signal. “Completed” means
the workflow evaluated successfully; it does not mean an order was placed.

MCX retained workflow outcomes from 11:35 through 14:40:

| Underlying | Collecting history | Data unavailable | Completed evaluation | Failed |
| --- | ---: | ---: | ---: | ---: |
| GOLDM | 36 | 0 | 0 | 0 |
| CRUDEOILM | 22 | 0 | 9 | 5 |
| SILVERM | 26 | 0 | 9 | 1 |
| NATGASMINI | 35 | 1 | 0 | 0 |

These are repeated polling outcomes, not independent trade opportunities.
MCX execution support and sufficient current candle history are separate
requirements; correcting contract conversion does not itself supply history.

## Confirmed operational defects

- **Execution persistence:** six SQLite lock failures prevented execution-record
  creation between 10:00:21 and 10:14:17: workflows 14 and 17 twice each, 15 and
  16 once each. Seven history-pruning failures and two strategy-event write
  failures occurred in the same window. The records do not establish the
  profitability of any missed evaluation.
- **Flow bookkeeping:** workflow 19 failed to finalize its execution record at
  12:30:20 because its execution object had detached from its database session.
  The sandbox trade did occur. The later reconciliation repaired bookkeeping;
  it must not be interpreted as reversing that trade.
- **Unfilled-entry protection:** 44 tick-processing exceptions occurred for the
  14:35 Bollinger run between 14:35:24 and 14:36:03. The accepted order had
  `status=open`, a requested quantity of 65, and no filled entry price. Profit
  protection was evaluated prematurely and rejected the unfilled position.
  The bounded adapter correction ignores those ticks without advancing a
  profit peak. Positive-price partial fills and completed fills retain normal
  protection; filled positions missing valuation still fail explicitly.

Sources: read-only SQLAlchemy queries against `db/openalgo.db` and
`db/sandbox.db`; `log/errors.jsonl`; `log/local-stack/app.log`. Logs and current
tables can change or be reset, so this document records the stated snapshot.

## Reading the live stop

The live legs table labels the value **Stop price (₹)** and shows the equivalent
signed gross P&L beneath it. For a long position, the displayed amount is:

`(stop price − filled entry price) × managed quantity × price multiplier`

A short position reverses the price difference. The multiplier must be known
for MCX; an unknown value produces “Gross at stop unavailable.”

For the reported example, `(119.85 − 109.70) × 65 = ₹659.75` gross at the stop.
₹119.85 is the option price, not a ₹119.85 profit cap. A recorded ₹958.75 peak
less ₹300 giveback produces ₹658.75 before price-tick rounding; rounding the
stop upward to ₹119.85 produces the displayed ₹659.75. Charges, slippage and
the eventual fill can change the realized outcome. This display calculation
does not change any trading rule or send an order.

## Follow-up: live permission and historical sandbox P&L

The later operational check found Bollinger run #2 stopped at **14:52:25** with
**₹656.50 realized sandbox P&L**. Live permission was enabled at **14:53:20**.
The workflow's run node was configured for live mode, but its 14:55, 14:56 and
14:57 evaluations reported no fresh qualifying signal. No live order had been
placed at that check.

Enabling live permission does not turn an earlier sandbox result into live
P&L. The detail view now identifies the actual run mode and number, and shows
monitoring separately from an active trade. The strategy list shows the same
provenance alongside total P&L. Labels use the run's recorded mode rather than
the current permission switch; unknown historical modes remain unavailable.
An old cached checkpoint is excluded when its run number differs from the
current run.

## Entry cutoff and historical rejection

The pasted `minimum_reward_risk=1.126016260162601626016260163` belongs to
09:35 and 09:40 Bollinger entry refusals. The 1.5R minimum was not met; this
is historical evidence rather than the latest live status. New refusals state
the actual ratio and required minimum instead of combining cash, stop and
reward requirements in one message.

The configured NFO session closes at 15:40 and its option-entry margin is
55 minutes, producing a **14:45 IST entry cutoff**. Live permission was
enabled eight minutes after that cutoff. The shared session check now runs
before scalping signal preparation, so monitoring reports the closed window.
Neither the cutoff nor the risk threshold was relaxed. Exits remain available.

## MCX history availability

A read-only check at 15:08:23 found NATGASMINI had five usable 5-minute candles
and one usable 15-minute candle; the trend check needs at least two of each.
GOLDM had no completed usable candles after its coverage reset at 15:05.
Older aggregates existed but preceded the current continuous coverage interval.
Repeated GOLDM feed gaps reset its warmup. Available evidence does not establish
whether those gaps came from trading inactivity or unsuitable quote packets.

The collector rejects stale or incomplete source quotes. Correcting contract
units does not make incomplete history valid. A service restart also restarts
collector warmup, so post-deployment monitoring must distinguish collecting
history from a completed evaluation without a signal.

## Verification

The combined backend regression run passed 961 tests. Focused frontend tests
cover actual run-mode labels, stale checkpoint exclusion and gross value at the
stop; TypeScript and the production build were checked. Resource review was
static: the new migration uses the shared engine factory, transaction/context
managers and unconditional engine disposal. No new unbounded cache or worker
registry was introduced. Generic strategy accounting uses the existing cached
symbol lookup; missing metadata preserves legacy external-fill bookkeeping,
while managed MCX entry admission still requires verified units.

The same 961 backend tests passed on merged `main`, with one SQLAlchemy warning
in an existing recovery fixture. The main checkout shares the SDK package name;
preloading the installed `openalgo` SDK before `pytest.main` avoids pytest
mistaking the repository root for that SDK. All 105 selected frontend tests and
the production TypeScript/Vite build passed.

## Deployment verification at 15:25 IST

There were no open managed runs before the service restart. All 34 startup
migrations completed successfully. The MCX migration populated 5,422 contract
rows with the expected factors: GOLDM 0.1, CRUDEOILM 1, SILVERM 1 and
NATGASMINI 1. A local metadata backup was retained before the change.

The browser confirmed **Last sandbox run P&L — Run #2 — +₹656.50**, separately
from **Live monitoring is on; no active run**, and the **Stop price (₹)** column.
At 15:25:21 the automation review showed 16 enabled monitors, zero open managed
runs and zero needing attention. CRUDEOILM's latest result had changed from the
old conversion rejection to **Feed restarted; collecting fresh contract
history**. Earlier rejection records remain preserved as historical evidence.

Bollinger remained the only live-enabled strategy; all other 15 strategies,
including the four MCX receivers, remained sandbox-only. The monitoring screen
showed NIFTY strategies outside their configured entry hours. No mode switch or
manual order was submitted during verification. Live MCX fills and profitability
are not established by these software tests or the successful migration.
