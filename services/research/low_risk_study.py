"""Reproducible exploratory development study; no store, broker or final-job writes.

Run with ``python -m services.research.low_risk_study --inputs PATH --output NEW_PATH``.
The five canonical exports and their input-manifest/provenance must already exist.
"""

import argparse
import hashlib
import json
from pathlib import Path

from services.research.dataset import digest, validate_dataset
from services.research.jobs import implementation_hash, run_ml_experiment, validate_ml_settings
from services.research.replay import run_replay, validate_configuration
from services.risk.cash_exit import pacing_config

HOLDS = (5, 10, 15)
COOLDOWNS = (0, 5, 15)
DATASETS = (3, 4, 5, 6, 7)


def development_sessions(data, protected):
    sessions = data["sessions"]
    if len(sessions) != 120 or sessions != sorted(set(sessions)):
        raise ValueError("Study requires exactly 60 development and 60 excluded final sessions")
    selected = sessions[:-60]
    if set(selected) & set(protected) or any(
        "2026-04-24" <= day <= "2026-07-21" for day in selected
    ):
        raise ValueError("Development sessions overlap globally protected final dates")
    return selected


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    path.chmod(0o444)


def run_window(data, configuration, output):
    """Fit 3 held-out models (+ 9 CV estimators), replay each at all 3 cooldowns."""
    output = Path(output)
    if any((output / f"hold-{hold}").exists() for hold in HOLDS):
        raise FileExistsError("Study output is immutable; select a fresh output directory")
    summaries = []
    for hold in HOLDS:
        config = dict(
            configuration,
            max_hold_minutes=hold,
            ml_settings=validate_ml_settings(
                {
                    "folds": 3,
                    "min_train_sessions": 10,
                    "estimators": 100,
                    "threshold": 0.5,
                    "max_hold_minutes": hold,
                }
            ),
        )
        location = output / f"hold-{hold}"
        try:
            model = run_ml_experiment(data, config, include_schedule=True)
        except ValueError as exc:
            # A failed sample/feature/fit gate is a result, never an invented zero-trade model.
            result = {"status": "research_unavailable", "reason": str(exc), "configuration": config}
            _write(location / "unavailable.json", result)
            summaries.append({"hold": hold, **result})
            continue
        schedule = model["research_signals"]
        base = model["replay_configuration"]
        sessions = model["evaluated_sessions"]
        _write(location / "model.json", {"configuration": config, "report": model})
        for cooldown in COOLDOWNS:
            varied = dict(base, pacing=pacing_config(cooldown))
            for stress in (False, True):
                report = run_replay(
                    data, varied, sessions, stress=stress, research_signals=schedule
                )
                scenario = "stress" if stress else "base"
                name = f"cooldown-{cooldown}-{scenario}.json"
                _write(
                    location / name,
                    {
                        "configuration": varied,
                        "configuration_hash": digest(varied),
                        "sessions": sessions,
                        "stress": stress,
                        "report": report,
                    },
                )
                summaries.append(
                    {
                        "hold": hold,
                        "cooldown": cooldown,
                        "scenario": scenario,
                        "file": str(Path(f"hold-{hold}") / name),
                        "metrics": report["metrics"],
                        "rejections": report["rejections"],
                        "insufficient_samples": report["metrics"]["trade_count"] < 20,
                    }
                )
    return summaries


def run_study(inputs, output):
    inputs, output = Path(inputs), Path(output)
    if output.exists():
        raise FileExistsError("Study output is immutable; select a fresh output directory")
    manifest = json.loads((inputs / "input-manifest.json").read_text())
    names = [*(f"dataset-{i}.json" for i in DATASETS), "research-costs.json", "provenance.json"]
    loaded, hashes = {}, {}
    for name in names:
        raw = (inputs / name).read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        expected = manifest.get(name, {})
        if expected.get("sha256") != checksum or expected.get("bytes") != len(raw):
            raise ValueError(f"Input manifest mismatch: {name}")
        loaded[name], hashes[name] = json.loads(raw), checksum
    datasets = {}
    protected = set(loaded["provenance.json"]["protected_dates"])
    for identifier in DATASETS:
        raw = loaded[f"dataset-{identifier}.json"]
        normalized = validate_dataset(raw)
        if (
            raw.get("content_hash") != normalized["content_hash"]
            or raw.get("sessions") != normalized["sessions"]
        ):
            raise ValueError(f"Dataset {identifier} is not a canonical immutable export")
        datasets[identifier] = normalized
        protected.update(normalized["sessions"][-60:])
    windows = {
        identifier: development_sessions(data, protected) for identifier, data in datasets.items()
    }
    source = implementation_hash()
    configs = {
        identifier: validate_configuration(
            data,
            "trend_breakout_filtered",
            {},
            loaded["research-costs.json"],
            seed=42,
            capital=25000,
            # This named historical study retains its original cash/profit recipe.
            policy_version="shared-300-3r-v1",
        )
        for identifier, data in datasets.items()
    }
    output.mkdir(parents=True)
    summary = []
    for identifier, data in datasets.items():
        config = dict(configs[identifier], implementation_hash=source, run_kind="ml")
        summary.append(
            {
                "dataset": identifier,
                "development_sessions": windows[identifier],
                "scenarios": run_window(data, config, output / f"dataset-{identifier}"),
            }
        )
    if implementation_hash() != source:
        raise RuntimeError("Source changed during the study; outputs are invalid")
    files = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*.json"))
    }
    result = {
        "study": "cash300-3r-development-v1",
        "status": "exploratory_only",
        "capital": 25000,
        "implementation_hash": source,
        "input_hashes": hashes,
        "input_manifest_sha256": hashlib.sha256(
            (inputs / "input-manifest.json").read_bytes()
        ).hexdigest(),
        "protected_dates": sorted(protected),
        "files": files,
        "windows": summary,
        "expected_estimator_fits": {"held_out_development": 15, "cross_validation": 45},
        "qualification": {
            "eligible_for_live": False,
            "reason": "Repeated development research; no fresh final or forward evidence. No settings or activation changed.",
        },
    }
    _write(output / "manifest.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_study(args.inputs, args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "windows": len(result["windows"]),
                "output": str(Path(args.output).resolve()),
            }
        )
    )


if __name__ == "__main__":
    main()
