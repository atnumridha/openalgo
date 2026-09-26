# Automated Strategy Foundation Design

## Goal

Add the shared safety, authorization, notification, and starter-configuration layer needed to run algorithmic strategies through OpenAlgo with AI assistance, while reusing OpenAlgo's existing Strategy Module, Flow engine, broker connections, Agent tools, MCP data access, and WhatsApp service.

This is the first shippable sub-project of the larger automated-trading system. Later projects can add more deterministic Flow graphs and AI ranking without creating a second order engine or bypassing the controls defined here.

## Existing capabilities to reuse

- Strategy Module already provides batch and signal strategies, per-leg stop/target/trailing rules, overall MTM stop/target, daily loss limits, schedulers, recovery, order tracking, sandbox/live modes, per-strategy live opt-in, and a kill switch.
- Flow already provides scheduled and event-driven triggers, market history, 116 technical indicators, conditions, broker/account reads, order nodes, and WhatsApp nodes.
- Agent already provides broker-aware market/account tools, guarded order tools, and validated Flow generation.
- OpenAlgo MCP already provides broker-pinned read-only market/account access for external AI scanning.
- WhatsApp already publishes generic order lifecycle alerts and has encrypted paired-device storage.

The implementation must compose these capabilities. It must not create a parallel order engine, indicator library, broker adapter, scheduler, or notification transport.

## Architecture

### 1. Trading-session live authorization

`live_enabled` remains the durable per-strategy opt-in. A second, short-lived authorization is required before any automated live entry may be opened.

The authorization is held by a small process-local registry keyed by username and the current OpenAlgo trading-session date. The browser session records the same authorization marker. Authorization is cleared or considered invalid after logout, application restart, broker reconnection, username change, or the next trading-session boundary.

Manual live starts, scheduled live starts, webhook-driven signal entries, and recovered entry attempts all use the same authorization service. Live exits are never blocked by an expired authorization: flattening an existing live position must remain possible.

The UI exposes an explicit "Authorize live automation for this session" confirmation. It shows whether the authorization is active and when it expires. Revoking it blocks new live entries but leaves existing protective and exit behavior operational.

### 2. Strategy portfolio governor

A strategy-module-scoped governor runs immediately before an entry order is dispatched. It never blocks exits.

Initial policy defaults:

- Maximum two simultaneous cash positions.
- Maximum one simultaneous NIFTY options position.
- Maximum combined configured open risk of 4% of available cash.
- Maximum configured cash risk per trade of 1.5% of available cash.
- Maximum configured long-option risk per minimum lot of 3% of available cash.
- At least 20% of available cash remains as a buffer.
- New live entries require configured protective risk and a target whose reward-to-risk is at least 1.5.
- A 4% daily strategy-module loss or three consecutive stopped runs blocks new entries for the session.
- Two consecutive stopped runs impose a 30-minute entry cooldown.
- New intraday entries are admitted only from 09:20 through 15:00 IST; option entries stop at 14:45 IST; strategy exits remain allowed.
- Stale or unavailable funds/position facts fail closed for new live entries and do not affect sandbox entries.

The governor returns a structured decision with a stable reason code, a human-readable message, and the calculated limits. Rejections are written to the existing strategy event audit and broadcast to the UI.

The first version governs Strategy Module automation only. Generic manual orders, Flow orders, baskets, and split orders remain governed by their existing controls; calling this a platform-wide governor would be inaccurate until those independent dispatch paths are integrated in a later project.

### 3. WhatsApp strategy lifecycle alerts

Generic accepted-order alerts already exist. Add non-blocking strategy-specific messages for material events:

- live authorization granted, revoked, or expired;
- live entry admitted or rejected by the governor;
- run started and stopped;
- entry accepted or rejected;
- stop, target, daily-loss lock, cooldown, stale-feed stop, recovery failure, and kill switch;
- broker or order acknowledgement failures requiring operator attention.

Routine ticks, P&L deltas, and "nothing found" updates are not sent. Notification failure never blocks an order, stop, or exit. Unpaired WhatsApp is treated as unavailable and does not create trading failures.

