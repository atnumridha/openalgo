"""Offline Conlan option adaptations through the shared serial replay engine.

Input JSON files are exported research datasets and a dated fee schedule. The
last 60 sessions stay sealed. This runner never touches a broker or database.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.research import conlan, jobs
from services.research.dataset import digest, validate_dataset
from services.research.replay import run_replay, validate_configuration
from services.risk.admission import ML_RISK_RECIPE
from services.risk.budget import BudgetPolicy

ROOT = Path(__file__).resolve().parents[1]
STUDY_SOURCES = ("services/research/conlan.py", "scripts/research_conlan_portfolio.py")


def study_source_hashes(root=ROOT):
    return {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in STUDY_SOURCES
    }


def canonical_export(data):
    """Recompute the split from candles and reject changed export metadata."""
    canonical = validate_dataset(data)
    for key, value in canonical.items():
        if data.get(key) != value:
            raise ValueError(f"Export differs from canonical dataset: {key}")
    return canonical


def load_global_provenance(path):
    raw = path.read_bytes()
    source = json.loads(raw)
    if not isinstance(source, dict) or not isinstance(source.get("protected_dates"), list):
        raise ValueError("Global provenance must contain a protected_dates array")
    dates = source["protected_dates"]
    if not dates or any(not isinstance(day, str) for day in dates):
        raise ValueError("Global protected dates must be nonempty date strings")
    return set(dates), hashlib.sha256(raw).hexdigest()


def bound_rule_schedule(data, family, sessions):
    """Bind the observed signal's first ranked quoted contract before replay."""
    allowed = set(sessions)
    meta = data["metadata"]
    underlying = [
        row
        for row in data["rows"]
        if row["symbol"] == meta["underlying_symbol"] and row["timestamp"][:10] in allowed
    ]
    frame = pd.DataFrame(underlying).set_index("timestamp")
    frame.index = pd.DatetimeIndex(frame.index)
    signals = conlan.rule_signals(frame, family)
    quotes = {(row["timestamp"], row["symbol"]) for row in data["rows"]}
    schedule = {}
    for at, row in signals[signals.direction.ne("")].iterrows():
        day, direction = at.strftime("%Y-%m-%d"), row.direction
        choices = sorted(
            (
                contract
                for contract in meta["contracts"]
                if contract["option_type"] == direction
                and contract["expiry"] >= day
                and (at.isoformat(), contract["symbol"]) in quotes
            ),
            key=lambda contract: (
                contract["expiry"],
                abs(contract["strike"] - row.close),
                contract["symbol"],
            ),
        )
        if choices:
            schedule[at.isoformat()] = {"direction": direction, "symbol": choices[0]["symbol"]}
    return schedule


