"""The operational repair fails closed and is idempotent."""
from types import SimpleNamespace

import pytest

from upgrade import repair_orphan_flows as repair


def setup_repair(monkeypatch, count=0):
    from database import strategy_module_db

    monkeypatch.setattr(strategy_module_db, "SmStrategyRun", SimpleNamespace(
        query=SimpleNamespace(filter_by=lambda **kw: SimpleNamespace(count=lambda: count))))


def test_repair_refuses_open_runs(monkeypatch):
    setup_repair(monkeypatch, count=1)
    monkeypatch.setattr(repair, "backup_database", lambda _: pytest.fail("must not back up/apply"))
    with pytest.raises(RuntimeError, match="active strategy runs"):
        repair.repair_orphans("unused")


def test_repair_noop_after_orphans_removed(monkeypatch):
    setup_repair(monkeypatch)
    monkeypatch.setattr(repair, "inspect_orphans", lambda: [])
    monkeypatch.setattr(repair, "backup_database", lambda _: pytest.fail("no unnecessary backup"))
    assert repair.repair_orphans("unused") == {"disabled": [], "backup": None}


def test_repair_retains_backup_and_reports_teardown_failure(monkeypatch, tmp_path):
    from services import flow_lifecycle_service

    setup_repair(monkeypatch)
    monkeypatch.setattr(repair, "inspect_orphans", lambda: [{"id": 4}])
    backup = tmp_path / "verified.db"
    monkeypatch.setattr(repair, "backup_database", lambda _: backup)
    monkeypatch.setattr(flow_lifecycle_service, "deactivate_workflow", lambda _: ({"error": "teardown failed"}, 500))
    with pytest.raises(RuntimeError, match="teardown failed"):
        repair.repair_orphans(tmp_path)
    assert '"disabled": []' in backup.with_suffix(".json").read_text()
