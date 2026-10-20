"""Worker-only cached inference for the fee-aware research model."""

import hashlib
import json
import time
from pathlib import Path
import joblib
import numpy as np
from ml_signals.fee_algo import clean_bars, features_and_levels, select_side

ROOT = Path(__file__).resolve().parents[1] / "models/fee_algo"
_models = {}
_predictions = {}


def observe(symbol, frame, now=None):
    now = time.time() if now is None else now
    started = time.perf_counter()
    if symbol not in ("BTCUSD", "ETHUSD", "SOLUSD"):
        return {"action": "HOLD", "reason": "Unsupported contract"}
    pointer = ROOT / symbol / "research.json"
    if not pointer.exists():
        return {
            "action": "HOLD",
            "reason": "No fee-aware research model trained for this contract.",
        }
    version = json.loads(pointer.read_text())["version"]
    if not version.isalnum():
        raise ValueError("Invalid model version")
    folder = ROOT / symbol / version
    key = (symbol, version)
    if key not in _models:
        card = json.loads((folder / "metrics.json").read_text())
        if (
            hashlib.sha256((folder / "model.joblib").read_bytes()).hexdigest()
            != card["artifact_sha256"]
        ):
            raise ValueError("Research model checksum mismatch")
        _models.clear()
        _models[key] = (joblib.load(folder / "model.joblib"), card)
    artifact, card = _models[key]
    frame = frame[frame.time + 60 <= now].tail(500).reset_index(drop=True)
    frame = clean_bars(frame)
    if (
        not np.all(np.diff(frame.time.to_numpy()[-100:]) == 60)
        or not 0 <= now - frame.time.iloc[-1] - 60 <= 90
    ):
        return {"action": "HOLD", "reason": "Completed candles are stale or contain gaps."}
    signature = hashlib.sha256(
        frame[["time", "open", "high", "low", "close", "volume"]].to_numpy().tobytes()
    ).hexdigest()
    cache_key = (*key, signature)
    if cache_key not in _predictions:
        features, atr = features_and_levels(frame)
        X = features[artifact["columns"]].fillna(artifact["medians"]).to_numpy(np.float32)[-1:]
        p = artifact["model"].predict_proba(X)[0]
        ev = [
            float(p[i] * artifact["payoffs"][i][0] - (1 - p[i]) * artifact["payoffs"][i][1])
            for i in range(2)
        ]
        side = select_side(p, ev, card["threshold"])
        # Failed holdout checks are visible but cannot issue an actionable call.
        action = (
            ("LONG" if side == 1 else "SHORT" if side == -1 else "HOLD")
            if card["research_qualified"]
            else "HOLD"
        )
        _predictions.clear()
        _predictions[cache_key] = {
            "action": action,
            "probabilities": p.tolist(),
            "expected_net_usd": ev,
            "signal_time": int(frame.time.iloc[-1] + 60),
            "reference_price": float(frame.close.iloc[-1]),
            "low5": float(frame.low.tail(5).min()),
            "high5": float(frame.high.tail(5).max()),
            "atr": float(atr.iloc[-1]),
            "model_version": version,
            "config": card["config"],
            "threshold": card["threshold"],
            "research_qualified": card["research_qualified"],
            "live_ready": False,
            "test": card["test"],
            "reason": card["reason"]
            if not card["research_qualified"]
            else (
                "No side has sufficient probability and positive expected net return."
                if not side
                else "Probability and net expectation checks passed."
            ),
            "probability_definition": card["probability_definition"],
            "calibration": card["calibration"],
        }
    return {
        **_predictions[cache_key],
        "updated_at": now,
        "inference_ms": (time.perf_counter() - started) * 1000,
    }
