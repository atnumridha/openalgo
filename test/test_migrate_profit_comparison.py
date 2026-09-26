"""An upgrade adds the comparison table without disturbing existing rows."""

from sqlalchemy import inspect, text

from database.engine_factory import create_db_engine
from upgrade import migrate_profit_comparison as migration


def test_migration_is_idempotent_and_keeps_existing_comparisons(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'comparison.db'}")
    try:
        assert migration.status(engine) is False
        assert migration.apply(engine) is True
        assert "sm_profit_comparison" in inspect(engine).get_table_names()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO sm_profit_comparison "
                    "(run_id, position_ref, snapshot, version, created_at, updated_at) "
                    "VALUES (5, 'one', '{}', 0, '2026-09-25', '2026-09-25')"
                )
            )
        assert migration.status(engine) is True
        assert migration.apply(engine) is True
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM sm_profit_comparison WHERE run_id=5")
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()
