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


def test_migration_import_does_not_require_exported_database_url():
    import os
    import subprocess
    import sys

    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", "import upgrade.migrate_trading_research"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
