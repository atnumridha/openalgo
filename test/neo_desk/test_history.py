from decimal import Decimal as D

import pytest

from database import neo_history_db as db
from services.neo_desk.history import history_page, ingest_fills

OWNER = "history-fixture"


def fill(id, side="BUY", qty=65, price="50", fees="2", time="2026-10-09T10:00:00+05:30"):
    return {
        "fill_id": id,
        "order_id": id,
        "symbol": "NIFTY13OCT2622500CE",
        "exchange": "NFO",
        "product": "NRML",
        "side": side,
        "quantity": qty,
        "price": price,
        "fees": fees,
        "time": time,
    }


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    from sqlalchemy.orm import scoped_session, sessionmaker

    from database.engine_factory import create_db_engine
    from services.neo_desk.sql_retention import MAIN_SPECS, install_journal

    engine = create_db_engine("sqlite:///" + str(tmp_path / "fills.db"))
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "db_session", session)
    db.init_db()
    install_journal(engine, [spec for spec in MAIN_SPECS if spec.table == "neo_recorded_fill"])
    yield
    session.remove()
    engine.dispose()


def test_repeat_import_is_idempotent():
    rows = [fill("a"), fill("b", "SELL", price="60", time="2026-10-09T10:30:00+05:30")]
    assert ingest_fills(OWNER, rows)["inserted"] == 2
    before = history_page(OWNER)
    assert ingest_fills(OWNER, rows)["inserted"] == 0
    assert history_page(OWNER)["summary"] == before["summary"]
    assert D(before["summary"]["gross_pnl"]) == 650 and D(before["summary"]["fees"]) == 4


def test_conflicting_id_rolls_back_the_whole_import():
    ingest_fills(OWNER, [fill("a")])
    with pytest.raises(ValueError, match="conflict"):
        ingest_fills(OWNER, [fill("b"), fill("a", price="99")])
    assert history_page(OWNER)["coverage"]["fill_count"] == 1


def test_cancelled_partial_fill_is_retained():
    ingest_fills(
        OWNER,
        [
            fill("a", qty=20) | {"status": "cancelled"},
            fill("zero", qty=0) | {"status": "cancelled"},
        ],
    )
    p = history_page(OWNER)
    assert p["coverage"]["fill_count"] == 1 and p["open_inventory"][0]["quantity"] == 20


def test_missing_opening_inventory():
    ingest_fills(OWNER, [fill("a", "SELL"), fill("b", "BUY", time="2026-10-09T11:00:00+05:30")])
    p = history_page(OWNER)
    assert p["rows"][0]["gross_pnl"] is None and p["rows"][0]["net_pnl"] is None


def test_unknown_actual_fees_are_not_zero_paid_fees():
    ingest_fills(
        OWNER,
        [
            fill("a", fees=None),
            fill("b", "SELL", price="60", fees=None, time="2026-10-09T11:00:00+05:30"),
        ],
    )
    p = history_page(OWNER)
    assert p["rows"][0]["fees"] is None and p["summary"]["actual_fees"] is None
    assert p["summary"]["estimated_fees"] is not None


def test_broker_fill_time_takes_precedence_over_order_exchange_time():
    from services.neo_desk.history import broker_rows

    raw = {"flDt": "13-Oct-2026", "flTm": "14:56:32", "exTm": "13-Oct-2026 14:55:40"}
    assert broker_rows([raw])[0]["time"] == "13-Oct-2026 14:56:32"
    assert "exTm" not in broker_rows([raw])[0]


def test_free_offer_estimate_has_zero_brokerage_but_keeps_taxes_and_does_not_claim_paid_fees():
    ingest_fills(
        OWNER,
        [
            fill("offer-buy", fees=None),
            fill("offer-sell", "SELL", price="60", fees=None, time="2026-10-09T11:00:00+05:30"),
        ],
    )
    result = history_page(OWNER, cost_plan="free_offer")
    assert D(result["fee_estimate"]["breakdown"]["brokerage"]) == 0
    assert D(result["summary"]["estimated_fees"]) > 0
    assert result["summary"]["actual_fees"] is None
    assert "assum" in result["fee_estimate"]["assumption"].lower()
    assert not result["fee_estimate"]["promotion_verified"]
    assert D(result["rows"][0]["estimated_net_pnl"]) == D("650") - D(
        result["rows"][0]["estimated_fees"]
    )
    assert result["rows"][0]["net_pnl"] is None


