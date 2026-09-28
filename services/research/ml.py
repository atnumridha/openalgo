"""Causal technical features and offline option-payoff learning helpers.

No broker, database or order access. Scikit-learn is an optional research-worker dependency.
Counterfactual single-lot labels are not shared-capital portfolio results.
"""

from bisect import bisect_right
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from services.research.costs import order_cost
from services.research.replay import _filtered_contract, _slipped, _tick, research_capital
from services.risk import BreachReason, PositionRisk, evaluate_position
from services.risk.admission import ML_RISK_RECIPE, planned_entry_risk
from services.risk.budget import BudgetPolicy, evaluate_budget
from services.risk.cash_exit import CASH_RECIPES, recipe_exit, recipe_policy
from services.risk.profit_exit import PROFIT_RECIPES, profit_bar, profit_config

MAX_SEED_GAP_DAYS = 7


def require_recent_seed(previous_day, session_day):
    """Bound a two-session feature seed without mistaking a months-old close for recent context."""
    try:
        gap = (date.fromisoformat(session_day) - date.fromisoformat(previous_day)).days
    except (TypeError, ValueError) as exc:
        raise ValueError("ML feature seed dates are invalid") from exc
    if not 1 <= gap <= MAX_SEED_GAP_DAYS:
        raise ValueError(
            f"ML previous-session feature seed is not recent: {previous_day} to {session_day} "
            f"({gap} calendar days; maximum {MAX_SEED_GAP_DAYS})"
        )


