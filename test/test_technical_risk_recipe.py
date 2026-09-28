"""Versioned technical-stop admission and immutable historical recipe evidence."""

from copy import deepcopy
from decimal import Decimal

import pytest
from test_low_risk_recipe import scheduled_data
from test_trading_research import fees

from services.research import dataset, replay
from services.research.ml import label_option_trade
from services.research.ml_live import entry_plan
from services.risk import PositionRisk
from services.risk import cash_exit as exits
from services.risk.profit_exit import evaluate_profit, profit_config

NEW = "one-lot-technical-profit-trail-v3"
OLD_FIXED = "one-lot-cash300-3r-v1"
OLD_PROFIT = "one-lot-cash300-profit-trail-v2"
OLD_POLICY = "shared-300-3r-v1"
NEW_POLICY = "equity-1pct-v2"
CONTRACT = {"symbol": "NIFTY_CE", "lot_size": 75, "multiplier": 1, "tick_size": 0.05}


@pytest.mark.parametrize("distance,stop,gross", [(10, "90", "750"), ("3.11", "96.85", "236.25")])
def test_technical_geometry_rounds_away_and_never_tightens_to_cash_cap(distance, stop, gross):
    actual, target, planned = exits.recipe_exit(100, distance, CONTRACT, NEW)
    assert actual == Decimal(stop)
    assert planned == Decimal(gross)
    assert target == Decimal("112")


def test_new_admission_skips_unaffordable_technical_stop_and_counts_fees():
    with pytest.raises(ValueError, match="budget"):
        entry_plan(CONTRACT, entry=100, atr=5, costs=fees(), capital=25000, risk_recipe=NEW)
    # 3.2 points x 75 = 240, so 20 rupees per side cannot fit the 250 all-in cap.
    with pytest.raises(ValueError, match="budget"):
        entry_plan(
            CONTRACT,
            entry=32,
            atr=1,
            costs=fees(brokerage_per_order=20),
            capital=25000,
            risk_recipe=NEW,
        )


def test_new_admission_one_lot_uses_away_tick_and_equity_reduction():
    cost = fees(
        slippage_bps=0,
        brokerage_per_order=0,
        exchange_rate=0,
        sebi_rate=0,
        gst_rate=0,
        stamp_buy_rate=0,
        stt_sell_rate=0,
    )
    plan = entry_plan(CONTRACT, entry=31.05, atr=1, costs=cost, capital=25000, risk_recipe=NEW)
    assert (plan["stop_price"], plan["quantity"], plan["gross_planned_risk"]) == (27.9, 75, 236.25)
    with pytest.raises(ValueError, match="budget"):
        entry_plan(
            CONTRACT,
            entry=31.05,
            atr=1,
            costs=cost,
            capital=25000,
            equity=23750,
            peak=25000,
            risk_recipe=NEW,
        )


@pytest.mark.parametrize(
    "recipe,policy",
    [(OLD_FIXED, NEW_POLICY), (OLD_PROFIT, NEW_POLICY), (NEW, OLD_POLICY), (NEW, None)],
)
def test_mixed_recipe_policy_fails_closed(recipe, policy):
    config = {
        "risk_recipe": recipe,
        "risk_policy_version": policy,
        "parameters": {"stop_pct": 0.1, "target_pct": 0.3},
        "max_hold_minutes": 15,
        "pacing": exits.pacing_config(5),
    }
    with pytest.raises(ValueError, match="bound|policy"):
        exits.current_configuration(config)


@pytest.mark.parametrize(
    "recipe,golden",
    [
        (OLD_FIXED, "d9b95a514e2ef2c80714beef53bcdc07c7b5914a044b05178a3c30225fe3ab5c"),
        (OLD_PROFIT, "c76c22ffd57aab3fc74e4fcbd49b450cb5301cddaf725fbd2f47800e24525e3d"),
    ],
)
def test_frozen_legacy_replay_report_is_identical(recipe, golden):
    data, signals = scheduled_data([False, False, True, False, False, False, True])
    config = replay.validate_configuration(
        data, "trend_breakout_filtered", {}, fees(slippage_bps=0), capital=25000, cooldown_minutes=0
    )
    config.update(
        risk_recipe=recipe,
        risk_policy_version=OLD_POLICY,
        engine_version="closed-bar-profit-trail-v4",
        research_signal_hash=dataset.digest(signals),
    )
    report = replay.run_replay(data, config, research_signals=signals)
    assert dataset.digest(report) == golden


@pytest.mark.parametrize("recipe", [OLD_PROFIT, NEW])
def test_versioned_profit_ratchets_keep_baseline_and_no_hard_target(recipe):
    config = profit_config(CONTRACT, fees(slippage_bps=0), recipe=recipe)
    assert config["version"] == recipe
    risk = PositionRisk(entry_price=100, quantity=75, stop_price=90, target_price=112)
    decision = evaluate_profit(risk, 120, config)
    assert (decision.stop_price, decision.target_price, decision.breached) == (116, None, False)


def test_default_configuration_binds_new_recipe():
    data, _ = scheduled_data([True])
    config = replay.validate_configuration(data, "trend_breakout_filtered", {}, fees())
    assert (config["risk_recipe"], config["risk_policy_version"]) == (
        exits.CASH_RISK_RECIPE,
        "fixed-300-v3",
    )


