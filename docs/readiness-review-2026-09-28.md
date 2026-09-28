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
