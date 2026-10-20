import json
import time
from dataclasses import asdict

import pytest

from strategies.liquidity import state
from strategies.liquidity.execution import types
from strategies.liquidity.feed import references
from strategies.liquidity.setup import Config, plan_order


def test_no_cached_forming_candle_promoted_by_clock():
    rows = [
        {"time": i * 3600, "open": 100, "close": 100, "high": h, "low": 90}
        for i, h in enumerate([102, 103, 110, 104, 105])
    ]
    assert references(rows, 3600, "1H", 18001, captured_at=17995) == []
    assert references(rows, 3600, "1H", 18001, captured_at=18001)[0]["price"] == 110
    rows.append({"time": 18000, "open": 100, "close": 109, "high": 111, "low": 95})
    r = references(rows, 3600, "1H", 18030, captured_at=18030)[0]
    assert r["retired_at"] == 18000  # Sweep in current HTF bar is already observed.


def test_approval_pins_complete_plan_and_is_owner_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)
    one = state.identifier("one")
    two = state.identifier("two")
    Ledger, _ = types(Config())
    s = Ledger(state.directory(one) / "paper.sqlite")
    try:
        plan = {
            "setup_id": "x",
            "quantity": 1,
            "entry": 100,
            "stop": 99,
            "target": 110,
            "net_risk": 0.5,
        }
        s.set("view", {"asof": time.time(), "plan": plan})
        s.set("command", None)
        state.command(one, "paper", "approve", "x", state.plan_revision(plan))
        cmd = s.take_command()
        assert cmd["approved_plan"] == plan
        assert cmd["approved_plan"] != dict(plan, quantity=2)
        with pytest.raises(ValueError, match="changed"):
            state.command(one, "paper", "approve", "x", state.plan_revision(dict(plan, quantity=2)))
        assert state.snapshot(two, "paper") == {}
        s.set("view", {"asof": time.time() - 10, "plan": plan})
        with pytest.raises(ValueError, match="expired"):
            state.command(one, "paper", "approve", "x")
        with pytest.raises(ValueError):
            state.directory("../other")
    finally:
        s.close()


def test_high_leverage_cannot_put_stop_beyond_liquidation():
    p = {
        "contract_value": ".001",
        "tick_size": ".5",
        "maker_commission_rate": ".0002",
        "taker_commission_rate": ".0005",
        "maintenance_margin": ".25",
        "maintenance_margin_scaling_factor": ".00000125",
        "initial_margin": ".5",
        "product_specs": {"isolated_liq_penalty_factor": ".0005"},
    }
    c = {
        "id": "x",
        "stage": "TRIGGERED",
        "direction": "LONG",
        "trigger": 99999,
        "extreme": 99200,
        "atr": 2000,
        "target": 104000,
        "triggered_at": 100,
        "expires": 500,
    }
    result = plan_order(
        c, {"bid": 100000, "ask": 100000.5, "time": 101}, p, Config(leverage=200), 101, 100
    )
    assert "liquidation" in result["blocked"]


def test_api_requires_owner_session_and_delta_without_starting(tmp_path, monkeypatch):
    from flask import Flask

    from blueprints.liquidity_strategy import liquidity_strategy_bp

    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(liquidity_strategy_bp)
    client = app.test_client()
    assert client.get("/liquidity-strategy/api/status").status_code == 401
    with client.session_transaction() as s:
        s.update(user="owner", broker="other")
    assert client.get("/liquidity-strategy/api/status").status_code == 403
    with client.session_transaction() as s:
        s["broker"] = "deltaexchange"
    r = client.get("/liquidity-strategy/api/status")
    assert r.status_code == 200 and r.json["data"]["config"]["mode"] == "paper"
    assert r.json["data"]["paper"] == {} and r.json["data"]["live"] == {}
