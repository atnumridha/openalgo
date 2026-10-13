from decimal import Decimal as D

from conftest import when
from test_native_entries import OWNER, isolated
from test_ownership import owned

from database import neo_desk_db as desk
from services.neo_desk.lifecycle import manage_once, recover_provider


def test_restart_stops_entries_and_preserves_protection(monkeypatch):
    rid, orders = owned(monkeypatch)
    protection = desk.view(OWNER)["protection"] | {
        "net_peak": "1300",
        "net_floor": "1050",
        "option_stop": "66.7",
    }
    desk.configure(OWNER, protection=protection)
    recover_provider()
    restored = desk.view(OWNER)
    assert restored["activation"] == "Stopped" and restored["run_id"] == rid
    assert restored["protection"]["option_stop"] == "66.7"
    manage_once(OWNER, now=when(), quote_provider=lambda *a: D(65))
    assert len(orders) == 2


def test_run_protection_survives_a_later_profile_and_trade(monkeypatch):
    from services.strategy_module import engine

    rid, orders = owned(monkeypatch)
    original = desk.view(OWNER)["protection"] | {
        "profile": "orb_controls",
        "controlled": True,
        "option_stop": "45",
        "net_peak": "1300",
        "net_floor": "1050",
    }
    desk.save_run_protection(OWNER, rid, original)
    engine.apply_fill(rid, 1, 55, False, filled_qty=65)
    manage_once(OWNER, now=when(), quote_provider=lambda *a: D(55))
    desk.configure(OWNER, profile="donchian_controls", protection={"option_stop": "99"})
    desk.db_session.remove()
    saved = desk.get_run_protection(OWNER, rid)
    assert saved["profile"] == "orb_controls" and saved["option_stop"] == "45"
    assert saved["net_floor"] == "1050"


def test_restored_older_run_is_visible_and_stops_replacement_entries(monkeypatch):
    from database import strategy_module_db as native
    from services.strategy_module import engine, state
    from services.neo_desk.lifecycle import manage_all_owned

    rid, orders = owned(monkeypatch)
    old = state.get_run_state(rid)
    engine.apply_fill(rid, 1, 55, False, filled_qty=65)
    manage_once(OWNER, now=when(), quote_provider=lambda *a: D(55))
    row = native.get_run(rid)
    row.stopped_at = None
    native.db_session.commit()
    state.hydrate_run_state(rid, old)
    desk.configure(OWNER, activation="Active", run_id=None, protection={})
    manage_all_owned(OWNER, now=when("15:29"), quote_provider=lambda *a: None)
    assert desk.view(OWNER)["activation"] == "Stopped"
    assert len(orders) == 2 and orders[-1]["action"] == "SELL"


def test_restart_rebinds_the_exact_durable_provider_run_without_a_new_order(monkeypatch):
    rid, orders = owned(monkeypatch)
    original = desk.view(OWNER)["protection"]
    desk.db_session.query(desk.NeoRunProtection).filter_by(run_id=rid).delete()
    desk.db_session.query(desk.NeoClaim).filter_by(owner=OWNER).update({"run_id": None})
    desk.db_session.commit()
    desk.configure(OWNER, run_id=None, pending=True, protection=original)
    recover_provider()
    c = desk.view(OWNER)
    assert c["activation"] == "Stopped" and c["run_id"] == rid and not c["pending"]
    assert desk.get_run_protection(OWNER, rid)["symbol"] == original["symbol"]
    assert len(orders) == 1


def test_restart_does_not_adopt_a_manual_native_run(monkeypatch):
    from database import strategy_module_db as native

    rid, orders = owned(monkeypatch)
    row = native.get_run(rid)
    row.trigger_source = "manual"
    native.db_session.commit()
    desk.db_session.query(desk.NeoRunProtection).filter_by(run_id=rid).delete()
    desk.db_session.commit()
    desk.configure(OWNER, run_id=None, pending=True)
    recover_provider()
    assert desk.view(OWNER)["run_id"] is None and desk.view(OWNER)["pending"]
    assert len(orders) == 1
