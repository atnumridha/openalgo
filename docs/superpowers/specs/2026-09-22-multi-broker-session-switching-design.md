# Multi-Broker Connections with Per-Session Switching

**Date:** 2026-09-22  
**Status:** Approved design  
**Initial brokers:** Kotak Neo and Delta Exchange India

## Objective

Allow one OpenAlgo installation and one user account to keep multiple broker
connections authenticated at the same time. A browser-session dropdown selects
which broker backs interactive pages and manual actions. Durable automation and
external integrations remain pinned to an explicit broker connection so changing
the dropdown cannot reroute an order.

The initial rollout supports the user's existing Kotak Neo connection and a new
Delta Exchange India connection. The storage and routing model is broker-neutral
so future broker types can adopt it without another schema redesign, but the first
implementation does not need to enable multi-connection setup for every plugin.

## Design principles

1. **Broker identity is explicit.** Every broker-dependent operation resolves to
   exactly one broker connection before reading data or changing state.
2. **Interactive selection is session-local.** A dropdown change affects only the
   current Flask/browser session.
3. **Automation is immutable while active.** Strategies, schedules, workflows,
   webhooks, pending orders, and MCP clients retain the connection selected when
   configured or started.
4. **Isolation extends through infrastructure.** Authentication caches, symbol
   caches, WebSocket pools, order-update feeds, and analyzer state are keyed by
   connection, not merely username.
5. **Ambiguity fails closed.** Trading is refused when a broker connection cannot
   be resolved uniquely. No legacy fallback may silently select the first row.
6. **Secrets stay server-side.** Credentials and tokens remain encrypted at rest
   and never appear in frontend state, logs, errors, or MCP configuration.

## Chosen architecture

OpenAlgo will gain first-class broker connections rather than a global active
broker. The current browser session stores an active connection ID for interactive
requests. Background work and API clients carry their own pinned connection ID.

Two alternatives were rejected:

- A process-wide active broker switch would interrupt other sessions, running
  strategies, and shared market-data feeds.
- Two OpenAlgo deployments behind a combined frontend would duplicate settings
  and databases and would not provide a genuine single-instance model.

## Data model

### `broker_connections`

Add a connection table owned by the OpenAlgo user. Required fields:

- `id`: opaque primary key used for routing.
- `user_id`: owning OpenAlgo username or stable user identifier.
- `broker`: plugin identifier such as `kotak` or `deltaexchange`.
- `display_name`: operator-facing label, unique per user.
- `credentials_encrypted`: encrypted, versioned broker-specific credential
  payload. It may contain API key/secret material needed to authenticate but is
  never serialized to clients.
- `auth_encrypted` and `feed_token_encrypted`: current broker session material.
- `broker_user_id`: broker-side account identifier when available.
- `is_revoked`, `status`, `last_verified_at`, `created_at`, `updated_at`.

Enforce uniqueness for `(user_id, display_name)`. Permit more than one connection
for a broker in the schema even though the initial UI creates only one Kotak and
one Delta connection.

### API credentials

Extend OpenAlgo API keys with `broker_connection_id`. A key authenticates its
owner and resolves exactly one broker connection. Existing unified API consumers
continue to submit the same API key shape; broker selection comes from the key,
not an untrusted request parameter.

The initial user's existing API key becomes the Kotak-pinned key. Generate a
separate Delta-pinned API key for the Delta MCP connection. An API key without a
valid connection is rejected for broker-dependent endpoints.

### Durable trading records

Add `broker_connection_id` to every durable object that can later cause or manage
broker activity, including:

- strategies and strategy runs;
- Flow workflows and executions;
- scheduled Python/OpenScript jobs where they trade;
- webhook/signal configurations;
- pending and deferred orders;
- GTT/scalping/risk-management ownership records;
- order and execution audit records where broker attribution is not already
  immutable.

An active run cannot change connection. Reassignment requires the owner to stop
the run and prove that its broker-managed positions are flat or explicitly accept
the residual-position warning through the existing safety flow.

### Analyzer state

Move Analyzer/Live mode from a platform-wide value to a per-connection value.
Every order path resolves the connection and its mode once, under the same safety
decision that dispatches the order. A dropdown switch never modifies this value.

## Migration and compatibility

The migration is additive and runs against a database backup.

1. Create the new connection and relationship columns.
2. Convert the current non-revoked `auth` record into an initial connection.
3. Associate the current API key and existing broker-bound durable records with
   that connection.
4. Preserve the current Kotak token and feed token ciphertext; decrypt and
   re-encrypt only through the existing supported key lifecycle when necessary.
5. Retain compatibility functions with their existing signatures during the
   transition, but have them resolve an explicit connection from request/session
   context. Background callers must be migrated to pass a connection ID.
6. Remove any code path that obtains an arbitrary "first available" broker for a
   trading operation. A temporary compatibility lookup is allowed only for
   read-only startup tasks when exactly one valid connection exists.

Rollback restores the pre-migration database backup and the prior application
revision. The migration must be idempotent so an interrupted startup can resume.

## Broker context and request flow

Introduce a small broker-context service responsible for:

- validating that a connection belongs to the authenticated user;
- resolving browser-session, API-key, strategy-run, or scheduled-job context;
- returning the broker plugin, decrypted session token, feed token, and broker
  user ID to existing service adapters;
- refusing missing, revoked, unhealthy, or ambiguous connections;
- keeping decrypted secrets scoped to the operation and out of logs.

Interactive web requests resolve `session["active_broker_connection_id"]`.
Broker-independent pages do not require a connection. Broker-dependent pages
return a typed `connection_required` or `connection_unavailable` error that the
frontend can render without logging the user out of OpenAlgo.

