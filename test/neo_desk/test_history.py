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
def isolated():
    db.init_db()
    db.db_session.query(db.NeoFill).filter_by(owner=OWNER).delete()
    db.db_session.commit()
    yield
    db.db_session.query(db.NeoFill).filter_by(owner=OWNER).delete()
    db.db_session.commit()
    db.db_session.remove()


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
    ingest_fills(OWNER, [fill("offer-buy", fees=None), fill("offer-sell", "SELL", price="60", fees=None, time="2026-10-09T11:00:00+05:30")])
    result = history_page(OWNER, cost_plan="free_offer")
    assert D(result["fee_estimate"]["breakdown"]["brokerage"]) == 0
    assert D(result["summary"]["estimated_fees"]) > 0
    assert result["summary"]["actual_fees"] is None
    assert "assum" in result["fee_estimate"]["assumption"].lower()
    assert not result["fee_estimate"]["promotion_verified"]
    assert D(result["rows"][0]["estimated_net_pnl"]) == D("650") - D(result["rows"][0]["estimated_fees"])
    assert result["rows"][0]["net_pnl"] is None


def test_per_trade_estimate_allocates_split_order_brokerage_by_fill_quantity():
    ingest_fills(OWNER, [fill("part-a", qty=20, fees=None) | {"order_id": "buy"}, fill("part-b", qty=45, fees=None) | {"order_id": "buy"}, fill("exit", "SELL", fees=None, price="60", time="2026-10-09T11:00:00+05:30")])
    result = history_page(OWNER, cost_plan="trade_free")
    assert D(result["fee_estimate"]["breakdown"]["brokerage"]) == 20
    assert sum(D(row["estimated_fees"]) for row in result["rows"]) == D(result["summary"]["estimated_fees"])


def test_date_scope_charges_and_matching_are_explicit_and_cancelled_unfilled_orders_excluded():
    ingest_fills(OWNER, [fill("yesterday", fees=None, time="2026-10-08T11:00:00+05:30"), fill("today", fees=None), fill("cancelled", qty=0, fees=None)])
    result = history_page(OWNER, start="2026-10-09", end="2026-10-09", cost_plan="free_offer")
    assert result["fee_estimate"]["fill_count"] == 1
    assert result["fee_estimate"]["executed_order_count"] == 1
    assert result["fee_estimate"]["recorded_dates"] == ["2026-10-09"]


def test_unknown_fee_plan_is_rejected():
    with pytest.raises(ValueError, match="fee plan"):
        history_page(OWNER, cost_plan="made_up")