def technical_features(frame, *, include_volume=False):
    """One output row per already-closed candle; no backward fill or future fit."""
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is None
        or not frame.index.is_monotonic_increasing
        or not frame.index.is_unique
    ):
        raise ValueError("Candle timestamps must be ordered, unique and timezone aware")
    f = frame.astype(float)
    if not np.isfinite(f[["open", "high", "low", "close"]]).all().all():
        raise ValueError("OHLC must be finite")
    if (
        (f.low <= 0)
        | (f.high < f[["open", "close"]].max(axis=1))
        | (f.low > f[["open", "close"]].min(axis=1))
    ).any():
        raise ValueError("OHLC is inconsistent")
    c, h, low, o = f.close, f.high, f.low, f.open
    out = pd.DataFrame(index=f.index)
    for n in (1, 3, 6, 12):
        out[f"return_{n}"] = c.pct_change(n, fill_method=None)
    emas = {
        n: c.ewm(span=n, adjust=False, min_periods=n).mean() for n in (8, 9, 12, 15, 21, 26, 50)
    }
    for n in (8, 9, 15, 21, 50):
        out[f"ema_{n}_distance"] = c / emas[n] - 1
    out["trend_spread"] = (emas[8] - emas[21]) / c
    out["ema_9_15_spread"] = (emas[9] - emas[15]) / c
    out["trend_slope"] = emas[21].pct_change(5, fill_method=None)
    macd = emas[12] - emas[26]
    out["macd"] = macd / c
    out["macd_histogram"] = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / c
    change = c.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["rsi"] = (gain / (gain + loss).replace(0, np.nan)).where(gain + loss != 0, 0.5)
    tr = pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["atr_fraction"] = atr / c
    up, down = h.diff(), -low.diff()
    plus = (
        up.where((up > down) & (up > 0), 0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        / atr
    )
    minus = (
        down.where((down > up) & (down > 0), 0)
        .ewm(alpha=1 / 14, adjust=False, min_periods=14)
        .mean()
        / atr
    )
    out["directional_spread"] = plus - minus
    out["adx"] = (
        ((plus - minus).abs() / (plus + minus).replace(0, np.nan))
        .ewm(alpha=1 / 14, adjust=False, min_periods=14)
        .mean()
    )
    mean, std = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    out["bollinger_position"] = (c - mean) / std.replace(0, np.nan)
    out["bollinger_width"] = 4 * std / c
    lo, hi = low.rolling(14).min(), h.rolling(14).max()
    out["stochastic"] = (c - lo) / (hi - lo).replace(0, np.nan)
    span = (h - low).replace(0, np.nan)
    out["body"] = (c - o) / span
    out["upper_wick"] = (h - pd.concat([o, c], axis=1).max(axis=1)) / span
    out["lower_wick"] = (pd.concat([o, c], axis=1).min(axis=1) - low) / span
    out["close_location"] = (c - low) / span
    out["high_break_distance"] = c / h.shift().rolling(20).max() - 1
    out["low_break_distance"] = c / low.shift().rolling(20).min() - 1
    out["efficiency"] = (c - c.shift(20)).abs() / change.abs().rolling(20).sum().replace(0, np.nan)
    out["realized_volatility"] = c.pct_change(fill_method=None).rolling(20).std(ddof=0)
    days = f.index.strftime("%Y-%m-%d")
    daily = f.groupby(days).agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    previous = daily.shift(1).reindex(days).set_axis(f.index)
    out["prior_close_distance"] = c / previous.close - 1
    out["prior_high_distance"] = c / previous.high - 1
    out["prior_low_distance"] = c / previous.low - 1
    out["session_return"] = c / o.groupby(days).transform("first") - 1
    out["session_high_distance"] = c / h.groupby(days).cummax() - 1
    out["session_low_distance"] = c / low.groupby(days).cummin() - 1
    minutes = f.index.hour * 60 + f.index.minute - 555
    out["time_sin"] = np.sin(2 * np.pi * minutes / 375)
    out["time_cos"] = np.cos(2 * np.pi * minutes / 375)
    if include_volume:
        v = f.volume.where(f.volume >= 0)
        out["relative_volume"] = v / v.shift().rolling(20).mean().replace(0, np.nan)
        out["volume_log"] = np.log1p(v)
        typical = (h + low + c) / 3
        vwap = (typical * v).groupby(days).cumsum() / v.groupby(days).cumsum().replace(0, np.nan)
        out["vwap_distance"] = c / vwap - 1
    return out.replace([np.inf, -np.inf], np.nan)


def label_option_trade(
    rows,
    signal_at,
    contract,
    atr,
    costs,
    session_close="15:25",
    *,
    max_hold_minutes=None,
    capital=10000,
    risk_recipe=None,
):
    """Net R for one eligible lot; unavailable future outcomes remain missing.

    Position stop/target decisions use the shared risk core. Portfolio admission,
    drawdown and multi-trade interaction are evaluated separately by run_replay.
    """
    if max_hold_minutes is not None and (
        type(max_hold_minutes) is not int or max_hold_minutes not in (5, 10, 15)
    ):
        raise ValueError("ML holding time must be 5, 10 or 15 minutes")
    deadline = (
        (datetime.fromisoformat(signal_at) + timedelta(minutes=max_hold_minutes)).isoformat()
        if max_hold_minutes is not None
        else None
    )
    timestamps = [r["timestamp"] for r in rows]
    start = bisect_right(timestamps, signal_at)
    expected = (datetime.fromisoformat(signal_at) + timedelta(minutes=1)).isoformat()
    if start == len(rows) or rows[start]["timestamp"] != expected:
        return None
    slip = costs["slippage_bps"] / 10000
    entry = _slipped(rows[start]["open"], slip, contract, buy=True)
    exact = Decimal(str(entry))
    technical = max(exact * Decimal(".10"), Decimal(str(atr)) * Decimal("1.5"))
    if risk_recipe in CASH_RECIPES:
        try:
            stop, target, _ = recipe_exit(exact, technical, contract, risk_recipe)
            stop, target = float(stop), float(target)
        except ValueError:
            return None
    else:
        stop = _tick(exact - technical, contract)
        target = _tick(exact + (exact - Decimal(str(stop))) * 2, contract, up=True)
    distance = exact - Decimal(str(stop))
    filter_distance = technical if risk_recipe in CASH_RECIPES else distance
    if not 20 <= entry <= 120 or filter_distance > exact * Decimal(".25"):
        return None
    units = contract["lot_size"] * contract["multiplier"]
    entry_fee = order_cost(Decimal(str(entry * units)), "BUY", costs)
    capital = research_capital({"capital": capital})
    policy = (
        recipe_policy(risk_recipe, capital)
        if risk_recipe in CASH_RECIPES
        else BudgetPolicy(capital=capital)
    )
    if Decimal(str(entry * units)) + entry_fee > capital * (1 - policy.cash_buffer_pct):
        return None
    if risk_recipe in (ML_RISK_RECIPE, *CASH_RECIPES):
        planned = planned_entry_risk(
            distance * Decimal(str(units)), Decimal(str(entry * units)), costs
        )
    elif risk_recipe is None:
        stop_fill = _slipped(stop, slip, contract)
        planned = (
            Decimal(str((entry - stop_fill) * units))
            + entry_fee
            + order_cost(Decimal(str(stop_fill * units)), "SELL", costs)
        )
    else:
        raise ValueError("Unsupported ML admission risk recipe")
    if planned <= 0:
        return None
    admission = evaluate_budget(
        policy,
        (),
        signal_at[:10],
        capital,
        capital,
        planned,
        proposed_gross_risk=distance * Decimal(str(units)) if risk_recipe in CASH_RECIPES else None,
    )
    if not admission.allowed:
        return None
    risk = PositionRisk(entry_price=entry, quantity=units, stop_price=stop, target_price=target)
    protection = (
        profit_config(contract, costs, recipe=risk_recipe)
        if risk_recipe in PROFIT_RECIPES
        else None
    )
    for bar in rows[start:]:
        at = bar["timestamp"]
        if at != expected or at[:10] != signal_at[:10] or at[11:16] > session_close:
            return None
        if protection:
            risk, price, reason = profit_bar(risk, bar, protection)
            ambiguous = False
            if reason is None and deadline is not None and at >= deadline:
                price, reason = bar["close"], "time_limit"
            elif reason is None and at[11:16] == session_close:
                price, reason = bar["close"], "session_close"
        else:
            opening = evaluate_position(risk, bar["open"])
            price, reason, ambiguous = None, None, False
            if opening.reason in (BreachReason.STOP, BreachReason.TARGET):
                price, reason = bar["open"], str(opening.reason)
            else:
                stopped = evaluate_position(risk, bar["low"]).reason == BreachReason.STOP
                won = evaluate_position(risk, bar["high"]).reason == BreachReason.TARGET
                if stopped:
                    price, reason, ambiguous = stop, "sl", won
                elif won:
                    price, reason = target, "target"
                elif deadline is not None and at >= deadline:
                    price, reason = bar["close"], "time_limit"
                elif at[11:16] == session_close:
                    price, reason = bar["close"], "session_close"
        if price is not None:
            fill = _slipped(price, slip, contract)
            net = (
                Decimal(str((fill - entry) * units))
                - entry_fee
                - order_cost(Decimal(str(fill * units)), "SELL", costs)
            ).quantize(Decimal(".01"))
            return {
                "net_r": float(net / planned),
                "gross_planned_risk": float(distance * Decimal(str(units))),
                "planned_risk": float(planned),
                "stop_price": stop,
                "target_price": target,
                "net_pnl": float(net),
                "entry_at": rows[start]["timestamp"],
                "exit_at": at,
                "ambiguous": ambiguous,
                "exit_reason": reason,
            }
        expected = (datetime.fromisoformat(at) + timedelta(minutes=1)).isoformat()
    return None


def assert_chronology(training, later):
    if training.empty or later.empty:
        raise ValueError("Chronological splits require observations")
    end = max(training.timestamp.max(), training.label_exit_at.dropna().max())
    if end >= later.timestamp.min():
        raise ValueError("Training observations or labels overlap the later period")


def signal_schedule(opportunities, predictions, threshold):
    if len(opportunities) != len(predictions) or not np.isfinite(predictions).all():
        raise ValueError("Predictions must be finite and match opportunities")
    ordered = opportunities[["timestamp", "direction", "symbol"]].copy()
    ordered["score"] = predictions
    ordered = ordered[ordered.score > threshold].sort_values(
        ["timestamp", "score", "direction"], ascending=[True, False, True], kind="stable"
    )
    return {
        row.timestamp: {"direction": row.direction, "symbol": row.symbol}
        for row in ordered.drop_duplicates("timestamp").itertuples(index=False)
    }


def validation_qualifies(metrics):
    """Validation evidence must meet the registered minimum in both scenarios."""
    return all(
        metrics[scenario]["net_pnl"] is not None
        and metrics[scenario]["net_pnl"] > 0
        and metrics[scenario]["trade_count"] >= 20
        and metrics[scenario]["ambiguous_exit_count"] == 0
        for scenario in ("base", "stress")
    )


OPTION_FEATURES = (
    "return_1",
    "return_3",
    "return_6",
    "rsi",
    "atr_fraction",
    "body",
    "upper_wick",
    "lower_wick",
    "relative_volume",
    "volume_log",
    "vwap_distance",
)


def build_underlying_features(data):
    underlying_symbol = data["metadata"]["underlying_symbol"]
    rows = [row for row in data["rows"] if row["symbol"] == underlying_symbol]
    if not rows:
        raise ValueError("ML research requires underlying candles")
    frame = pd.DataFrame(rows).set_index("timestamp").sort_index()
    frame.index = pd.DatetimeIndex(frame.index)
    # Reset the recursive indicators at the start of the previous session.
    # The live adapter can reproduce exactly this bounded seed from observed
    # bars, including prior-day OHLC, without relying on an unbounded cache.
    days = list(dict.fromkeys(frame.index.strftime("%Y-%m-%d")))
    outputs = []
    for index, day in enumerate(days):
        if index:
            require_recent_seed(days[index - 1], day)
        allowed = days[max(0, index - 1) : index + 1]
        window = frame[frame.index.strftime("%Y-%m-%d").isin(allowed)]
        features = technical_features(
            window[["open", "high", "low", "close", "volume"]], include_volume=False
        )
        outputs.append(features[features.index.strftime("%Y-%m-%d") == day])
    return pd.concat(outputs) if outputs else pd.DataFrame()


def build_opportunities(
    data,
    underlying_features,
    costs,
    *,
    labels=False,
    check_cancel=None,
    max_hold_minutes=None,
    capital=10000,
    risk_recipe=None,
):
    """Opportunity eligibility uses only data observable at the signal timestamp."""
    if risk_recipe not in (None, ML_RISK_RECIPE, *CASH_RECIPES):
        raise ValueError("Unsupported ML admission risk recipe")
    meta = data["metadata"]
    capital = research_capital({"capital": capital})
    policy = (
        recipe_policy(risk_recipe, capital)
        if risk_recipe in CASH_RECIPES
        else BudgetPolicy(capital=capital)
    )
    if check_cancel:
        check_cancel()
    by_time, by_contract_day = defaultdict(dict), defaultdict(list)
    for row in data["rows"]:
        by_time[row["timestamp"]][row["symbol"]] = row
        if row["symbol"] != meta["underlying_symbol"]:
            by_contract_day[(row["symbol"], row["timestamp"][:10])].append(row)
    option_features = {}
    for key, rows in by_contract_day.items():
        if check_cancel:
            check_cancel()
        frame = pd.DataFrame(rows).set_index("timestamp")
        frame.index = pd.DatetimeIndex(frame.index)
        option_features[key] = technical_features(
            frame[["open", "high", "low", "close", "volume"]], include_volume=True
        )
    histories = defaultdict(lambda: deque(maxlen=11))
    output, rejected = [], defaultdict(int)
    previous_day = None
    for count, (at, bars) in enumerate(sorted(by_time.items())):
        if check_cancel and count % 100 == 0:
            check_cancel()
        day = at[:10]
        if day != previous_day:
            histories.clear()
            previous_day = day
        for symbol, row in bars.items():
            if symbol == meta["underlying_symbol"]:
                continue
            history = histories[symbol]
            if history and datetime.fromisoformat(at) - datetime.fromisoformat(
                history[-1]["timestamp"]
            ) != timedelta(minutes=1):
                history.clear()
            history.append(row)
        underlying = bars.get(meta["underlying_symbol"])
        if (
            underlying is None
            or at[11:16] >= meta["session_close"]
            or pd.Timestamp(at) not in underlying_features.index
        ):
            continue
        u = underlying_features.loc[at]
        if u.isna().any():
            rejected["underlying_feature_warmup"] += 1
            continue
        for direction in ("CE", "PE"):
            contract, atr = _filtered_contract(
                meta["contracts"],
                bars,
                histories,
                underlying,
                direction,
                day,
                capital,
                policy,
                costs,
                costs["slippage_bps"] / 10000,
                rejected,
            )
            if contract is None:
                continue
            o = option_features[(contract["symbol"], day)].loc[at, list(OPTION_FEATURES)]
            if o.isna().any():
                rejected["option_feature_warmup"] += 1
                continue
            features = {"u_" + k: float(v) for k, v in u.items()} | {
                "o_" + k: float(v) for k, v in o.items()
            }
            features.update(
                direction_ce=float(direction == "CE"),
                premium=bars[contract["symbol"]]["close"],
                moneyness=(underlying["close"] - contract["strike"]) / underlying["close"],
                days_to_expiry=(
                    datetime.fromisoformat(contract["expiry"]) - datetime.fromisoformat(day)
                ).days,
                lot_size=contract["lot_size"],
            )
            record = {
                "timestamp": at,
                "direction": direction,
                "symbol": contract["symbol"],
                **features,
            }
            if labels:
                label = label_option_trade(
                    by_contract_day[(contract["symbol"], day)],
                    at,
                    contract,
                    atr,
                    costs,
                    meta["session_close"],
                    max_hold_minutes=max_hold_minutes,
                    capital=capital,
                    risk_recipe=risk_recipe,
                )
                record.update(
                    net_r=label["net_r"] if label else np.nan,
                    label_exit_at=label["exit_at"] if label else None,
                    label_ambiguous=label["ambiguous"] if label else None,
                )
                if label is None:
                    rejected["unavailable_label"] += 1
            output.append(record)
    return pd.DataFrame(output), dict(rejected)


ML_FEATURES = (
    "u_return_1",
    "u_return_3",
    "u_return_6",
    "u_return_12",
    "u_ema_8_distance",
    "u_ema_9_distance",
    "u_ema_15_distance",
    "u_ema_21_distance",
    "u_ema_50_distance",
    "u_trend_spread",
    "u_ema_9_15_spread",
    "u_trend_slope",
    "u_macd",
    "u_macd_histogram",
    "u_rsi",
    "u_atr_fraction",
    "u_bollinger_position",
    "u_bollinger_width",
    "u_stochastic",
    "u_body",
    "u_upper_wick",
    "u_lower_wick",
    "u_close_location",
    "u_high_break_distance",
    "u_low_break_distance",
    "u_efficiency",
    "u_realized_volatility",
    "u_prior_close_distance",
    "u_prior_high_distance",
    "u_prior_low_distance",
    "u_session_return",
    "u_session_high_distance",
    "u_session_low_distance",
    "u_time_sin",
    "u_time_cos",
    "o_return_1",
    "o_return_3",
    "o_return_6",
    "o_rsi",
    "o_atr_fraction",
    "o_body",
    "o_upper_wick",
    "o_lower_wick",
    "o_relative_volume",
    "o_volume_log",
    "o_vwap_distance",
    "direction_ce",
    "premium",
    "moneyness",
    "days_to_expiry",
    "lot_size",
)


def _require_frame_columns(frame, columns):
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"ML frame is missing required features: {missing}")
    selected = frame.loc[:, list(columns)].copy()
    if not np.isfinite(selected.to_numpy(dtype=float)).all():
        raise ValueError("ML features must be finite")
    return selected


