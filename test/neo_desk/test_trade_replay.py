import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from database import neo_history_db as db
from services.neo_desk.chart_archive import ChartArchive
from services.neo_desk.history import NativeAccounting, ingest_fills
from services.neo_desk.sql_retention import MAIN_SPECS, install_journal
from services.neo_desk.trade_replay import trade_replay


@pytest.fixture
def archive(tmp_path, monkeypatch):
    import services.neo_desk.trade_replay as replay

    engine = create_engine("sqlite:///" + str(tmp_path / "replay.db"))
    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "db_session", session)
    db.init_db()
    install_journal(
        engine, [s for s in MAIN_SPECS if s.table in ("neo_recorded_fill", "neo_research_job")]
    )
    archive = ChartArchive(engine)
    monkeypatch.setattr(replay, "get_archive", lambda: archive)
    yield archive
    session.remove()
    engine.dispose()


def fill(identity, side, stamp, price="50", owner="owner"):
    return {
        "fill_id": identity,
        "order_id": identity,
        "symbol": "NIFTY19OCT2622200PE",
        "exchange": "NFO",
        "product": "NRML",
        "side": side,
        "quantity": 65,
        "price": price,
        "fees": None,
        "time": stamp,
    }


def pair():
    ingest_fills(
        "owner",
        [
            fill("a", "BUY", "2026-10-14T10:00:12+05:30"),
            fill("b", "SELL", "2026-10-14T10:02:25+05:30", "60"),
        ],
    )
    rows, _ = NativeAccounting("owner")._match(NativeAccounting("owner").fills())
    return rows[0]["trade_id"]


def candles(archive, missing=False):
    stamp = int(datetime.fromisoformat("2026-10-14T10:00:00+05:30").timestamp())
    bars = [
        {"timestamp": stamp + i * 60, "open": 50, "high": 62, "low": 49, "close": 60, "volume": 100}
        for i in range(3)
        if not (missing and i == 1)
    ]
    archive.save("NIFTY19OCT2622200PE", "NFO", "1m", bars)
    return stamp


def test_recorded_prices_and_times_survive_chart_restart_without_broker(archive, monkeypatch):
    identity = pair()
    candles(archive)
    result = trade_replay("owner", identity, fetch=False)
    assert result["trade"]["entry_price"] == "50" and result["trade"]["exit_price"] == "60"
    assert result["coverage"]["complete"] and len(result["trade"]["option_bars"]) == 3
    assert result["trade"]["initial_option_stop"] is None and not result["trade"]["trail"]
    assert any("not recorded" in n for n in result["coverage"]["gaps"])
    # A complete replay no longer depends on the market-data provider or candles table.
    with archive.engine.begin() as c:
        c.execute(text("DELETE FROM neo_chart_candle"))
    archive.engine.dispose()
    assert trade_replay("owner", identity, fetch=False) == result


def test_replay_cannot_access_another_owner_or_mode(archive):
    identity = pair()
    candles(archive)
    with pytest.raises(ValueError, match="account"):
        trade_replay("foreign", identity, fetch=False)
    with pytest.raises(ValueError, match="Choose"):
        trade_replay("owner", identity, mode="demo", fetch=False)


def test_missing_minutes_stay_missing_and_can_be_enriched(archive):
    identity = pair()
    candles(archive, missing=True)
    result = trade_replay("owner", identity, fetch=False)
    assert not result["coverage"]["complete"] and len(result["trade"]["option_bars"]) == 2
    assert any("1 option minutes" in n for n in result["coverage"]["gaps"])
    candles(archive)
    assert trade_replay("owner", identity, fetch=False)["coverage"]["complete"]


def test_empty_or_expired_history_keeps_fill_facts_without_fictional_chart(archive):
    identity = pair()
    result = trade_replay("owner", identity, fetch=False)
    assert not result["coverage"]["complete"] and result["trade"]["option_bars"] == []
    assert datetime.fromisoformat(result["trade"]["entry_time"]) == datetime.fromisoformat(
        "2026-10-14T10:00:12+05:30"
    )


def test_zero_filled_cancelled_order_cannot_be_replayed(archive):
    ingest_fills("owner", [dict(fill("cancelled", "BUY", "2026-10-14T10:00:00+05:30"), quantity=0)])
    with pytest.raises(ValueError, match="account"):
        trade_replay("owner", "cancelled", fetch=False)


