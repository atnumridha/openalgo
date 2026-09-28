# Strategy readiness review — 28 September 2026

Reviewed each of the 16 installed strategies through the real Automation review
page at `http://127.0.0.1:5001/strategy/monitor`, and checked local scheduler,
execution, candle and policy records at approximately 17:29–17:36 IST.

## Checklist results

The checklist has eight setup checks, followed by checks that can only run at
the next signal. Passing setup does not prove a valid signal, executable quote,
affordable contract, broker fill or profit.

| ID | Strategy | Mode | Setup checks | Current qualification for an entry |
| --- | --- | --- | --- | --- |
| 19 | NIFTY Bollinger 20/2 Reversal (Research) | Live | 8/8 passed | Monitoring; outside index entry hours |
| 13 | NIFTY EMA 9/15 + Bank Nifty | Sandbox | 6/8 passed | Live mode and permission off; outside entry hours |
| 14 | NIFTY MACD + EMA 200 | Sandbox | 6/8 passed | Live mode and permission off; outside entry hours |
| 15 | NIFTY 5 EMA Reversal | Sandbox | 6/8 passed | Live mode and permission off; outside entry hours |
| 16 | NIFTY EMA 50/200 + Daily Regime | Sandbox | 6/8 passed | Live mode and permission off; outside entry hours |
| 17 | NIFTY Opening Box Breakout | Sandbox | 6/8 passed | Live mode and permission off; outside entry hours |
| 18 | NIFTY SMA 5/34 Zero-Cross (Research) | Sandbox | 6/8 passed | Live mode and permission off; outside entry hours |
| 20 | NIFTY 5/15-Minute Trend Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; new receiver evaluation awaits entry hours |
| 21 | NIFTY Breakout and Retest Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; new receiver evaluation awaits entry hours |
| 22 | NIFTY Long-Option Momentum Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; new receiver evaluation awaits entry hours |
| 23 | SENSEX 5/15-Minute Trend Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; new receiver evaluation awaits entry hours |
| 24 | SENSEX Breakout and Retest Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; new receiver evaluation awaits entry hours |
| 25 | GOLDM Momentum and Breakout Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; insufficient reliable candle coverage |
| 26 | CRUDEOILM Momentum and Breakout Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; five-minute history warming |
| 27 | SILVERM Momentum and Breakout Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; insufficient reliable candle coverage |
| 28 | NATGASMINI Momentum and Breakout Signal Receiver | Sandbox | 6/8 passed | Live mode and permission off; five-minute history warming |

All 16 passed session approval, pinned broker, signal monitoring, dated costs,
daily risk allowance and optional research checks. The 15 Sandbox strategies'
two live blockers are accurate configuration states, not scheduler faults.
This review did not enable real-money trading or change any risk control.

## Market data and runtime

- Both local services were ready; all 16 signal monitors were enabled, with no
  open managed run. The four MCX Flows completed 9–10 checks each over the most
  recent ten minutes, with zero failed executions.
- NIFTY's last in-session snapshots had the current completed bars and enough
  history for the original seven profiles. These are historical evidence after
  the entry window, not proof of a fresh current signal.
- CRUDEOILM and NATGASMINI had roughly 28 complete observed one-minute futures
  bars at the spot check. Their momentum rules need ten contiguous completed
  five-minute bars and two fresh fifteen-minute confirmation bars. Their ATM
  option pairs were ready at the latest sampled check, but strike changes can
  require fresh premium history.
- GOLDM and SILVERM futures ticks were recent, but usable coverage had reset to
  roughly 0.6 and 1.6 minutes respectively. Premium readiness also fluctuated
  between collecting and unavailable. Recent ticks alone do not establish
  complete, trustworthy OHLC history. Missing native trade time, volume
  evidence, gaps or interruptions must not be fabricated or bypassed. The
  per-packet cause was not established by this snapshot.

## Corrected display

The receiver evaluator uses `data_ready=false` for insufficient warm-up or
confirmation as well as unavailable data. The UI previously always called this
a missing latest candle, even when its history showed that candle. It now uses
the recorded evaluator reason and a general data-readiness notice, preserving
the entry block. This frontend-only correction does not restart collectors.

## Expiring requirements