def chronological_folds(frame, *, folds=3, min_train_sessions=10):
    if frame.empty:
        raise ValueError("Cross-validation requires observations")
    if type(folds) is not int or not 2 <= folds <= 10:
        raise ValueError("folds must be a whole number between 2 and 10")
    if type(min_train_sessions) is not int or min_train_sessions < 2:
        raise ValueError("min_train_sessions must be at least 2")
    ordered = frame.sort_values(["timestamp", "direction", "symbol"], kind="stable").reset_index(
        drop=True
    )
    sessions = list(dict.fromkeys(ordered.timestamp.str[:10]))
    if len(sessions) < min_train_sessions + folds:
        raise ValueError("Not enough sessions for the requested chronological folds")
    edges = np.linspace(min_train_sessions, len(sessions), folds + 1, dtype=int)
    result = []
    for index in range(folds):
        train_sessions = sessions[: int(edges[index])]
        validation_sessions = sessions[int(edges[index]) : int(edges[index + 1])]
        training = ordered[ordered.timestamp.str[:10].isin(train_sessions)].dropna(
            subset=["net_r", "label_exit_at"]
        )
        # Missing future outcomes must never change which rows receive predictions.
        validation = ordered[ordered.timestamp.str[:10].isin(validation_sessions)].copy()
        before = len(training)
        training = training[training.label_exit_at < validation.timestamp.min()].copy()
        if training.empty:
            raise ValueError(
                "No usable training observations remain after purging overlapping labels"
            )
        assert_chronology(training, validation)
        result.append(
            {
                "fold": index + 1,
                "train_sessions": train_sessions,
                "validation_sessions": validation_sessions,
                "training": training,
                "validation": validation,
                "purged_observations": before - len(training),
            }
        )
    return result


