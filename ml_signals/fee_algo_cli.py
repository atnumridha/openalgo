"""Train fee-aware research models without activating any live trading strategy."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import joblib
from ml_signals.fee_algo import Config, train_research


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["train"])
    parser.add_argument("--symbol", default="BTCUSD", choices=["BTCUSD", "ETHUSD", "SOLUSD"])
    parser.add_argument("--max-rows", type=int, default=100000)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[1] / "models/fee_algo"
    )
    args = parser.parse_args()
    if not 10000 <= args.max_rows <= 300000:
        parser.error("max-rows must be 10000..300000")
    from ml_signals import data

    frame = data.load_frame(data.PRICE_SOURCE, symbol=args.symbol)
    frame = frame[frame.time + 60 <= time.time()].tail(args.max_rows).reset_index(drop=True)
    # Product metadata must be explicit for another contract; BTC's checked
    # coefficients are the only built-in training configuration in this release.
    if args.symbol != "BTCUSD":
        parser.error(
            "Train BTCUSD first; other products require verified contract/fee configuration."
        )
    cfg = Config(symbol=args.symbol)
    started = time.perf_counter()
    result = train_research(frame, cfg, progress=lambda message: print(message, flush=True))
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = args.output / args.symbol / version
    folder.mkdir(parents=True, exist_ok=False)
    joblib.dump(result, folder / "model.joblib")
    # Verify the serialized object is the exact evaluated model, without refitting.
    restored = joblib.load(folder / "model.joblib")
    from ml_signals.fee_algo import features_and_levels
    import numpy as np

    features, _ = features_and_levels(frame)
    X = features.fillna(result["medians"]).to_numpy(np.float32)[-100:]
    assert np.array_equal(result["model"].predict_proba(X), restored["model"].predict_proba(X))
    card = {
        **result["card"],
        "version": version,
        "training_seconds": time.perf_counter() - started,
        "artifact_sha256": hashlib.sha256((folder / "model.joblib").read_bytes()).hexdigest(),
        "rows": len(frame),
        "serialized_prediction_check": True,
    }
    (folder / "metrics.json").write_text(json.dumps(card, indent=2, allow_nan=False))
    pointer = args.output / args.symbol / "research.json"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": version}))
    temporary.replace(pointer)
    print(
        json.dumps(
            {
                "artifact": str(folder),
                "research_qualified": card["research_qualified"],
                "test": card["test"],
                "reason": card["reason"],
                "training_seconds": card["training_seconds"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
