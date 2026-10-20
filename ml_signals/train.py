"""Profit-aware walk-forward trainer and per-symbol model registry.

One model per interval, each judged by what its trades would have made after
Delta's fees, not by how often it named the right class.

For each interval:

1. Every bar's long and short trade is simulated with stop and target scaled
   to that bar's volatility (``ml_signals.decision``), for each candidate in a
   small grid. A bar is labelled LONG or SHORT when that trade nets a profit
   after fees, WAIT otherwise.
2. The history is split by time into train, calibration, validation and a
   final test fold that nothing is tuned on. A gap the length of the hold
   separates them, so no label straddles a boundary.
3. The classifier is fitted on train only and its probabilities calibrated on
   the calibration slice only. The old trainer calibrated on the fold it then
   scored, which flattered every figure it reported.
4. Expected value per side uses the average net win and loss measured on the
   calibration slice. The grid candidate and the minimum edge are chosen on
   validation, scored as non-overlapping trades: one position at a time, the
   next signal taken only after the last trade closed.
5. The chosen setting is scored once on the test fold and compared with a
   random-entry baseline taking the same number of trades. Promotion, which
   unlocks Live trading, needs a positive net after fees, a minimum number of
   trades, and a result above the baseline's 95th percentile.
6. The model kept is refitted on everything before the test fold, so the test
   fold stays untouched by the model that is deployed.

HistGradientBoostingClassifier is used because LightGBM's macOS wheel needs a
system OpenMP library this deployment cannot install.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from ml_signals.decision import (
    INTERVAL_MINUTES,
    DecisionParams,
    Payoff,
    choose,
    expected_values,
    levels_pct,
    take_non_overlapping,
)
from ml_signals.features import build_features
from ml_signals.labels import FEE_PLANS, FeePlan, plan_from_settings, trade_outcomes

ROOT = Path(__file__).resolve().parents[1]
#: Root model folder. Each symbol has its own subfolder.
MODEL_ROOT = Path(os.environ.get("OPENALGO_ML_MODEL_DIR", ROOT / "models" / "ml_signals"))
CLASSES = np.asarray(["WAIT", "LONG", "SHORT"])
TRAINER_VERSION = 2
#: The edge an interval is given when nothing it could do was worth judging:
#: no expected value reaches it, so it only ever says WAIT.
NO_TRADE_EDGE_PCT = 1_000_000.0


class ProbabilityCalibrator:
    """Multiclass isotonic calibration fitted on rows the estimator never saw."""

    def __init__(self, estimator=None, classes=None):
        self.estimator = estimator
        self.classes_ = np.asarray(classes if classes is not None else [0, 1, 2])
        self.calibrators_: list[IsotonicRegression | None] = []

    def _aligned_raw(self, X):
        raw = self.estimator.predict_proba(X)
        output = np.zeros((len(raw), len(self.classes_)), dtype=float)
        for source_index, class_value in enumerate(
            getattr(self.estimator, "classes_", self.classes_)
        ):
            output[:, list(self.classes_).index(class_value)] = raw[:, source_index]
        return output

    def fit(self, X, y):
        aligned = self._aligned_raw(X)
        self.calibrators_ = []
        for index, class_value in enumerate(self.classes_):
            target = (np.asarray(y) == class_value).astype(float)
            if len(np.unique(target)) < 2:
                self.calibrators_.append(None)
                continue
            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(aligned[:, index], target)
            self.calibrators_.append(calibrator)
        return self

    def predict_proba(self, X):
        raw = self._aligned_raw(X)
        output = np.column_stack(
            [
                raw[:, index] if calibrator is None else calibrator.predict(raw[:, index])
                for index, calibrator in enumerate(self.calibrators_)
            ]
        )
        totals = output.sum(axis=1, keepdims=True)
        return output / np.where(totals > 0, totals, 1)


@dataclass(frozen=True)
class TrainConfig:
    """What a training run is allowed to choose from.

    ``stop_pct`` and ``target_pct`` are the operator's caps; the stop and
    target actually used are scaled to volatility under them. ``fee_plan`` of
    "settings" uses the fee profile saved in ML settings.
    """

    stop_pct: float = 0.2
    target_pct: float = 2.0
    hold_minutes: int = 28
    fee_plan: str = "settings"
    count_voucher: bool = False
    intervals: tuple[str, ...] = ("1m", "3m", "5m", "15m")
    stop_atr_mults: tuple[float, ...] = (0.6, 1.0)
    reward_risks: tuple[float, ...] = (1.5, 2.5)
    min_edges: tuple[float, ...] = (0.02, 0.05, 0.1, 0.2)
    stop_floor_pct: float = 0.05
    train_fraction: float = 0.55
    calibration_fraction: float = 0.15
    validation_fraction: float = 0.15
    min_test_trades: int = 30
    baseline_draws: int = 200
    max_training_rows: int = 200_000
    sentiment_enabled: bool = True
    seed: int = 7
    # Accepted for older callers; the decision is by expected value now.
    minimum_probability: float = 0.55


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, default=_json_default))
    os.replace(temp, path)


def _model_version() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _impute(
    frame: pd.DataFrame, columns: list[str] | None = None
) -> tuple[np.ndarray, list[str], dict[str, float]]:
    numeric = frame.select_dtypes(include=[np.number]).copy()
    if columns is not None:
        numeric = numeric.reindex(columns=columns)
    columns = list(numeric.columns)
    medians = {
        col: float(numeric[col].median()) if numeric[col].notna().any() else 0.0 for col in columns
    }
    return numeric.fillna(medians).to_numpy(dtype=np.float32), columns, medians


def _class_weight(y: np.ndarray) -> np.ndarray:
    labels, counts = np.unique(y, return_counts=True)
    weights = {
        int(label): len(y) / (len(labels) * count)
        for label, count in zip(labels, counts, strict=True)
    }
    return np.asarray([weights[int(label)] for label in y], dtype=float)


def _base_estimator(seed: int) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=0.06,
        max_iter=220,
        max_leaf_nodes=15,
        l2_regularization=1.0,
        min_samples_leaf=40,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=25,
        random_state=seed,
    )


def _ordered_proba(model: Any, X: np.ndarray) -> np.ndarray:
    raw = model.predict_proba(X)
    out = np.zeros((len(X), 3), dtype=float)
    for source_index, class_value in enumerate(model.classes_):
        if int(class_value) in (0, 1, 2):
            out[:, int(class_value)] = raw[:, source_index]
    return out


@dataclass(frozen=True)
class Split:
    """Row ranges by time, with a hold-length gap before each later slice."""

    train: slice
    calibration: slice
    validation: slice
    test: slice


def chronological_split(n: int, gap: int, config: TrainConfig) -> Split | None:
    """Train, calibration, validation and test slices in time order, never overlapping."""
    usable = n - 3 * gap
    if usable < 400:
        return None
    train_end = int(usable * config.train_fraction)
    calibration_end = train_end + gap + int(usable * config.calibration_fraction)
    validation_end = calibration_end + gap + int(usable * config.validation_fraction)
    return Split(
        train=slice(0, train_end),
        calibration=slice(train_end + gap, calibration_end),
        validation=slice(calibration_end + gap, validation_end),
        test=slice(validation_end + gap, n),
    )


def _payoffs(net: dict[int, np.ndarray], rows: np.ndarray) -> tuple[Payoff, Payoff]:
    out = []
    for side in (1, -1):
        values = net[side][rows]
        values = values[np.isfinite(values)]
        wins = values[values > 0]
        losses = values[values <= 0]
        out.append(
            Payoff(
                avg_win_pct=float(wins.mean()) if len(wins) else 0.0,
                avg_loss_pct=float(-losses.mean()) if len(losses) else 0.0,
                win_rate=float(len(wins) / len(values)) if len(values) else 0.0,
            )
        )
    return out[0], out[1]


def score_trades(
    rows: np.ndarray,
    sides: np.ndarray,
    net: dict[int, np.ndarray],
    exit_index: dict[int, np.ndarray],
) -> dict[str, Any]:
    """Non-overlapping trades among the chosen rows, and what they netted after fees."""
    chosen = sides != 0
    candidates = rows[chosen]
    candidate_sides = sides[chosen]
    taken = take_non_overlapping(candidates, exit_index, candidate_sides)
    side_of = dict(zip(candidates.tolist(), candidate_sides.tolist(), strict=True))
    nets = np.asarray([net[int(side_of[i])][i] for i in taken], dtype=float)
    return {
        "trades": int(len(nets)),
        "net_pct": float(nets.sum()) if len(nets) else 0.0,
        "avg_net_pct": float(nets.mean()) if len(nets) else 0.0,
        "win_pct": float((nets > 0).mean() * 100) if len(nets) else 0.0,
        "longs": int(sum(1 for i in taken if side_of[i] > 0)),
        "shorts": int(sum(1 for i in taken if side_of[i] < 0)),
    }


def random_baseline(
    rows: np.ndarray,
    trades: int,
    net: dict[int, np.ndarray],
    exit_index: dict[int, np.ndarray],
    *,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    """Random entries with random sides, the same number of trades, one at a time.

    Returns the distribution of their total net so a model's result can be
    placed against it.
    """
    if trades <= 0 or len(rows) == 0:
        return {"draws": 0, "mean_net_pct": 0.0, "p95_net_pct": 0.0}
    rng = np.random.default_rng(seed)
    totals = []
    for _ in range(draws):
        order = np.sort(rng.choice(rows, size=min(len(rows), trades * 4), replace=False))
        sides = rng.choice(np.asarray([1, -1]), size=len(order))
        taken = take_non_overlapping(order, exit_index, sides)[:trades]
        side_of = dict(zip(order.tolist(), sides.tolist(), strict=True))
        totals.append(float(sum(net[int(side_of[i])][i] for i in taken)))
    values = np.asarray(totals)
    return {
        "draws": int(draws),
        "mean_net_pct": float(values.mean()),
        "p95_net_pct": float(np.percentile(values, 95)),
    }


def _labels_from(net: dict[int, np.ndarray]) -> np.ndarray:
    """0 WAIT, 1 LONG, 2 SHORT: the side that nets a profit after fees, if any."""
    long_net = np.nan_to_num(net[1], nan=-np.inf)
    short_net = np.nan_to_num(net[-1], nan=-np.inf)
    best = np.maximum(long_net, short_net)
    return np.where(best > 0, np.where(long_net >= short_net, 1, 2), 0).astype(np.int32)


def _fee_plan(config: TrainConfig, symbol: str) -> FeePlan:
    if config.fee_plan == "settings":
        try:
            return plan_from_settings(symbol, count_voucher=config.count_voucher)
        except Exception:
            return replace(FEE_PLANS["scalper"], count_voucher=config.count_voucher).for_symbol(
                symbol
            )
    return replace(FEE_PLANS[config.fee_plan], count_voucher=config.count_voucher).for_symbol(
        symbol
    )


def train_interval(
    bars: pd.DataFrame,
    interval: str,
    *,
    config: TrainConfig,
    plan: FeePlan,
    sentiment_frames: dict[str, pd.DataFrame] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[Any, dict[str, Any], list[str], dict[str, float]] | None:
    """One interval's model, its decision parameters and its scorecard."""
    say = progress or (lambda _message: None)
    bars = bars.sort_values("time").reset_index(drop=True)
    if len(bars) > config.max_training_rows:
        bars = bars.iloc[-config.max_training_rows :].reset_index(drop=True)
    features = build_features(
        bars,
        interval=interval,
        sentiment_frames=sentiment_frames if config.sentiment_enabled else None,
        include_sentiment=config.sentiment_enabled,
    )
    atr = features["atr_14_pct"].to_numpy(dtype=float)
    valid = features.notna().any(axis=1).to_numpy() & np.isfinite(atr)
    gap = max(1, int(np.ceil(config.hold_minutes / INTERVAL_MINUTES[interval]))) + 1
    split = chronological_split(len(bars), gap, config)
    if split is None:
        say(f"{interval}: not enough history to train")
        return None

    X_all, columns, medians = _impute(features)

    def rows_of(part: slice) -> np.ndarray:
        idx = np.arange(part.start, part.stop)
        return idx[valid[idx]]

    train_rows = rows_of(split.train)
    calibration_rows = rows_of(split.calibration)
    validation_rows = rows_of(split.validation)
    test_rows = rows_of(split.test)

    candidates = []
    untradable = []
    for stop_mult in config.stop_atr_mults:
        for reward_risk in config.reward_risks:
            params = DecisionParams(
                interval=interval,
                hold_minutes=config.hold_minutes,
                stop_atr_mult=stop_mult,
                reward_risk=reward_risk,
                stop_floor_pct=config.stop_floor_pct,
                stop_cap_pct=config.stop_pct,
                target_cap_pct=config.target_pct,
            )
            stop, target = levels_pct(params, atr)
            outcome = trade_outcomes(
                bars,
                stop_pct=stop,
                target_pct=target,
                max_hold_minutes=config.hold_minutes,
                fee_plan=plan,
            )
            labels = _labels_from(outcome.net)
            if len(np.unique(labels[train_rows])) < 2:
                continue
            say(f"{interval}: fitting stop {stop_mult}x ATR, reward {reward_risk}:1")
            estimator = _base_estimator(config.seed)
            estimator.fit(
                X_all[train_rows],
                labels[train_rows],
                sample_weight=_class_weight(labels[train_rows]),
            )
            calibrated = ProbabilityCalibrator(estimator, classes=[0, 1, 2]).fit(
                X_all[calibration_rows], labels[calibration_rows]
            )
            long_payoff, short_payoff = _payoffs(outcome.net, calibration_rows)
            params = replace(params, long=long_payoff, short=short_payoff)
            proba = _ordered_proba(calibrated, X_all[validation_rows])
            ev_long, ev_short = expected_values(proba[:, 1], proba[:, 2], params)
            best_edge, best_score = None, None
            for edge in config.min_edges:
                sides = choose(ev_long, ev_short, edge)
                score = score_trades(validation_rows, sides, outcome.net, outcome.exit_index)
                if score["trades"] < max(5, config.min_test_trades // 3):
                    continue
                if best_score is None or score["net_pct"] > best_score["net_pct"]:
                    best_edge, best_score = edge, score
            if best_edge is None:
                untradable.append(
                    {
                        "params": replace(params, min_edge_pct=NO_TRADE_EDGE_PCT),
                        "validation": score_trades(
                            validation_rows,
                            np.zeros(len(validation_rows), dtype=int),
                            outcome.net,
                            outcome.exit_index,
                        ),
                        "outcome": outcome,
                        "labels": labels,
                    }
                )
                continue
            candidates.append(
                {
                    "params": replace(params, min_edge_pct=best_edge),
                    "validation": best_score,
                    "outcome": outcome,
                    "labels": labels,
                }
            )

    tradable = bool(candidates)
    if not candidates:
        if not untradable:
            say(f"{interval}: every bar had the same label, so there is nothing to learn")
            return None
        # Keep a model that only ever says WAIT, so the page can say why
        # instead of the interval disappearing.
        candidates = untradable[:1]
    best = max(candidates, key=lambda c: c["validation"]["net_pct"])
    params: DecisionParams = best["params"]
    outcome = best["outcome"]
    labels = best["labels"]

    # Score once on the untouched test fold, with a model that never saw it.
    estimator = _base_estimator(config.seed)
    estimator.fit(
        X_all[train_rows], labels[train_rows], sample_weight=_class_weight(labels[train_rows])
    )
    calibrated = ProbabilityCalibrator(estimator, classes=[0, 1, 2]).fit(
        X_all[calibration_rows], labels[calibration_rows]
    )
    proba = _ordered_proba(calibrated, X_all[test_rows])
    ev_long, ev_short = expected_values(proba[:, 1], proba[:, 2], params)
    test_sides = choose(ev_long, ev_short, params.min_edge_pct)
    test_score = score_trades(test_rows, test_sides, outcome.net, outcome.exit_index)
    baseline = random_baseline(
        test_rows,
        test_score["trades"],
        outcome.net,
        outcome.exit_index,
        draws=config.baseline_draws,
        seed=config.seed,
    )
    promoted, reason = promotion_decision(test_score, baseline, config)
    if not tradable:
        promoted, reason = (
            False,
            (
                "No stop, target and edge setting traded often enough on the validation period "
                f"(at least {max(5, config.min_test_trades // 3)} trades) to be judged, so this "
                "interval only says WAIT."
            ),
        )

    # The deployed model learns from everything before the test fold, and is
    # calibrated on the slice right before it, so the test fold stays unseen.
    deploy_rows = np.concatenate([train_rows, rows_of(split.validation)])
    say(f"{interval}: refitting the deployed model")
    deployed = _base_estimator(config.seed + 1)
    deployed.fit(
        X_all[deploy_rows], labels[deploy_rows], sample_weight=_class_weight(labels[deploy_rows])
    )
    deployed_calibrated = ProbabilityCalibrator(deployed, classes=[0, 1, 2]).fit(
        X_all[calibration_rows], labels[calibration_rows]
    )

    card = {
        "interval": interval,
        "rows": int(len(bars)),
        "decision": params.to_dict(),
        "validation": best["validation"],
        "test": test_score,
        "baseline": baseline,
        "promoted": promoted,
        "promotion_reason": reason,
        "tradable": tradable,
        "label_counts": {
            name: int((labels[train_rows] == code).sum())
            for code, name in enumerate(("WAIT", "LONG", "SHORT"))
        },
        "grid": [
            {
                "stop_atr_mult": c["params"].stop_atr_mult,
                "reward_risk": c["params"].reward_risk,
                "min_edge_pct": c["params"].min_edge_pct,
                "validation": c["validation"],
            }
            for c in candidates
        ],
        "periods": {
            name: [int(bars["time"].iloc[part.start]), int(bars["time"].iloc[part.stop - 1])]
            for name, part in asdict(split).items()
            if part.stop > part.start
        },
    }
    return deployed_calibrated, card, columns, medians


def promotion_decision(
    test: dict[str, Any], baseline: dict[str, Any], config: TrainConfig
) -> tuple[bool, str]:
    """Whether the test-fold result earns Live trading, and why, in plain words."""
    trades = test["trades"]
    net = test["net_pct"]
    if trades < config.min_test_trades:
        return False, (
            f"Took {trades} trades on the unseen period; at least {config.min_test_trades} "
            "are needed before the result means anything."
        )
    if net <= 0:
        return False, (
            f"Lost {abs(net):.2f}% of notional after fees over {trades} trades on the unseen period."
        )
    if net <= baseline["p95_net_pct"]:
        return False, (
            f"Made {net:.2f}% after fees over {trades} trades, but random entries with the same "
            f"number of trades reach {baseline['p95_net_pct']:.2f}% one time in twenty, so this "
            "could be luck."
        )
    return True, (
        f"Made {net:.2f}% after fees over {trades} trades on the unseen period, above what "
        f"random entries reach one time in twenty ({baseline['p95_net_pct']:.2f}%)."
    )


def train_model(
    bars_by_interval: dict[str, pd.DataFrame],
    *,
    sentiment_frames: dict[str, pd.DataFrame] | None = None,
    config: TrainConfig = TrainConfig(),
    progress: Callable[[str, float], None] | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Train one model per interval for one symbol and save them as one version."""
    from ml_signals.data import normalize_symbol

    symbol_name = normalize_symbol(symbol)
    plan = _fee_plan(config, symbol_name)
    intervals = [i for i in config.intervals if i in bars_by_interval]
    models: dict[str, Any] = {}
    cards: dict[str, dict[str, Any]] = {}
    schema: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    for number, interval in enumerate(intervals):
        base = number / max(1, len(intervals))
        messages: list[str] = []

        def say(message: str, base: float = base, messages: list[str] = messages) -> None:
            messages.append(message)
            if progress:
                progress(f"{symbol_name} {message}", min(0.98, base))

        result = train_interval(
            bars_by_interval[interval],
            interval,
            config=config,
            plan=plan,
            sentiment_frames=sentiment_frames,
            progress=say,
        )
        if result is None:
            skipped[interval] = messages[-1] if messages else f"{interval}: not trained"
            continue
        model, card, columns, medians = result
        models[interval], cards[interval] = model, card
        schema[interval] = {"columns": columns, "medians": medians}
    if not models:
        raise ValueError(f"No interval of {symbol_name} had enough history to train a model.")

    version = _model_version()
    version_dir = symbol_dir(symbol_name) / version
    version_dir.mkdir(parents=True, exist_ok=False)
    joblib.dump(models, version_dir / "models.joblib")
    (version_dir / "schema.json").write_text(json.dumps(schema, default=_json_default))
    promoted_intervals = [i for i, card in cards.items() if card["promoted"]]
    metrics = {
        "symbol": symbol_name,
        "version": version,
        "trainer_version": TRAINER_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "trainer": (
            "sklearn.HistGradientBoostingClassifier per interval, isotonic calibration on a "
            "held-out slice, expected-value decision"
        ),
        "config": asdict(config),
        "fee_plan": {"name": plan.name, "count_voucher": plan.count_voucher},
        "intervals": cards,
        "skipped_intervals": skipped,
        "promoted": bool(promoted_intervals),
        "promoted_intervals": promoted_intervals,
        "promotion_reason": (
            "Live trading is allowed on " + ", ".join(promoted_intervals) + "."
            if promoted_intervals
            else "No interval beat random entries after fees on the unseen period, so Live "
            "stays locked. Sandbox trading is still available."
        ),
        "sentiment_enabled": config.sentiment_enabled,
        "model_dir": str(version_dir),
    }
    (version_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=_json_default))
    return metrics


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def symbol_dir(symbol: str | None = None) -> Path:
    """Where one symbol's model versions and current.json live."""
    from ml_signals.data import normalize_symbol

    return MODEL_ROOT / normalize_symbol(symbol)


def _current_path(symbol: str | None = None) -> Path:
    return symbol_dir(symbol) / "current.json"


def _safe_version(version: str) -> str:
    text = str(version or "")
    if not text or "/" in text or "\\" in text or text.startswith("."):
        raise FileNotFoundError(text)
    return text


def migrate_legacy_layout() -> list[str]:
    """Move pre-shortlist BTC models into models/ml_signals/BTCUSD/. Idempotent."""
    from ml_signals.data import DEFAULT_SYMBOL

    if not MODEL_ROOT.exists():
        return []
    target = symbol_dir(DEFAULT_SYMBOL)
    moved: list[str] = []
    for entry in sorted(MODEL_ROOT.iterdir()):
        if not entry.is_dir() or not (entry / "metrics.json").exists():
            continue
        destination = target / entry.name
        if destination.exists():
            continue
        target.mkdir(parents=True, exist_ok=True)
        os.replace(entry, destination)
        metrics_path = destination / "metrics.json"
        try:
            metrics = json.loads(metrics_path.read_text())
            metrics["model_dir"] = str(destination)
            metrics.setdefault("symbol", DEFAULT_SYMBOL)
            metrics_path.write_text(json.dumps(metrics, indent=2, default=_json_default))
        except (OSError, ValueError):
            pass
        moved.append(entry.name)
    legacy_current = MODEL_ROOT / "current.json"
    if legacy_current.exists() and not _current_path(DEFAULT_SYMBOL).exists():
        target.mkdir(parents=True, exist_ok=True)
        os.replace(legacy_current, _current_path(DEFAULT_SYMBOL))
    return moved


def load_version(symbol: str | None, version: str) -> dict[str, Any]:
    """A saved version as ``{"metrics", "models": {interval: entry}}``.

    A version from the first trainer holds one model for every interval and
    no decision parameters; it loads with ``legacy`` set so a caller can say
    so instead of suggesting trades from it.
    """
    root = symbol_dir(symbol) / _safe_version(version)
    metrics = json.loads((root / "metrics.json").read_text())
    metrics["model_dir"] = str(root)
    models: dict[str, dict[str, Any]] = {}
    if (root / "models.joblib").exists():
        fitted = joblib.load(root / "models.joblib")
        schema = json.loads((root / "schema.json").read_text())
        for interval, model in fitted.items():
            card = (metrics.get("intervals") or {}).get(interval) or {}
            models[interval] = {
                "model": model,
                "columns": schema[interval]["columns"],
                "medians": schema[interval]["medians"],
                "decision": DecisionParams.from_dict(card["decision"]) if card else None,
                "promoted": bool(card.get("promoted", False)),
                "promotion_reason": card.get("promotion_reason"),
                "legacy": False,
            }
    elif (root / "model.joblib").exists():
        model = joblib.load(root / "model.joblib")
        columns_path, medians_path = root / "feature_columns.json", root / "feature_medians.json"
        entry = {
            "model": model,
            "columns": json.loads(columns_path.read_text()) if columns_path.exists() else None,
            "medians": json.loads(medians_path.read_text()) if medians_path.exists() else {},
            "decision": None,
            "promoted": False,
            "promotion_reason": "Trained before trades were judged after fees; retrain to use it.",
            "legacy": True,
        }
        for interval in INTERVAL_MINUTES:
            models[interval] = entry
    return {"metrics": metrics, "models": models}


def current_version(symbol: str | None = None) -> str | None:
    migrate_legacy_layout()
    path = _current_path(symbol)
    if not path.exists():
        return None
    try:
        return str(json.loads(path.read_text())["version"])
    except (OSError, ValueError, KeyError):
        return None


def load_current(symbol: str | None = None) -> dict[str, Any]:
    version = current_version(symbol)
    if version is None:
        raise FileNotFoundError("No active model. Train and activate one first.")
    return load_version(symbol, version)


def list_models(symbol: str | None = None) -> list[dict[str, Any]]:
    migrate_legacy_layout()
    root = symbol_dir(symbol)
    if not root.exists():
        return []
    active = current_version(symbol)
    output = []
    for directory in sorted(root.iterdir(), reverse=True):
        metrics_path = directory / "metrics.json"
        if directory.is_dir() and metrics_path.exists():
            try:
                value = json.loads(metrics_path.read_text())
            except (OSError, ValueError):
                continue
            value["active"] = directory.name == active
            value.pop("feature_columns", None)
            for card in (value.get("intervals") or {}).values():
                card.pop("grid", None)
            output.append(value)
    return output


def activate_model(version: str, symbol: str | None = None) -> dict[str, Any]:
    migrate_legacy_layout()
    path = symbol_dir(symbol) / _safe_version(version) / "metrics.json"
    if not path.exists():
        raise FileNotFoundError(version)
    _atomic_json(
        _current_path(symbol),
        {"version": version, "activated_at": datetime.now(UTC).isoformat()},
    )
    return json.loads(path.read_text())
