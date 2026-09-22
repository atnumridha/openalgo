# Multi-Broker Session Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Kotak Neo and Delta Exchange India authenticated in one OpenAlgo installation, switch the interactive broker per browser session, and pin every automation and Codex MCP connection to one broker.

**Architecture:** Add encrypted first-class broker connections and resolve them through a single immutable `BrokerContext`. Browser requests derive context from the Flask session, API/MCP requests derive it from a connection-bound OpenAlgo API key, and durable automation stores the connection ID. Caches, feeds, Analyzer mode, order previews, and audit records are connection-scoped so one broker cannot affect the other.

**Tech Stack:** Python 3.12+/Flask/SQLAlchemy/SQLite, React 19/TypeScript/Zustand/TanStack Query, FastMCP stdio, pytest, Vitest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-22-multi-broker-session-switching-design.md`

## Global Constraints

- Initial multi-connection support is limited to `kotak` and `deltaexchange`.
- Preserve the existing Kotak auth row, API key, and active Flask sessions during migration.
- The browser selection is stored only in its Flask session; it is never process-global.
- Strategies, schedules, Flow workflows, webhooks, pending orders, GTT, and MCP are pinned to `broker_connection_id`.
- Analyzer/Live mode is stored per broker connection and defaults to the migrated installation's current mode.
- Any missing, revoked, foreign, or ambiguous broker context fails closed before broker I/O.
- Secrets remain Fernet-encrypted at rest and are never returned, logged, committed, or written into Codex configuration.
- Keep production compatible with Gunicorn `eventlet -w 1`; do not introduce asyncio into Flask paths or cross real/green thread primitives.
- Do not submit a live broker order during implementation or verification.
- Preserve unrelated working-tree changes, including the existing Codex MCP launcher work.

## Review Focus

- Two browser sessions choose different brokers: each session's funds, orders, mode, and socket subscriptions must remain isolated; Task 8 pins this with concurrent-client tests.
- A broker is switched after an order preview is rendered: dispatch must reject the stale preview instead of rerouting it; Task 5 tests the selection nonce.
- Kotak refreshes or expires while Delta is streaming: only the Kotak auth/feed/order-update pools are invalidated; Task 6 tests pool identity and teardown.
- A partially migrated legacy database starts twice: migration must be idempotent, retain the Kotak ciphertext/API key, and never choose an arbitrary row; Task 1 tests interruption and rerun fixtures.
- Kotak crosses its 3 AM expiry while Delta trades 24/7: session validation must mark only Kotak expired and leave Delta usable; Task 3 tests broker-specific expiry policy.

---

## File Structure

- `database/broker_connection_db.py`: broker-connection persistence, encryption boundary, and connection-scoped API-key lookup.
- `services/broker_context.py`: immutable routing context and request/API/automation resolvers.
- `upgrade/migrate_multi_broker.py`: idempotent schema/data migration and status command.
- `blueprints/broker_connections.py`: connection CRUD, authentication, selection, health, and disconnect endpoints.
- `utils/request_broker.py`: Flask request helper that resolves the active connection without leaking secrets.
- `frontend/src/api/broker-connections.ts`: typed connection API client.
- `frontend/src/stores/brokerConnectionStore.ts`: session selection and health state.
- `frontend/src/components/layout/BrokerConnectionSelect.tsx`: header dropdown.
- `frontend/src/pages/BrokerConnections.tsx`: connection setup/reconnect screen for Kotak and Delta.
- `mcp/codex_launcher.py`: start an MCP process pinned to one connection without persisting its API key.

Existing auth, settings, order services, automation stores, WebSocket proxy, frontend layout, and MCP integrity files are modified only where listed below.

---

### Task 1: Add the broker-connection schema and idempotent migration

**Files:**
- Create: `database/broker_connection_db.py`
- Create: `upgrade/migrate_multi_broker.py`
- Modify: `database/auth_db.py`
- Modify: `upgrade/migrate_all.py`
- Test: `test/test_migrate_multi_broker.py`
- Test: `test/test_migrate_all.py`

**Interfaces:**
- Produces: `BrokerConnection`, `BrokerConnectionSetting`, and connection-bound `ApiKeys.broker_connection_id`.
- Produces: `migrate_multi_broker.apply(engine) -> bool` and `status(engine) -> bool`.
- Consumes: `database.auth_db.encrypt_token`, `decrypt_token`, the shared engine, and the legacy `Auth`, `ApiKeys`, and `Settings` rows.

- [ ] **Step 1: Write failing migration tests**

```python
def test_legacy_kotak_row_becomes_one_connection_without_reencrypting_ciphertext(legacy_engine):
    before = legacy_engine.execute(text("select auth, feed_token from auth where name='atanumridha'")).one()
    assert migration.apply(legacy_engine)
    row = legacy_engine.execute(text("select user_id, broker, auth_encrypted, feed_token_encrypted from broker_connections")).one()
    assert tuple(row) == ("atanumridha", "kotak", before.auth, before.feed_token)

def test_rerun_after_columns_exist_is_idempotent(partially_migrated_engine):
    assert migration.apply(partially_migrated_engine)
    assert migration.apply(partially_migrated_engine)
    assert scalar(partially_migrated_engine, "select count(*) from broker_connections") == 1

def test_legacy_api_key_is_bound_to_migrated_connection(legacy_engine):
    assert migration.apply(legacy_engine)
    assert scalar(legacy_engine, "select broker_connection_id from api_keys") is not None
