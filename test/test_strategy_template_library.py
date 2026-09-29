"""Installing one library item must not install or arm the other templates."""

from datetime import datetime
from uuid import uuid4

import pytest
import pytz
from flask import Flask

from database import flow_db
from database import strategy_module_db as store


@pytest.fixture
def owner(monkeypatch):
    from services.strategy_module import scalping_pack

    user = "library-test-" + uuid4().hex
    store.init_db()
    flow_db.init_db()
    monkeypatch.setattr(scalping_pack, "_connection_for_owner", lambda *_: str(uuid4()))
    yield user
    for row in store.list_strategies(user):
        for flow in flow_db.get_workflows_for_strategy(row["id"]):
            flow_db.delete_workflow(flow.id)
        store.set_automation_state(row["id"], user, "disabled")
        store.set_strategy_status(row["id"], "stopped", None)
        store.delete_strategy(row["id"], user)
    store.db_session.remove()
    flow_db.db_session.remove()


def test_listing_uninstalled_templates_never_creates_strategies(owner):
    from services.strategy_module import template_library as library

    catalog = library.catalog(owner)
    assert len(catalog) == 27
    assert len({item["id"] for item in catalog}) == 27
    assert all(item["installed_strategy_id"] is None for item in catalog)
    assert not store.list_strategies(owner)
    assert {item["underlying"] for item in catalog} == {
        "NIFTY",
        "SENSEX",
        "GOLDM",
        "CRUDEOILM",
        "SILVERM",
        "NATGASMINI",
    }
    baskets = [item for item in catalog if item["id"] == "buy-call"]
    assert baskets and baskets[0]["provenance"] == "screenshot-detail"


def test_retrying_old_receiver_install_does_not_silently_switch_its_rules(owner):
    from blueprints.strategy_module import validate_strategy_config
    from services.strategy_module import starter_pack, template_library

    definition = starter_pack.legacy_starter_definitions()[1] | {"broker_connection_id": str(uuid4())}
    config, error = validate_strategy_config(definition)
    assert not error
    row, error = store.create_strategy(owner, config)
    assert not error
    result = template_library.install(owner, "nifty-retest")
    assert result["strategy_id"] == row["id"]
    assert store.get_strategy(row["id"], owner).scalp_profile is None
    nodes = flow_db.get_workflow(result["workflow_id"]).nodes
    assert any(node["id"] == "trend5" for node in nodes)


@pytest.mark.parametrize("offset", range(11))
def test_one_template_install_creates_only_one_stopped_sandbox_pair_and_is_repeatable(
    owner, offset
):
    from services.strategy_module import template_library as library

    item = library.catalog(owner)[offset]
    first = library.install(owner, item["id"])
    assert first["created"] is True
    row = store.get_strategy(first["strategy_id"], owner)
    assert row.name == item["name"]
    assert row.status == "stopped" and row.automation_state == "disabled" and not row.live_enabled
    assert row.scheduler is None and row.broker_connection_id
    flow = flow_db.get_workflow(first["workflow_id"])
    assert not flow.is_active and flow.schedule_job_id is None
    assert flow.broker_connection_id == row.broker_connection_id
    assert {
        n["data"]["mode"]
        for n in flow.nodes
        if n["type"] in {"strategyModuleRun", "strategySignal"}
    } == {"sandbox"}
    assert len(store.list_strategies(owner)) == 1
    before = store.strategy_to_dict(row)
    second = library.install(owner, item["id"])
    assert second == first | {"created": False}
    assert store.strategy_to_dict(store.get_strategy(row.id, owner)) == before
    assert len(flow_db.get_workflows_for_strategy(row.id)) == 1
    catalog = library.catalog(owner)
    assert sum(c["installed_strategy_id"] is not None for c in catalog) == 1
    assert not store.list_user_runs(owner)