def test_actual_protection_is_bound_to_owner_mode_order_and_recorded_time(archive):
    identity = pair()
    stamp = candles(archive)

    def journal(
        c, owner, source, key, payload, mode="live", at="2026-10-14T04:31:20+00:00", kind="insert"
    ):
        c.execute(
            text(
                "INSERT INTO neo_sql_journal(owner,mode,source_table,source_key,change_kind,occurred_at,trading_date,recorded_at,payload) VALUES(:owner,:mode,:source,:key,:kind,:at,'2026-10-14',:at,:payload)"
            ),
            {
                "owner": owner,
                "mode": mode,
                "source": source,
                "key": key,
                "kind": kind,
                "at": at,
                "payload": json.dumps(payload),
            },
        )

    with archive.engine.begin() as c:
        journal(
            c,
            "owner",
            "sm_strategy_order",
            "1",
            {
                "run_id": 3,
                "broker_order_id": "a",
                "symbol": "NIFTY19OCT2622200PE",
                "exchange": "NFO",
            },
        )
        journal(
            c,
            "foreign",
            "neo_run_protection",
            "3",
            {"run_id": 3, "protection": {"option_stop": "999"}},
        )
        journal(
            c,
            "owner",
            "neo_run_protection",
            "3",
            {
                "run_id": 3,
                "protection": {
                    "option_stop": "45",
                    "option_target": "80",
                    "index_stop": "22000",
                    "profile": "orb_controls",
                },
            },
        )
        journal(
            c,
            "owner",
            "neo_run_protection",
            "3",
            {"run_id": 3, "protection": {"option_stop": "99"}},
            at="2026-10-14T05:00:00+00:00",
            kind="update",
        )
    result = trade_replay("owner", identity, fetch=False)
    assert result["trade"]["trail"] == [
        {
            "time": stamp + 80,
            "option_stop": "45",
            "option_target": "80",
            "index_stop": "22000",
            "index_target": None,
            "index_reference": None,
            "net_floor": None,
        }
    ]


def test_saved_backtest_metadata_and_deleted_result_remain_owner_bound(archive):
    from services.neo_desk.research_jobs import get_job, saved_jobs

    db.db_session.add(
        db.NeoResearchJob(
            id="saved",
            owner="owner",
            status="complete",
            request={
                "request_id": "neo-compare:5:fixture",
                "profile": "orb_trail",
                "start": "2026-10-14",
                "end": "2026-10-14",
                "expiry": "2026-10-19",
            },
            result={"profile": "orb_trail", "trades": [{"option_bars": [{"time": 5}]}]},
        )
    )
    db.db_session.commit()
    assert saved_jobs("owner")[0]["id"] == "saved" and "result" not in saved_jobs("owner")[0]
    assert saved_jobs("foreign") == []
    db.db_session.query(db.NeoResearchJob).filter_by(id="saved").delete()
    db.db_session.commit()
    assert get_job("owner", "saved")["result"]["trades"][0]["option_bars"][0]["time"] == 5
    with pytest.raises(ValueError):
        get_job("foreign", "saved")


def test_broker_exchange_and_option_symbol_resolve_to_native_chart_without_rewriting_fills(
    archive, monkeypatch
):
    from database import token_db

    monkeypatch.setattr(
        token_db,
        "get_oa_symbol",
        lambda symbol, exchange: (
            "NIFTY19OCT2622200PE" if (symbol, exchange) == ("NIFTY26O1922200PE", "NFO") else None
        ),
    )
    ingest_fills(
        "owner",
        [
            {
                **fill("a", "BUY", "2026-10-14T10:00:12+05:30"),
                "symbol": "NIFTY26O1922200PE",
                "exchange": "nse_fo",
            },
            {
                **fill("b", "SELL", "2026-10-14T10:02:25+05:30", "60"),
                "symbol": "NIFTY26O1922200PE",
                "exchange": "nse_fo",
            },
        ],
    )
    candles(archive)
    rows, _ = NativeAccounting("owner")._match(NativeAccounting("owner").fills())
    result = trade_replay("owner", rows[0]["trade_id"], fetch=False)
    assert len(result["trade"]["option_bars"]) == 3 and result["coverage"]["complete"]
    assert result["trade"]["symbol"] == "NIFTY26O1922200PE"
    assert NativeAccounting("owner").fills()[0]["exchange"] == "nse_fo"
