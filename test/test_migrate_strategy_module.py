"""Regression tests for the strategy-module schema migration."""

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import JSON, Boolean, Column, Integer, MetaData, String, Table, inspect

from database.engine_factory import create_db_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upgrade"))

import migrate_strategy_module as migration  # noqa: E402

OLD_SCHEMA_STAGES = (
    "initial",
    "product_release",
    "interrupted_after_position",
    "interrupted_after_stop_timestamp",
    "missing_index_only",
)


def _legacy_strategy_engine(tmp_path, stage="initial"):
    """Build a populated database at one plausible prior migration stage."""
    stage_number = OLD_SCHEMA_STAGES.index(stage)
    engine = create_db_engine(f"sqlite:///{(tmp_path / f'{stage}.db').as_posix()}")

    run_columns = ["id INTEGER PRIMARY KEY", "strategy_id INTEGER NOT NULL"]
    order_columns = [
        "id INTEGER PRIMARY KEY",
        "run_id INTEGER NOT NULL",
        "leg_id INTEGER NOT NULL",
        "kind VARCHAR(30) NOT NULL",
    ]
    if stage_number >= 1:
        order_columns.append("product VARCHAR(10)")
    if stage_number >= 2:
        order_columns.append("position_ref VARCHAR(32)")
    if stage_number >= 3:
        run_columns.append("stop_requested_at DATETIME")
    if stage_number >= 4:
        run_columns.append("stop_requested_reason VARCHAR(30)")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE sm_strategy (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
        )
        connection.exec_driver_sql(f"CREATE TABLE sm_strategy_run ({', '.join(run_columns)})")
        connection.exec_driver_sql(f"CREATE TABLE sm_strategy_order ({', '.join(order_columns)})")
        connection.exec_driver_sql("INSERT INTO sm_strategy VALUES (1, 'keep-strategy')")

        run_insert_columns = ["id", "strategy_id"]
        run_insert_values = ["1", "1"]
        if stage_number >= 3:
            run_insert_columns.append("stop_requested_at")
            run_insert_values.append("'2026-08-30 21:55:00'")
        if stage_number >= 4:
            run_insert_columns.append("stop_requested_reason")
            run_insert_values.append("'operator'")
        connection.exec_driver_sql(
            f"INSERT INTO sm_strategy_run ({', '.join(run_insert_columns)}) "
            f"VALUES ({', '.join(run_insert_values)})"
        )

        order_insert_columns = ["id", "run_id", "leg_id", "kind"]
        order_insert_values = ["1", "1", "7", "'entry'"]
        if stage_number >= 1:
            order_insert_columns.append("product")
            order_insert_values.append("'NRML'")
        if stage_number >= 2:
            order_insert_columns.append("position_ref")
            order_insert_values.append("'position-7'")
        connection.exec_driver_sql(
            f"INSERT INTO sm_strategy_order ({', '.join(order_insert_columns)}) "
            f"VALUES ({', '.join(order_insert_values)})"
        )

    return engine


def _column_details(engine, table):
    return {column["name"]: column for column in inspect(engine).get_columns(table)}


def _original_row_snapshot(engine):
    """Read only facts that existed before any runtime-safety migration."""
    with engine.connect() as connection:
        return {
            "strategy": connection.exec_driver_sql(
                "SELECT id, marker FROM sm_strategy ORDER BY id"
            ).all(),
            "run": connection.exec_driver_sql(
                "SELECT id, strategy_id FROM sm_strategy_run ORDER BY id"
            ).all(),
            "order": connection.exec_driver_sql(
                "SELECT id, run_id, leg_id, kind FROM sm_strategy_order ORDER BY id"
            ).all(),
        }


def _schema_snapshot(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name LIKE 'sm_%' ORDER BY type, name"
        ).all()