def ml_dependencies():
    from importlib.metadata import PackageNotFoundError, version

    try:
        return {
            "available": True,
            "sklearn_version": version("scikit-learn"),
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
        }
    except PackageNotFoundError:
        return {
            "available": False,
            "reason": "RandomForest requires the optional research dependencies. Run uv sync --group research on the server.",
        }


def _forest_parameters(seed, estimators, threshold):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be a whole number between 0 and 4294967295")
    if type(estimators) is not int or not 50 <= estimators <= 500:
        raise ValueError("estimators must be a whole number between 50 and 500")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not np.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise ValueError("Prediction threshold must be between 0 and 1")


def _fit_forest(training, *, seed, estimators, check_cancel=None):
    from services.research.dataset import digest
    from services.research.ml_prediction import training_weights

    dependencies = ml_dependencies()
    if not dependencies["available"]:
        raise ValueError(dependencies["reason"])
    from sklearn.ensemble import RandomForestClassifier

    if check_cancel:
        check_cancel()
    x = _require_frame_columns(training, ML_FEATURES).to_numpy(dtype=float)
    labels = training.net_r.to_numpy(dtype=float)
    if not np.isfinite(labels).all():
        raise ValueError("Training labels must be finite")
    y = (labels > 0).astype(int)
    sample_weights = training_weights(training, uniqueness=True)
    provenance_columns = [
        "timestamp",
        "direction",
        "symbol",
        "net_r",
        "label_exit_at",
        *ML_FEATURES,
    ]
    provenance = digest(training[provenance_columns].to_dict("records"))
    classes = np.unique(y)
    if len(classes) == 1:
        model = None
        artifact = {"constant": float(classes[0]), "trees": []}
    else:
        weights = {
            int(label): len(y) / (len(classes) * int((y == label).sum())) for label in classes
        }
        model = RandomForestClassifier(
            n_estimators=25,
            max_depth=8,
            min_samples_leaf=5,
            class_weight=weights,
            random_state=seed,
            n_jobs=1,
            warm_start=True,
        )
        # Bounded batches let cancellation and the worker lease be checked during a fit.
        for count in range(25, estimators + 25, 25):
            if check_cancel:
                check_cancel()
            model.set_params(n_estimators=min(count, estimators))
            model.fit(x, y, sample_weight=sample_weights)
        artifact = {
            "trees": [
                {
                    "children_left": tree.tree_.children_left.tolist(),
                    "children_right": tree.tree_.children_right.tolist(),
                    "feature": tree.tree_.feature.tolist(),
                    "threshold": tree.tree_.threshold.tolist(),
                    "value": tree.tree_.value.tolist(),
                }
                for tree in model.estimators_
            ],
            "classes": model.classes_.tolist(),
        }
    artifact.update(
        schema_version=2,
        feature_recipe="causal-two-session-v1",
        weighting="session_balanced_average_uniqueness",
        sample_weight_hash=digest(sample_weights.tolist()),
        feature_importance=dict(
            zip(
                ML_FEATURES,
                model.feature_importances_.tolist()
                if model is not None
                else [0.0] * len(ML_FEATURES),
                strict=True,
            )
        ),
        features=list(ML_FEATURES),
        training_hash=provenance,
        dependencies=dependencies,
    )
    if check_cancel:
        check_cancel()
    return model, artifact


