"""The new cash recipe must not inherit legacy 2R sizing or entry caps."""

from copy import deepcopy
from decimal import Decimal

import pytest
from test_research_minute_execution import filtered_payload
from test_trading_research import fees

from services.research import dataset, replay
from services.research.ml_live import entry_plan
from services.risk.budget import BudgetTrade
from services.risk.cash_exit import CASH_RISK_RECIPE
from services.risk.profit_exit import PROFIT_RECIPE

RECIPE = "one-lot-cash300-3r-v1"
CONTRACT = {"symbol": "NIFTY_CE", "lot_size": 75, "multiplier": 1, "tick_size": 0.05}


@pytest.mark.parametrize(
    "entry,atr,lot,stop,target,gross",
    [
        (100, 5, 75, 96, 112, 300),
        (100, 5, 65, 95.4, 113.8, 299),
        (20, 0, 75, 18, 26, 150),
    ],
)
def test_cash_entry_rounds_toward_entry_and_sets_exact_three_r(
    entry, atr, lot, stop, target, gross
):
    plan = entry_plan(
        dict(CONTRACT, lot_size=lot),
        entry=entry,
        atr=atr,
        costs=fees(slippage_bps=0),
        capital=25000,
        risk_recipe=RECIPE,
    )
    assert (plan["quantity"], plan["stop_price"], plan["target_price"]) == (lot, stop, target)
    assert plan["gross_planned_risk"] == gross
    assert plan["planned_risk"] > gross


def test_current_recipe_reserves_fees_in_daily_allowance():
    losses = [
        BudgetTrade(
            "1",
            "2026-01-01",
            "shared",
            "closed",
            Decimal("1800"),
            net_pnl=Decimal("-1700"),
            filled=True,
            close_sequence=1,
            completion_day="2026-01-01",
        )
    ]
    with pytest.raises(ValueError, match="budget"):
        entry_plan(
            CONTRACT,
            entry=100,
            atr=5,
            costs=fees(),
            capital=25000,
            day="2026-01-01",
            ledger=losses,
            risk_recipe=RECIPE,
        )


def test_legacy_entry_remains_two_r():
    plan = entry_plan(CONTRACT, entry=100, atr=5, costs=fees(slippage_bps=0), capital=25000)
    assert (plan["stop_price"], plan["target_price"]) == (90, 120)


def test_new_configuration_binds_three_r_and_pacing_and_rejects_ratio_override():
    data = dataset.validate_dataset(filtered_payload())
    config = replay.validate_configuration(
        data, "trend_breakout_filtered", {}, fees(), capital=25000
    )
    assert config["risk_recipe"] == CASH_RISK_RECIPE
    assert config["parameters"]["target_pct"] == 0.3
    assert config["pacing"] == {"cooldown_minutes": 5, "daily_trade_cap": None}
    hashes = {
        dataset.digest(
            replay.validate_configuration(
                data, "trend_breakout_filtered", {}, fees(), capital=25000, cooldown_minutes=n
            )
        )
        for n in (0, 5, 15)
    }
    assert len(hashes) == 3
    with pytest.raises(ValueError, match="3R"):
        replay.validate_configuration(data, "trend_breakout_filtered", {"target_pct": 0.2}, fees())