- Current live-session approval expires at 03:00 IST on 29 September. It must
  be reviewed again for the next trading session; it is not renewed silently.
- Saved NFO, BFO and MCX cost schedules end on 10 October 2026. Rates and dates
  need a genuine review before extension.
- Research is optional account-wide, including future managed strategies.
  Broker/session approval, strategy opt-in, signals, funds, contracts, stops
  and portfolio limits remain mandatory.

Green is a time-specific observation. No monitoring process should hide a
failure, grant live approval, relax risk controls or start orders to keep it
green. Data warm-up, closed market windows and intentionally selected Sandbox
mode must be reported separately from operational failures.

## Sandbox follow-up, 17:45–17:55 IST

Forty MCX workflow executions completed in the ten-minute diagnostic window;
none failed. Crude Oil Mini and Natural Gas Mini progressed from 7 five-minute
candles at 17:45 to 8 at 17:50, with two fifteen-minute confirmation candles.
The evaluator requires ten contiguous five-minute candles. Gold Mini and Silver
Mini had three five-minute candles at 17:50 and no usable fifteen-minute
confirmation history. Their earlier coverage interruptions remain a limitation.

Two read-only WebSocket samples (35 and 50 seconds) observed 270 packets for the
Gold/Silver futures and current Gold option pair. All carried native trade time
and fresh volume fields; the second sample's maximum trade age was 20 seconds.
This does not establish the cause of earlier gaps. No feed-quality or risk
requirements were changed. The retained Sandbox run #2 for Bollinger recorded
realised P&L of ₹656.50; this is a simulation result, not proof of profitability.
At this inspection Bollinger's monitoring and live permission were disabled.

The UI previously replaced warm-up detail with a between-candle waiting message.
The review now displays the most recent recorded candle assessment from its
existing event log, separated by strategy, profile and execution mode, with
counts, timestamps and an explicit historical-data warning. Counts do not prove
contiguity or entry eligibility. The list says “No open trade” for an armed,
stopped run; start notifications identify Sandbox or Live monitoring, and live
permission notifications no longer claim the execution mode changed. Read-only
monitor requests time out after ten seconds so a hung request cannot leave
Refresh disabled indefinitely. These frontend changes need no collector restart.

Validation: 45 focused UI tests passed; production TypeScript/Vite build passed
with the existing bundle-size warning.

## Live MCX diagnosis, 18:06–18:27 IST

All four MCX strategies were saved in Live mode with live permission and armed
monitoring at 18:06:56. The refreshed dashboard showed ₹10,000 available. At
18:27 the scheduler was running, with four Live and twelve Sandbox monitors;
there were no managed Live runs or orders recorded.

The repeated “Signal expired; waiting for the next receiver candle” message is
the receiver's routine timing gate. The scheduler checks every minute, while
entry rules are evaluated during the first 55 seconds after each five-minute
close. It does not mean a qualifying entry was found and lost on every check.
The review UI now displays the next five-minute close instead, preserving
genuine expiry warnings during history fetching or order preparation. The
latest entry rejection is visible without expanding raw details.

At 18:15, CRUDEOILM produced a confirmed bearish/PE setup. Entry was rejected
before order submission because three completed one-minute option candles were
unavailable for its protective stop. The collector had repeatedly switched
between the 9,100 and 9,150 ATM pairs, unsubscribing the previous pair and
invalidating its coverage on every switch. Funds did not cause this rejection.

The collector fix retains the two most recently requested pairs per root, with
a twenty-symbol total bound across four roots and their futures. A third pair
evicts the oldest, invalidating its coverage and queued packets. The selected
entry contract and native timestamp, volume, continuity, expiry, quote, cash
and risk checks are unchanged. No candles are fabricated or recovered across
an actual subscription interruption.

At 18:25, CRUDEOILM, SILVERM and NATGASMINI had sufficient data to evaluate but
no qualifying setup; GOLDM reported unavailable five-minute market history.
Silver had therefore recovered from its earlier warm-up. These are recorded
observations, not a promise of an entry on the next candle.

