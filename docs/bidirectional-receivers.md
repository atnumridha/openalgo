# Closed-bar option receivers

The nine NIFTY, SENSEX and MCX receiver templates use three distinct rule families. The version is `receiver-closed-bars-v2`. Bullish signals buy one ATM CE lot; bearish signals buy one ATM PE lot. Flat or conflicting conditions produce no entry. The seven existing scalping profiles keep their existing signal rules.

| Receiver | Completed five-minute setup |
| --- | --- |
| Trend | EMA9 above EMA15 with both rising over three bars; the current candle touches the EMA band and closes bullish above EMA9. Bearish conditions are reflected exactly. At least 35 bars are needed. |
| Breakout and retest | A candle with body at least half its range closes beyond the preceding six-bar range. A separate candle one to three bars later must touch the broken level and reject in the breakout direction. A close through the level invalidates the setup. An earlier qualifying retest consumes it. |
| Momentum | A directional candle closes beyond the preceding six-bar range, with a body at least 70% of its range and a range at least 1.2 times the preceding six-bar median. |

Every family also requires the latest completed 15-minute candle to have a matching directional body and a close beyond the previous 15-minute close. The prior confirmation candle must be from the current session. The latest ten five-minute bars must be contiguous. Timestamps must be aligned, unique, ordered and timezone aware. Future and incomplete bars cannot contribute to a signal. A shared durable Flow candle claim prevents repeated polling from entering twice on the same signal. Signal review reports the setup and confirmation result separately for CE and PE; insufficient history leaves unevaluated checks unknown instead of reporting a false rule failure.

NIFTY has all three families; SENSEX has trend and retest; GOLDM, CRUDEOILM, SILVERM and NATGASMINI use momentum. Their schedules poll every minute but only consider a fresh five-minute signal within 55 seconds of its close. Polling also warms the exact broker-pinned MCX ATM CE/PE pair ahead of the signal. Missing premium observations are never filled with invented candles. A changed ATM pair needs its own observed warmup. The bounded collector retains at most 16 symbols per connection.

## Risk and exits

The existing managed order pipeline handles both directions. It validates the account pin, enabled mode, live permission, risk budget, whole-lot affordability and executable quote before an entry. The option's initial stop is one tick below the lowest low of its three contiguous completed one-minute premium candles ending at the signal. A trade whose genuine technical stop exceeds the ₹300 planned gross loss limit is refused; the stop is not moved closer to force admission. Fees, total daily risk and cash affordability are checked separately. The shared ₹2,000 daily limit, three-loss pause and other account checks remain applicable.

The plan uses the current shared 3R option-premium objective and managed profit protection, with no fixed take-profit order. The holding deadline is 15 minutes after the signal, including sufficient time before the configured session exit. BFO and MCX require explicit verified contract price multipliers; GOLDM's 100 quantity with multiplier 0.1 is ten rupees per price point. That multiplier, original technical stop and plan survive recovery. Actual fills, gaps and costs can exceed planned loss budgets.

These are deterministic rule implementations and risk-path tests, not evidence of profitable trading or a measured win rate. Prospectively collected sandbox results must establish how they perform with available broker data.

## Existing installations

Installing a new template creates the new rules, stopped and sandbox-selected. Reinstalling existing rows preserves their current configuration. Recreating a missing Flow for an older receiver keeps its legacy rules; it does not silently upgrade them.

The explicit upgrade tool is read-only by default:

```sh
python upgrade/upgrade_receiver_rules.py /absolute/path/to/openalgo.db
```

It recognizes only the nine stock receiver names with their exact old long-option legs and matching stock graphs. Leg IDs, cosmetic labels and node positions are preserved. Comparison covers every saved leg field, including additional controls absent from the old template. Custom trailing stops, strategy profit locks, trail-to-entry, other rule edits, mismatched broker pins or modes, ambiguous links and open runs are refused. The plan changes only the receiver profile and its Flow rules; saved mode, activation, permissions, account risk limits, history and unrelated strategies are preserved. No broker API is called.

After reviewing the proposed changes, stop the application and all workers before applying:

```sh
python upgrade/upgrade_receiver_rules.py /absolute/path/to/openalgo.db --apply --offline
```

Application creates an owner-only SQLite backup, rechecks the entire proposal under a write transaction and applies it once. Any skipped receiver prevents all writes. Repeat runs are idempotent. Restart the application afterwards to replace cached Flow graphs. This code change itself does not apply the upgrade or activate trading.

## Verification and resources

Fixtures cover all three families in both directions, flat/conflicting data, subsequent-bar retests, future-data prefix equivalence, repeated Flow claims, warmup between signal windows, account-pin refusal, affordability, and filled-order recovery on BFO/MCX. Admission tests also exercise the original seven profiles with the unchanged shared risk contract.

Rules and evaluation frames are local and bounded; history uses the existing bounded cache. The new upgrade utility closes every SQLite connection and backup file descriptor. The receiver adds no retained registry or worker. MCX subscriptions are owned and bounded by the existing collector. This is a static resource review, not a prolonged leak measurement.
