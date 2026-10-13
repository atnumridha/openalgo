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
