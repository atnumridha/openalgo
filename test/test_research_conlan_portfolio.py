"""The full-portfolio adapter binds quoted contracts and seals final sessions."""

import copy
import json
import sys

import pytest
from test_trading_research import payload

from scripts.research_conlan_portfolio import (
    bound_rule_schedule,
    load_global_provenance,
    main,
    run_portfolio_study,
    study_source_hashes,
)
from services.research.dataset import validate_dataset


def test_direct_ml_study_binds_executable_admission_recipe(monkeypatch):
    from test_research_random_forest import ml_payload
    from test_trading_research import fees

    from scripts import research_conlan_portfolio as runner
    from services.risk.admission import ML_RISK_RECIPE

    data = validate_dataset(ml_payload())
    seen = []
    monkeypatch.setattr(runner, "bound_rule_schedule", lambda *_: {})
    monkeypatch.setattr(runner, "run_replay", lambda *_a, **_k: {"metrics": {}})
    monkeypatch.setattr(runner.jobs, "run_ml_experiment",
                        lambda _data, config: seen.append(config["risk_recipe"]) or {"ml": {}})
    result = runner.run_portfolio_study(data, fees(), protected_dates=data["sessions"][-60:])
    assert seen == [ML_RISK_RECIPE] * 3
    assert all(result["results"][f"ml-{hold}m"]["configuration"]["risk_recipe"] == ML_RISK_RECIPE
               for hold in (5, 10, 15))
    assert all("risk_recipe" not in result["results"][f"{family}-{hold}m"]["configuration"]
               for family in runner.conlan.FAMILIES for hold in (5, 10, 15))


def test_rule_schedule_only_uses_development_and_binds_observed_contract():
    data = validate_dataset(payload(80))
    schedule = bound_rule_schedule(data, "sma_macd", data["sessions"][:-60])
    assert all(at[:10] in data["sessions"][:-60] for at in schedule)
    assert all(choice == {"direction": "CE", "symbol": "NIFTY_CE"} for choice in schedule.values())


def test_global_protected_dates_refuse_development_overlap():
    data = validate_dataset(payload(80))
    with pytest.raises(ValueError, match="globally protected"):
        run_portfolio_study(
            data, {}, protected_dates=set(data["sessions"][-60:]) | {data["sessions"][0]}
        )


def test_exported_session_split_must_match_canonical_candles():
    data = validate_dataset(payload(80))
    changed = copy.deepcopy(data)
    changed["sessions"][-60], changed["sessions"][-61] = (
        changed["sessions"][-61],
        changed["sessions"][-60],
    )
    with pytest.raises(ValueError, match="canonical"):
        run_portfolio_study(changed, {}, protected_dates=data["sessions"][-60:])


def test_global_provenance_is_required_for_subset_study():
    data = validate_dataset(payload(80))
    with pytest.raises(ValueError, match="protected"):
        run_portfolio_study(data, {})


def test_rule_and_runner_source_changes_are_recorded(tmp_path):
    for relative in ("services/research/conlan.py", "scripts/research_conlan_portfolio.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("original")
    before = study_source_hashes(tmp_path)
    (tmp_path / "services/research/conlan.py").write_text("changed")
    after = study_source_hashes(tmp_path)
    assert before["services/research/conlan.py"] != after["services/research/conlan.py"]
    assert (
        before["scripts/research_conlan_portfolio.py"]
        == after["scripts/research_conlan_portfolio.py"]
    )


def test_subset_cli_requires_global_provenance_and_rejects_other_final_date(tmp_path, monkeypatch):
    data = validate_dataset(payload(80))
    dataset_path = tmp_path / "dataset-3.json"
    dataset_path.write_text(json.dumps(data))
    costs_path = tmp_path / "costs.json"
    costs_path.write_text(json.dumps({"broker": "kotak", "exchange": "NFO"}))
    argv = [
        "study",
        "--dataset",
        str(dataset_path),
        "--costs",
        str(costs_path),
        "--output",
        str(tmp_path / "out"),
        "--current-kotak-assumption",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="2"):
        main()
    provenance = tmp_path / "provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "protected_dates": data["sessions"][-60:] + [data["sessions"][0]],
                "dataset_ids": [3, 4],
            }
        )
    )
    monkeypatch.setattr(sys, "argv", argv + ["--protected-dates", str(provenance)])
    with pytest.raises(ValueError, match="globally protected"):
        main()


def test_provenance_content_change_changes_recorded_identity(tmp_path):
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({"protected_dates": ["2026-01-01"], "dataset_ids": [3]}))
    before_dates, before_hash = load_global_provenance(provenance)
    provenance.write_text(json.dumps({"protected_dates": ["2026-01-01"], "dataset_ids": [3, 4]}))
    after_dates, after_hash = load_global_provenance(provenance)
    assert before_dates == after_dates
    assert before_hash != after_hash
