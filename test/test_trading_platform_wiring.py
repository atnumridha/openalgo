from flask import Flask
from sqlalchemy import text

from blueprints import react_app
from database.engine_factory import create_db_engine
from upgrade import migrate_all, migrate_trading_research


def test_research_bookmark_serves_spa_without_becoming_an_unknown_route(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(react_app.react_bp)
    monkeypatch.setattr(react_app, "serve_react_app", lambda: ("research-shell", 200))
    assert app.test_client().get("/strategy/research").data == b"research-shell"


def test_upgrade_runner_includes_required_idempotent_research_migration(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path}/upgrade.db")
    try:
        migration = next(
            (name for name, _ in migrate_all.MIGRATIONS if name == "migrate_trading_research.py"),
            None,
        )
        assert migration in migrate_all.REQUIRED_MIGRATIONS
        assert not migrate_trading_research.status(engine)
        assert migrate_trading_research.apply(engine)
        assert migrate_trading_research.status(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO trading_risk_account (scope,capital,peak,paused) VALUES ('u|sandbox',10000,11000,1)"
                )
            )
        assert migrate_trading_research.apply(engine)
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT peak FROM trading_risk_account")).scalar_one()
                == 11000
            )
    finally:
        engine.dispose()


def test_research_upgrade_adds_revision_to_existing_accounts_without_changing_facts(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path}/old-risk.db")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE trading_risk_account ("
                                    "scope VARCHAR(180) PRIMARY KEY, capital NUMERIC(20,4) NOT NULL, "
                                    "peak NUMERIC(20,4) NOT NULL, paused BOOLEAN NOT NULL, "
                                    "pause_reason TEXT)"))
            connection.execute(text("INSERT INTO trading_risk_account "
                                    "(scope,capital,peak,paused,pause_reason) "
                                    "VALUES ('u|sandbox',10000,11000,1,'operator review')"))
        assert not migrate_trading_research.status(engine)
        assert migrate_trading_research.apply(engine)
        assert migrate_trading_research.status(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT scope,capital,peak,paused,pause_reason,"
                                           "allocation_revision FROM trading_risk_account")).one() == (
                "u|sandbox", 10000, 11000, 1, "operator review", 0)
        assert migrate_trading_research.apply(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT allocation_revision FROM trading_risk_account")).scalar_one() == 0
    finally:
        engine.dispose()


def test_migration_status_and_apply_initialize_clean_environment(tmp_path):
    import os
    import subprocess
    import sys

    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    environment["LOG_FORMAT"] = "%(message)s"
    url = f"sqlite:///{tmp_path / 'clean-upgrade.db'}"
    code = """
import os
import sys
from upgrade import migrate_trading_research as migration
from database.engine_factory import create_db_engine

assert 'DATABASE_URL' not in os.environ
assert 'database.trading_risk_db' not in sys.modules
url = sys.argv[1]
migration.get_database_url = lambda: url
engine = create_db_engine(url)
try:
    assert migration.status(engine) is False
    assert os.environ['DATABASE_URL'] == url
    assert migration.apply(engine) is True
    assert migration.status(engine) is True
    assert migration.apply(engine) is True
finally:
    engine.dispose()
print('clean status/apply passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, url],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "clean status/apply passed" in result.stdout
