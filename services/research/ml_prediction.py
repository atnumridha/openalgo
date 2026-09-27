"""Causal option-direction features and session-balanced prediction diagnostics."""

import numpy as np
import pandas as pd


def align_direction(frame):
    """Express a move in the direction that benefits the selected long option."""
    if "direction_ce" not in frame or not frame.direction_ce.isin([0, 1]).all():
        raise ValueError("Option direction must be encoded as CE=1 or PE=0")
    out = frame.copy()
    side = frame.direction_ce * 2 - 1
    signed = {
        "u_return_1",
        "u_return_3",
        "u_return_6",
        "u_return_12",
        "u_ema_8_distance",
        "u_ema_21_distance",
        "u_ema_50_distance",
        "u_trend_spread",
        "u_trend_slope",
        "u_macd",
        "u_macd_histogram",
        "u_bollinger_position",
        "u_body",
        "u_directional_spread",
        "moneyness",
    }
    for column in signed.intersection(frame.columns):
        out[column] = frame[column] * side
    for column in ("u_rsi", "u_close_location", "u_stochastic"):
        if column in frame:
            out[column] = (frame[column] - 0.5) * side
    if {"u_high_break_distance", "u_low_break_distance"}.issubset(frame.columns):
        out["u_high_break_distance"] = np.where(
            side == 1, frame.u_high_break_distance, -frame.u_low_break_distance
        )
        out["u_low_break_distance"] = np.where(
            side == 1, frame.u_low_break_distance, -frame.u_high_break_distance
        )
    return out


def recent_sessions(frame, count):
    if count < 1:
        raise ValueError("Recent window must include at least one session")
    days = frame.timestamp.str[:10]
    return frame.loc[days.isin(sorted(days.unique())[-count:])].copy()


def session_weights(timestamps):
    days = pd.Series(list(timestamps)).str[:10]
    if days.empty or days.isna().any():
        raise ValueError("Session weights require dated observations")
    counts = days.groupby(days).transform("size").to_numpy()
    return len(days) / days.nunique() / counts


def training_weights(frame, *, uniqueness=False):
    data = frame.reset_index(drop=True)
    if data.empty:
        raise ValueError("Training requires observations")
    days = data.timestamp.str[:10]
    raw = np.ones(len(data))
    if uniqueness:
        if (data.label_exit_at.str[:10] != days).any():
            raise ValueError("Training label exits must stay inside their session")
        for _, group in data.groupby(days):
            start = pd.to_datetime(group.timestamp).array.asi8 // 60_000_000_000 + 1
            end = pd.to_datetime(group.label_exit_at).array.asi8 // 60_000_000_000
            if (end < start).any() or end.max() - start.min() > 1440:
                raise ValueError("Training label intervals must be bounded and chronological")
            origin = start.min()
            start, end = start - origin, end - origin
            concurrent = np.zeros(int(end.max()) + 1)
            for first, last in zip(start, end, strict=True):
                concurrent[first : last + 1] += 1
            for index, first, last in zip(group.index, start, end, strict=True):
                raw[index] = np.mean(1 / concurrent[first : last + 1])
    totals = pd.Series(raw).groupby(days).transform("sum").to_numpy()
    return raw / totals * len(data) / days.nunique()


def _arrays(actual, predicted, timestamps):
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if (
        actual.ndim != 1
        or predicted.shape != actual.shape
        or len(actual) != len(timestamps)
        or not len(actual)
    ):
        raise ValueError("Predictions, targets and dates must have matching nonempty shapes")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Targets and predictions must be finite")
    return actual, predicted, session_weights(timestamps)


def prediction_metrics(actual, predicted, timestamps):
    actual, predicted, weight = _arrays(actual, predicted, timestamps)
    error = predicted - actual
    ranks_y, ranks_p = pd.Series(actual).rank(), pd.Series(predicted).rank()
    correlation = float(ranks_y.corr(ranks_p)) if ranks_y.std() > 0 and ranks_p.std() > 0 else None
    return {
        "observations": len(actual),
        "sessions": len({t[:10] for t in timestamps}),
        "mse": float(np.average(error**2, weights=weight)),
        "mae": float(np.average(np.abs(error), weights=weight)),
        "bias": float(np.average(error, weights=weight)),
        "mean_prediction": float(np.average(predicted, weights=weight)),
        "mean_actual": float(np.average(actual, weights=weight)),
        "rank_correlation": correlation,
    }


def fit_calibration(predicted, actual, timestamps):
    actual, predicted, weights = _arrays(actual, predicted, timestamps)
    mean_y, mean_p = np.average(actual, weights=weights), np.average(predicted, weights=weights)
    covariance = np.average((actual - mean_y) * (predicted - mean_p), weights=weights)
    variance = np.average((predicted - mean_p) ** 2, weights=weights)
    slope = float(np.clip(covariance / (variance + 0.05), 0, 1))
    return {"slope": slope, "intercept": float(mean_y - slope * mean_p)}


def daily_mse(actual, predicted, timestamps):
    actual, predicted, _ = _arrays(actual, predicted, timestamps)
    return pd.Series((predicted - actual) ** 2).groupby(pd.Series(list(timestamps)).str[:10]).mean()


def paired_daily_interval(candidate, control):
    if not candidate.index.equals(control.index) or len(candidate) < 5:
        raise ValueError("Paired comparisons need the same ordered sessions and at least five days")
    differences = (candidate - control).to_numpy()
    if not np.isfinite(differences).all():
        raise ValueError("Daily differences must be finite")
    rng = np.random.default_rng(42)
    count, length = len(differences), 5
    starts = rng.integers(0, count - length + 1, size=(2000, int(np.ceil(count / length))))
    indices = (starts[..., None] + np.arange(length)).reshape(2000, -1)[:, :count]
    means = differences[indices].mean(axis=1)
    return {
        "mean_difference": float(differences.mean()),
        "lower_95": float(np.quantile(means, 0.025)),
        "upper_95": float(np.quantile(means, 0.975)),
        "sessions": count,
        "block_sessions": length,
        "resamples": 2000,
    }


def reliability_bins(actual, predicted, timestamps):
    actual, predicted, _ = _arrays(actual, predicted, timestamps)
    edges = np.unique(np.quantile(predicted, [0, 0.2, 0.4, 0.6, 0.8, 1]))
    groups = np.searchsorted(edges[1:-1], predicted, side="right")
    timestamps = np.asarray(timestamps)
    return [
        prediction_metrics(actual[groups == i], predicted[groups == i], timestamps[groups == i])
        for i in np.unique(groups)
    ]
