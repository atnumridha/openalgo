"""Only exact stock receiver rules may be upgraded, never arbitrary flows."""

from copy import deepcopy

import pytest


def saved_pair():
    from services.strategy_module import starter_pack, starter_workflows

    strategy = starter_pack.legacy_starter_definitions()[1] | {
        "id": 21,
        "user_id": "alice",
        "status": "stopped",
        "current_run_id": None,
        "scalp_profile": None,
        "automation_state": "armed",
        "live_enabled": True,
        "broker_connection_id": "pin",
    }
    graph = starter_workflows.legacy_definition(
        strategy["name"], 21, "NIFTY", "NSE_INDEX", "standard", "alice"
    )
    next(n for n in graph["nodes"] if n["id"] == "run")["data"]["mode"] = "live"
    workflow = graph | {"id": 21, "is_active": True, "broker_connection_id": "pin"}
    return strategy, workflow


def test_upgrade_is_explicit_distinct_idempotent_and_preserves_live_choices():
    from services.strategy_module.receiver_upgrade import plan

    strategy, workflow = saved_pair()
    before = deepcopy((strategy, workflow))
    result = plan(strategy, workflow)
    assert result["strategy_changes"] == {"scalp_profile": "receiver_retest"}
    assert len(result["workflow_changes"]["nodes"]) == 2
    run = next(n for n in result["workflow_changes"]["nodes"] if n["id"] == "run")
    assert run["data"]["mode"] == "live"
    assert run["data"]["barEvidence"] == {"scalpProfile": "receiver_retest"}
    assert (strategy, workflow) == before
    assert (
        plan(strategy | result["strategy_changes"], workflow | result["workflow_changes"]) is None
    )


@pytest.mark.parametrize(
    "edit", ["rule", "mode_mismatch", "owner", "pin", "leg", "running", "profile"]
)
def test_ambiguous_or_customized_receiver_is_never_rewritten(edit):
    from services.strategy_module.receiver_upgrade import UnsupportedReceiver, plan

    strategy, workflow = saved_pair()
    if edit == "rule":
        next(n for n in workflow["nodes"] if n["id"] == "trend5")["data"]["operator"] = "<"
    if edit == "mode_mismatch":
        strategy["live_enabled"] = False
    if edit == "owner":
        strategy["user_id"] = "bob"
    if edit == "pin":
        workflow["broker_connection_id"] = "other"
    if edit == "leg":
        strategy["legs"][0]["sl_pts"] = 7
    if edit == "running":
        strategy["status"] = "running"
    if edit == "profile":
        strategy["scalp_profile"] = "ema915"
    with pytest.raises(UnsupportedReceiver):
        plan(strategy, workflow)


def test_cosmetic_labels_and_positions_are_preserved_on_retained_nodes():
    from services.strategy_module.receiver_upgrade import plan

    strategy, workflow = saved_pair()
    start = next(n for n in workflow["nodes"] if n["id"] == "start")
    start["data"]["label"] = "My schedule"
    start["position"] = {"x": 123, "y": 456}
    result = plan(strategy, workflow)
    new_start = next(n for n in result["workflow_changes"]["nodes"] if n["id"] == "start")
    assert (
        new_start["data"]["label"] == "My schedule" and new_start["position"] == start["position"]
    )


@pytest.mark.parametrize(
    "extra",
    [{"trail": {"x": 5, "y": 2}}, {"strike": 25000}, {"premium_stop_points": 4}, {"quantity": 75}],
)
def test_additional_leg_controls_require_manual_review(extra):
    from services.strategy_module.receiver_upgrade import UnsupportedReceiver, plan

    strategy, workflow = saved_pair()
    strategy["legs"][0].update(extra)
    with pytest.raises(UnsupportedReceiver, match="leg"):
        plan(strategy, workflow)


