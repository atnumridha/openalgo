"""Server bar and execution decisions keep the research contract identity."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from test_research_minute_execution import filtered_payload
from test_research_ml import candles
from test_trading_research import fees

from services.research import dataset, ml, replay
from services.research.ml_live import entry_plan, score_observed, validate_completed_rows
from services.risk.admission import ML_RISK_RECIPE, planned_entry_risk


def test_two_session_feature_recipe_replays_identically_from_bounded_history():
    first = candles(140)
    second = first.copy()
    second.index = second.index + pd.Timedelta(days=1)
    second[["open", "high", "low", "close"]] += 12
    full = pd.concat((first, second))
    records = full.reset_index(names="timestamp")
    records["timestamp"] = records.timestamp.map(lambda item: item.isoformat())
    records["symbol"] = "NIFTY"
    data = {"metadata": {"underlying_symbol": "NIFTY"}, "rows": records.to_dict("records")}
    historical = ml.build_underlying_features(data)
    prefix = {**data, "rows": data["rows"][:-20]}
    serving = ml.build_underlying_features(prefix)
    pd.testing.assert_series_equal(historical.loc[serving.index[-1]], serving.iloc[-1])
    assert "ema_9_15_spread" in serving


def test_completed_rows_reject_gap_future_and_stale_bars():
    now = pd.Timestamp("2026-01-02T10:03:20+05:30").to_pydatetime()
    rows = [{"timestamp": f"2026-01-02T10:0{i}:00+05:30", "symbol": "NIFTY"} for i in range(1, 5)]
    assert validate_completed_rows(rows[:3], now, "NIFTY") == rows[-2]["timestamp"]
    with pytest.raises(ValueError, match="future|incomplete"):
        validate_completed_rows(rows, now, "NIFTY")
    with pytest.raises(ValueError, match="gap"):
        validate_completed_rows([rows[0], rows[2]], now, "NIFTY")
    with pytest.raises(ValueError, match="stale"):
        validate_completed_rows(rows[:1], now, "NIFTY")


def test_adaptive_entry_plan_matches_replay_stop_target_and_whole_lots():
    contract = {"symbol": "NIFTY_CE", "lot_size": 75, "multiplier": 1, "tick_size": 0.05}
    plan = entry_plan(contract, entry=100, atr=5, costs=fees(slippage_bps=0), capital=25000)
    assert plan["symbol"] == "NIFTY_CE"
    assert plan["quantity"] % 75 == 0
    assert plan["stop_price"] == 90
    assert plan["target_price"] == 120
    assert plan["quantity"] >= 75


def test_completed_broker_shaped_bars_score_the_exact_observed_contract():
    data = filtered_payload()
    previous = []
    for row in data["rows"]:
        if row["symbol"] == "NIFTY":
            copied = deepcopy(row)
            copied["timestamp"] = (
                datetime.fromisoformat(row["timestamp"]) - timedelta(days=1)
            ).isoformat()
            previous.append(copied)
    data["rows"].extend(previous)
    data["rows"] = [
        row
        for row in data["rows"]
        if row["timestamp"][:10] != "2026-01-01" or row["timestamp"][11:16] <= "10:00"
    ]
    data["rows"].sort(key=lambda row: (row["timestamp"], row["symbol"]))
    artifact = {
        "schema_version": 2,
        "feature_recipe": "causal-two-session-v1",
        "features": list(ml.ML_FEATURES),
        "training_hash": "a" * 64,
        "weighting": "session_balanced_average_uniqueness",
        "sample_weight_hash": "b" * 64,
        "feature_importance": dict.fromkeys(ml.ML_FEATURES, 0.0),
        "dependencies": {
            "available": True,
            "sklearn_version": "test",
            "numpy_version": "test",
            "pandas_version": "test",
        },
        "trees": [],
        "constant": 1.0,
    }
    now = datetime.fromisoformat("2026-01-01T10:00:20+05:30")
    result = score_observed(data, artifact, fees(), capital=25000, threshold=0.5, now=now)
    assert result["symbol"] == "NIFTY_CE"
    assert result["contract"]["symbol"] == result["symbol"]
    assert result["signal_at"] == "2026-01-01T10:00:00+05:30"
    assert result["score"] == 1


def test_all_ineligible_observed_options_report_filters_instead_of_attribute_error():
    data = filtered_payload()
    prior = []
    for row in data["rows"]:
        if row["symbol"] == "NIFTY":
            copied = deepcopy(row)
            copied["timestamp"] = (
                datetime.fromisoformat(row["timestamp"]) - timedelta(days=1)
            ).isoformat()
            prior.append(copied)
        else:
            row["volume"] = 0
    data["rows"].extend(prior)
    data["rows"] = [
        row
        for row in data["rows"]
        if row["timestamp"][:10] != "2026-01-01" or row["timestamp"][11:16] <= "10:00"
    ]
    data["rows"].sort(key=lambda row: (row["timestamp"], row["symbol"]))
    artifact = {
        "schema_version": 2,
        "feature_recipe": "causal-two-session-v1",
        "features": list(ml.ML_FEATURES),
        "training_hash": "a" * 64,
        "weighting": "session_balanced_average_uniqueness",
        "sample_weight_hash": "b" * 64,
        "feature_importance": dict.fromkeys(ml.ML_FEATURES, 0.0),
        "dependencies": {
            "available": True,
            "sklearn_version": "test",
            "numpy_version": "test",
            "pandas_version": "test",
        },
        "trees": [],
        "constant": 1.0,
    }
    with pytest.raises(ValueError, match="No eligible observed option contract.*liquidity_filter"):
        score_observed(
            data,
            artifact,
            fees(),
            capital=25000,
            threshold=0.5,
            now=datetime.fromisoformat("2026-01-01T10:00:20+05:30"),
        )


def test_entry_planner_matches_replay_on_identical_entry_and_contract():
    body = filtered_payload()
    data = dataset.validate_dataset(body)
    costs = fees(
        slippage_bps=10, brokerage_per_order=0, exchange_rate=0.0003553, stt_sell_rate=0.0015
    )
    schedule = {"2026-01-01T10:00:00+05:30": {"direction": "CE", "symbol": "NIFTY_CE"}}
    config = legacy_configuration(
        data, "trend_breakout_filtered", {}, costs, capital=25000
    )
    config.update(
        max_hold_minutes=5,
        research_signal_hash=dataset.digest(schedule),
        research_model_hash="a" * 64,
        risk_recipe=ML_RISK_RECIPE,
    )
    result = replay.run_replay(data, config, research_signals=schedule)
    assert result["trades"]
    trade = result["trades"][0]
    plan = entry_plan(
        data["metadata"]["contracts"][0],
        entry=trade["entry_price"],
        atr=2,
        costs=costs,
        capital=25000,
        day="2026-01-01",
    )
    assert plan["quantity"] == trade["quantity"]
    assert plan["stop_price"] == trade["stop_price"]
    assert plan["target_price"] == trade["target_price"]
    assert plan["planned_risk"] == pytest.approx(trade["planned_risk"])


def test_nonzero_fee_sizing_passes_actual_shared_admission_boundary(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    from database import trading_risk_db as ledger
    from services.risk.budget import BudgetPolicy, evaluate_budget
    from services.strategy_module import trading_budget

    costs = fees(
        slippage_bps=10, brokerage_per_order=0, exchange_rate=0.0003553, stt_sell_rate=0.0015
    )
    contract = {"symbol": "NIFTY_CE", "lot_size": 75, "multiplier": 1, "tick_size": 0.05}
    plan = entry_plan(contract, entry=31.55, atr=1, costs=costs, capital=25000)
    assert plan["quantity"] == 225
    assert plan["planned_risk"] == pytest.approx(
        float(
            planned_entry_risk(
                Decimal(str(plan["sl_pts"])) * plan["quantity"],
                Decimal("31.55") * plan["quantity"],
                costs,
            )
        )
    )
    assert planned_entry_risk(
        Decimal(str(plan["sl_pts"])) * 300, Decimal("31.55") * 300, costs
    ) > Decimal("1000")

    observed = []
    monkeypatch.setattr(ledger, "get_costs", lambda _: costs)
    monkeypatch.setattr(ledger, "list_trades", lambda *_a, **_k: [])
    monkeypatch.setattr(trading_budget, "reconcile_account", lambda *_: None)
    monkeypatch.setattr(
        ledger,
        "reserve",
        lambda user, mode, ref, day, risk, premium, segment, broker, strategy_id, details, **kw: (
            observed.append(risk)
            or evaluate_budget(
                BudgetPolicy(capital=Decimal("25000")),
                (),
                day,
                Decimal("25000"),
                Decimal("25000"),
                risk,
            )
        ),
    )
    from services.research import qualification

    monkeypatch.setattr(qualification, "register_entry", lambda *_: None)
    facts = SimpleNamespace(
        entry_risk=Decimal(str(plan["sl_pts"])) * plan["quantity"],
        estimated_debit=Decimal("31.55") * plan["quantity"],
        available_cash=Decimal("25000"),
        broker_quantities=(),
        open_derivative_positions=0,
    )
    leg = {
        "symbol": "NIFTY_CE",
        "exchange": "NFO",
        "position": "B",
        "quantity": plan["quantity"],
        "lot_size": 75,
        "position_ref": "ml-test",
    }
    decision, ref = trading_budget.reserve_entry(
        "alice",
        {"id": 7, "strategy_type": "intraday"},
        [leg],
        "sandbox",
        "sandbox",
        facts,
        datetime.fromisoformat("2026-01-01T10:00:00+05:30"),
    )
    assert decision.allowed and ref == "ml-test"
    assert len(observed) == 1 and float(observed[0]) == pytest.approx(plan["planned_risk"])


def test_frozen_adapter_rejects_other_owner_and_model_change(monkeypatch):
    from database import trading_research_db
    from services.research import jobs
    from services.research.dataset import digest
    from services.strategy_module import ml_forest

    artifact = {
        "schema_version": 2,
        "feature_recipe": "causal-two-session-v1",
        "features": list(ml.ML_FEATURES),
        "training_hash": "a" * 64,
        "weighting": "session_balanced_average_uniqueness",
        "sample_weight_hash": "b" * 64,
        "feature_importance": dict.fromkeys(ml.ML_FEATURES, 0.0),
        "dependencies": {
            "available": True,
            "sklearn_version": "test",
            "numpy_version": "test",
            "pandas_version": "test",
        },
        "trees": [],
        "constant": 1.0,
    }
    model_hash = digest(artifact)
    parent = {
        "id": 1,
        "kind": "ml",
        "frozen_at": "2026-01-01T00:00:00Z",
        "configuration_hash": "config",
        "report": {"ml": {"artifact": artifact, "model_hash": model_hash}},
    }
    final = {
        "id": 2,
        "parent_run_id": 1,
        "configuration_hash": "config",
        "report": {"ml": {"model_hash": model_hash}},
    }

    class Store:
        def get_run(self, owner, run_id):
            return {1: parent, 2: final}.get(run_id) if owner == "alice" else None

    monkeypatch.setattr(trading_research_db, "get_store", lambda: Store())
    monkeypatch.setattr(ml_forest, "final_screen_passes", lambda _: True)
    monkeypatch.setattr(jobs, "historical_ml_reason", lambda *_: None)
    strategy = {"ml_final_run_id": 2, "ml_model_hash": model_hash}
    assert ml_forest.frozen_model("alice", strategy)[0] == final
    with pytest.raises(ValueError, match="unavailable"):
        ml_forest.frozen_model("bob", strategy)
    with pytest.raises(ValueError, match="changed"):
        ml_forest.frozen_model("alice", {**strategy, "ml_model_hash": "b" * 64})


def test_resolved_ml_leg_keeps_scored_symbol_quantity_and_protection():
    from services.strategy_module.ml_forest import resolved_leg

    strategy = {"legs": [{"id": 3, "position": "B", "lots": 1, "atm_offset": "ATM"}]}
    contract = {
        "symbol": "NIFTY28OCT2523500CE",
        "option_type": "CE",
        "master_expiry": "28-OCT-25",
        "lot_size": 75,
    }
    context = {
        "symbol": contract["symbol"],
        "direction": "CE",
        "contract": contract,
        "quantity": 150,
        "lots": 2,
        "sl_pts": 10,
        "target_pts": 20,
    }
    leg = resolved_leg(strategy, context)
    assert leg["symbol"] == context["symbol"]
    assert leg["quantity"] == 150 and leg["lots"] == 2
    assert leg["sl_pts"] == 10 and leg["target_pts"] == 20
    with pytest.raises(ValueError, match="identity"):
        resolved_leg(strategy, {**context, "symbol": "WRONG"})


def test_live_admission_matches_filtered_replay_session_cap_and_exit_cooldown(monkeypatch):
    from database import strategy_module_db
    from services.strategy_module import ml_forest, scalping

    pace = {"entries": 2, "active": False, "last_exit": "2026-01-01T10:00:00+05:30"}
    calls = []
    monkeypatch.setattr(
        strategy_module_db,
        "ml_filled_entry_pace",
        lambda strategy_id, mode, day: calls.append((strategy_id, mode, day)) or pace,
    )
    with pytest.raises(scalping.WaitingForSignal, match="cooldown"):
        ml_forest.require_replay_pacing(7, "sandbox", "2026-01-01T10:14:00+05:30", "15:25")
    ml_forest.require_replay_pacing(7, "sandbox", "2026-01-01T10:15:00+05:30", "15:25")
    assert calls == [(7, "sandbox", "2026-01-01")] * 2
    pace["entries"] = 3
    with pytest.raises(scalping.WaitingForSignal, match="cap"):
        ml_forest.require_replay_pacing(7, "sandbox", "2026-01-01T10:15:00+05:30", "15:25")
    pace["entries"] = 1
    pace["active"] = True
    with pytest.raises(scalping.WaitingForSignal, match="open exposure"):
        ml_forest.require_replay_pacing(7, "sandbox", "2026-01-01T10:15:00+05:30", "15:25")
    pace["active"] = False
    with pytest.raises(scalping.WaitingForSignal, match="session close"):
        ml_forest.require_replay_pacing(7, "sandbox", "2026-01-01T15:24:00+05:30", "15:25")


def test_live_cost_rates_ignore_retrospective_dates_but_require_current_coverage():
    from services.research.costs import execution_economics, validate_cost_dates

    old = fees()
    current = {
        **old,
        "schedule_id": "current",
        "source": "verified current",
        "effective_from": "2026-01-01",
        "effective_to": "2026-01-31",
    }
    assert execution_economics(old) == execution_economics(current)
    validate_cost_dates(current, ["2026-01-20"])
    with pytest.raises(ValueError, match="cover"):
        validate_cost_dates(current, ["2026-02-01"])
    current["slippage_bps"] += 1
    assert execution_economics(old) != execution_economics(current)


def test_filled_entry_pacing_reads_isolated_durable_orders(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from database import strategy_module_db as db

    engine = create_engine("sqlite+pysqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(db, "db_session", session)
    try:
        base = (
            datetime.fromisoformat("2026-01-01T10:00:00+05:30").astimezone(UTC).replace(tzinfo=None)
        )
        for run_id, mode, filled, stopped in (
            (1, "sandbox", 75, base + timedelta(minutes=5)),
            (2, "sandbox", 0, base + timedelta(minutes=10)),
            (3, "live", 75, base + timedelta(minutes=12)),
        ):
            session.add(
                db.SmStrategyRun(
                    id=run_id,
                    strategy_id=7,
                    mode=mode,
                    started_at=base + timedelta(minutes=run_id - 1),
                    stopped_at=stopped,
                )
            )
            session.add(
                db.SmStrategyOrder(
                    run_id=run_id,
                    leg_id=1,
                    kind="entry",
                    symbol="NIFTY_CE",
                    exchange="NFO",
                    action="BUY",
                    qty=75,
                    filled_qty=filled,
                    status="complete" if filled else "rejected",
                )
            )
        session.commit()
        assert db.ml_filled_entry_pace(7, "sandbox", "2026-01-01") == {
            "entries": 1,
            "active": False,
            "last_exit": "2026-01-01T10:05:00+05:30",
        }
    finally:
        session.close()
        engine.dispose()


def legacy_configuration(*args, **kwargs):
    """Existing fixtures exercise archived two-bucket/2R behavior explicitly."""
    kwargs.setdefault("capital", 10000)
    return replay.validate_configuration(*args, **kwargs, policy_version="two-bucket-v1")