@pytest.mark.parametrize("stage", OLD_SCHEMA_STAGES)
def test_apply_upgrades_every_populated_old_stage_idempotently(tmp_path, stage):
    """Each released or interrupted old shape keeps its rows and stored truth."""
    engine = _legacy_strategy_engine(tmp_path, stage)
    try:
        before = _original_row_snapshot(engine)

        assert migration.apply(engine)
        first_schema = _schema_snapshot(engine)
        assert migration.apply(engine)

        run_columns = _column_details(engine, "sm_strategy_run")
        order_columns = _column_details(engine, "sm_strategy_order")
        strategy_columns = _column_details(engine, "sm_strategy")
        assert strategy_columns.keys() >= {
            "automation_state", "automation_state_reason", "automation_state_updated_at"
        }
        with engine.connect() as connection:
            state = connection.exec_driver_sql(
                "SELECT automation_state FROM sm_strategy WHERE id = 1"
            ).scalar_one()
        assert state == "disabled"
        assert order_columns.keys() >= {"product", "position_ref"}
        assert run_columns.keys() >= {"stop_requested_at", "stop_requested_reason"}
        assert order_columns["product"]["nullable"] is True
        assert order_columns["position_ref"]["nullable"] is True
        assert run_columns["stop_requested_at"]["nullable"] is True
        assert run_columns["stop_requested_reason"]["nullable"] is True

        indexes = {item["name"]: item for item in inspect(engine).get_indexes("sm_strategy_order")}
        assert indexes["ix_sm_order_run_leg_position"]["column_names"] == [
            "run_id",
            "leg_id",
            "position_ref",
        ]
        assert indexes["ix_sm_order_run_leg_position"]["unique"] == 0
        assert _original_row_snapshot(engine) == before
        assert _schema_snapshot(engine) == first_schema
        assert "sm_automation_event" in inspect(engine).get_table_names()
        assert "sm_risk_reservation" in inspect(engine).get_table_names()

        with engine.connect() as connection:
            migrated_order = connection.exec_driver_sql(
                "SELECT product, position_ref FROM sm_strategy_order WHERE id = 1"
            ).one()
            migrated_run = connection.exec_driver_sql(
                "SELECT stop_requested_at, stop_requested_reason FROM sm_strategy_run WHERE id = 1"
            ).one()

        assert migrated_order.product == (None if stage == "initial" else "NRML")
        assert migrated_order.position_ref == (
            "position-7" if OLD_SCHEMA_STAGES.index(stage) >= 2 else None
        )
        assert migrated_run.stop_requested_at == (
            "2026-08-30 21:55:00" if OLD_SCHEMA_STAGES.index(stage) >= 3 else None
        )
        assert migrated_run.stop_requested_reason == (
            "operator" if OLD_SCHEMA_STAGES.index(stage) >= 4 else None
        )
    finally:
        engine.dispose()


def test_migration_preserves_existing_automation_state_on_repeated_runs(tmp_path):
    engine = _legacy_strategy_engine(tmp_path)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE sm_strategy ADD COLUMN automation_state "
                "VARCHAR(20) NOT NULL DEFAULT 'disabled'"
            )
            connection.exec_driver_sql(
                "ALTER TABLE sm_strategy ADD COLUMN automation_state_reason TEXT"
            )
            connection.exec_driver_sql(
                "ALTER TABLE sm_strategy ADD COLUMN automation_state_updated_at DATETIME"
            )
            connection.exec_driver_sql(
                "UPDATE sm_strategy SET automation_state = 'close_failed', "
                "automation_state_reason = 'broker rejected exit', "
                "automation_state_updated_at = '2026-09-25 09:30:00' WHERE id = 1"
            )

        assert migration.apply(engine)
        assert migration.apply(engine)
        with engine.connect() as connection:
            state = connection.exec_driver_sql(
                "SELECT automation_state, automation_state_reason, "
                "automation_state_updated_at FROM sm_strategy WHERE id = 1"
            ).one()
        assert tuple(state) == (
            "close_failed", "broker rejected exit", "2026-09-25 09:30:00"
        )
    finally:
        engine.dispose()