def test_per_trade_estimate_allocates_split_order_brokerage_by_fill_quantity():
    ingest_fills(
        OWNER,
        [
            fill("part-a", qty=20, fees=None) | {"order_id": "buy"},
            fill("part-b", qty=45, fees=None) | {"order_id": "buy"},
            fill("exit", "SELL", fees=None, price="60", time="2026-10-09T11:00:00+05:30"),
        ],
    )
    result = history_page(OWNER, cost_plan="trade_free")
    assert D(result["fee_estimate"]["breakdown"]["brokerage"]) == 20
    assert sum(D(row["estimated_fees"]) for row in result["rows"]) == D(
        result["summary"]["estimated_fees"]
    )


def test_date_scope_charges_and_matching_are_explicit_and_cancelled_unfilled_orders_excluded():
    ingest_fills(
        OWNER,
        [
            fill("yesterday", fees=None, time="2026-10-08T11:00:00+05:30"),
            fill("today", fees=None),
            fill("cancelled", qty=0, fees=None),
        ],
    )
    result = history_page(OWNER, start="2026-10-09", end="2026-10-09", cost_plan="free_offer")
    assert result["fee_estimate"]["fill_count"] == 1
    assert result["fee_estimate"]["executed_order_count"] == 1
    assert result["fee_estimate"]["recorded_dates"] == ["2026-10-09"]


def test_unknown_fee_plan_is_rejected():
    with pytest.raises(ValueError, match="fee plan"):
        history_page(OWNER, cost_plan="made_up")


def test_same_batch_duplicate_fill_is_recorded_once():
    result = ingest_fills(OWNER, [fill("same-batch"), fill("same-batch")])
    assert result["inserted"] == 1 and result["duplicates"] == 1


def test_capture_failure_is_not_reported_as_empty_success(monkeypatch):
    from services.neo_desk.history import refresh_history

    monkeypatch.setattr("database.auth_db.get_auth_token", lambda owner: "fixture-auth")
    monkeypatch.setattr(
        "broker.kotak.api.order_api.get_trade_book",
        lambda auth: {"stat": "Not_Ok", "emsg": "Session expired"},
    )
    with pytest.raises(ValueError, match="unavailable"):
        refresh_history(OWNER)


def test_live_reports_retain_executions_after_primary_record_removal():
    ingest_fills(
        OWNER,
        [
            fill("retained-entry"),
            fill("retained-exit", "SELL", price="60", time="2026-10-09T11:00:00+05:30"),
        ],
    )
    db.db_session.query(db.NeoFill).filter_by(owner=OWNER).delete()
    db.db_session.commit()
    assert D(history_page(OWNER)["summary"]["gross_pnl"]) == 650


def test_concurrent_duplicate_capture_is_idempotent():
    from concurrent.futures import ThreadPoolExecutor

    def capture(_):
        try:
            return ingest_fills(OWNER, [fill("concurrent")])
        finally:
            db.db_session.remove()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(capture, range(2)))
    assert sum(r["inserted"] for r in results) == 1
    assert history_page(OWNER)["coverage"]["fill_count"] == 1


def test_mixed_exchange_estimates_and_net_are_persisted_without_inventing_paid_fees():
    rows = [
        fill("nse-buy", fees=None),
        fill("nse-sell", "SELL", price="60", fees=None, time="2026-10-09T11:00:00+05:30"),
    ]
    rows += [
        {
            **r,
            "fill_id": "bse-" + r["fill_id"],
            "order_id": "bse-" + r["order_id"],
            "symbol": "SENSEX22OCT2674000CE",
            "exchange": "bse_fo",
        }
        for r in rows
    ]
    ingest_fills(OWNER, rows)
    result = history_page(OWNER, cost_plan="trade_free")
    assert result["summary"]["estimated_net_pnl"] is not None
    assert all(r["estimated_fees"] is not None for r in result["rows"])
    assert result["summary"]["actual_fees"] is None
    assert result["summary"]["net_pnl"] is None
    assert result["fee_estimate"]["storage"] == "SQL saved estimate"
    saved_at = result["fee_estimate"]["calculated_at"]
    # A new DB session must load the saved estimate, rather than losing it on restart.
    db.db_session.remove()
    assert history_page(OWNER, cost_plan="trade_free")["fee_estimate"]["calculated_at"] == saved_at
    assert history_page("another-owner")["summary"]["fill_count"] == 0


