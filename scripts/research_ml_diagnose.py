"""Report later feature drift against a completed run's training observations."""

import argparse
import json
import os
import sys
from pathlib import Path

os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from services.research.ml_diagnostics import feature_drift
from utils.logging import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Inspect offline feature drift; never refits a model."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    root = parser.parse_args().run_dir
    with (root / "frozen-selection.json").open() as stream:
        frozen = json.load(stream)
    features = frozen["features"]
    training = pd.concat(
        [pd.read_parquet(root / f"opportunities-{key}.parquet") for key in ("q1", "q2")]
    ).dropna(subset=["net_r", "label_exit_at"])
    output = {
        "method": "PSI with training-decile bins and a fixed 0.5 pseudocount; training ranges and means. Descriptive diagnostics, not significance tests or calibrated probabilities.",
        "training_rows": len(training),
        "training_sessions": int(training.timestamp.str[:10].nunique()),
        "overlap_note": "Within-session payoff labels overlap; observation count is not the number of independent trades.",
        "periods": {},
    }
    for key in ("q3", "q4", "2026"):
        later = pd.read_parquet(root / f"opportunities-{key}.parquet")
        output["periods"][key] = feature_drift(training[features], later[features])
        ordered = sorted(output["periods"][key].items(), key=lambda x: x[1]["psi"], reverse=True)
        logger.info(
            "%s largest distribution shifts: %s",
            key,
            [(k, round(v["psi"], 3)) for k, v in ordered[:5]],
        )
    with (root / "drift-diagnostics.json").open("w") as stream:
        json.dump(output, stream, indent=2, allow_nan=False)
    logger.info("Saved descriptive diagnostics. Model and trading decisions were not changed.")


if __name__ == "__main__":
    main()
