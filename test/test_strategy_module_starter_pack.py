"""Safety and idempotency contract for the sandbox starter strategies."""

import sys
from datetime import datetime
from pathlib import Path

import pytest
import pytz
from flask import Flask

sys.path.insert(0, str(Path(__file__).parents[1]))

from blueprints import strategy_module  # noqa: E402
from database import strategy_module_db as store  # noqa: E402
from database.engine_factory import create_db_engine  # noqa: E402
from limiter import limiter  # noqa: E402
from services.strategy_module import starter_pack  # noqa: E402

USER = "starter-pack-user"


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    path = tmp_path_factory.mktemp("starter-pack") / "strategy-module-test.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    store.db_session.remove()
    store.db_session.configure(bind=engine)
    store.engine = engine
    store.Base.metadata.create_all(bind=engine)
    yield engine
    store.db_session.remove()
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(isolated_store):
    store.db_session.remove()
    with isolated_store.begin() as connection:
        for table in reversed(store.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield
    store.db_session.remove()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    application = Flask(__name__)
    application.config.update(
        TESTING=True,
        SECRET_KEY="starter-pack-tests",
        PROPAGATE_EXCEPTIONS=True,
    )
    application.register_blueprint(strategy_module.strategy_module_bp)
    return application


@pytest.fixture
def client(app):
    test_client = app.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["logged_in"] = True
        flask_session["user"] = USER
        flask_session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    return test_client


def test_every_starter_definition_is_a_safe_unscheduled_strategy_module_config():
    """A changed template that skips validation or loosens risk must be rejected here."""
    definitions = starter_pack.starter_definitions()

    assert len(definitions) == 6
    assert len({definition["name"] for definition in definitions}) == 6
    for definition in definitions:
        validated, error = strategy_module.validate_strategy_config(definition)

        assert error is None, f"{definition['name']}: {error}"
        assert validated["scheduler"] is None
        assert validated["pricetype"] == "MARKET"
        assert validated["strategy_type"] == "intraday"
        assert validated["entry_time"].strftime("%H:%M") == "09:20"
        assert validated["exit_time"].strftime("%H:%M") == "15:20"
        assert validated["daily_loss_limit_inr"] > 0
        for leg in validated["legs"]:
            assert leg["sl_pts"] > 0
            assert leg["target_pts"] > 0
            assert leg["target_pts"] / leg["sl_pts"] >= 1.5


def test_cash_templates_are_signal_receivers_for_exact_liquid_symbols():
    """Changing a cash template into a stale resolver-dependent leg must fail here."""
    cash_definitions = [
        definition
        for definition in starter_pack.starter_definitions()
        if definition["strategy_kind"] == "signal"
    ]

    assert len(cash_definitions) == 3
    for definition in cash_definitions:
        leg = definition["legs"][0]
        assert leg["segment"] == "cash"
        assert leg["exchange"] == "NSE"
        assert leg["qty_mode"] == "units"
        assert leg["symbol"] in {"RELIANCE", "HDFCBANK", "ICICIBANK"}


def test_nifty_option_templates_are_batch_strategies_with_dynamic_weekly_atm_legs():
    """Replacing a rolling ATM option with a literal expiring symbol must fail here."""
    option_definitions = [
        definition
        for definition in starter_pack.starter_definitions()
        if definition["strategy_kind"] == "batch"
    ]

    assert len(option_definitions) == 3
    for definition in option_definitions:
        assert definition["underlying"] == "NIFTY"
        assert definition["underlying_exchange"] == "NSE_INDEX"
        assert definition["universe_tab"] == "weekly_monthly"
        assert len(definition["legs"]) == 1
        leg = definition["legs"][0]
        assert leg["segment"] == "options"
        assert leg["lots"] == 1
        assert leg["expiry"] == "weekly"
        assert leg["strike_mode"] == "atm"
        assert leg["atm_offset"] == "ATM"
        assert "symbol" not in leg


def test_install_creates_stopped_sandbox_strategies_once_and_never_starts_a_run():
    """A duplicate install or accidental activation must fail this user-visible contract."""
    first = starter_pack.install(USER)

    assert len(first.created) == 6
    assert first.existing == ()
    assert len(first.webhook_tokens) == 6
    assert all(token.startswith(store.WEBHOOK_TOKEN_PREFIX) for token in first.webhook_tokens.values())
    rows = store.list_strategies(USER)
    assert len(rows) == 6
    assert all(row["status"] == "stopped" for row in rows)
    assert all(row["live_enabled"] is False for row in rows)
    assert all(row["scheduler"] is None for row in rows)
    assert all(store.list_runs(row["id"]) == [] for row in rows)
    token_hashes = {
        row["name"]: store.get_strategy(row["id"], USER).webhook_token_hash for row in rows
    }

    second = starter_pack.install(USER)

    assert second.created == ()
    assert len(second.existing) == 6
    assert second.webhook_tokens == {}
    assert {entry["name"] for entry in second.existing} == {entry["name"] for entry in first.created}
    assert all(store.list_runs(row["id"]) == [] for row in store.list_strategies(USER))
    assert {
        row["name"]: store.get_strategy(row["id"], USER).webhook_token_hash
        for row in store.list_strategies(USER)
    } == token_hashes


def test_authenticated_install_route_returns_tokens_only_when_it_creates_rows(client):
    """Returning stored tokens on a repeat request would make a credential replayable."""
    first = client.post("/strategy/api/automation/starter-pack")

    assert first.status_code == 201
    first_body = first.get_json()
    assert len(first_body["created"]) == 6
    assert first_body["existing"] == []
    assert len(first_body["webhook_tokens"]) == 6

    second = client.post("/strategy/api/automation/starter-pack")

    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body["created"] == []
    assert len(second_body["existing"]) == 6
    assert second_body["webhook_tokens"] == {}