def _predict_forest(model, artifact, frame):
    from services.research.ml_artifact import predict_probabilities

    x = _require_frame_columns(frame, ML_FEATURES).to_numpy(dtype=float)
    predicted = predict_probabilities(artifact, x)
    if not np.isfinite(predicted).all():
        raise ValueError("RandomForest predictions must be finite")
    return predicted


def prediction_accuracy(frame, predictions, threshold):
    """Labelled opportunity accuracy is not the win rate of executed trades."""
    labels = pd.to_numeric(frame.net_r, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(labels)
    actual = labels[valid] > 0
    guessed = np.asarray(predictions)[valid] > threshold
    tp = int((actual & guessed).sum())
    tn = int((~actual & ~guessed).sum())
    fp = int((~actual & guessed).sum())
    fn = int((actual & ~guessed).sum())
    count = int(valid.sum())
    return {
        "labelled_observations": count,
        "unlabelled_observations": int((~valid).sum()),
        "accuracy_pct": round((tp + tn) / count * 100, 2) if count else None,
        "precision_pct": round(tp / (tp + fp) * 100, 2) if tp + fp else None,
        "recall_pct": round(tp / (tp + fn) * 100, 2) if tp + fn else None,
        "majority_baseline_pct": round(
            max(int(actual.sum()), count - int(actual.sum())) / count * 100, 2
        )
        if count
        else None,
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
    }


def prediction_diagnostics(training, target, predictions):
    from services.research.ml_prediction import (
        daily_mse,
        paired_daily_interval,
        prediction_metrics,
        reliability_bins,
    )

    valid = target.net_r.notna()
    actual = (target.loc[valid, "net_r"] > 0).astype(float).to_numpy()
    scores = np.asarray(predictions)[valid]
    dates = target.loc[valid, "timestamp"].tolist()
    if not len(actual):
        return {"brier_score": None, "reliability": [], "baseline_difference_95": None}
    baseline = np.full(len(actual), float((training.net_r > 0).mean()))
    candidate_mse, baseline_mse = (
        daily_mse(actual, scores, dates),
        daily_mse(actual, baseline, dates),
    )
    return {
        "brier_score": prediction_metrics(actual, scores, dates)["mse"],
        "baseline_brier_score": prediction_metrics(actual, baseline, dates)["mse"],
        "baseline_probability": float(baseline[0]),
        "baseline_difference_95": paired_daily_interval(candidate_mse, baseline_mse)
        if len(candidate_mse) >= 10
        else None,
        "reliability": reliability_bins(actual, scores, dates),
        "convention": "Equal-session Brier loss; training-only constant-probability baseline. Five-session block interval. Negative differences favor the model. Reliability is diagnostic only, not fitted on evaluation outcomes.",
    }


def _prediction_rows(frame, predictions):
    return [
        {
            "timestamp": row.timestamp,
            "direction": row.direction,
            "symbol": row.symbol,
            "probability": float(score),
        }
        for row, score in zip(frame.itertuples(index=False), predictions, strict=True)
    ]


def random_forest_cross_validate(
    opportunities,
    *,
    seed=42,
    folds=3,
    min_train_sessions=10,
    estimators=200,
    threshold=0.5,
    check_cancel=None,
):
    from services.research.dataset import digest

    _forest_parameters(seed, estimators, threshold)
    fold_reports, predictions, schedule = [], [], {}
    for fold in chronological_folds(
        opportunities, folds=folds, min_train_sessions=min_train_sessions
    ):
        if check_cancel:
            check_cancel()
        model, artifact = _fit_forest(
            fold["training"],
            seed=(seed + fold["fold"]) % 2**32,
            estimators=estimators,
            check_cancel=check_cancel,
        )
        scores = _predict_forest(model, artifact, fold["validation"])
        choices = signal_schedule(fold["validation"], scores, threshold)
        schedule.update(choices)
        predictions.extend(_prediction_rows(fold["validation"], scores))
        fold_reports.append(
            {
                "fold": fold["fold"],
                "train_sessions": fold["train_sessions"],
                "validation_sessions": fold["validation_sessions"],
                "train_observations": len(fold["training"]),
                "validation_observations": len(fold["validation"]),
                "purged_observations": fold["purged_observations"],
                "signal_count": len(choices),
                "accuracy": prediction_accuracy(fold["validation"], scores, threshold),
                "diagnostics": prediction_diagnostics(fold["training"], fold["validation"], scores),
                "model_hash": digest(artifact),
            }
        )
    metadata = {
        "model": "RandomForestClassifier",
        "seed": seed,
        "estimators": estimators,
        "threshold": threshold,
        "features": list(ML_FEATURES),
        "folds": len(fold_reports),
        "folds_report": fold_reports,
        "validation": "expanding chronological sessions; overlapping training labels purged",
    }
    return {
        "schedule": schedule,
        "predictions": predictions,
        "model_metadata": metadata,
        "model_hash": digest(metadata),
        "prediction_hash": digest(predictions),
    }


def random_forest_signals(
    opportunities,
    train_sessions,
    target_sessions,
    *,
    seed=42,
    estimators=200,
    threshold=0.5,
    check_cancel=None,
):
    from services.research.dataset import digest

    _forest_parameters(seed, estimators, threshold)
    if not train_sessions or not target_sessions or set(train_sessions) & set(target_sessions):
        raise ValueError("RandomForest signals require distinct training and target sessions")
    ordered = opportunities.sort_values(
        ["timestamp", "direction", "symbol"], kind="stable"
    ).reset_index(drop=True)
    days = ordered.timestamp.str[:10]
    training = ordered[days.isin(train_sessions)].dropna(subset=["net_r", "label_exit_at"])
    target = ordered[days.isin(target_sessions)].copy()
    if training.empty or target.empty:
        raise ValueError("RandomForest signals require usable training and target observations")
    # Fail rather than silently fitting across a user-specified split boundary.
    assert_chronology(training, target)
    model, artifact = _fit_forest(
        training, seed=seed, estimators=estimators, check_cancel=check_cancel
    )
    scores = _predict_forest(model, artifact, target)
    metadata = {
        "model": "RandomForestClassifier",
        "seed": seed,
        "estimators": estimators,
        "threshold": threshold,
        "features": list(ML_FEATURES),
        "train_sessions": list(train_sessions),
        "target_sessions": list(target_sessions),
        "train_observations": len(training),
        "target_observations": len(target),
        **artifact["dependencies"],
    }
    predictions = _prediction_rows(target, scores)
    return {
        "schedule": signal_schedule(target, scores, threshold),
        "predictions": predictions,
        "artifact": artifact,
        "model_metadata": metadata,
        "model_hash": digest(artifact),
        "prediction_hash": digest(predictions),
        "accuracy": prediction_accuracy(target, scores, threshold),
        "diagnostics": prediction_diagnostics(training, target, scores),
    }
