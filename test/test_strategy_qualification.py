"""Prospective forward evidence and reviewed release boundaries."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from database.engine_factory import create_db_engine


def costs():
    return {
        "schedule_id": "test",
        "source": "operator estimate",
        "effective_from": "2026-01-01",
        "effective_to": "2027-12-31",
        "brokerage_per_order": 1,
        "exchange_rate": 0,
        "sebi_rate": 0,
        "gst_rate": 0,
        "stamp_buy_rate": 0,
        "stt_sell_rate": 0,
        "slippage_bps": 10,
    }


def binding():
    return {
        "binding_hash": "stable",
        "broker_connection_id": 7,
        "broker": "test",
        "broker_epoch": "epoch1",
        "costs": costs(),
        "strategy_hash": "strategy",
        "workflow_hash": "flow",
        "source_hash": "source",
        "risk_policy_version": "two-bucket-v1",
        "workflow_id": 9,
        "entry_origin": {"workflow_id": 9, "execution_id": 10},
    }


def final_run():
    return {
        "id": 4,
        "kind": "final",
        "status": "completed",
        "frozen_at": "2026-01-01T00:00:00Z",
        "report": {
            "metrics": {"trade_count": 20, "net_pnl": 100},
            "incomplete_outcomes": [],
            "split": {"kind": "final", "holdout_sessions": 60},
        },
        "configuration_hash": "final",
    }


def quote(at, action="BUY"):
    return {
        "broker_connection_id": 7,
        "broker": "test",
        "symbol": "OPT",
        "exchange": "NFO",
        "action": action,
        "quantity": 10,
        "bid": 100 if action == "BUY" else 120,
        "ask": 101 if action == "BUY" else 121,
        "bid_qty": 100,
        "ask_qty": 100,
        "market_at": at.isoformat(),
        "captured_at": at.isoformat(),
        "source": "authenticated_broker",
    }


def evidence(at, ref="r1"):
    orders = []
    for idx, action, price in [(1, "BUY", 100), (2, "SELL", 121)]:
        orders.append(
            {
                "id": idx,
                "action": action,
                "symbol": "OPT",
                "exchange": "NFO",
                "quantity": 10,
                "filled_qty": 10,
                "avg_fill_price": price,
                "status": "complete",
                "placed_at": at.isoformat(),
                "filled_at": (at + timedelta(seconds=2)).isoformat(),
            }
        )
    return {
        "scope": "alice|sandbox",
        "ref": ref,
        "status": "closed",
        "filled": True,
        "ledger_revision": 1,
        "strategy_id": 1,
        "session_day": at.date().isoformat(),
        "planned_risk": 100,
        "net_pnl": 999999,
        "broker": "test",
        "details": {"costs": costs(), "symbol": "OPT", "exchange": "NFO", "quantity": 10},
        "evidence": {"orders": orders},
        "budget_snapshot": {"equity": 10000, "peak_equity": 10000, "paused": False},
    }


def test_executable_prices_fees_and_stress_ignore_reported_profit():
    from services.risk.qualification import evaluate_trade

    at = datetime(2026, 9, 26, tzinfo=UTC)
    receipts = {str(i): quote(at, side) for i, side in [(1, "BUY"), (2, "SELL")]}
    result = evaluate_trade(evidence(at), receipts, binding(), at.isoformat())
    assert result["valid"]
    # Buy at ask 101 + 0.101; sell at bid 120 - 0.120; two 1-unit fees.
    assert result["net_pnl"] == pytest.approx(185.79)
    assert result["stressed_net_pnl"] == pytest.approx(181.58)


@pytest.mark.parametrize(
    "mutation",
    [
        "stale",
        "future",
        "wrong_account",
        "missing_time",
        "partial",
        "duplicate",
        "unbalanced",
        "before_enrollment",
        "depth",
        "other_instrument",
    ],
)
def test_invalid_execution_cannot_qualify(mutation):
    from services.risk.qualification import evaluate_trade

    at = datetime(2026, 9, 26, tzinfo=UTC)
    row = evidence(at)
    receipts = {str(i): quote(at, side) for i, side in [(1, "BUY"), (2, "SELL")]}
    if mutation == "stale":
        receipts["1"]["market_at"] = (at - timedelta(seconds=6)).isoformat()
    if mutation == "future":
        receipts["1"]["captured_at"] = (at + timedelta(seconds=3)).isoformat()
    if mutation == "wrong_account":
        receipts["1"]["broker_connection_id"] = 8
    if mutation == "missing_time":
        row["evidence"]["orders"][0]["filled_at"] = None
    if mutation == "partial":
        row["evidence"]["orders"][0]["status"] = "open"
    if mutation == "duplicate":
        row["evidence"]["orders"].append(row["evidence"]["orders"][0])
    if mutation == "unbalanced":
        row["evidence"]["orders"][1]["filled_qty"] = 9
    if mutation == "before_enrollment":
        receipts["1"]["captured_at"] = (at - timedelta(seconds=1)).isoformat()
    if mutation == "depth":
        receipts["1"]["ask_qty"] = 9
    if mutation == "other_instrument":
        row["evidence"]["orders"][1]["symbol"] = "OTHER"
        receipts["2"]["symbol"] = "OTHER"
    assert not evaluate_trade(row, receipts, binding(), at.isoformat())["valid"]


@pytest.fixture
def store(tmp_path):
    from database.strategy_qualification_db import QualificationStore

    engine = create_db_engine(f"sqlite:///{tmp_path / 'qualification.db'}")
    result = QualificationStore(engine=engine)
    result.init_db()
    from database.trading_risk_db import RiskTrade

    RiskTrade.__table__.create(engine, checkfirst=True)
    yield result
    engine.dispose()


def test_registration_owner_scope_and_duplicate_evidence(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    assert store.register_entry("bob", 1, "r1", binding(), now) is None
    assert store.record_trade("alice", "old", evidence(now), now) is False
    registered = store.register_entry("alice", 1, "r1", binding(), now)
    assert registered == store.register_entry("alice", 1, "r1", binding(), now)
    assert store.get_campaign("bob", campaign["id"]) is None
    assert store.record_quote("bob", "r1", 1, quote(now), now) is False
    store.record_quote("alice", "r1", 1, quote(now), now)
    store.record_quote("alice", "r1", 2, quote(now, "SELL"), now)
    store.record_trade("alice", "r1", evidence(now), now)
    revision = store.get_campaign("alice", campaign["id"])["revision"]
    store.record_trade("alice", "r1", evidence(now), now)
    assert store.get_campaign("alice", campaign["id"])["revision"] == revision
    with pytest.raises(ValueError):
        store.create_campaign("alice", 1, 4, binding(), final_run(), now)


def test_marked_drawdown_is_retained_after_recovery(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    store.register_entry("alice", 1, "r1", binding(), now)
    row = evidence(now)
    row["budget_snapshot"]["equity"] = 8000
    store.record_trade("alice", "r1", row, now)
    row["budget_snapshot"]["equity"] = 10000
    row["ledger_revision"] = 2
    store.record_trade("alice", "r1", row, now)
    assert store.get_campaign("alice", campaign["id"])["max_drawdown_pct"] == 20


def test_policy_boundaries_and_missing_marked_evidence():
    from services.risk.qualification import evaluate_campaign

    trades = [
        {
            "valid": True,
            "status": "closed",
            "session_day": f"2026-08-{1 + i % 30:02d}",
            "net_pnl": 10,
            "stressed_net_pnl": 8,
            "issues": [],
        }
        for i in range(100)
    ]
    result = evaluate_campaign(final_run(), trades, max_drawdown_pct=15, marks_complete=True)
    assert result["eligible"]
    assert not evaluate_campaign(final_run(), trades, max_drawdown_pct=15.01, marks_complete=True)[
        "eligible"
    ]
    assert not evaluate_campaign(final_run(), trades[:99], max_drawdown_pct=0, marks_complete=True)[
        "eligible"
    ]
    assert not evaluate_campaign(final_run(), trades, max_drawdown_pct=0, marks_complete=False)[
        "eligible"
    ]


def test_approval_compare_and_swap_expiry_and_revoke(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    current = store.get_campaign("alice", campaign["id"])
    store.reconcile(
        "alice", campaign["id"], current["revision"], current["evidence_digest"], "reviewed", now
    )
    store.register_entry("alice", 1, "r1", binding(), now)
    with pytest.raises(ValueError):
        store.approve(
            "alice",
            campaign["id"],
            current["revision"],
            current["evidence_digest"],
            binding(),
            "approve",
            now,
        )
    current = store.get_campaign("alice", campaign["id"])
    assert current["reconciliation"]["status"] == "stale"


def test_campaign_drawdown_cannot_be_hidden_by_other_strategy_gains(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    store.register_entry("alice", 1, "r1", binding(), now)
    receipt = quote(now)
    receipt.update(quantity=100, ask_qty=100)
    store.record_quote("alice", "r1", 1, receipt, now)
    row = evidence(now)
    row["status"] = "open"
    row["evidence"]["orders"] = row["evidence"]["orders"][:1]
    row["evidence"]["orders"][0].update(quantity=100, filled_qty=100)
    row["evidence"]["mark"] = 80
    row["budget_snapshot"].update(equity=15000, peak_equity=15000)
    store.record_trade("alice", "r1", row, now)
    assert store.get_campaign("alice", campaign["id"])["max_drawdown_pct"] > 21


@pytest.fixture
def service(store, monkeypatch):
    from services.research import qualification

    monkeypatch.setattr(qualification, "get_store", lambda: store)
    monkeypatch.setattr(qualification, "current_binding", lambda *args, **kwargs: binding())
    monkeypatch.setattr(qualification, "_refresh_from_ledger", lambda *args: None)
    return qualification


def seed_eligible(store):
    started = datetime(2026, 8, 1, tzinfo=UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), started)
    for index in range(100):
        at = started + timedelta(days=index // 3, hours=index % 3)
        ref = f"trade{index}"
        store.register_entry("alice", 1, ref, binding(), at)
        store.record_quote("alice", ref, 1, quote(at), at)
        store.record_quote("alice", ref, 2, quote(at, "SELL"), at)
        store.record_trade("alice", ref, evidence(at, ref), at + timedelta(seconds=2))
        source_row(store, evidence(at, ref))
    return campaign["id"]


def review_payload(store, cid, **values):
    shown = store.get_campaign("alice", cid)
    return values | {
        "expected_revision": shown["revision"],
        "evidence_digest": shown["evidence_digest"],
    }


def source_row(store, row):
    from sqlalchemy.orm import Session

    from database.trading_risk_db import RiskTrade

    with Session(store.engine) as db:
        record = db.get(RiskTrade, (row["scope"], row["ref"]))
        if record is None:
            record = RiskTrade(
                scope=row["scope"],
                ref=row["ref"],
                session_day=row["session_day"],
                bucket="first",
                status=row["status"],
                planned_risk=100,
                premium=1000,
                net_pnl=row["net_pnl"],
                filled=True,
                segment="index",
                broker="sandbox",
                strategy_id=1,
                details=row["details"],
            )
            db.add(record)
        record.evidence = row["evidence"] | {"_ledger_revision": row["ledger_revision"]}
        db.commit()


def test_reviewed_release_lifecycle_and_reconnect(service, store, monkeypatch):
    cid = seed_eligible(store)
    # Adjust dataset to 30 distinct sessions without replacing production policy.
    assert service.detail("alice", cid)["qualification"]["metrics"]["closed_trade_count"] == 100
    with pytest.raises(ValueError):
        service.approve(
            "alice", cid, review_payload(store, cid, reason="reviewed", acknowledged=True)
        )
    service.reconcile(
        "alice", cid, review_payload(store, cid, reason="fills checked", costs_confirmed=True)
    )
    approved = service.approve(
        "alice",
        cid,
        review_payload(store, cid, reason="accept simulation assumptions", acknowledged=True),
    )
    assert approved["approval"]["status"] == "approved"
    assert service.live_release_reason("alice", 1, {}, "two-bucket-v1", costs()) is None
    monkeypatch.setattr(
        service, "current_binding", lambda *a, **k: binding() | {"broker_epoch": "epoch2"}
    )
    assert service.live_release_reason("alice", 1, {}, "two-bucket-v1", costs())
    monkeypatch.setattr(service, "current_binding", lambda *a, **k: binding())
    monkeypatch.setattr(service, "utcnow", lambda: datetime.now(UTC) + timedelta(days=8))
    assert service.detail("alice", cid)["approval"]["status"] == "expired"
    assert service.live_release_reason("alice", 1, {}, "two-bucket-v1", costs())
    revoked = service.revoke("alice", cid, {"reason": "withdraw release"})
    assert revoked["approval"]["status"] == "revoked"


def test_manual_entries_do_not_become_flow_evidence(service, store, monkeypatch):
    store.create_campaign("alice", 1, 4, binding(), final_run(), datetime.now(UTC))
    monkeypatch.setattr(
        service, "current_binding", lambda *a, **k: binding() | {"entry_origin": None}
    )
    with pytest.raises(ValueError):
        service.register_entry("alice", 1, "manual")
    assert store.get_registration("alice", "manual") is None


def test_api_payload_cannot_supply_pnl_or_lower_thresholds(service):
    with pytest.raises(ValueError):
        service.create_campaign("alice", {"strategy_id": 1, "final_run_id": 4, "net_pnl": 1000})
    with pytest.raises(ValueError):
        service.reconcile("alice", 1, {"reason": "checked", "costs_confirmed": True, "trades": []})


def test_out_of_order_fill_correction_cannot_restore_optimistic_price(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    store.register_entry("alice", 1, "r1", binding(), now)
    store.record_quote("alice", "r1", 1, quote(now), now)
    store.record_quote("alice", "r1", 2, quote(now, "SELL"), now)
    original = evidence(now)
    revised = deepcopy(original)
    revised["ledger_revision"] = 2
    revised["evidence"]["orders"][0]["avg_fill_price"] = 115
    store.record_trade("alice", "r1", revised, now)
    revision = store.get_campaign("alice", campaign["id"])["revision"]
    store.record_trade("alice", "r1", original, now)
    current = store.get_campaign("alice", campaign["id"])
    assert current["revision"] == revision
    assert current["trades"][0]["net_pnl"] == pytest.approx(45.65)


def test_partial_fill_mark_can_complete_without_permanent_evidence_gap(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    store.register_entry("alice", 1, "r1", binding(), now)
    store.record_quote("alice", "r1", 1, quote(now), now)
    partial = evidence(now)
    partial["status"] = "open"
    partial["broker"] = "sandbox"
    partial["evidence"]["orders"] = partial["evidence"]["orders"][:1]
    order = partial["evidence"]["orders"][0]
    order["qty"] = order.pop("quantity")
    order.update(filled_qty=5, status="open", filled_at=None)
    partial["evidence"]["mark"] = 90
    store.record_trade("alice", "r1", partial, now + timedelta(seconds=1))
    state = store.get_campaign("alice", campaign["id"])
    assert state["marks_complete"]
    # Entry cost 505.505+1, liquidation449.55-1 -> net -57.955.
    assert state["trades"][0]["marked_net"] == pytest.approx(-57.955)
    store.record_quote("alice", "r1", 2, quote(now, "SELL"), now)
    complete = evidence(now)
    complete["ledger_revision"] = 2
    store.record_trade("alice", "r1", complete, now + timedelta(seconds=2))
    state = store.get_campaign("alice", campaign["id"])
    assert state["marks_complete"] and state["trades"][0]["valid"]


def test_same_revision_with_different_fills_invalidates_evidence(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    store.register_entry("alice", 1, "r1", binding(), now)
    store.record_quote("alice", "r1", 1, quote(now), now)
    store.record_quote("alice", "r1", 2, quote(now, "SELL"), now)
    row = evidence(now)
    store.record_trade("alice", "r1", row, now)
    row["evidence"]["orders"][0]["avg_fill_price"] = 110
    store.record_trade("alice", "r1", row, now)
    assert not store.get_campaign("alice", campaign["id"])["trades"][0]["valid"]


def test_new_evidence_revokes_release_and_prior_reconciliation(service, store):
    cid = seed_eligible(store)
    service.reconcile(
        "alice", cid, review_payload(store, cid, reason="reviewed", costs_confirmed=True)
    )
    service.approve(
        "alice", cid, review_payload(store, cid, reason="accept assumptions", acknowledged=True)
    )
    now = datetime(2026, 8, 1, tzinfo=UTC)
    late = evidence(now, "trade0")
    late["ledger_revision"] = 2
    late["evidence"]["orders"][1]["avg_fill_price"] = 110
    store.record_trade("alice", "trade0", late, now + timedelta(seconds=3))
    state = service.detail("alice", cid)
    assert state["approval"]["status"] == "invalidated"
    assert state["reconciliation"]["status"] == "stale"
    assert service.live_release_reason("alice", 1, {}, "two-bucket-v1", costs())


def test_concurrent_registration_keeps_one_prospective_trade(store):
    from concurrent.futures import ThreadPoolExecutor

    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _: store.register_entry("alice", 1, "same", binding(), now), range(2)
            )
        )
    assert results[0] == results[1]
    state = store.get_campaign("alice", campaign["id"])
    assert len(state["trades"]) == 1 and state["revision"] == 1


def test_late_observation_of_older_drawdown_is_not_discarded(store):
    now = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), now)
    store.register_entry("alice", 1, "r1", binding(), now)
    store.record_quote("alice", "r1", 1, quote(now), now)
    store.record_quote("alice", "r1", 2, quote(now, "SELL"), now)
    recovered = evidence(now)
    recovered["ledger_revision"] = 2
    store.record_trade("alice", "r1", recovered, now + timedelta(seconds=2))
    older = evidence(now)
    older["budget_snapshot"]["equity"] = 8200
    store.record_trade("alice", "r1", older, now + timedelta(seconds=3))
    state = store.get_campaign("alice", campaign["id"])
    assert state["max_drawdown_pct"] >= 18
    assert state["trades"][0]["net_pnl"] == pytest.approx(185.79)


def test_missed_terminal_callback_closes_release_until_replayed(service, store):
    cid = seed_eligible(store)
    service.reconcile(
        "alice", cid, review_payload(store, cid, reason="reviewed", costs_confirmed=True)
    )
    service.approve(
        "alice", cid, review_payload(store, cid, reason="accept assumptions", acknowledged=True)
    )
    updated = evidence(datetime(2026, 8, 1, tzinfo=UTC), "trade0")
    updated["ledger_revision"] = 2
    updated["evidence"]["orders"][1]["avg_fill_price"] = 110
    source_row(store, updated)
    assert service.live_release_reason("alice", 1, {}, "two-bucket-v1", costs())
    assert not service.detail("alice", cid)["qualification"]["eligible"]
    with pytest.raises(ValueError):
        service.approve(
            "alice", cid, review_payload(store, cid, reason="accept assumptions", acknowledged=True)
        )
    with pytest.raises(ValueError):
        current = store.get_campaign("alice", cid)
        store.reconcile(
            "alice",
            cid,
            current["revision"],
            current["evidence_digest"],
            "reviewed",
            datetime.now(UTC),
        )


def test_review_cannot_acknowledge_evidence_not_shown_to_operator(service, store):
    cid = seed_eligible(store)
    stale_review = review_payload(store, cid, reason="reviewed", costs_confirmed=True)
    stale_approval = review_payload(store, cid, reason="accept assumptions", acknowledged=True)
    at = datetime(2026, 8, 1, tzinfo=UTC)
    corrected = evidence(at, "trade0")
    corrected["ledger_revision"] = 2
    corrected["evidence"]["orders"][1]["avg_fill_price"] = 110
    store.record_trade("alice", "trade0", corrected, at + timedelta(seconds=3))
    source_row(store, corrected)
    with pytest.raises(ValueError):
        service.reconcile("alice", cid, stale_review)
    service.reconcile(
        "alice", cid, review_payload(store, cid, reason="reviewed latest", costs_confirmed=True)
    )
    with pytest.raises(ValueError):
        service.approve("alice", cid, stale_approval)


def test_pending_unfilled_registration_has_no_missing_exposure_mark(store):
    at = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), at)
    store.register_entry("alice", 1, "r1", binding(), at)
    pending = evidence(at)
    pending.update(status="pending", filled=False, ledger_revision=0)
    pending["evidence"] = {}
    store.record_trade("alice", "r1", pending, at)
    assert store.get_campaign("alice", campaign["id"])["marks_complete"]


def test_bucket_stop_is_recorded_as_risk_breach(store):
    at = datetime.now(UTC)
    campaign = store.create_campaign("alice", 1, 4, binding(), final_run(), at)
    store.register_entry("alice", 1, "r1", binding(), at)
    store.record_quote("alice", "r1", 1, quote(at), at)
    store.record_quote("alice", "r1", 2, quote(at, "SELL"), at)
    row = evidence(at)
    row["budget_snapshot"]["exit_buckets"] = ["first"]
    store.record_trade("alice", "r1", row, at + timedelta(seconds=2))
    assert store.get_campaign("alice", campaign["id"])["risk_breach"]


def test_audit_capacity_cannot_prevent_immediate_revocation(service, store, monkeypatch):
    from database import strategy_qualification_db

    cid = seed_eligible(store)
    service.reconcile(
        "alice", cid, review_payload(store, cid, reason="reviewed", costs_confirmed=True)
    )
    service.approve(
        "alice", cid, review_payload(store, cid, reason="accept assumptions", acknowledged=True)
    )
    monkeypatch.setattr(strategy_qualification_db, "MAX_AUDITS", 3)
    assert (
        service.revoke("alice", cid, {"reason": "withdraw release"})["approval"]["status"]
        == "revoked"
    )
    assert (
        service.revoke("alice", cid, {"reason": "withdraw again"})["approval"]["status"]
        == "revoked"
    )