```

- [ ] **Step 2: Run the migration tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_migrate_multi_broker.py test/test_migrate_all.py -q`
Expected: FAIL because `migrate_multi_broker` and the new tables/columns do not exist.

- [ ] **Step 3: Define the persistence models**

```python
class BrokerConnection(Base):
    __tablename__ = "broker_connections"
    id = Column(String(36), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    broker = Column(String(32), nullable=False, index=True)
    display_name = Column(String(80), nullable=False)
    credentials_encrypted = Column(Text, nullable=False)
    auth_encrypted = Column(Text)
    feed_token_encrypted = Column(Text)
    broker_user_id = Column(String(255))
    analyze_mode = Column(Boolean, nullable=False, default=True)
    status = Column(String(24), nullable=False, default="disconnected")
    is_revoked = Column(Boolean, nullable=False, default=False)
    last_verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("user_id", "display_name"),)

class BrokerConnectionSetting(Base):
    __tablename__ = "broker_connection_settings"
    connection_id = Column(String(36), primary_key=True)
    key = Column(String(80), primary_key=True)
    value = Column(Text, nullable=False)
```

Change `ApiKeys` uniqueness from `user_id` to `(user_id, broker_connection_id)` and add a non-null connection ID after backfill.

- [ ] **Step 4: Implement the migration and register it as required**

Use a transactional SQLite table rebuild for `api_keys`, preserve hashes/ciphertexts byte-for-byte, create the initial connection with `uuid.uuid4()`, copy the singleton Analyzer mode, and add:

```python
MIGRATIONS.append(("migrate_multi_broker.py", "Multi-Broker Connections"))
REQUIRED_MIGRATIONS = REQUIRED_MIGRATIONS | frozenset({"migrate_multi_broker.py"})
```

- [ ] **Step 5: Run migration tests and schema status twice**

Run: `env -u LOG_FORMAT uv run pytest test/test_migrate_multi_broker.py test/test_migrate_all.py -q`
Expected: PASS, including the interrupted/rerun fixture.

- [ ] **Step 6: Commit Task 1**

```bash
git add database/broker_connection_db.py database/auth_db.py upgrade/migrate_multi_broker.py upgrade/migrate_all.py test/test_migrate_multi_broker.py test/test_migrate_all.py
git commit -m "feat: add broker connection persistence"
```

---

### Task 2: Establish the immutable broker-context boundary

**Files:**
- Create: `services/broker_context.py`
- Modify: `database/broker_connection_db.py`
- Modify: `database/auth_db.py`
- Test: `test/test_broker_context.py`
- Test: `test/test_auth_connection_keys.py`

**Interfaces:**
- Produces: `BrokerContext`, `resolve_connection`, `resolve_api_key_context`, `resolve_single_legacy_context`, `broker_context_scope`, and `current_broker_context`.
- Produces: `get_api_key_for_connection(user_id, connection_id) -> str | None`.
- Consumes: Task 1 models and existing encryption/cache primitives.

- [ ] **Step 1: Write failing ownership and ambiguity tests**

```python
def test_foreign_connection_fails_closed(rows):
    with pytest.raises(BrokerContextError, match="does not belong"):
        resolve_connection("alice", rows.bob_connection_id)

def test_legacy_resolution_refuses_two_connections(rows):
    rows.add_connection("alice", "deltaexchange")
    with pytest.raises(BrokerContextError, match="explicit broker connection"):
        resolve_single_legacy_context("alice")

def test_api_key_resolves_exact_bound_connection(rows):
    context = resolve_api_key_context(rows.delta_api_key)
    assert (context.connection_id, context.broker) == (rows.delta_id, "deltaexchange")
```

- [ ] **Step 2: Run the context tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_broker_context.py test/test_auth_connection_keys.py -q`
Expected: FAIL because the resolver module does not exist.

- [ ] **Step 3: Implement the context contract**

```python
@dataclass(frozen=True, slots=True)
class BrokerContext:
    connection_id: str
    user_id: str
    broker: str
    broker_user_id: str | None
    auth_token: str | None
    feed_token: str | None
    analyze_mode: bool

