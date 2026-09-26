# SENSEX and MCX Intraday Strategy Expansion Design

## Goal

Extend the existing OpenAlgo Strategy Module and Flow foundation with sandbox-first,
intraday-only SENSEX and MCX strategy packs. The expansion must reuse the existing
instrument master, option resolver, broker adapters, exchange calendar, portfolio
governor, lifecycle audit, live-session authorization, and WhatsApp transport. It
must not create a parallel order engine or let AI bypass deterministic controls.

The initial MCX universe is GOLDM, CRUDEOILM, SILVERM, and NATGASMINI. The BFO
universe is SENSEX. All five underlyings remain independently rejectable at runtime
when a valid, liquid derivative contract cannot be resolved.

## Trading boundaries

- All new strategies are intraday. No position intentionally remains open after
  its exchange session.
- The initial execution product is long options only. Futures, naked short options,
  averaging down, martingale sizing, and overnight carry are excluded.
- Every new strategy is installed and activated in sandbox mode for the first
  one-to-two trading sessions.
- Live mode remains unavailable until both the existing per-strategy live opt-in
  and the short-lived trading-session authorization are present.
- AI may rank candidates and explain signals, but entries, sizing, exits, and risk
  rejection remain deterministic.

## Strategy pack

### SENSEX

1. SENSEX 5/15-minute trend confirmation.
2. SENSEX breakout and retest.

Both strategies resolve the nearest eligible BFO expiry and an ATM or configured
near-ATM CE/PE leg from the current SENSEX level. Entries require a completed
five-minute trigger aligned with the completed fifteen-minute trend.

### MCX

3. GOLDM momentum and breakout.
4. CRUDEOILM momentum and breakout.
5. SILVERM momentum and breakout.
6. NATGASMINI momentum and breakout.

Each MCX strategy resolves its own current expiry and option leg from the instrument
master. A missing option contract, stale quote, invalid lot size, or insufficient
liquidity produces a no-trade decision rather than a guessed symbol or fallback
order.

SILVERM and NATGASMINI use stricter volatility and spread admission thresholds than
GOLDM and CRUDEOILM. Their sandbox strategies may emit a rejected-signal audit and
WhatsApp explanation, but must not relax those limits to force a trade.

## Contract and market resolution

- SENSEX maps to `BSE_INDEX` market data and `BFO` derivatives.
- GOLDM, CRUDEOILM, SILVERM, and NATGASMINI map to `MCX` for both market data and
  derivatives.
- Expiry, option symbol, lot size, tick size, and tradability are resolved through
  the existing OpenAlgo instrument-master and broker data services.
- The system never stores a reusable expiring contract symbol in a starter template.
- The existing exchange calendar determines whether a session is open and supplies
  its closing boundary. New entries stop before the exchange-specific close and all
  positions receive a deterministic intraday exit before that close.
- Completed candles are mandatory. In-progress candles cannot authorize an entry.

## Signal admission and liquidity

Every candidate must pass all applicable checks:

- completed five-minute trigger and compatible completed fifteen-minute regime;
- current non-stale bid, ask, and last price;
- positive bid and ask with an acceptable percentage and tick spread;
- authoritative lot size and estimated debit;
- sufficient option volume/open interest when the broker provides them;
- no entry after the exchange-specific cutoff;
- no entry inside an unresolved range, after an extended move, or when the
  minimum-lot risk exceeds the configured limit;
- protective stop and target with reward-to-risk of at least 1.5.

Unavailable fields fail closed where they are required for safe execution. Sandbox
runs retain the rejection reason so the thresholds can be reviewed without placing
an order.

## Portfolio governor expansion

Replace the NIFTY-specific option counter with derivative exposure buckets while
preserving backward-compatible API data during migration.

Initial defaults:

- maximum one open NIFTY option position;
- maximum one open SENSEX option position;
- maximum one open MCX option position across the four commodity underlyings;
- maximum two derivative positions in total;
- maximum configured combined open risk of 4% of available cash;
- maximum configured long-option risk per minimum lot of 3% of available cash;
- at least 20% of available cash remains after the estimated debit;
- SILVERM and NATGASMINI may use a lower per-trade admission cap because of their
  higher short-horizon volatility;
- cooldown, consecutive-loss lock, daily-loss lock, and kill-switch behavior remain
  shared across the portfolio.

The governor runs before every entry, including later entries on an already-open
signal run. It never blocks an exit. Sandbox decisions are recorded but do not need
live broker funds to simulate safely; live decisions fail closed on missing account
or exposure facts.

## Workflow and runtime behavior

- Each strategy has an idempotently installed Flow workflow that evaluates its
  market only during that exchange's trading session.
- Workflows run on completed-candle boundaries, not on arbitrary polling moments.
- Workflows call the existing strategy lifecycle/signal surface and never dispatch
  directly around the Strategy Module's authorization and governor.
- Installation creates only missing definitions and workflows. It does not modify
  or delete the existing six starter strategies.
- After verification, the six new workflows are activated in sandbox mode. They
  remain safe to stop individually or through the existing kill switch.
- A strategy that cannot resolve its current contract remains active but idle and
  reports the actionable configuration/data reason.

## WhatsApp and UI behavior

The Strategies and Flow pages show the new SENSEX and commodity entries, exchange,
mode, status, last evaluation, current resolved contract when available, and last
rejection reason.

WhatsApp sends non-blocking messages for:

- daily strategy-session start and end summaries;
- valid sandbox entry and exit simulations;
- stops, targets, daily-loss locks, cooldowns, and kill-switch events;
- stale data, missing contract, invalid lot size, excessive spread/risk, or broker
  acknowledgement failure when operator attention is useful;
- live authorization changes.

It does not send routine five-minute "no signal" messages. Notification delivery
failure never changes an order, stop, exit, or risk decision.

## Failure and safety behavior

- Contract ambiguity, stale/incomplete quotes, missing lot sizes, closed markets,
  unavailable broker data, or unsupported options fail closed for entries.
- Exit and protective behavior stays available after live authorization expires.
- No broker credential, API secret, TOTP seed, webhook token, or WhatsApp session
  material is exposed in source, logs, UI diagnostics, or notification text.
- Existing strategies and user-created workflows are preserved.
- Sandbox activation cannot silently enable live trading.

## Acceptance criteria

- The starter-pack installer idempotently creates six new definitions and six
  exchange-aware sandbox workflows: two SENSEX and one each for GOLDM, CRUDEOILM,
  SILVERM, and NATGASMINI.
- The resolver obtains valid BFO/MCX contracts, expiries, lot sizes, and tick sizes
  from authoritative current data and fails closed when it cannot.
- The portfolio governor enforces per-bucket and combined derivative exposure for
  both new and already-open runs without blocking exits.
- Exchange-aware entry cutoffs and forced intraday exits are derived from the
  calendar/session service and are covered by tests.
- SILVERM and NATGASMINI use stricter admission controls and cannot force a trade
  when spread, liquidity, or minimum-lot risk is unacceptable.
- All six new strategies and workflows are visible in the UI and can be stopped
  independently.
- Material lifecycle and daily summary WhatsApp messages are deduplicated,
  non-blocking, and tested for unavailable-delivery behavior.
- The complete backend and frontend test suites pass, the application starts, and
  authenticated UI verification confirms the new items are active in sandbox mode
  with no live authorization implicitly granted.

## Deferred scope

- Futures execution and short-option strategies.
- Overnight commodity positions.
- Portfolio optimization marketed as quantum computation. Any future optimizer must
  first prove deterministic, reproducible improvement in offline evaluation and
  cannot bypass the controls in this design.
- Automatic promotion from sandbox to live.