def test_net_estimate_summary_includes_all_pages_and_excludes_unresolved_matches():
    rows = []
    for i in range(55):
        rows += [
            fill(f"b-{i}", fees=None, time=f"2026-10-09T10:{i:02}:00+05:30"),
            fill(f"s-{i}", "SELL", price="60", fees=None, time=f"2026-10-09T10:{i:02}:30+05:30"),
        ]
    rows += [
        {
            **fill("unresolved-sell", "SELL", fees=None, time="2026-10-09T11:00:00+05:30"),
            "symbol": "NIFTY13OCT2622550PE",
        },
        {
            **fill("unresolved-buy", fees=None, time="2026-10-09T11:01:00+05:30"),
            "symbol": "NIFTY13OCT2622550PE",
        },
        fill("ambiguous-a", qty=20, fees=None, time="2026-10-09T12:00:00+05:30"),
        fill("ambiguous-b", qty=45, price="51", fees=None, time="2026-10-09T12:00:00+05:30"),
        fill("ambiguous-exit", "SELL", price="60", fees=None, time="2026-10-09T12:01:00+05:30"),
    ]
    ingest_fills(OWNER, rows)
    result = history_page(OWNER)
    remaining = history_page(OWNER, cursor=50)["rows"]
    unresolved = [r for r in remaining if r["gross_pnl"] is None]
    assert len(unresolved) == 3 and all(r["estimated_net_pnl"] is None for r in unresolved)
    assert len(result["rows"]) == 50 and result["summary"]["estimated_net_known_count"] == 55
    assert D(result["summary"]["estimated_net_pnl"]) == sum(
        D(r["estimated_net_pnl"]) for r in result["rows"]
    ) + sum(D(r["estimated_net_pnl"]) for r in remaining if r["estimated_net_pnl"] is not None)


def test_default_report_uses_account_notice_and_retains_snapshot_after_new_fills():
    ingest_fills(
        OWNER,
        [
            fill("before", fees=None, time="2026-10-21T10:00:00+05:30"),
            fill("after", fees=None, time="2026-10-22T10:00:00+05:30"),
        ],
    )
    first = history_page(OWNER)
    assert first["fee_estimate"]["cost_plan"] == "account"
    assert D(first["fee_estimate"]["breakdown"]["brokerage"]) == 10
    ingest_fills(OWNER, [fill("later", fees=None, time="2026-10-22T11:00:00+05:30")])
    second = history_page(OWNER)
    assert D(second["fee_estimate"]["breakdown"]["brokerage"]) == 20
    assert second["fee_estimate"]["input_hash"] != first["fee_estimate"]["input_hash"]


def test_saved_fee_estimates_are_separate_for_owner_mode_and_plan():
    from services.neo_desk.fee_history import saved_charge_estimate
    from services.neo_desk.fees import FeePlan
    from services.neo_desk.history import NativeAccounting

    ingest_fills(OWNER, [fill("one", fees=None)])
    fills = NativeAccounting(OWNER).fills()
    paid = saved_charge_estimate(OWNER, "live", fills, FeePlan(brokerage=D(10)), "trade_free")
    free = saved_charge_estimate(OWNER, "live", fills, FeePlan(brokerage=D(0)), "free_offer")
    sandbox = saved_charge_estimate(OWNER, "sandbox", [], FeePlan(brokerage=D(10)), "trade_free")
    assert paid["breakdown"]["brokerage"] == "10.00"
    assert free["breakdown"]["brokerage"] == "0.00"
    assert sandbox["fill_count"] == 0
    assert db.db_session.query(db.NeoFeeEstimate).filter_by(owner=OWNER).count() == 3
    db.db_session.remove()
    assert (
        saved_charge_estimate(OWNER, "live", fills, FeePlan(brokerage=D(10)), "trade_free") == paid
    )