The legacy `session["broker"]` value may be mirrored during migration for old
routes, but it is derived from the selected connection and is not authoritative.

## Authentication and credentials

The connection setup UI collects credentials for the selected plugin and writes
only encrypted server-side values. Kotak retains its TOTP/MPIN login flow and
daily session lifecycle. Delta uses its HMAC API key and secret against the India
production endpoint and does not participate in the 3 AM Indian-broker logout.

Logging into or refreshing one connection invalidates only that connection's
authentication cache, WebSocket adapter, and order-update adapter. Logging out
offers two explicit operations:

- disconnect the selected broker connection;
- sign out of OpenAlgo and disconnect all broker connections.

No credential value is returned after submission. Credential replacement uses a
write-only form. Broker responses are sanitized through the existing redaction
layer before logging or display.

## WebSocket, symbols, and caches

All pool and cache keys become connection-aware, for example
`(connection_id, broker, user_id)` rather than `(broker, user_id)` or a global
active broker.

Each authenticated connection may maintain its own market-data and order-update
feed. Updating one token tears down and recreates only that adapter. Symbol-master
caches are keyed at least by broker plugin; connection-specific symbol metadata
must include the connection ID if the broker can return account-dependent
instruments.

The frontend drops and re-subscribes its displayed feed when the dropdown changes.
Background strategy subscriptions remain attached to their pinned connection and
are not affected.

## User interface

Add a broker-connection dropdown to the authenticated application header. Each
entry shows display name, broker name, and a compact health state: connected,
expired, connecting, or error.

Changing the dropdown calls a session-scoped selection endpoint and invalidates
only broker-dependent frontend queries. Funds, holdings, positions, orders,
trades, charts, searches, tools, and currency formatting then reload for the new
connection.

Every manual order confirmation displays the broker connection and its
Analyzer/Live mode prominently. The confirmation payload contains the connection
ID selected when the preview was built; dispatch rejects the request if the
browser selection changed before confirmation rather than rerouting it.

Strategy, Flow, schedule, and webhook editors require a broker connection. The
detail view continues showing the pinned connection even if the header dropdown
changes.

## Codex and MCP

Expose two explicit stdio MCP connections from the same OpenAlgo installation:

- `openalgo-kotak`, authenticated with a Kotak-pinned OpenAlgo API key;
- `openalgo-delta`, authenticated with a Delta-pinned OpenAlgo API key.

The MCP client cannot change the key's broker connection. Browser dropdown state
is irrelevant to MCP. Existing tool names and schemas remain stable; the selected
server name provides the broker context. Tool annotations and the trust envelope
remain enabled, and order tools remain available subject to the target
connection's Analyzer/Live state and normal Codex approvals.

MCP launchers retrieve their OpenAlgo API keys from encrypted storage by a stable
connection identifier and never persist plaintext keys in Codex configuration.

## Error handling

Errors identify the connection by display name and broker type but never include
secrets or raw broker payloads. Required failure classes include:

- connection missing or not owned by the user;
- credentials incomplete or invalid;
- session expired or revoked;
- broker/IP-whitelist rejection;
- connection unhealthy or feed unavailable;
- requested operation unsupported by that broker;
- stale order preview after a session dropdown change;
- automation attempting to run without a pinned connection.

A failure in one connection does not change the other connection's status,
subscriptions, Analyzer mode, or running work.

## Security requirements

- Encrypt credential payloads and session tokens with the existing Fernet
  lifecycle and migration safeguards.
- Redact API keys, secrets, tokens, signatures, cookies, and raw credential
  payloads from all logs and audit responses.
- Authorize connection selection and management against the logged-in owner.
- Bind API keys to a connection server-side; do not trust a client-supplied broker
  name to override that binding.
- Include connection identity in order audits, approvals, duplicate detection,
  risk ownership, and rate-limit accounting.
- Maintain Delta's static-IP requirements and surface an actionable sanitized
  whitelist error.
- Rotate credentials that were shared through chat after integration.

## Verification plan

Use test-driven implementation and verify at four levels.

### Unit and migration tests

- connection ownership, encryption, status, and lookup;
- idempotent single-broker migration and rollback fixture;
- per-connection API-key verification and cache invalidation;
- per-connection Analyzer/Live mode;
- ambiguity and revoked-connection fail-closed behavior.

### Service and integration tests

- all order, account, quote, history, symbol, and option service paths receive an
  explicit connection context;
- WebSocket and order-update pools coexist and one-token refresh leaves the other
  pool untouched;
- strategies, Flow, schedules, webhooks, pending orders, and risk exits remain
  pinned through browser switching;
- stale manual-order previews are rejected;
- logout and expiry isolate their effects to one connection.

### Frontend tests

- dropdown selection is session-local and invalidates the correct queries;
- connection health and broker-specific currency/product UI update correctly;
- order confirmations show immutable broker and mode information;
- running automation views retain their pinned broker.

### End-to-end verification

- authenticate Kotak and Delta concurrently;
- read funds, positions, instruments, and quotes independently;
- maintain simultaneous feeds;
- discover all tools through `openalgo-kotak` and `openalgo-delta`;
- place Analyzer-only test orders on each connection and confirm they cannot cross;
- submit no live order during implementation verification.

## Delivery boundaries

The first delivery supports Kotak Neo and Delta Exchange India in one OpenAlgo
installation. It does not promise an immediate multi-connection UI for every
broker plugin, account aggregation across brokers, cross-broker smart order
routing, or automatic movement of a running strategy between connections.
