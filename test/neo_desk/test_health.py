from datetime import timedelta

from services.neo_desk.health import account_refresh
from test.neo_desk.conftest import when


def test_account_error_visible():
    previous = {
        "value": {"availabletradinglimit": "12345"},
        "observed_at": (when() - timedelta(seconds=90)).isoformat(),
    }
    result = account_refresh(previous, False, {}, when(), "Funds service unavailable")
    assert result["value"]["availabletradinglimit"] == "12345"
    assert (
        result["error"] == "Funds service unavailable"
        and result["age_seconds"] == 90
        and result["stale"]
    )


def test_readiness_follows_current_entry_mode_and_activation_without_retaining_cached_sandbox(monkeypatch):
    from services.neo_desk import health
    current = {"sandbox": False}
    config = {"mode":"sandbox", "activation":"Stopped", "status":"Stopped", "run_id":None, "pending":False}
    health.cache.clear()
    monkeypatch.setattr("database.settings_db.get_analyze_mode",lambda:current["sandbox"])
    monkeypatch.setattr("database.auth_db.get_auth_token",lambda _:None)
    monkeypatch.setattr("websocket_proxy.app_integration.proxy_status",lambda:{"alive":True})
    monkeypatch.setattr("services.neo_desk.lifecycle.management_status",lambda:{"ready":True,"message":None})
    monkeypatch.setattr(health.desk,"view",lambda _:config)
    assert health.execution_feedback("mode-fixture")["mode"] == "live"
    current["sandbox"] = True
    assert health.execution_feedback("mode-fixture")["mode"] == "sandbox"
    config["activation"] = "Active"
    assert health.execution_feedback("mode-fixture")["activation"] == "Active"
    health.cache.clear()