def scheduled_data(outcomes):
    body = filtered_payload()
    body["metadata"]["bar_minutes"] = 1
    body["metadata"]["contracts"][0].update(strike=22000, lot_size=75)
    body["rows"] = []
    from datetime import datetime, timedelta

    start = datetime.fromisoformat("2026-01-01T09:16:00+05:30")
    schedule = {}
    for i in range(80):
        at = start + timedelta(minutes=i)
        option = {
            "symbol": "NIFTY_CE",
            "timestamp": at.isoformat(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 10000,
        }
        if i >= 12 and (i - 12) % 3 == 0 and (i - 12) // 3 < len(outcomes):
            schedule[(at - timedelta(minutes=1)).isoformat()] = {
                "direction": "CE",
                "symbol": "NIFTY_CE",
            }
            option.update(
                high=113 if outcomes[(i - 12) // 3] else 101,
                low=99 if outcomes[(i - 12) // 3] else 95,
            )
        body["rows"].extend(
            [option, dict(option, symbol="NIFTY", open=22000, high=22001, low=21999, close=22000)]
        )
    return dataset.validate_dataset(body), schedule


@pytest.mark.parametrize(
    "outcomes,want",
    [([False] * 6, 3), ([False, False, True, False, False, False, True], 6), ([True] * 6, 6)],
)
def test_replay_chronological_loss_stop_and_no_successful_entry_cap(outcomes, want):
    data, signals = scheduled_data(outcomes)
    config = replay.validate_configuration(
        data, "trend_breakout_filtered", {}, fees(slippage_bps=0), capital=25000, cooldown_minutes=0
    )
    config["risk_recipe"] = RECIPE
    config["risk_policy_version"] = "shared-300-3r-v1"
    config["research_signal_hash"] = dataset.digest(signals)
    result = replay.run_replay(data, config, research_signals=signals)
    assert len(result["trades"]) == want
    for trade in result["trades"]:
        assert trade["quantity"] == 75
        assert trade["gross_planned_risk"] <= 300
        assert Decimal(str(trade["target_price"])) - Decimal(str(trade["entry_price"])) == 3 * (
            Decimal(str(trade["entry_price"])) - Decimal(str(trade["stop_price"]))
        )
    if outcomes[-1] is False or not outcomes[0]:
        assert result["rejections"].get("consecutive_losses_stop", 0) >= 1


@pytest.mark.parametrize("stress", [False, True])
def test_label_live_and_replay_share_cash_exit_and_net_costs(stress):
    from services.research.ml import label_option_trade

    data, signals = scheduled_data([True])
    costs = fees(slippage_bps=0)
    config = replay.validate_configuration(
        data, "trend_breakout_filtered", {}, costs, capital=25000, cooldown_minutes=0
    )
    config["risk_recipe"] = RECIPE
    config["risk_policy_version"] = "shared-300-3r-v1"
    config["research_signal_hash"] = dataset.digest(signals)
    result = replay.run_replay(data, config, stress=stress, research_signals=signals)
    trade = result["trades"][0]
    effective = deepcopy(costs)
    if stress:
        effective["slippage_bps"] = 10
        effective["brokerage_per_order"] *= 1.5
    contract = data["metadata"]["contracts"][0]
    label = label_option_trade(
        [r for r in data["rows"] if r["symbol"] == "NIFTY_CE"],
        next(iter(signals)),
        contract,
        2,
        effective,
        "13:00",
        capital=25000,
        risk_recipe=RECIPE,
    )
    assert label["net_pnl"] == trade["net_pnl"]
    assert label["exit_at"] == trade["exit_at"]
    assert label["gross_planned_risk"] == trade["gross_planned_risk"]
    live = entry_plan(
        contract,
        entry=trade["entry_price"],
        atr=2,
        costs=effective,
        capital=25000,
        risk_recipe=RECIPE,
    )
    assert (live["stop_price"], live["target_price"], live["planned_risk"]) == (
        trade["stop_price"],
        trade["target_price"],
        trade["planned_risk"],
    )


def test_new_scalp_context_uses_option_target_and_keeps_deadline():
    from datetime import datetime

    from services.strategy_module.scalping import exit_reason, trade_context

    context = trade_context(
        "ema915",
        {"direction": "CE", "timestamp": "2026-01-01T10:00:00+05:30", "low": 99, "high": 102},
        100,
    )
    assert context["exit_basis"] == "option_premium"
    assert context["risk_recipe"] == CASH_RISK_RECIPE
    assert exit_reason(context, datetime.fromisoformat("2026-01-01T10:01:00+05:30"), 110) is None
    assert (
        exit_reason(context, datetime.fromisoformat("2026-01-01T10:15:00+05:30"), 110)
        == "scheduler"
    )
    old = {
        "direction": "CE",
        "entry": 100,
        "stop": 99,
        "target": 102,
        "deadline": context["deadline"],
        "exit_basis": "underlying_index",
    }
    assert (
        exit_reason(old, datetime.fromisoformat("2026-01-01T10:01:00+05:30"), 110)
        == "overall_target"
    )


def test_new_queued_ml_binds_current_recipe_and_source(monkeypatch):
    from services.research import jobs

    data = dataset.validate_dataset(filtered_payload())
    data["sessions"] = [f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(120)]

    class Store:
        def get_dataset(self, owner, id):
            return data

        def queue_run(self, *args, **kwargs):
            return args, kwargs

    # No estimator or persistence work is necessary to validate a queued request.
    monkeypatch.setattr(jobs, "ml_dependencies", lambda: {"available": True})
    monkeypatch.setattr(
        jobs,
        "validate_configuration",
        lambda *args, **kwargs: {
            "candidate": "trend_breakout_filtered",
            "parameters": deepcopy(replay.DEFAULTS),
            "risk_recipe": CASH_RISK_RECIPE,
            "risk_policy_version": "equity-1pct-v2",
            "pacing": {"cooldown_minutes": 5, "daily_trade_cap": None},
        },
    )
    args, kwargs = jobs.queue_run(
        Store(),
        "owner",
        {
            "dataset_id": 1,
            "candidate": "trend_breakout_filtered",
            "costs": fees(),
            "run_kind": "ml",
        },
    )
    configuration = args[2]
    assert configuration["risk_recipe"] == CASH_RISK_RECIPE
    assert configuration["risk_policy_version"] == "equity-1pct-v2"


def test_optimization_rejects_independent_target_grid():
    from services.research.jobs import validate_parameter_grid

    data = dataset.validate_dataset(filtered_payload())
    with pytest.raises(ValueError, match="3R|fixed"):
        validate_parameter_grid(data, "trend_breakout_filtered", {"target_pct": [0.2, 0.3]}, fees())


@pytest.mark.parametrize(
    "tick,entry,lot", [("0", 100, 75), (None, 100, 75), (0.05, 100.01, 75), (1, 100, 1000)]
)
def test_unrepresentable_tick_stops_fail_closed(tick, entry, lot):
    with pytest.raises(ValueError, match="tick|Cash stop"):
        entry_plan(
            dict(CONTRACT, tick_size=tick, lot_size=lot),
            entry=entry,
            atr=5,
            costs=fees(),
            capital=25000,
            risk_recipe=RECIPE,
        )


def test_cash_cap_does_not_bypass_entry_volatility_filter():
    with pytest.raises(ValueError, match="volatility"):
        entry_plan(CONTRACT, entry=20, atr=10, costs=fees(), capital=25000, risk_recipe=RECIPE)


def test_daily_loss_stop_resets_for_new_session():
    from datetime import datetime, timedelta

    data, signals = scheduled_data([False] * 4)
    body = deepcopy(data)
    body["rows"] += [
        dict(r, timestamp=(datetime.fromisoformat(r["timestamp"]) + timedelta(days=1)).isoformat())
        for r in data["rows"]
    ]
    data = dataset.validate_dataset(body)
    signals |= {
        (datetime.fromisoformat(at) + timedelta(days=1)).isoformat(): choice
        for at, choice in list(signals.items())
    }
    config = replay.validate_configuration(
        data,
        "trend_breakout_filtered",
        {},
        fees(slippage_bps=0),
        capital=25000,
        cooldown_minutes=0,
        policy_version="shared-300-3r-v1",
    )
    config["research_signal_hash"] = dataset.digest(signals)
    result = replay.run_replay(data, config, research_signals=signals)
    assert len(result["trades"]) == 6
    assert result["trades"][3]["budget_after_close"]["consecutive_losses"] == 1


def test_current_scalp_protection_preserves_contract_and_sets_cash_target(monkeypatch):
    from datetime import datetime, timedelta

    from services.strategy_module import scalping

    monkeypatch.setattr(scalping, "quote_price", lambda *a: 100)
    expiry = (datetime.now(scalping.IST) + timedelta(days=2)).strftime("%d-%b-%y")
    leg = dict(CONTRACT, quantity=75, exchange="NFO", expiry=expiry)
    context = {"profile": "ema915", "risk_recipe": RECIPE, "exit_basis": "option_premium"}
    result = scalping.protect_leg(leg, context, object())
    assert (result["symbol"], result["quantity"], result["sl_pts"], result["target_pts"]) == (
        "NIFTY_CE",
        75,
        4,
        12,
    )
    assert result["scalp_context"]["gross_planned_risk"] == 300


def test_frozen_final_refuses_old_artifact_even_when_configuration_is_current(monkeypatch):
    from services.research import jobs

    data = dataset.validate_dataset(filtered_payload())
    config = replay.validate_configuration(data, "trend_breakout_filtered", {}, fees())
    from datetime import date, timedelta

    data["sessions"] = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(120)]
    artifact = {"old": "artifact"}

    def no_feature_work(_):
        pytest.fail("Old artifact reached final feature preparation")

    monkeypatch.setattr(jobs, "build_underlying_features", no_feature_work)
    parent = {
        "kind": "ml",
        "status": "completed",
        "frozen_at": "2026-01-01",
        "configuration_hash": dataset.digest(config),
        "report": {"ml": {"artifact": artifact, "model_hash": dataset.digest(artifact)}},
    }
    monkeypatch.setattr(jobs, "validate_artifact", lambda _: None)
    with pytest.raises(ValueError, match="artifact.*recipe"):
        jobs.run_ml_final_experiment(data, config, parent)


def test_current_configuration_has_no_legacy_pacing_and_rejects_boolean_parameters():
    data = dataset.validate_dataset(filtered_payload())
    config = replay.validate_configuration(data, "trend_breakout_filtered", {}, fees())
    assert "daily_trade_cap" not in config["filters"]
    assert "cooldown_minutes" not in config["filters"]
    assert config["max_hold_minutes"] == 15
    with pytest.raises(ValueError):
        replay.validate_configuration(data, "trend_breakout_filtered", {"stop_pct": True}, fees())


def test_profit_recipe_runs_past_900_and_exits_on_the_rising_floor():
    from services.research.ml import label_option_trade

    data, signals = scheduled_data([True])
    signal = next(iter(signals))
    option_rows = [r for r in data["rows"] if r["symbol"] == "NIFTY_CE"]
    from datetime import datetime, timedelta

    start = datetime.fromisoformat(signal) + timedelta(minutes=1)
    prices = [(100, 104, 99, 104), (108, 113, 107, 112), (116, 121, 115, 120), (118, 119, 115, 116)]
    for i, (o, h, low, c) in enumerate(prices):
        at = (start + timedelta(minutes=i)).isoformat()
        row = next(r for r in option_rows if r["timestamp"] == at)
        row.update(open=o, high=h, low=low, close=c)
    config = replay.validate_configuration(
        data,
        "trend_breakout_filtered",
        {},
        fees(slippage_bps=0),
        capital=25000,
        cooldown_minutes=0,
        policy_version="shared-300-3r-v1",
    )
    assert config["risk_recipe"] == PROFIT_RECIPE
    config["research_signal_hash"] = dataset.digest(signals)
    trade = replay.run_replay(data, config, research_signals=signals)["trades"][0]
    label = label_option_trade(
        option_rows,
        signal,
        data["metadata"]["contracts"][0],
        2,
        fees(slippage_bps=0),
        "13:00",
        capital=25000,
        risk_recipe=PROFIT_RECIPE,
        max_hold_minutes=15,
    )
    assert trade["exit_price"] == 116
    assert trade["gross_pnl"] == 1200
    assert trade["exit_reason"] == "profit_stop"
    assert trade["gross_planned_risk"] == 300
    assert trade["stop_price"] == 96
    assert trade["final_stop_price"] == 116
    assert label["net_pnl"] == trade["net_pnl"]
    assert label["exit_at"] == trade["exit_at"]


def test_managed_leg_restores_bound_profit_floor_after_checkpoint():
    from services.risk.profit_exit import profit_config
    from services.strategy_module import state
    from services.strategy_module.recovery import _rebuild_legacy_leg
    from services.strategy_module.risk_adapter import evaluate_leg

    config = profit_config(CONTRACT, fees(slippage_bps=0))
    leg = state._new_leg_state(
        dict(
            CONTRACT,
            leg_id=1,
            position="B",
            quantity=75,
            exchange="NFO",
            sl_pts=4,
            target_pts=12,
            profit_protection=config,
        )
    )
    leg.update(entry_avg=100, status="open", entry_filled_qty=75)
    d = evaluate_leg(leg, 112)
    assert not d.breached and d.stop_price == 108
    restored = _rebuild_legacy_leg("1", [], [], leg, {})
    assert restored["profit_protection"] == config
    d = evaluate_leg(restored, 107)
    assert d.breached and d.stop_price == 108
