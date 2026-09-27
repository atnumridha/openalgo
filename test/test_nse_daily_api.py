"""Archive UI may download public data, but cannot cross into trading/replay."""

from datetime import date

import httpx
import pytest
from flask import Flask
from test_nse_daily_archive import bundle
from test_trading_research_api import login

from blueprints import trading_research
from services.research import nse_archive, nse_archive_jobs


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(nse_archive, "ROOT", tmp_path)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="nse-test")
    app.register_blueprint(trading_research.trading_research_bp)
    yield app.test_client(), tmp_path


def test_archive_requires_session_for_reads_and_download_actions(api):
    client, _ = api
    assert client.get("/strategy/api/research/daily-options").status_code == 401
    assert client.post("/strategy/api/research/daily-options", json={}).status_code == 401


def test_daily_archive_is_available_without_a_research_dataset(api):
    client, root = api
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=bundle()))
    ) as http:
        nse_archive.sync(root, date(2026, 9, 25), date(2026, 9, 25), client=http, delay=0)
    login(client)
    result = client.get("/strategy/api/research/daily-options")
    assert result.status_code == 200
    assert result.json["data"]["session_count"] == 1
    assert result.json["data"]["intraday_eligible"] is False
    export = client.get(
        "/strategy/api/research/daily-options/export?session=2026-09-25&symbol=NIFTY"
    )
    assert export.status_code == 200
    assert b"settlement" in export.data
    assert b"NIFTY" in export.data
    assert "attachment" in export.headers["Content-Disposition"]


def test_download_request_does_not_accept_arbitrary_urls_paths_or_dates(api):
    client, _ = api
    login(client)
    response = client.post(
        "/strategy/api/research/daily-options",
        json={"url": "http://localhost:5555", "output": "/tmp/other"},
    )
    assert response.status_code == 400
    assert (
        client.get("/strategy/api/research/daily-options/export?session=../../x").status_code == 400
    )


def test_previous_session_query_never_uses_same_day(api):
    client, root = api
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=bundle()))
    ) as http:
        nse_archive.sync(root, date(2026, 9, 25), date(2026, 9, 25), client=http, delay=0)
    login(client)
    response = client.get(
        "/strategy/api/research/daily-options/snapshot?before=2026-09-25&symbol=NIFTY"
    )
    assert response.json["data"]["session"] is None


def test_worker_exit_before_manifest_write_is_visible_as_failure(api, monkeypatch):
    from concurrent.futures import Future

    client, _ = api
    exited = Future()
    exited.set_result(1)
    monkeypatch.setattr(nse_archive_jobs, "_future", exited)
    login(client)
    result = client.get("/strategy/api/research/daily-options")
    assert result.json["data"]["status"] == "failed"
    assert result.json["data"]["message"]


@pytest.mark.parametrize("new_status", ["running", "completed"])
@pytest.mark.parametrize("outcome", ["exit", "exception"])
def test_previous_ui_failure_does_not_mask_a_newer_cli_run(api, monkeypatch, new_status, outcome):
    from concurrent.futures import Future

    client, _ = api
    exited = Future()
    if outcome == "exit":
        exited.set_result(1)
    else:
        exited.set_exception(OSError("worker could not start"))
    monkeypatch.setattr(nse_archive_jobs, "_future", exited)
    monkeypatch.setattr(nse_archive_jobs, "_requested_at", 100, raising=False)
    monkeypatch.setattr(
        nse_archive,
        "status",
        lambda root: {
            "status": new_status,
            "updated_at": "1970-01-01T00:03:20+00:00",
            "error_count": 0,
        },
    )
    login(client)
    result = client.get("/strategy/api/research/daily-options")
    assert result.json["data"]["status"] == new_status


def test_new_worker_failure_is_visible_even_when_old_history_exists(api, monkeypatch):
    from concurrent.futures import Future

    client, _ = api
    exited = Future()
    exited.set_result(1)
    monkeypatch.setattr(nse_archive_jobs, "_future", exited)
    monkeypatch.setattr(nse_archive_jobs, "_requested_at", 200, raising=False)
    monkeypatch.setattr(
        nse_archive,
        "status",
        lambda root: {
            "status": "completed",
            "updated_at": "1970-01-01T00:01:40+00:00",
            "error_count": 0,
        },
    )
    login(client)
    result = client.get("/strategy/api/research/daily-options")
    assert result.json["data"]["status"] == "failed"