Validation: the new retention regressions failed before the fix; 171 related
backend tests and all 2,831 frontend tests passed afterward. The frontend suite
requires `NODE_OPTIONS=--no-experimental-webstorage` with the installed Node 26
runtime so its native localStorage does not shadow JSDOM. Production build and
independent code review passed. The reviewer also exercised 2,000 rotations
with injected subscription failures and verified bounded subscription state.

Deployment: the frontend build can be served without restarting collectors.
The collector correction takes effect only after a backend restart; the
currently running collector has not been restarted by this review. A restart
will invalidate active coverage and require fresh native candle warm-up. The
saved readiness watch explicitly prohibits automatic collector restarts, so
that deployment step needs a separate user decision. Monitoring now checks
every five minutes and reports meaningful order/fill evidence or new blockers;
it never forces entries, changes risk settings or renews live permission.

## Candle assessment follow-up, 18:58–19:05 IST

The review panel skipped newer empty-history failures and retained older warm-up
counts. For GOLDM this left the 18:45 count of three five-minute candles visible
after newer checks reported unavailable history. It now recognizes the receiver's
five-minute, fifteen-minute and empty-completed-history failures as assessments.
An empty assessment explicitly reports that the current usable count is unknown;
it does not reuse earlier counts or invent zero candles. Routine between-candle
polls still preserve the last actual assessment, with its timestamp and age.
Past entry rejections are labelled as past attempts whose blocker may still apply.
Live panels no longer append the Sandbox-fill explanation.

At 19:00 CRUDEOILM had 22 completed five-minute and seven fifteen-minute candles.
Its strong, expanded candle did not close beyond the required six-bar range, so
there was no entry setup. At 19:05 it had 23 and seven candles respectively and
still no setup. Its 18:15 option-history rejection remains relevant historical
evidence; the collector retention fix still requires the pending backend restart.
GOLDM reported unavailable five-minute history at 19:00, then one five-minute
candle and unavailable fifteen-minute history at 19:05. Earlier repeated usable
coverage resets are not explained merely by an enabled monitor or fresh quotes.

A separate passive 180-second quote observation recorded 190 GOLDM, 192 SILVERM
and 188 CRUDEOILM future packets. Maximum native trade ages were 12, 25 and seven
seconds respectively. No missing native timestamps, stale volume flags, native
time reversals, over-60-second trade gaps, volume decreases or collector coverage
changes were observed in that interval. This did not reproduce or establish the
cause of the earlier interruptions. No data-quality checks were weakened, and
no collector restart or trading action was performed.

Validation: regressions reproduced the skipped-assessment cases before the fix;
all 2,835 frontend tests, the production build and independent focused review
passed. The change is frontend-only and does not load the pending collector fix.

## New streaming outage and reconnect fix, 19:06–19:22 IST

All four futures' stored stream arrivals stopped at approximately 19:06:40.
At 19:07 the market-data and order-update sockets reported ping/pong timeouts;
subsequent connection and REST requests reported DNS resolution errors. REST
quotes later recovered, but the market-data stream did not. The application and
research worker remained running. At 19:15 all four MCX receivers reported
unavailable five-minute market history. This is a new shared feed failure,
superseding CRUDEOILM's earlier healthy-data/no-setup status. No managed Live
runs or orders were recorded when checked at 19:15.

The market-data adapter scheduled one reconnect at 19:07:23. That asynchronous
attempt failed DNS before opening at 19:07:46. Its close callback returned early
because the reconnect-in-progress flag was still true, leaving no retry timer.
An isolated regression reproduced this failure. The fix deduplicates pending
timers while allowing a failed asynchronous handshake to schedule the next
bounded, backed-off attempt. Old-client callbacks cannot alter a replacement's
connection state; retiring the old client and consuming its retry timer are one
locked transition. Explicit stops during retirement or credential lookup still
prevent a replacement connection. SFeed's close already joins its thread, so
the legacy-only completion wait is now conditional.

Validation: four initial reconnect regressions failed before the correction;
the additional stop-during-recreation regression also reproduced before its fix.
All 124 related feed, collector and subscription tests passed, and independent
review found no remaining blockers. The running backend was not restarted.
Loading both the option-pair retention and reconnect fixes still needs the
previously requested restart decision; fresh candle warm-up is required after
the actual outage. No stale bars, fabricated candles or relaxed guards were used.
