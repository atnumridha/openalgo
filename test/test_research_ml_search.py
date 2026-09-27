"""Regression checks for chronological search, qualification and ranking."""

import copy
import json
import sys

import pandas as pd
import pytest


def test_runner_refuses_cached_labels_after_shared_risk_implementation_changes(
    tmp_path, monkeypatch
):
    pytest.importorskip("sklearn")
    from scripts import research_ml_search as runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    cached = tmp_path / "data/research/technical-ml-2026-09-26-corrected"
    cached.mkdir(parents=True)
    (cached / "registered-inputs.json").write_text(
        json.dumps(
            {
                "implementation_hash": "changed-risk-implementation",
                "source_hashes": {},
            }
        )
    )
    output = tmp_path / "search"
    monkeypatch.setattr(sys, "argv", ["research_ml_search.py", "--output", str(output)])
    with pytest.raises(ValueError, match="risk.*changed"):
        runner.main()
    assert not (output / "registered-search.json").exists()


def table(day, *, exit_day=None):
    return pd.DataFrame(
        {
            "timestamp": [f"{day}T10:00:00+05:30"],
            "label_exit_at": [f"{exit_day or day}T10:30:00+05:30"],
            "net_r": [1.0],
        }
    )


def metrics(net, trades=25, ambiguous=0):
    return {
        "net_pnl": net,
        "trade_count": trades,
        "ambiguous_exit_count": ambiguous,
        "max_drawdown_pct": 10,
    }


def scenarios(net, trades=25, ambiguous=0):
    return {key: metrics(net, trades, ambiguous) for key in ("base", "stress")}


def test_training_uses_only_specified_past_tables_and_drops_missing_labels():
    from services.research.ml_search import chronological_fold

    past = pd.concat([table("2025-01-01"), table("2025-01-02")], ignore_index=True)
    past.loc[1, "net_r"] = float("nan")
    data = {"past": past, "cal": table("2025-04-01"), "later": table("2025-07-01")}
    train, cal, later = chronological_fold(data, ["past"], "cal", "later")
    assert train.timestamp.tolist() == ["2025-01-01T10:00:00+05:30"]
    assert cal.timestamp.tolist() == ["2025-04-01T10:00:00+05:30"]
    assert later.timestamp.tolist() == ["2025-07-01T10:00:00+05:30"]


@pytest.mark.parametrize("which", ["past", "cal"])
def test_labels_cannot_cross_into_next_period(which):
    from services.research.ml_search import chronological_fold

    data = {"past": table("2025-01-01"), "cal": table("2025-04-01"), "later": table("2025-07-01")}
    data[which].loc[0, "label_exit_at"] = "2025-07-01T10:01:00+05:30"
    with pytest.raises(ValueError, match="overlap"):
        chronological_fold(data, ["past"], "cal", "later")


def test_reserved_dates_are_refused_in_every_role():
    from services.research.ml_search import chronological_fold

    for role in ("past", "cal", "later"):
        data = {
            "past": table("2025-01-01"),
            "cal": table("2025-04-01"),
            "later": table("2025-07-01"),
        }
        data[role] = table("2026-04-24")
        with pytest.raises(ValueError, match="reserved"):
            chronological_fold(data, ["past"], "cal", "later")


def test_incomplete_and_too_few_trades_cannot_displace_qualified_threshold():
    from services.research.ml_search import choose_threshold

    options = [
        {"threshold": 0.1, "metrics": scenarios(9999, trades=1)},
        {"threshold": 0.2, "metrics": scenarios(100, trades=20)},
        {"threshold": 0.3, "metrics": {"base": metrics(None), "stress": metrics(99999)}},
    ]
    assert choose_threshold(options)["threshold"] == 0.2


def test_ambiguous_calibration_and_ties_use_conservative_deterministic_selection():
    from services.research.ml_search import choose_threshold

    options = [
        {"threshold": 0.3, "metrics": scenarios(9999, ambiguous=1)},
        {"threshold": 0.2, "metrics": scenarios(100)},
        {"threshold": 0.1, "metrics": scenarios(100)},
    ]
    assert choose_threshold(options)["threshold"] == 0.1


def test_positive_sum_does_not_hide_a_losing_fold_or_failed_calibration():
    from services.research.ml_search import summarize_candidate

    folds = [
        {"calibration_passes": True, "metrics": scenarios(net), "baseline": scenarios(0)}
        for net in (500, 500, -100)
    ]
    result = summarize_candidate("example", folds)
    assert result["sum_stress_net_pnl"] == 900
    assert result["worst_stress_net_pnl"] == -100
    assert result["positive_periods"] == 2
    assert result["passes_development_screen"] is False
    folds[-1]["metrics"] = scenarios(100)
    folds[0]["calibration_passes"] = False
    assert summarize_candidate("example", folds)["passes_development_screen"] is False


def test_full_screen_needs_each_period_and_sufficient_real_trades():
    from services.research.ml_search import summarize_candidate

    folds = [
        {"calibration_passes": True, "metrics": scenarios(100), "baseline": scenarios(0)}
        for _ in range(3)
    ]
    assert summarize_candidate("example", folds)["passes_development_screen"] is True
    assert summarize_candidate("example", folds[:2])["passes_development_screen"] is False
    fewer = copy.deepcopy(folds)
    fewer[0]["metrics"] = scenarios(100, trades=19)
    assert summarize_candidate("example", fewer)["passes_development_screen"] is False
    folds[0]["metrics"]["stress"]["net_pnl"] = None
    result = summarize_candidate("example", folds)
    assert result["passes_development_screen"] is False
    assert result["sum_stress_net_pnl"] is None


def test_rank_prefers_consistency_over_one_large_winner():
    from services.research.ml_search import rank_candidates, summarize_candidate

    def candidate(name, nets):
        return summarize_candidate(
            name,
            [
                {"calibration_passes": False, "metrics": scenarios(n), "baseline": scenarios(0)}
                for n in nets
            ],
        )

    spike = candidate("spike", [10000, -100, -100])
    consistent = candidate("consistent", [100, 100, 100])
    assert rank_candidates([spike, consistent])[0]["candidate"] == "consistent"