def test_status_reports_changes_without_modifying_the_database(tmp_path, capsys):
    """Status is a read-only preview even on a populated prior release."""
    engine = _legacy_strategy_engine(tmp_path, "product_release")
    try:
        before_schema = _schema_snapshot(engine)
        before_rows = _original_row_snapshot(engine)

        assert migration.status(engine) is False

        output = capsys.readouterr().out
        assert "sm_strategy_order.position_ref" in output
        assert "sm_strategy_run.stop_requested_at" in output
        assert "sm_strategy_run.stop_requested_reason" in output
        assert "ix_sm_order_run_leg_position" in output
        assert _schema_snapshot(engine) == before_schema
        assert _original_row_snapshot(engine) == before_rows
    finally:
        engine.dispose()


def test_relative_sqlite_path_is_resolved_from_project_root(tmp_path, monkeypatch):
    """The documented upgrade-directory invocation still targets the app DB."""
    monkeypatch.setattr(migration, "PROJECT_ROOT", str(tmp_path))

    resolved = migration.resolve_sqlite_path("sqlite:///db/openalgo.db")

    expected = f"sqlite:///{(tmp_path / 'db' / 'openalgo.db').as_posix()}"
    assert resolved == expected


def test_native_absolute_sqlite_path_is_not_rewritten(tmp_path):
    """Native absolute paths remain valid on both Windows and Linux runners."""
    absolute_url = f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}"

    assert migration.resolve_sqlite_path(absolute_url) == absolute_url


@pytest.mark.skipif(os.name != "nt", reason="Windows path contract")
def test_windows_drive_sqlite_path_is_not_rewritten():
    assert migration.resolve_sqlite_path("sqlite:///D:/OpenAlgo/db/openalgo.db") == (
        "sqlite:///D:/OpenAlgo/db/openalgo.db"
    )


@pytest.mark.skipif(os.name == "nt", reason="Linux path contract")
def test_linux_rooted_sqlite_path_is_not_rewritten():
    assert migration.resolve_sqlite_path("sqlite:////var/lib/openalgo/openalgo.db") == (
        "sqlite:////var/lib/openalgo/openalgo.db"
    )


def _backfill_engine(tmp_path, case="safe"):
    engine = _legacy_strategy_engine(tmp_path)
    with engine.begin() as connection:
        for column, ddl in (
            ("user_id", "TEXT DEFAULT 'alice'"),
            ("strategy_kind", "TEXT DEFAULT 'signal'"),
            ("live_enabled", "BOOLEAN DEFAULT FALSE"),
            ("broker_connection_id", "TEXT DEFAULT 'connection-1'"),
            ("created_at", "DATETIME DEFAULT '2026-09-01 09:30:00'"),
        ):
            connection.exec_driver_sql(f"ALTER TABLE sm_strategy ADD COLUMN {column} {ddl}")
        if case == "live_strategy":
            connection.exec_driver_sql("UPDATE sm_strategy SET live_enabled = TRUE")
        if case == "batch":
            connection.exec_driver_sql("UPDATE sm_strategy SET strategy_kind = 'batch'")
    workflows = Table(
        "flow_workflows", MetaData(), Column("id", Integer, primary_key=True),
        Column("nodes", JSON), Column("is_active", Boolean),
        Column("broker_connection_id", String),
    )
    workflows.create(engine)
    node = {"id": "run", "type": "strategyModuleRun", "data": {
        "strategyId": "1" if case == "string_id" else 1,
        "brokerOwner": "bob" if case == "foreign_owner" else "alice",
        "mode": "live" if case == "live_workflow" else "sandbox",
    }}
    nodes = [node]
    if case == "customized":
        nodes.append({"id": "custom-filter", "type": "condition", "data": {"value": 42}})
    if case == "duplicate_nodes":
        nodes.append(dict(node, id="second-run"))
    if case in {"malformed_list_type", "malformed_dict_type"}:
        nodes.insert(0, {"type": [] if case == "malformed_list_type" else {}, "data": {}})
    if case.startswith("protective_"):
        node["type"] = "strategySignal"
        node["data"]["action"] = "long_entry"
        exits = [{"id": f"exit-{index}", "type": "strategySignal",
                  "data": {**node["data"], "action": "long_exit"}} for index in (1, 2)]
        nodes.extend(exits)
        if case == "protective_exit_only":
            nodes.remove(node)
        if case == "protective_multiple_entries":
            exits[0]["data"]["action"] = "short_entry"
        if case == "protective_shared_exit":
            exits[0]["data"]["strategyId"] = 99
        if case == "protective_live_exit":
            exits[0]["data"]["mode"] = "live"
        if case == "protective_foreign_exit":
            exits[0]["data"]["brokerOwner"] = "bob"
        if case == "protective_invalid_exit":
            exits[0]["data"]["action"] = "buy"
    with engine.begin() as connection:
        if case != "missing":
            connection.execute(workflows.insert(), {
                "id": 1, "nodes": nodes, "is_active": case != "inactive",
                "broker_connection_id": "other" if case == "connection_mismatch" else "connection-1",
            })
        if case == "duplicate_links":
            connection.execute(workflows.insert(), {
                "id": 2, "nodes": [node], "is_active": True,
                "broker_connection_id": "connection-1",
            })
        if case in {"unrelated_list_type", "unrelated_dict_type"}:
            connection.execute(workflows.insert(), {
                "id": 2, "nodes": [{"type": [] if case == "unrelated_list_type" else {}, "data": {}}],
                "is_active": True, "broker_connection_id": "connection-1",
            })
    return engine


