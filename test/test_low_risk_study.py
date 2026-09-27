"""Bounded development research never refits by pacing or consumes protected days."""

import json
from copy import deepcopy
from datetime import date, timedelta

import pytest


def test_global_protected_dates_fail_before_fit():
    from services.research.low_risk_study import development_sessions

    days = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(120)]
    with pytest.raises(ValueError, match="protected"):
        development_sessions({"sessions": days}, {days[1]})
    assert development_sessions({"sessions": days}, set(days[-60:])) == days[:60]


def test_scenarios_reuse_one_fit_per_hold_and_preserve_schedule(tmp_path, monkeypatch):
    from test_low_risk_recipe import scheduled_data
    from test_trading_research import fees

    from services.research import low_risk_study as study
    from services.research.dataset import digest
    from services.research.replay import validate_configuration

    data, signals = scheduled_data([True])
    config = validate_configuration(data, "trend_breakout_filtered", {}, fees(), capital=25000)
    calls = []

    def fit(data, configuration, **kwargs):
        calls.append(configuration["max_hold_minutes"])
        rc = dict(configuration, research_signal_hash=digest(signals), research_model_hash="f" * 64)
        return {
            "research_signals": signals,
            "replay_configuration": rc,
            "evaluated_sessions": data["sessions"],
            "ml": {"artifact": {}, "model_hash": "f" * 64},
        }

    monkeypatch.setattr(study, "run_ml_experiment", fit)
    summaries = study.run_window(data, config, tmp_path)
    assert calls == [5, 10, 15]
    assert len(summaries) == 18
    configs = []
    for path in tmp_path.glob("hold-*/*-base.json"):
        item = json.loads(path.read_text())
        configs.append(item["configuration"])
        assert item["report"]["trades"][0]["quantity"] == 75
        assert item["configuration"]["research_signal_hash"] == digest(signals)
    assert len(configs) == 9
    assert len({digest(c) for c in configs}) == 9
    with pytest.raises(FileExistsError):
        study.run_window(data, config, tmp_path)
