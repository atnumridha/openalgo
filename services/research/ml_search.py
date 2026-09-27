"""Pure chronology and evidence checks for a bounded offline model search."""

import math

import pandas as pd

from services.research.ml import assert_chronology, validation_qualifies

RESERVED_START = "2026-04-24"


def chronological_fold(tables, training_keys, calibration_key, later_key):
    keys = [*training_keys, calibration_key, later_key]
    if not training_keys or len(set(keys)) != len(keys):
        raise ValueError("Training, calibration and later periods must be distinct")
    for key in keys:
        table = tables[key]
        if table.empty:
            raise ValueError("Chronological splits require observations")
        for column in ("timestamp", "label_exit_at"):
            if column in table and (table[column].dropna().str[:10] >= RESERVED_START).any():
                raise ValueError("The reserved final period cannot be used in development")
    training = pd.concat([tables[key] for key in training_keys], ignore_index=True)
    training = training.dropna(subset=["net_r", "label_exit_at"]).sort_values("timestamp")
    calibration, later = tables[calibration_key], tables[later_key]
    assert_chronology(training, calibration)
    assert_chronology(calibration, later)
    return training, calibration, later


def _complete(metrics):
    return all(
        metrics[s]["net_pnl"] is not None and math.isfinite(metrics[s]["net_pnl"])
        for s in ("base", "stress")
    )


def choose_threshold(candidates):
    if not candidates:
        raise ValueError("Threshold selection requires recorded candidates")

    def key(candidate):
        metrics = candidate["metrics"]
        complete = _complete(metrics)
        return (
            complete and validation_qualifies(metrics),
            complete,
            complete and min(metrics[s]["trade_count"] for s in ("base", "stress")) >= 20,
            metrics["stress"]["net_pnl"] if complete else -math.inf,
            metrics["base"]["net_pnl"] if complete else -math.inf,
            -candidate["threshold"],
        )

    return max(candidates, key=key)


def summarize_candidate(name, folds):
    if not folds:
        raise ValueError("A candidate must contain evaluation folds")
    complete = all(_complete(f["metrics"]) for f in folds)
    metrics = [f["metrics"] for f in folds]
    sums = {
        scenario: (round(sum(m[scenario]["net_pnl"] for m in metrics), 2) if complete else None)
        for scenario in ("base", "stress")
    }
    baseline_complete = all(_complete(f["baseline"]) for f in folds)
    improvement = (
        complete
        and baseline_complete
        and all(
            sums[s] > round(sum(f["baseline"][s]["net_pnl"] for f in folds), 2)
            for s in ("base", "stress")
        )
    )
    positive = sum(
        _complete(m) and all(m[s]["net_pnl"] > 0 for s in ("base", "stress")) for m in metrics
    )
    trades = sum(m["base"]["trade_count"] for m in metrics)
    checks = {
        "three_folds_completed": len(folds) == 3,
        "all_calibrations_pass": all(f["calibration_passes"] for f in folds),
        "complete_outcomes": complete,
        "no_ambiguous_exits": all(
            m[s]["ambiguous_exit_count"] == 0 for m in metrics for s in ("base", "stress")
        ),
        "all_later_periods_positive_base_and_stress": positive == len(folds),
        "at_least_20_base_trades_each_and_60_total": (
            trades >= 60 and all(m["base"]["trade_count"] >= 20 for m in metrics)
        ),
        "improves_aggregate_rule_baseline": improvement,
    }
    return {
        "candidate": name,
        "folds": folds,
        "positive_periods": positive,
        "sum_base_net_pnl": sums["base"],
        "sum_stress_net_pnl": sums["stress"],
        "worst_stress_net_pnl": (
            min(m["stress"]["net_pnl"] for m in metrics) if complete else None
        ),
        "base_trade_count": trades,
        "checks": checks,
        "passes_development_screen": all(checks.values()),
        "eligible_for_live": False,
    }


def rank_candidates(candidates):
    def key(candidate):
        worst, total = candidate["worst_stress_net_pnl"], candidate["sum_stress_net_pnl"]
        return (
            -int(candidate["passes_development_screen"]),
            -candidate["positive_periods"],
            -worst if worst is not None else math.inf,
            -total if total is not None else math.inf,
            candidate["candidate"],
        )

    return sorted(candidates, key=key)