def resolve_api_key_context(api_key: str, *, require_active: bool = True) -> BrokerContext: ...
def resolve_connection(user_id: str, connection_id: str, *, require_active: bool = True) -> BrokerContext: ...
@contextmanager
def broker_context_scope(context: BrokerContext): ...
def current_broker_context(*, required: bool = True) -> BrokerContext | None: ...
```

Use `contextvars.ContextVar`; keep its contents immutable and never cross it into real-thread callbacks. Cache by connection ID plus token revision, not username.

- [ ] **Step 4: Update API-key verification to return connection identity**

Keep `verify_api_key(key) -> user_id | None` as a compatibility wrapper, add `verify_api_key_context`, and make `get_broker_name` / `get_auth_token_broker` delegate to it. Compatibility lookup is allowed only when exactly one valid connection exists.

- [ ] **Step 5: Run context, auth-cache, and multi-session tests**

Run: `env -u LOG_FORMAT uv run pytest test/test_broker_context.py test/test_auth_connection_keys.py test/test_auth_cache_race.py test/test_auth_upsert_multisession.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add services/broker_context.py database/broker_connection_db.py database/auth_db.py test/test_broker_context.py test/test_auth_connection_keys.py
git commit -m "feat: resolve explicit broker contexts"
```

---

### Task 3: Add connection management, Kotak/Delta authentication, and isolated expiry

**Files:**
- Create: `blueprints/broker_connections.py`
- Modify: `app.py`
- Modify: `broker/kotak/api/auth_api.py`
- Modify: `broker/deltaexchange/api/auth_api.py`
- Modify: `utils/auth_utils.py`
- Modify: `blueprints/auth.py`
- Modify: `blueprints/brlogin.py`
- Modify: `blueprints/broker_credentials.py`
- Test: `test/test_broker_connections_api.py`
- Test: `test/test_multi_broker_expiry.py`
- Test: `test/test_broker_credentials.py`

**Interfaces:**
- Produces endpoints: `GET/POST /api/broker/connections`, `POST /<id>/authenticate`, `POST /<id>/select`, `POST /<id>/disconnect`, and `POST /disconnect-all`.
- Produces plugin calls `authenticate_broker(..., credentials: Mapping[str, str])` for Kotak and Delta.
- Consumes: `resolve_connection` and encrypted credential store.

- [ ] **Step 1: Write failing API/security tests**

```python
def test_connection_list_never_returns_secret(client, connected_user):
    body = client.get("/api/broker/connections").get_json()
    assert body["data"][0].keys() >= {"id", "broker", "display_name", "status", "analyze_mode"}
    assert "credentials_encrypted" not in json.dumps(body)
    assert "api_secret" not in json.dumps(body)

def test_selection_is_session_local(app, two_clients, two_connections):
    first, second = two_clients
    first.post(f"/api/broker/connections/{two_connections.delta}/select")
    assert first.get("/auth/session").get_json()["broker"] == "deltaexchange"
    assert second.get("/auth/session").get_json()["broker"] == "kotak"

def test_kotak_expiry_does_not_expire_delta(two_connections, freeze_time):
    expire_due_connections()
    assert connection(two_connections.kotak).status == "expired"
    assert connection(two_connections.delta).status == "connected"
```

- [ ] **Step 2: Run API tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_broker_connections_api.py test/test_multi_broker_expiry.py -q`
Expected: FAIL with missing routes.

- [ ] **Step 3: Implement write-only credential payloads**

```python
KOTAK_FIELDS = frozenset({"ucc", "consumer_key"})
DELTA_FIELDS = frozenset({"api_key", "api_secret"})

def create_connection(user_id: str, broker: str, display_name: str, credentials: Mapping[str, str]) -> str:
    validate_exact_fields(broker, credentials)
    encrypted = encrypt_token(json.dumps({"version": 1, **credentials}))
    return insert_connection(..., credentials_encrypted=encrypted)
```

Return only `has_credentials: true` and a fixed-length mask derived without revealing secret length.

- [ ] **Step 4: Refactor Kotak and Delta authentication to consume stored credentials**

Remove module-time dependence on `BROKER_API_KEY` / `BROKER_API_SECRET` for these two plugins. The caller decrypts the connection payload and passes it explicitly. Preserve old call signatures only for the one-connection compatibility path.

- [ ] **Step 5: Implement session selection and broker-specific expiry**

Set `session["active_broker_connection_id"]`, mirror `session["broker"]`, and return connection metadata from `/auth/session`. Kotak follows configured daily expiry; Delta's 24/7 connection is not revoked at 3 AM.

- [ ] **Step 6: Run connection, expiry, redaction, and login tests**

Run: `env -u LOG_FORMAT uv run pytest test/test_broker_connections_api.py test/test_multi_broker_expiry.py test/test_broker_credentials.py test/test_auth_resume.py test/test_auth_logout.py test/test_logging_redaction.py -q`
Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add blueprints/broker_connections.py app.py broker/kotak/api/auth_api.py broker/deltaexchange/api/auth_api.py utils/auth_utils.py blueprints/auth.py blueprints/brlogin.py blueprints/broker_credentials.py test/test_broker_connections_api.py test/test_multi_broker_expiry.py test/test_broker_credentials.py
git commit -m "feat: manage multiple broker connections"
```

---

### Task 4: Route REST and service calls through connection-bound API keys

**Files:**
- Create: `utils/request_broker.py`
- Modify: `services/place_order_service.py`
- Modify: `services/funds_service.py`
- Modify: `services/holdings_service.py`
- Modify: `services/positionbook_service.py`
- Modify: `services/orderbook_service.py`
- Modify: `services/tradebook_service.py`
- Modify: `services/openposition_service.py`
- Modify: `services/modify_order_service.py`
- Modify: `services/cancel_order_service.py`
- Modify: `services/cancel_all_order_service.py`
- Modify: `services/place_gtt_order_service.py`
- Modify: `services/modify_gtt_order_service.py`
- Modify: `services/cancel_gtt_order_service.py`
- Modify: `services/basket_order_service.py`
- Modify: `services/split_order_service.py`
- Modify: `services/place_smart_order_service.py`
- Modify: `services/place_options_order_service.py`
- Modify: `services/options_multiorder_service.py`
- Modify: `services/close_position_service.py`
- Modify: `restx_api/place_order.py`
- Modify: `blueprints/orders.py`
- Test: `test/test_connection_routing_services.py`
- Test: `test/test_connection_bound_rest_api.py`

**Interfaces:**
- Produces: `resolve_request_context(api_key: str | None = None) -> BrokerContext`.
- Updates broker-facing services to accept `broker_context: BrokerContext | None` and resolve once at their public entry point.
- Consumes: Task 2 context resolvers.

- [ ] **Step 1: Write failing cross-routing tests**

```python
@pytest.mark.parametrize("key,want_broker", [(KOTAK_KEY, "kotak"), (DELTA_KEY, "deltaexchange")])
def test_funds_routes_by_key_not_browser_session(key, want_broker, service_spy):
    response = get_funds(api_key=key)
    assert response["status"] == "success"
    assert service_spy.last_broker == want_broker