@pytest.mark.parametrize("case,expected,reason_fragment", [
    ("safe", "armed", "sandbox"),
    ("customized", "armed", "sandbox"),
    ("inactive", "disabled", "inactive"),
    ("live_workflow", "disabled", "sandbox"),
    ("duplicate_links", "disabled", "multiple"),
    ("duplicate_nodes", "disabled", "multiple"),
    ("foreign_owner", "disabled", "owner"),
    ("missing", "disabled", "linked"),
    ("string_id", "disabled", "linked"),
    ("connection_mismatch", "disabled", "connection"),
    ("live_strategy", "disabled", "live"),
    ("batch", "disabled", "signal"),
    ("malformed_list_type", "disabled", "malformed"),
    ("malformed_dict_type", "disabled", "malformed"),
    ("unrelated_list_type", "armed", "sandbox"),
    ("unrelated_dict_type", "armed", "sandbox"),
    ("protective_valid", "armed", "sandbox"),
    ("protective_exit_only", "disabled", "entry"),
    ("protective_multiple_entries", "disabled", "multiple"),
    ("protective_shared_exit", "disabled", "shared"),
    ("protective_live_exit", "disabled", "sandbox"),
    ("protective_foreign_exit", "disabled", "owner"),
    ("protective_invalid_exit", "disabled", "action"),
])
def test_backfill_arms_only_safe_active_sandbox_signal_links(tmp_path, case, expected, reason_fragment):
    """An unsafe admission or any mutation of graph/run/order evidence is a regression."""
    engine = _backfill_engine(tmp_path, case)
    try:
        before = _original_row_snapshot(engine)
        with engine.connect() as connection:
            flows = connection.exec_driver_sql("SELECT * FROM flow_workflows ORDER BY id").all()
        assert migration.apply(engine)
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT automation_state, automation_state_reason, automation_state_updated_at "
                "FROM sm_strategy WHERE id = 1"
            ).one()
            assert row.automation_state == expected
            assert reason_fragment in row.automation_state_reason.lower()
            assert row.automation_state_updated_at is not None
            assert connection.exec_driver_sql("SELECT * FROM flow_workflows ORDER BY id").all() == flows
        assert _original_row_snapshot(engine) == before
    finally:
        engine.dispose()


