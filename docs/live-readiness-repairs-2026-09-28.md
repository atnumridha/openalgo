# Live readiness repairs — 28 September 2026

The day review found no managed live fills. The two completed Bollinger trades
were Sandbox trades. A live permission badge alone did not mean a strategy could
submit: mode, session approval, research policy, market hours, data and risk gates
were separate requirements.

## Changes

- Explicit live-session approval is stored in `live_session_authorization`. A
  restart preserves its original expiry. A changed broker/account/login/pin,
  revocation or expired session denies new live entries. Previous audit events
  are not migrated into approvals. On first deployment, approve the session
  again through Strategies.
- Closed-trade portfolio reservations are reconciled from attributable entry
  and exit fills. Owner, mode, broker, run, leg, position reference and order
  identity must agree. Partial, late, unresolved, missing or oversized histories
  retain their reservation. Database persistence must succeed before memory
  risk is released.
- Automation review shows all known live setup blockers together. It retains
  the check/time-window status and open-run evidence alongside those blockers.
  It reads local evidence without renewing approval, creating risk accounts or
  requesting broker orders. Fresh cash, quotes, liquidity, stops and full
  research binding are still checked at entry.
- Nine option receivers use separate trend, later-bar retest and momentum
  profiles. Bullish signals buy calls; bearish signals buy puts. Their existing
  managed execution path enforces owner/pin/mode, closed-bar freshness, durable
  duplicate claims, option stops and portfolio admission.
- Structure stops support verified NFO, BFO and supported MCX quote units. The
  existing seven NIFTY profiles retain their execution and stop rules.
- MCX collectors subscribe to the verified ATM call/put pair before a signal
  and retain only bounded observed candle history. Pair changes and interrupted
  connections require fresh coverage. An exhausted connection is replaced with
  cleanup of its callbacks and worker; temporary reconnects retain their client.
  Missing historical premiums still block entry until enough real bars arrive.

## Using live mode

Open Strategies → Automation review and select the intended strategy. Complete
the blocked setup checks. Research qualification is optional only when that
choice has actually been saved in Research; the default remains required.
Saved approval is checked against the current broker session. Use the strategy's
Start live control to switch its linked Flow through the existing stop/flatness
checks. The final real-money start must be performed by the account owner.

“Monitoring enabled” means scheduled signal checks are enabled. “LIVE · new
entries blocked” identifies a live-configured strategy with unmet setup checks.
“Run active” identifies an open managed run; inspect order fills and protection
to distinguish an order request from an actual position. “LIVE · configured”
does not promise a trade or profit.

## Existing receiver installations

New installations get the new profiles. Existing known stock receiver graphs
need the offline `upgrade/upgrade_receiver_rules.py` migration. Dry-run is the
default. Stop the app and workers before `--apply --offline`; retain the private
backup and restart to discard old cached graphs. The upgrade preserves modes,
activation, broker pins and saved risk settings, and refuses edited graphs,
ambiguous links or open exposure. It does not enable LIVE.

## Validation boundaries

Regression fixtures test bullish and bearish direction, causality, retest timing,
duplicate prevention, affordability, contract units, authorization lifecycle and
reservation evidence. Browser testing uses an isolated API fixture and verifies
the checklist, technical direction and stop-confirmation cancellation. These
are software checks, not new evidence of strategy profitability or a completed
real broker trade.

Planned risk remains ₹300 gross per trade with the saved ₹2,000 daily loss
allowance and three-consecutive-loss pause. Existing profit protection starts
at ₹300 gross profit and ratchets with a maximum planned ₹300 giveback. Actual
fills, gaps, costs and slippage can differ from a stop threshold.