def test_request_broker_field_cannot_override_key(delta_key):
    response = post_json("/api/v1/placeorder", {"apikey": delta_key, "broker": "kotak", **ORDER})
    assert response.status_code == 400
    assert response.json["code"] == "broker_context_mismatch"
```

- [ ] **Step 2: Run routing tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_connection_routing_services.py test/test_connection_bound_rest_api.py -q`
Expected: FAIL because API keys still map by username.

- [ ] **Step 3: Add the request resolver and explicit service parameter**

```python
def get_funds(*, api_key=None, auth_token=None, broker=None, broker_context=None):
    context = broker_context or resolve_service_context(api_key, auth_token, broker)
    with broker_context_scope(context):
        return _get_funds_for_context(context)
```

Apply the same resolve-once pattern to account, order, GTT, basket, split, smart, option, and close-position public service entry points. Never resolve again from mutable browser state after an order operation begins.

- [ ] **Step 4: Update REST and browser routes**

REST routes resolve from the API key. Browser routes call `resolve_browser_context()` from `utils/request_broker.py`. Return typed 409 errors for missing/expired connections and 400 for a broker-context mismatch.

- [ ] **Step 5: Run service, REST, and existing order/account suites**

Run: `env -u LOG_FORMAT uv run pytest test/test_connection_routing_services.py test/test_connection_bound_rest_api.py test/test_data_schemas_validation.py test/test_approve_orders.py test/test_portfolio_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add utils/request_broker.py services/place_order_service.py services/funds_service.py services/holdings_service.py services/positionbook_service.py services/orderbook_service.py services/tradebook_service.py services/openposition_service.py services/modify_order_service.py services/cancel_order_service.py services/cancel_all_order_service.py services/place_gtt_order_service.py services/modify_gtt_order_service.py services/cancel_gtt_order_service.py services/basket_order_service.py services/split_order_service.py services/place_smart_order_service.py services/place_options_order_service.py services/options_multiorder_service.py services/close_position_service.py restx_api/place_order.py blueprints/orders.py test/test_connection_routing_services.py test/test_connection_bound_rest_api.py
git commit -m "feat: route broker services by connection"
```

---

### Task 5: Make Analyzer mode and order confirmation connection-scoped

**Files:**
- Modify: `database/settings_db.py`
- Modify: `services/analyzer_service.py`
- Modify: `blueprints/auth.py`
- Modify: `services/place_order_service.py`
- Modify: `services/modify_order_service.py`
- Modify: `services/cancel_order_service.py`
- Modify: `services/options_multiorder_service.py`
- Modify: `services/place_smart_order_service.py`
- Modify: `services/basket_order_service.py`
- Modify: `services/split_order_service.py`
- Modify: `services/close_position_service.py`
- Modify: `services/agent/tools/account.py`
- Modify: `services/agent/safety/risk.py`
- Test: `test/test_connection_analyzer_mode.py`
- Test: `test/test_stale_broker_order_preview.py`

**Interfaces:**
- Produces: `get_analyze_mode(connection_id: str) -> bool` and `set_analyze_mode(connection_id: str, mode: bool) -> None`.
- Produces an order-preview `broker_selection_nonce` bound to connection, arguments, user, and expiry.
- Consumes immutable `BrokerContext` at dispatch.

- [ ] **Step 1: Write failing independent-mode and stale-preview tests**

```python
def test_each_connection_has_independent_analyzer_mode(two_connections):
    set_analyze_mode(two_connections.kotak, True)
    set_analyze_mode(two_connections.delta, False)
    assert get_analyze_mode(two_connections.kotak) is True
    assert get_analyze_mode(two_connections.delta) is False

def test_order_preview_is_rejected_after_session_switch(client, preview, delta_connection):
    client.post(f"/api/broker/connections/{delta_connection}/select")
    response = client.post("/orders/confirm", json={"preview_nonce": preview.nonce})
    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_broker_selection"
    assert broker_dispatch.calls == []
```

- [ ] **Step 2: Run safety tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_connection_analyzer_mode.py test/test_stale_broker_order_preview.py -q`
Expected: FAIL because mode is still singleton and previews are not connection-bound.

- [ ] **Step 3: Replace singleton mode reads in every order path**

Read mode from the already-resolved context. Compatibility `get_analyze_mode()` without an ID may read the current scoped context, but raises `BrokerContextError` when no context exists and more than one connection is active.

- [ ] **Step 4: Bind previews and approvals to the connection**

```python
@dataclass(frozen=True)
class OrderPreviewBinding:
    user_id: str
    connection_id: str
    arguments_hash: str
    expires_at: datetime