@pytest.mark.parametrize(
    "extra",
    [
        {"trail_sl_to_entry": True},
        {"lock_profit": {"mode": "lock", "if_profit_reaches": 500, "lock_profit": 200}},
    ],
)
def test_additional_strategy_risk_controls_require_manual_review(extra):
    from services.strategy_module.receiver_upgrade import UnsupportedReceiver, plan

    strategy, workflow = saved_pair()
    strategy.update(extra)
    with pytest.raises(UnsupportedReceiver, match="risk"):
        plan(strategy, workflow)


def test_normalized_leg_identity_and_cosmetic_fields_do_not_block_upgrade():
    from services.strategy_module.receiver_upgrade import plan

    strategy, workflow = saved_pair()
    strategy["legs"][0].update(id=7, label="My option", trail=None)
    strategy.update(trail_sl_to_entry=False, lock_profit=None)
    assert plan(strategy, workflow)["strategy_changes"] == {"scalp_profile": "receiver_retest"}


@pytest.mark.parametrize(
    "saved_lock", ["null", '{"mode":"lock","if_profit_reaches":500,"lock_profit":200}']
)
def test_offline_upgrade_backs_up_and_preserves_modes_and_all_other_fields(tmp_path, saved_lock):
    import json
    import sqlite3
    from contextlib import closing

    from upgrade.upgrade_receiver_rules import apply

    path = tmp_path / "receiver.db"
    strategy, workflow = saved_pair()
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "CREATE TABLE sm_strategy (id INTEGER PRIMARY KEY,name TEXT,user_id TEXT,status TEXT,current_run_id INTEGER,scalp_profile TEXT,automation_state TEXT,live_enabled INTEGER,broker_connection_id TEXT,strategy_kind TEXT,underlying TEXT,underlying_exchange TEXT,strategy_type TEXT,legs TEXT,notes TEXT,lock_profit TEXT,trail_sl_to_entry INTEGER DEFAULT 0)"
        )
        keys = [r[1] for r in db.execute("PRAGMA table_info(sm_strategy)")]
        values = [
            json.dumps(strategy["legs"])
            if k == "legs"
            else (
                saved_lock
                if k == "lock_profit"
                else 0
                if k == "trail_sl_to_entry"
                else "keep"
                if k == "notes"
                else strategy.get(k)
            )
            for k in keys
        ]
        db.execute("INSERT INTO sm_strategy VALUES (" + ",".join("?" for _ in keys) + ")", values)
        db.execute(
            "CREATE TABLE flow_workflows (id INTEGER PRIMARY KEY,name TEXT,nodes TEXT,edges TEXT,description TEXT,is_active INTEGER,broker_connection_id TEXT)"
        )
        db.execute(
            "INSERT INTO flow_workflows VALUES (?,?,?,?,?,?,?)",
            (
                21,
                workflow["name"],
                json.dumps(workflow["nodes"]),
                json.dumps(workflow["edges"]),
                "old",
                1,
                "pin",
            ),
        )
        db.execute("CREATE TABLE sm_strategy_run (id INTEGER,strategy_id INTEGER,stopped_at TEXT)")
        db.commit()
    planned, skipped, backup = apply(path)
    if saved_lock != "null":
        assert not planned and backup is None
        assert len(skipped) == 1 and "Custom receiver risk controls" in skipped[0]
        assert apply(path, do_apply=True, offline=True) == (planned, skipped, None)
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT lock_profit,scalp_profile FROM sm_strategy").fetchone() == (
                saved_lock,
                None,
            )
        return
    assert len(planned) == 1 and not skipped and backup is None
    with pytest.raises(ValueError, match="offline"):
        apply(path, do_apply=True)
    planned, skipped, backup = apply(path, do_apply=True, offline=True)
    assert backup.is_file() and backup.stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(path)) as db:
        row = db.execute(
            "SELECT scalp_profile,live_enabled,automation_state,notes FROM sm_strategy"
        ).fetchone()
        assert row == ("receiver_retest", 1, "armed", "keep")
        assert db.execute(
            "SELECT is_active,broker_connection_id FROM flow_workflows"
        ).fetchone() == (1, "pin")
    assert apply(path)[0] == []