def run_portfolio_study(data, costs, *, capital=25000, include_ml=True, protected_dates=None):
    """Run six rule portfolios and three ML portfolios on development only."""
    data = canonical_export(data)
    if len(data["sessions"]) < 80:
        raise ValueError("At least 80 sessions are needed to seal the final 60")
    development = data["sessions"][:-60]
    protected = set(protected_dates) if protected_dates is not None else set()
    if not set(data["sessions"][-60:]) <= protected:
        raise ValueError("A global protected-date provenance covering final sessions is required")
    if set(development) & protected:
        raise ValueError("Development sessions intersect globally protected final sessions")
    source_hashes = study_source_hashes()
    results = {}
    for family in conlan.FAMILIES:
        schedule = bound_rule_schedule(data, family, development)
        for hold in (5, 10, 15):
            config = validate_configuration(
                data, "trend_breakout_filtered", {}, costs, capital=capital
            )
            config.update(
                max_hold_minutes=hold,
                research_signal_hash=digest(schedule),
                risk_policy_version=BudgetPolicy().version,
                implementation_hash=jobs.implementation_hash(),
                study_source_hashes=source_hashes,
            )
            report = run_replay(data, config, development, research_signals=schedule)
            stress = run_replay(data, config, development, stress=True, research_signals=schedule)
            results[f"{family}-{hold}m"] = {
                "adaptation": "Conlan underlying direction mapped to a prebound observed long option; fixed replay stops, sizing, fees and serial portfolio admission. Not the original stock portfolio or one-lot opportunity comparison.",
                "configuration": config,
                "signal_count": len(schedule),
                "schedule": schedule,
                "study_source_hashes": source_hashes,
                "report": report,
                "stress": stress,
            }
    if include_ml:
        for hold in (5, 10, 15):
            config = validate_configuration(
                data, "trend_breakout_filtered", {}, costs, capital=capital
            )
            config.update(
                risk_policy_version=BudgetPolicy().version,
                risk_recipe=ML_RISK_RECIPE,
                implementation_hash=jobs.implementation_hash(),
                study_source_hashes=source_hashes,
                ml_settings={
                    "folds": 3,
                    "min_train_sessions": 10,
                    "estimators": 100,
                    "threshold": 0.5,
                    "max_hold_minutes": hold,
                },
            )
            results[f"ml-{hold}m"] = {
                "configuration": config,
                "study_source_hashes": source_hashes,
                "report": jobs.run_ml_experiment(data, config),
            }
    return {
        "dataset_hash": data["content_hash"],
        "capital": capital,
        "development_sessions": len(development),
        "protected_final_sessions": 60,
        "global_protected_dates_hash": digest(sorted(protected)),
        "study_source_hashes": source_hashes,
        "cost_basis": "Supplied dated research cost schedule; caller must label retrospective current Kotak rates as an assumption.",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, action="append", required=True)
    parser.add_argument("--costs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capital", type=int, default=25000)
    parser.add_argument("--skip-ml", action="store_true")
    parser.add_argument(
        "--protected-dates",
        type=Path,
        required=True,
        help="Global provenance JSON with protected_dates for all prepared datasets",
    )
    parser.add_argument("--current-kotak-assumption", action="store_true", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output directory already exists; choose a new path")
    costs = json.loads(args.costs.read_text())
    if costs.get("broker") != "kotak" or costs.get("exchange") != "NFO":
        parser.error("The supplied research schedule must be scoped to Kotak NFO")
    stems = [path.stem for path in args.dataset]
    if len(set(stems)) != len(stems):
        parser.error("Dataset file stems must be unique")
    protected, provenance_hash = load_global_provenance(args.protected_dates)
    for path in args.dataset:
        data = canonical_export(json.loads(path.read_text()))
        if not set(data["sessions"][-60:]) <= protected:
            parser.error(f"Global provenance does not cover {path.name} final sessions")
    args.output.mkdir(parents=True)
    source_hashes = study_source_hashes()
    shutil.copyfile(args.protected_dates, args.output / "provenance.json")
    for relative in STUDY_SOURCES:
        target = args.output / "source-snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    if study_source_hashes(args.output / "source-snapshot") != source_hashes:
        raise ValueError("Study source changed during snapshot capture")
    for path in args.dataset:
        data = json.loads(path.read_text())
        result = run_portfolio_study(
            data,
            costs,
            capital=args.capital,
            include_ml=not args.skip_ml,
            protected_dates=protected,
        )
        (args.output / f"{path.stem}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    if study_source_hashes() != source_hashes:
        raise ValueError("Study source changed while the runner was executing")
    if hashlib.sha256(args.protected_dates.read_bytes()).hexdigest() != provenance_hash:
        raise ValueError("Global provenance changed while the runner was executing")
    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "assumption": "Current Kotak NFO charges applied retrospectively for research, not verified historical rates.",
                "datasets": stems,
                "capital": args.capital,
                "protected_final_sessions_per_dataset": 60,
                "global_protected_dates": sorted(protected),
                "global_provenance_hash": provenance_hash,
                "study_source_hashes": source_hashes,
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