```

The confirm route compares the binding with the current session selection and the submitted arguments before dispatch. MCP/API calls remain bound by their API key and normal tool/client approval flow.

- [ ] **Step 5: Audit singleton mode references**

Run: `rg -n "get_analyze_mode\(\)|set_analyze_mode\([^,]+\)" services blueprints restx_api`
Expected: only documented one-connection compatibility wrappers and tests remain.

- [ ] **Step 6: Run order, agent-risk, GTT, and analyzer suites**

Run: `env -u LOG_FORMAT uv run pytest test/test_connection_analyzer_mode.py test/test_stale_broker_order_preview.py test/test_approve_orders.py test/sandbox/test_gtt_manager.py -q`
Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add database/settings_db.py services blueprints/auth.py test/test_connection_analyzer_mode.py test/test_stale_broker_order_preview.py
git commit -m "feat: isolate broker trading modes"
```

---

### Task 6: Isolate WebSocket, symbol, and order-update lifecycles

**Files:**
- Modify: `websocket_proxy/broker_factory.py`
- Modify: `websocket_proxy/server.py`
- Modify: `websocket_proxy/connection_manager.py`
- Modify: `services/order_update_service.py`
- Modify: `database/cache_invalidation.py`
- Modify: `database/token_db_enhanced.py`
- Modify: `database/cache_restoration.py`
- Modify: `services/websocket_client.py`
- Test: `test/test_multi_broker_websocket_isolation.py`
- Test: `test/test_auth_upsert_multisession.py`
- Test: `test/test_order_update_adapters.py`

**Interfaces:**
- Produces pool key `connection_id` and client subscription identity `(socket_id, connection_id)`.
- Produces `invalidate_connection(connection_id)` and `cleanup_pool(connection_id)`.
- Consumes Task 2 connection context; never queries a first auth row.

- [ ] **Step 1: Write failing simultaneous-feed tests**

```python
def test_two_connections_get_distinct_pools(factory, contexts):
    kotak = factory.initialize(contexts.kotak)
    delta = factory.initialize(contexts.delta)
    assert kotak is not delta
    assert set(factory.pool_keys()) == {contexts.kotak.connection_id, contexts.delta.connection_id}

def test_kotak_refresh_does_not_disconnect_delta(factory, contexts):
    factory.initialize(contexts.kotak)
    delta = factory.initialize(contexts.delta)
    invalidate_connection(contexts.kotak.connection_id)
    assert delta.connected is True
```

- [ ] **Step 2: Run WebSocket tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_multi_broker_websocket_isolation.py test/test_order_update_adapters.py -q`
Expected: FAIL because maps are keyed by user/broker.

- [ ] **Step 3: Re-key pools, adapters, and invalidation events**

Replace username-keyed maps with connection IDs. Carry `{connection_id, user_id, broker}` through the WebSocket authentication response and ZMQ invalidation event. Update health/stat output to show display name but not credentials.

- [ ] **Step 4: Make symbol caches broker/connection aware**

Keep globally identical instrument masters keyed by broker. Include connection ID for any account-dependent cache. Remove `active_broker` singleton restoration; restore all connected broker masters.

- [ ] **Step 5: Run feed, cache, reconnect, and leak tests**

Run: `env -u LOG_FORMAT uv run pytest test/test_multi_broker_websocket_isolation.py test/test_order_update_adapters.py test/test_auth_upsert_multisession.py test/test_websocket_unsubscribe_contract.py test/test_event_bus_bounded.py -q`
Expected: PASS.

- [ ] **Step 6: Run the repository FD audit required by `CLAUDE.md`**

Run the `.claude/skills/fd-audit` procedure against the changed DB/WebSocket/thread files and attach its result to the implementation summary.
Expected: no new unclosed sockets, sessions, files, or cross-eventlet waits.

- [ ] **Step 7: Commit Task 6**

```bash
git add websocket_proxy services/order_update_service.py services/websocket_client.py database/cache_invalidation.py database/token_db_enhanced.py database/cache_restoration.py test/test_multi_broker_websocket_isolation.py test/test_order_update_adapters.py
git commit -m "feat: isolate broker feed lifecycles"
```

---

### Task 7: Pin strategies, Flow, schedules, pending work, GTT, and scalping

**Files:**
- Modify: `database/strategy_module_db.py`
- Modify: `database/flow_db.py`
- Modify: `database/scalping_db.py`
- Modify: `database/sandbox_db.py`
- Modify: `database/strategy_book_db.py`
- Modify: `blueprints/strategy_module.py`
- Modify: `blueprints/flow.py`
- Modify: `blueprints/python_strategy.py`
- Modify: `blueprints/scalping.py`
- Modify: `services/strategy_module/runtime.py`
- Modify: `services/strategy_module/order_dispatch.py`
- Modify: `services/strategy_module/scheduler.py`
- Modify: `services/flow_executor_service.py`
- Modify: `services/flow_scheduler_service.py`
- Modify: `services/pending_order_execution_service.py`
- Modify: `services/scalping_risk_monitor_service.py`
- Modify: `services/place_gtt_order_service.py`
- Test: `test/test_automation_broker_pinning.py`
- Test: `test/test_strategy_module_broker_connection.py`
- Test: `test/test_flow_broker_connection.py`

**Interfaces:**
- Produces immutable `broker_connection_id` on every durable trading owner/run.
- Consumes `resolve_connection(owner_user_id, broker_connection_id)` before starting or resuming work.

- [ ] **Step 1: Write failing pinning and reassignment tests**

```python
@pytest.mark.parametrize("kind", ["strategy", "flow", "schedule", "pending", "gtt", "scalping"])
def test_automation_runs_on_pinned_connection_after_browser_switch(kind, automation_factory, clients):
    item = automation_factory(kind, connection_id=KOTAK_ID)
    clients.owner.post(f"/api/broker/connections/{DELTA_ID}/select")
    run = item.start()
    assert run.broker_connection_id == KOTAK_ID
    assert dispatch.last_context.connection_id == KOTAK_ID