def test_backfill_rerun_preserves_operator_choice_and_does_not_enroll_new_rows(tmp_path):
    engine = _backfill_engine(tmp_path)
    try:
        assert migration.apply(engine)
        with engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT automation_state FROM sm_strategy").scalar_one() == "armed"
            connection.exec_driver_sql(
                "UPDATE sm_strategy SET automation_state = 'disabled', "
                "automation_state_reason = 'operator paused', automation_state_updated_at = NULL"
            )
            connection.exec_driver_sql("INSERT INTO sm_strategy (id, marker) VALUES (2, 'new')")
        assert migration.apply(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT automation_state, automation_state_reason FROM sm_strategy ORDER BY id"
            ).all() == [("disabled", "operator paused"), ("disabled", None)]
    finally:
        engine.dispose()


def test_backfill_resumes_original_candidates_after_columns_were_added(tmp_path, monkeypatch):
    engine = _backfill_engine(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(migration, "add_missing_indexes", lambda _engine: False)
            assert migration.apply(engine) is False
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO sm_strategy (id, marker) VALUES (2, 'new')")
        assert migration.apply(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT automation_state, automation_state_reason FROM sm_strategy ORDER BY id"
            ).all()[0][0] == "armed"
            assert connection.exec_driver_sql(
                "SELECT automation_state_reason FROM sm_strategy WHERE id = 2"
            ).scalar_one() is None
    finally:
        engine.dispose()


def test_status_reports_pending_backfill_after_schema_phase_interruption(tmp_path, monkeypatch, capsys):
    engine = _backfill_engine(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(migration, "backfill_automation_admission", lambda _engine: False)
            assert migration.apply(engine) is False
        before = _schema_snapshot(engine)
        assert migration.status(engine) is False
        assert "backfill" in capsys.readouterr().out.lower()
        assert _schema_snapshot(engine) == before
        assert migration.apply(engine)
        assert migration.status(engine) is True
    finally:
        engine.dispose()


def test_preexisting_admission_columns_are_never_enrolled_in_backfill(tmp_path):
    engine = _backfill_engine(tmp_path)
    try:
        assert migration.add_missing_columns(engine)
        assert migration.apply(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT automation_state, automation_state_reason FROM sm_strategy"
            ).one() == ("disabled", None)
    finally:
        engine.dispose()


def test_backfill_after_interruption_preserves_operator_admission(tmp_path, monkeypatch):
    engine = _backfill_engine(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(migration, "add_missing_indexes", lambda _engine: False)
            assert migration.apply(engine) is False
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE sm_strategy SET automation_state_reason = 'operator paused'"
            )
        assert migration.apply(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT automation_state, automation_state_reason FROM sm_strategy"
            ).one() == ("disabled", "operator paused")
    finally:
        engine.dispose()


def test_interrupted_backfill_does_not_arm_replacement_with_reused_sqlite_id(tmp_path, monkeypatch):
    engine = _backfill_engine(tmp_path)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(migration, "add_missing_indexes", lambda _engine: False)
            assert migration.apply(engine) is False
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM sm_strategy WHERE id = 1")
            connection.exec_driver_sql(
                "INSERT INTO sm_strategy (id, marker, created_at) "
                "VALUES (1, 'replacement', '2026-09-25 12:00:00')"
            )
        assert migration.apply(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT marker, automation_state, automation_state_reason FROM sm_strategy"
            ).one() == ("replacement", "disabled", None)
    finally:
        engine.dispose()


def test_boot_ensures_legacy_automation_columns_twice_and_preserves_operator_choice(tmp_path, monkeypatch):
    from database import strategy_module_db as store

    engine = _legacy_strategy_engine(tmp_path)
    try:
        monkeypatch.setattr(store, "engine", engine)
        store.init_db()
        with engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT automation_state FROM sm_strategy").scalar_one() == "disabled"
            connection.exec_driver_sql(
                "UPDATE sm_strategy SET automation_state = 'close_failed', "
                "automation_state_reason = 'keep choice', "
                "automation_state_updated_at = '2026-09-25 09:30:00'"
            )
        store.init_db()
        assert migration.apply(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT automation_state, automation_state_reason, automation_state_updated_at FROM sm_strategy"
            ).one() == ("close_failed", "keep choice", "2026-09-25 09:30:00")
    finally:
        engine.dispose()