### 4. Sandbox-only starter strategy pack

Add an idempotent installer for a small set of ordinary Strategy Module configurations:

1. NIFTY 5/15-minute trend signal receiver.
2. NIFTY breakout-and-retest signal receiver.
3. NIFTY long-option momentum signal receiver.
4. NIFTY 50 cash momentum signal receiver.
5. Cash support mean-reversion signal receiver.
6. Opening-range breakout signal receiver.

The cash templates are signal receivers for exact configured symbols. The NIFTY option templates are batch strategies with dynamically resolved ATM legs, because an exact option symbol would expire and become unsafe as a reusable starter. Flow or the AI scanner is responsible for deterministic market analysis and invokes the existing strategy lifecycle or signal surface appropriate to the template. Every installed strategy is stopped, sandbox-only, live-disabled, unscheduled, and carries conservative stop/target/daily-loss defaults. Installation never starts a run, activates live trading, or activates a Flow.

Duplicate installation reports existing names and creates only missing strategies. Webhook tokens are returned only for newly created strategies and are shown once using the existing token contract.

### 5. Strategy UI controls

The existing Strategies page gains:

- an automation safety card showing Sandbox/Live authorization state and expiry;
- authorize and revoke controls with explicit confirmation;
- the configured portfolio-governor summary;
- an "Install recommended starter pack" action with a review dialog;
- installation results linking to each created or existing strategy;
- a clear path to the Agent for AI-assisted Flow generation and to Flow for review/activation.

The UI must not suggest that installing the pack starts trading. Live authorization and each strategy's existing `live_enabled` switch are separate gates.

## Data flow

1. Flow or the Agent/MCP scanner reads broker-pinned market data and evaluates an opportunity.
2. The deterministic producer sends a signal to an installed Strategy Module strategy.
3. Strategy Module validates the signal and resolves the instrument.
4. For a sandbox run, the existing sandbox path proceeds unchanged.
5. For a live entry, the session authorization and portfolio governor must both admit it.
6. Strategy Module writes the order intent before dispatch, uses the existing broker path, and manages fills, stops, targets, and exits.
7. Existing audit and Socket.IO events update the UI; material lifecycle events also enqueue WhatsApp messages.
8. AI may rank, explain, or generate inactive Flow graphs, but it cannot bypass validation, authorization, risk decisions, or per-strategy live opt-in.

## Security and failure behavior

- No broker credentials, API keys, webhook tokens, TOTP seeds, or WhatsApp session material are added to source control or logs.
- Live authorization is denied by default and after any ambiguous reset condition.
- All new entry gates fail closed; all exit paths fail open with respect to authorization/governor policy.
- Starter-pack installation is reversible by deleting stopped strategies through the existing UI.
- No strategy, workflow, scheduler, or live mode is activated as part of installation or migration.
- All external notifications are best-effort and asynchronous.

## Out of scope for this sub-project

- A market-wide autonomous AI daemon.
- Automatic activation of generated Flow workflows.
- Platform-wide governance of manual, basket, split, scalping, or third-party API orders.
- Naked option selling.
- Automatic liquidation of positions not owned by Strategy Module.
- Changing broker credentials or the currently connected broker.

## Acceptance criteria

- A live batch start and a live signal entry are rejected without current-session authorization even when `live_enabled` is true.
- Revoking or expiring authorization blocks new live entries but never blocks stop, target, kill-switch, or manual exit orders.
- Sandbox strategies remain usable without live authorization or broker-live risk facts.
- Governor decisions are deterministic, audited, and visible in the API/UI.
- Material strategy events generate non-blocking WhatsApp lifecycle alerts without duplicating generic order alerts.
- Starter-pack installation is idempotent, creates only sandbox-only stopped strategies, and never starts or activates anything.
- The Strategies page accurately presents all gates and does not imply that installation equals activation.
- Backend and frontend tests cover the reset boundary, entry-versus-exit behavior, risk rejection cases, duplicate installation, notification failures, and UI confirmations.