def test_active_strategy_cannot_change_connection(active_strategy):
    response = patch_strategy(active_strategy.id, broker_connection_id=DELTA_ID)
    assert response.status_code == 409
```

- [ ] **Step 2: Run automation tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_automation_broker_pinning.py test/test_strategy_module_broker_connection.py test/test_flow_broker_connection.py -q`
Expected: FAIL because durable records do not carry a connection.

- [ ] **Step 3: Add and backfill connection columns**

Extend Task 1 migration for the tables in this task. Store IDs as indexed strings across separate SQLite databases without cross-database foreign keys. Reject new records without an owned connection; backfill legacy records only when exactly one migrated connection exists.

- [ ] **Step 4: Resolve context at start/resume and retain it for exits**

Pass `BrokerContext` into runtime sessions, Flow executors, pending execution, GTT, and scalping monitors. A risk exit always uses the connection that opened the position, including `force_live=True` residual exits.

- [ ] **Step 5: Run strategy, Flow, pending, GTT, and scalping suites**

Run: `env -u LOG_FORMAT uv run pytest test/test_automation_broker_pinning.py test/test_strategy_module_broker_connection.py test/test_flow_broker_connection.py test/test_strategy_module_runtime.py test/test_strategy_module_order_dispatch.py test/test_pending_order_execution_service.py test/sandbox/test_gtt_manager.py test/test_scalping_risk_monitor.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add database blueprints/strategy_module.py blueprints/flow.py blueprints/python_strategy.py blueprints/scalping.py services/strategy_module services/flow_executor_service.py services/flow_scheduler_service.py services/pending_order_execution_service.py services/scalping_risk_monitor_service.py services/place_gtt_order_service.py test/test_automation_broker_pinning.py test/test_strategy_module_broker_connection.py test/test_flow_broker_connection.py
git commit -m "feat: pin automation to broker connections"
```

---

### Task 8: Add the per-session broker dropdown and connection-aware frontend state

**Files:**
- Create: `frontend/src/api/broker-connections.ts`
- Create: `frontend/src/stores/brokerConnectionStore.ts`
- Create: `frontend/src/components/layout/BrokerConnectionSelect.tsx`
- Create: `frontend/src/components/layout/BrokerConnectionSelect.test.tsx`
- Modify: `frontend/src/components/layout/Navbar.tsx`
- Modify: `frontend/src/components/layout/Navbar.test.tsx`
- Modify: `frontend/src/components/auth/AuthSync.tsx`
- Create: `frontend/src/components/auth/AuthSync.test.tsx`
- Modify: `frontend/src/stores/authStore.ts`
- Modify: `frontend/src/stores/themeStore.ts`
- Modify: `frontend/src/types/auth.ts`
- Modify: `frontend/src/app/providers.tsx`

**Interfaces:**
- Produces: `BrokerConnectionSummary`, `brokerConnectionsApi.select(id)`, and `useBrokerConnectionStore`.
- Consumes Task 3 endpoints; emits a connection-change event for sockets and query invalidation.

- [ ] **Step 1: Write failing dropdown/session-isolation tests**

```tsx
it('selects Delta, clears broker-scoped queries, and keeps the second session on Kotak', async () => {
  renderNavbar({ connections: [kotak, delta], activeId: kotak.id })
  await user.selectOptions(screen.getByLabelText(/broker connection/i), delta.id)
  expect(api.select).toHaveBeenCalledWith(delta.id)
  expect(queryClient.getQueryData(['funds', kotak.id])).toBeUndefined()
  expect(screen.getByText(/delta exchange india/i)).toBeVisible()
})

it('shows each connection mode without toggling it during selection', async () => {
  renderDropdown({ kotak: 'analyzer', delta: 'live' })
  await select(delta.id)
  expect(modeApi.toggle).not.toHaveBeenCalled()
  expect(screen.getByText('LIVE')).toBeVisible()
})
```

- [ ] **Step 2: Run frontend tests and confirm RED**

Run: `cd frontend && npm test -- --run src/components/layout/BrokerConnectionSelect.test.tsx src/components/layout/Navbar.test.tsx`
Expected: FAIL because the component/store do not exist.

- [ ] **Step 3: Implement typed connection state and API**

```ts
export type BrokerConnectionSummary = {
  id: string
  broker: 'kotak' | 'deltaexchange'
  display_name: string
  status: 'connected' | 'expired' | 'connecting' | 'error' | 'disconnected'
  analyze_mode: boolean
}
```

Do not persist the active connection in localStorage; the Flask session is authoritative. On selection success, update the store from the response, clear TanStack broker-data queries, resync mode, and reconnect displayed sockets.

- [ ] **Step 4: Add accessible desktop/mobile dropdowns**

Use the existing shadcn `Select`, label it "Broker connection", show health and ANALYZE/LIVE badges, and keep the control keyboard/touch accessible. A failed selection preserves the old connection and shows a toast.

- [ ] **Step 5: Run component, auth sync, and build checks**

Run: `cd frontend && npm test -- --run src/components/layout/BrokerConnectionSelect.test.tsx src/components/layout/Navbar.test.tsx src/components/auth/AuthSync.test.tsx`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: exit 0.