@pytest.mark.parametrize("stress", [False, True])
@pytest.mark.parametrize("recipe", [NEW, exits.CASH_RISK_RECIPE])
def test_new_label_live_replay_use_same_unclamped_stop_and_all_in_risk(stress, recipe):
    data, signals = scheduled_data([True])
    data = deepcopy(data)
    for row in data["rows"]:
        if row["symbol"] == "NIFTY_CE":
            for key in ("open", "high", "low", "close"):
                row[key] = round(row[key] * 0.25, 2)
    data = dataset.validate_dataset(data)
    costs = fees(slippage_bps=0, brokerage_per_order=0)
    config = replay.validate_configuration(
        data,
        "trend_breakout_filtered",
        {},
        costs,
        capital=25000,
        cooldown_minutes=0,
        risk_recipe=recipe,
    )
    config["research_signal_hash"] = dataset.digest(signals)
    report = replay.run_replay(data, config, stress=stress, research_signals=signals)
    assert report["trades"]
    trade = report["trades"][0]
    effective = dict(costs)
    if stress:
        effective["slippage_bps"] = 10
    contract = data["metadata"]["contracts"][0]
    label = label_option_trade(
        [r for r in data["rows"] if r["symbol"] == "NIFTY_CE"],
        next(iter(signals)),
        contract,
        0.5,
        effective,
        "13:00",
        max_hold_minutes=15,
        capital=25000,
        risk_recipe=recipe,
    )
    live = entry_plan(
        contract,
        entry=trade["entry_price"],
        atr=0.5,
        costs=effective,
        capital=25000,
        risk_recipe=recipe,
    )
    assert label is not None
    assert (label["net_pnl"], label["exit_at"]) == (trade["net_pnl"], trade["exit_at"])
    for field in ("stop_price", "target_price", "planned_risk", "gross_planned_risk"):
        assert label[field] == pytest.approx(trade[field])
        assert live[field] == pytest.approx(trade[field])
    assert trade["quantity"] == 75
    assert trade["budget_after_close"]["day_start_equity"] == 25000
    assert trade["budget_after_close"]["daily_limit"] == (750 if recipe == NEW else 2000)


@pytest.mark.parametrize(
    "recipe,price,stop",
    [
        (NEW, 109.95, 106.95),
        (NEW, 110, 109),
        (NEW, 115, 112),
        (NEW, 118, 115),
        (OLD_PROFIT, 110, 107),
    ],
)
def test_new_thousand_profit_milestone_locks_nine_hundred_and_then_trails(recipe, price, stop):
    from dataclasses import replace

    config = profit_config(CONTRACT, fees(slippage_bps=0), recipe=recipe)
    risk = PositionRisk(entry_price=100, quantity=100, stop_price=95, target_price=109)
    decision = evaluate_profit(risk, price, config)
    assert decision.stop_price == stop
    assert not decision.breached
    carried = replace(risk, stop_price=decision.stop_price, highest_price=decision.highest_price)
    retreat = evaluate_profit(carried, price - 0.1, config)
    assert retreat.stop_price == stop


def test_queued_current_configuration_does_not_relabel_legacy_recipe(monkeypatch):
    from services.research import jobs

    data, _ = scheduled_data([True])
    data["sessions"] = [str(i) for i in range(100)]
    config = {
        "candidate": "trend_breakout_filtered",
        "parameters": replay.DEFAULTS,
        "max_hold_minutes": 15,
        "pacing": exits.pacing_config(5),
        "risk_recipe": OLD_PROFIT,
        "risk_policy_version": OLD_POLICY,
    }
    monkeypatch.setattr(jobs, "validate_configuration", lambda *a, **k: deepcopy(config))

    class Store:
        def get_dataset(self, *a):
            return data

        def queue_run(self, *a, **k):
            pytest.fail("A legacy recipe was silently upgraded and queued")

    with pytest.raises(ValueError, match="current.*recipe|recipe.*current"):
        jobs.queue_run(
            Store(),
            "owner",
            {"dataset_id": 1, "candidate": "trend_breakout_filtered", "costs": fees()},
        )


def test_live_entry_accepts_serialized_daily_baseline_and_cannot_replenish_it():
    cost = fees(
        slippage_bps=0,
        brokerage_per_order=0,
        exchange_rate=0,
        sebi_rate=0,
        gst_rate=0,
        stamp_buy_rate=0,
        stt_sell_rate=0,
    )
    plan = entry_plan(
        CONTRACT,
        entry=25,
        atr=1,
        costs=cost,
        capital=25000,
        risk_recipe=NEW,
        day_start_equity=25000.0,
    )
    assert plan["quantity"] == 75
    from services.risk.budget import BudgetTrade

    loss = BudgetTrade(
        "1",
        "2026-01-01",
        "shared",
        "closed",
        Decimal("150"),
        net_pnl=Decimal("-150"),
        filled=True,
        close_sequence=1,
        completion_day="2026-01-01",
    )
    with pytest.raises(ValueError, match="budget"):
        entry_plan(
            CONTRACT,
            entry=25,
            atr=1,
            costs=cost,
            capital=25000,
            risk_recipe=NEW,
            day="2026-01-01",
            ledger=(loss,),
            day_start_equity=10000.0,
        )


def test_new_gross_profit_floor_continues_trailing_even_when_fees_exceed_profit():
    config = profit_config(CONTRACT, fees(slippage_bps=0, brokerage_per_order=1000), recipe=NEW)
    risk = PositionRisk(entry_price=100, quantity=100, stop_price=95, target_price=109)
    assert evaluate_profit(risk, 115, config).stop_price == 112
