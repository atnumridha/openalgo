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