- [ ] **Step 6: Commit Task 8**

```bash
git add frontend/src/api/broker-connections.ts frontend/src/stores/brokerConnectionStore.ts frontend/src/components/layout frontend/src/components/auth/AuthSync.tsx frontend/src/components/auth/AuthSync.test.tsx frontend/src/stores/authStore.ts frontend/src/stores/themeStore.ts frontend/src/types/auth.ts frontend/src/app/providers.tsx
git commit -m "feat: add per-session broker switcher"
```

---

### Task 9: Add the connection setup/reconnect UI and broker-pinned editors

**Files:**
- Create: `frontend/src/pages/BrokerConnections.tsx`
- Create: `frontend/src/pages/BrokerConnections.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Profile.tsx`
- Modify: `frontend/src/pages/strategy/Wizard.tsx`
- Modify: `frontend/src/pages/strategy/Edit.tsx`
- Modify: `frontend/src/pages/flow/FlowEditor.tsx`
- Modify: `frontend/src/pages/python-strategy/NewPythonStrategy.tsx`
- Modify: `frontend/src/pages/python-strategy/SchedulePythonStrategy.tsx`
- Modify: `frontend/src/pages/Scalping.tsx`
- Modify: `frontend/src/types/strategy_module.ts`
- Modify: `frontend/src/types/flow.ts`
- Modify: `frontend/src/pages/strategy/Detail.test.tsx`

**Interfaces:**
- Produces write-only Kotak/Delta setup forms and reconnect/disconnect actions.
- Adds `broker_connection_id` to creation payloads and read-only connection identity to active run views.
- Consumes Task 3 and Task 7 APIs.

- [ ] **Step 1: Write failing credential-redaction and immutable-run UI tests**

```tsx
it('never repopulates a saved secret into the Delta form', async () => {
  renderConnections({ delta: { has_credentials: true } })
  expect(screen.getByLabelText(/api secret/i)).toHaveValue('')
})

it('locks broker selection while a strategy run is active', async () => {
  renderStrategyEdit({ connection: kotak, runStatus: 'running' })
  expect(screen.getByLabelText(/broker connection/i)).toBeDisabled()
  expect(screen.getByText(/stop the run and flatten positions/i)).toBeVisible()
})
```

- [ ] **Step 2: Run page/editor tests and confirm RED**

Run: `cd frontend && npm test -- --run src/pages/BrokerConnections.test.tsx src/pages/strategy/Detail.test.tsx`
Expected: FAIL because the page and fields do not exist.

- [ ] **Step 3: Implement write-only connection forms**

Kotak fields: UCC, consumer key, mobile, TOTP, MPIN during authentication. Delta fields: API key and API secret. Submit credentials once; subsequent responses show only `has_credentials`, status, and verification time.

- [ ] **Step 4: Add required connection selectors to automation editors**

Default new records to the current session connection but include the explicit ID in the submitted payload. Existing records show their pinned connection. Disable reassignment while any run/position ownership is active.

- [ ] **Step 5: Run page, strategy, Flow, and accessibility tests**

Run: `cd frontend && npm test -- --run src/pages/BrokerConnections.test.tsx src/pages/strategy/Detail.test.tsx src/pages/flow/FlowEditorViewport.test.tsx src/components/layout/BrokerConnectionSelect.test.tsx`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: exit 0.

- [ ] **Step 6: Commit Task 9**

```bash
git add frontend/src/pages/BrokerConnections.tsx frontend/src/pages/BrokerConnections.test.tsx frontend/src/App.tsx frontend/src/pages/Profile.tsx frontend/src/pages/strategy/Wizard.tsx frontend/src/pages/strategy/Edit.tsx frontend/src/pages/strategy/Detail.test.tsx frontend/src/pages/flow/FlowEditor.tsx frontend/src/pages/python-strategy/NewPythonStrategy.tsx frontend/src/pages/python-strategy/SchedulePythonStrategy.tsx frontend/src/pages/Scalping.tsx frontend/src/types/strategy_module.ts frontend/src/types/flow.ts
git commit -m "feat: configure broker connections in the UI"
```

---

### Task 10: Pin two Codex MCP connections to the same OpenAlgo instance

**Files:**
- Modify: `mcp/codex_launcher.py`
- Modify: `.codex/config.toml`
- Modify: `docs/mcp-tool-reference.md`
- Modify: `test/test_codex_mcp_launcher.py`
- Modify: `test/test_mcp_integrity.py`

**Interfaces:**
- Consumes `OPENALGO_BROKER_CONNECTION_ID` and retrieves only that connection's encrypted API key.
- Produces two Codex server registrations: `openalgo-kotak` and `openalgo-delta`.
- Keeps all existing MCP tool schemas unchanged.

- [ ] **Step 1: Write failing launcher-pinning tests**

```python
def test_launcher_requires_explicit_connection_when_multiple_exist(store):
    store.add(KOTAK_ID)
    store.add(DELTA_ID)
    with pytest.raises(RuntimeError, match="OPENALGO_BROKER_CONNECTION_ID"):
        launch(connection_id=None, runner=noop)

def test_launcher_reads_only_the_selected_connection_key(store):
    argv = capture_launch(connection_id=DELTA_ID)
    assert argv.api_key == store.api_key(DELTA_ID)
    assert argv.api_key != store.api_key(KOTAK_ID)
```