def test_install_basket_is_inert(owner):
    from services.strategy_module import template_library as library

    result = library.install(owner, "buy-call")
    row = store.get_strategy(result["strategy_id"], owner)
    assert result["created"] is True and result["workflow_id"] is None
    assert row.name == "Kotak Buy Call"
    assert row.status == "stopped" and row.automation_state == "disabled" and not row.live_enabled
    assert row.scheduler is None
    assert [leg["position"] for leg in row.legs] == ["B"]
    assert not flow_db.get_workflows_for_strategy(row.id)
    assert library.install(owner, "buy-call") == result | {"created": False}
    assert len(store.list_strategies(owner)) == 1
    assert not store.list_user_runs(owner)


def test_unknown_template_cannot_write_or_select_another_owners_strategy(owner):
    from services.strategy_module import template_library as library

    with pytest.raises(ValueError, match="Unknown"):
        library.install(owner, "../other")
    assert not store.list_strategies(owner)
    first = library.install(owner, library.catalog(owner)[0]["id"])
    assert library.catalog("different-user")[0]["installed_strategy_id"] is None
    assert store.get_strategy(first["strategy_id"], "different-user") is None


def test_library_routes_require_authentication_and_report_one_install(owner, monkeypatch):
    from blueprints.strategy_module import strategy_module_bp
    from limiter import limiter

    monkeypatch.setattr(limiter, "enabled", False)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="library-test")
    app.add_url_rule("/auth/login", endpoint="auth.login", view_func=lambda: "Login")
    app.register_blueprint(strategy_module_bp)
    client = app.test_client()
    assert client.get("/strategy/api/templates").status_code in {302, 401}
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["user"] = owner
        session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    response = client.get("/strategy/api/templates")
    assert response.status_code == 200
    key = response.get_json()["data"][0]["id"]
    assert client.post("/strategy/api/templates/unknown/install").status_code == 404
    result = client.post(f"/strategy/api/templates/{key}/install")
    assert result.status_code == 201 and result.get_json()["created"] is True
    assert client.post(f"/strategy/api/templates/{key}/install").status_code == 200
    assert len(store.list_strategies(owner)) == 1


def test_failed_flow_install_stays_retryable_in_catalog_without_duplicate_strategy(
    owner, monkeypatch
):
    from services.strategy_module import template_library as library

    key = library.catalog(owner)[0]["id"]
    real_create = flow_db.create_workflow
    monkeypatch.setattr(flow_db, "create_workflow", lambda **_: None)
    with pytest.raises(RuntimeError, match="retry"):
        library.install(owner, key)
    partial = store.list_strategies(owner)
    assert len(partial) == 1
    item = library.catalog(owner)[0]
    assert item["installed_strategy_id"] is None and item["installation_pending"] is True
    monkeypatch.setattr(flow_db, "create_workflow", real_create)
    result = library.install(owner, key)
    assert result["strategy_id"] == partial[0]["id"]
    assert library.catalog(owner)[0]["installation_pending"] is False
    assert len(store.list_strategies(owner)) == 1


def test_same_display_name_from_other_owner_is_not_reused(owner):
    from services.strategy_module import template_library as library

    key = library.catalog(owner)[0]["id"]
    first = library.install(owner, key)
    foreign_owner = owner + "-other"
    try:
        second = library.install(foreign_owner, key)
        assert first["workflow_id"] != second["workflow_id"]
        assert first["strategy_id"] != second["strategy_id"]
        for user, result in ((owner, first), (foreign_owner, second)):
            nodes = flow_db.get_workflow(result["workflow_id"]).nodes
            assert {
                n["data"]["brokerOwner"] for n in nodes if n["type"] == "strategyModuleRun"
            } == {user}
    finally:
        for row in store.list_strategies(foreign_owner):
            for flow in flow_db.get_workflows_for_strategy(row["id"]):
                flow_db.delete_workflow(flow.id)
            store.delete_strategy(row["id"], foreign_owner)