- [ ] **Step 2: Run MCP tests and confirm RED**

Run: `env -u LOG_FORMAT uv run pytest test/test_codex_mcp_launcher.py test/test_mcp_integrity.py -q`
Expected: FAIL because the launcher chooses the first available key.

- [ ] **Step 3: Make launcher selection explicit and secret-free**

Read `OPENALGO_BROKER_CONNECTION_ID`, call `get_api_key_for_connection`, and pass the decrypted key only in the child process argv. Configuration contains connection IDs and paths, never API keys.

- [ ] **Step 4: Register both global Codex MCP servers**

Read the exact Kotak and Delta connection IDs from `broker_connections` after Task 3, validate that each ID belongs to the signed-in user and expected broker, then register `openalgo-kotak` and `openalgo-delta` with `OPENALGO_BROKER_CONNECTION_ID` set to the corresponding exact ID. Use the repository's resolved absolute Python and launcher paths. Do not copy credentials into commands or configuration. Keep the existing `openalgo` registration until both replacements pass Step 5; remove it only after successful verification.

- [ ] **Step 5: Verify both handshakes and read-only calls**

Use `ClientSession.list_tools()` on both processes and call `get_funds`, `get_position_book`, and `analyzer_status`. Assert each response's connection metadata matches the configured ID. Do not call an order tool.

- [ ] **Step 6: Run MCP suites and linter**

Run: `env -u LOG_FORMAT uv run pytest test/test_codex_mcp_launcher.py test/test_mcp_integrity.py -q`
Expected: PASS.
Run: `uv run ruff check mcp/codex_launcher.py test/test_codex_mcp_launcher.py test/test_mcp_integrity.py`
Expected: PASS.

- [ ] **Step 7: Commit Task 10**

```bash
git add mcp/codex_launcher.py .codex/config.toml docs/mcp-tool-reference.md test/test_codex_mcp_launcher.py test/test_mcp_integrity.py
git commit -m "feat: pin Codex MCP servers to brokers"
```

---

### Task 11: Perform migration rehearsal, security verification, and documentation

**Files:**
- Modify: `docs/userguide/README.md`
- Create: `docs/userguide/04-broker-connections/README.md`
- Modify: `docs/INDEX.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/bdd/admin_and_security.feature`
- Test: `test/test_multi_broker_e2e.py`
- Test: `test/test_logging_redaction.py`

**Interfaces:**
- Consumes every prior task.
- Produces an operator-facing migration/reconnect/rollback guide and final regression evidence.

- [ ] **Step 1: Write the end-to-end acceptance test**

```python
def test_kotak_and_delta_coexist_end_to_end(app, migrated_database, fake_brokers):
    browser_a, browser_b = login_two_sessions(app)
    select(browser_a, KOTAK_ID)
    select(browser_b, DELTA_ID)
    assert funds(browser_a)["connection_id"] == KOTAK_ID
    assert funds(browser_b)["connection_id"] == DELTA_ID
    toggle_analyzer(browser_a, True)
    assert mode(browser_b) == "live"
    refresh_token(KOTAK_ID)
    assert fake_brokers.delta.feed.connected
    assert analyzer_order(KOTAK_KEY).broker == "kotak"
    assert analyzer_order(DELTA_KEY).broker == "deltaexchange"
```

- [ ] **Step 2: Run acceptance test and fix only failures in approved scope**

Run: `env -u LOG_FORMAT uv run pytest test/test_multi_broker_e2e.py test/test_logging_redaction.py -q`
Expected: PASS with no credential material in captured logs.

- [ ] **Step 3: Rehearse migration against a copy of the operator database**

Create a timestamped copy under `/private/tmp`, run `upgrade/migrate_multi_broker.py` twice against that copy, run `--status`, and compare row counts/ciphertext hashes. Never run the first rehearsal against `db/openalgo.db`.

- [ ] **Step 4: Apply the migration to the real database with a recoverable backup**

Stop OpenAlgo cleanly, copy all affected DB files to a timestamped backup directory, run the master migration, inspect status, then restart. If status fails, restore the backup before starting the old revision.

- [ ] **Step 5: Add Delta and verify both connections without live orders**

Enter the rotated Delta credentials through the write-only connection UI, authenticate, confirm Kotak remains connected, verify independent funds/positions/quotes/feeds, and submit one Analyzer-only order per connection.

- [ ] **Step 6: Run backend, frontend, migration, and static checks**

Run: `env -u LOG_FORMAT uv run pytest`
Expected: PASS; if a pre-existing collection failure remains, record the exact test and also run every changed-area suite explicitly.
Run: `uv run ruff check .`
Expected: PASS.
Run: `cd frontend && npm test -- --run`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: exit 0.
Run: `git diff --check`
Expected: no output.

- [ ] **Step 7: Document use and rollback**

Document adding/reconnecting connections, the session-local dropdown, per-broker mode, strategy pinning, two MCP names, Delta 24/7 expiry behavior, static-IP errors, secret rotation, and backup restoration. Do not include example secrets.

- [ ] **Step 8: Commit Task 11**

```bash
git add docs test/test_multi_broker_e2e.py test/test_logging_redaction.py
git commit -m "docs: explain multi-broker operation"
```

- [ ] **Step 9: Request final whole-branch review**

Review the complete branch against the spec, inspect every migration and order-routing diff, and rerun the exact verification commands after addressing findings. No merge or live-order enablement occurs without an explicit operator decision.
