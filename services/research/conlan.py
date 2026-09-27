"""Independent implementations of mathematical ideas in the Conlan book repository.

No upstream source is redistributed. Portfolio examples are offline fractional
asset simulations, not option execution adapters. All indexes denote observed
bar closes. Research adaptations and deviations are recorded in the study plan.
"""

import math

import numpy as np
import pandas as pd

from services.research.ema_scalp import _validate

FAMILIES = {"sma_macd": "SMA 5/34 zero-cross", "bollinger": "Bollinger 20/2 reversal"}


def _series(series):
    if (
        not isinstance(series.index, pd.DatetimeIndex)
        or series.index.tz is None
        or not series.index.is_unique
        or not series.index.is_monotonic_increasing
    ):
        raise ValueError("Require unique ordered timezone-aware observations")
    return series.astype(float)


def rule_signals(frame, family, *, band_window=20):
    _validate(frame)
    close = frame.close
    if family == "sma_macd":
        sign = np.sign(close.rolling(5).mean() - close.rolling(34).mean())
        signal = sign.where(sign.ne(sign.shift()), 0).fillna(0)
    elif family == "bollinger":
        if type(band_window) is not int or not 2 <= band_window <= 200:
            raise ValueError("Bollinger window must be between 2 and 200")
        mean, std = close.rolling(band_window).mean(), close.rolling(band_window).std(ddof=1)
        signal = pd.Series(
            np.where(close < mean - 2 * std, 1, np.where(close > mean + 2 * std, -1, 0)),
            index=frame.index,
        )
    else:
        raise ValueError("Unknown book signal family")
    out = frame[["open", "high", "low", "close"]].copy()
    out["signal"] = signal.astype(int)
    # This mapping is explicitly an option adaptation, not the stock sell rule.
    out["direction"] = np.where(signal > 0, "CE", np.where(signal < 0, "PE", ""))
    out["stop_price"] = np.where(signal > 0, frame.low, frame.high)
    return out


def money_flow(frame, window=20):
    """MFV, rolling MFV and Chaikin money flow using actual traded volume."""
    _validate(frame)
    if type(window) is not int or window < 2:
        raise ValueError("Money flow window must be at least two")
    if "volume" not in frame or not np.isfinite(frame.volume).all() or (frame.volume < 0).any():
        raise ValueError("Money flow requires observed nonnegative volume")
    span = (frame.high - frame.low).replace(0, np.nan)
    mfv = frame.volume * (2 * frame.close - frame.high - frame.low) / span
    total = mfv.rolling(window).sum()
    return pd.DataFrame(
        {
            "money_flow_volume": mfv,
            "rolling_money_flow": total,
            "chaikin_money_flow": total / frame.volume.rolling(window).sum().replace(0, np.nan),
        }
    )


def rolling_sharpe(prices, window=100):
    if type(window) is not int or window < 2:
        raise ValueError("Rolling window must be at least two observations")
    returns = prices.pct_change(fill_method=None)
    return returns.rolling(window).mean() / returns.rolling(window).std(ddof=1).replace(0, np.nan)


def calendar_change(series, days):
    """Difference from the last observation AT OR BEFORE the calendar lag."""
    series = _series(series)
    if type(days) is not int or days < 1:
        raise ValueError("Calendar lag must be a positive number of days")
    positions = series.index.searchsorted(series.index - pd.Timedelta(days=days), side="right") - 1
    values = np.full(len(series), np.nan)
    valid = positions >= 0
    values[valid] = series.to_numpy()[valid] - series.to_numpy()[positions[valid]]
    return pd.Series(values, index=series.index)


def cusum_events(changes, threshold):
    changes = _series(changes)
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("CUSUM threshold must be positive and finite")
    up = down = 0.0
    events = []
    for at, value in changes.items():
        if not math.isfinite(value):
            up = down = 0.0
            continue
        up, down = max(0.0, up + value), min(0.0, down + value)
        if up > threshold:
            events.append(at)
            up = 0.0
        elif down < -threshold:
            events.append(at)
            down = 0.0
    return pd.DatetimeIndex(events, tz=changes.index.tz)


def triple_barriers(
    prices, events, *, horizon, upper=0.02, lower=-0.01, volatility=None, bar_interval=None
):
    """Close-observed log-return barriers; missing future horizons stay unknown.

    With volatility, upper/lower are multipliers of the causal volatility at
    the event. This is distinct from intrabar option stops in the replay engine.
    The vertical exit uses the first observed close at/after the time barrier.
    """
    prices = _series(prices)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("Barrier prices must be positive and finite")
    horizon = pd.Timedelta(horizon)
    if horizon <= pd.Timedelta(0) or not (
        math.isfinite(upper) and math.isfinite(lower) and upper > 0 > lower
    ):
        raise ValueError("Invalid barrier parameters")
    rows = []
    for at in events:
        if at not in prices.index:
            raise ValueError("Event does not reference an observed price")
        start = prices.index.get_loc(at)
        end = prices.index.searchsorted(at + horizon)
        scale = float(volatility.loc[at]) if volatility is not None else 1.0
        result = {"timestamp": at, "label": np.nan, "exit_at": pd.NaT, "log_return": np.nan}
        if not math.isfinite(scale) or scale <= 0:
            rows.append(result)
            continue
        path = np.log(prices.iloc[start + 1 : min(end + 1, len(prices))] / prices.iloc[start])
        hits = path[
            (path.index <= at + horizon) & ((path >= upper * scale) | (path <= lower * scale))
        ]
        if len(hits):
            result.update(
                label=1 if hits.iloc[0] > 0 else -1,
                exit_at=hits.index[0],
                log_return=float(hits.iloc[0]),
            )
        elif end < len(prices):
            result.update(
                label=0,
                exit_at=prices.index[end],
                log_return=float(np.log(prices.iloc[end] / prices.iloc[start])),
            )
        if bar_interval is not None and pd.notna(result["exit_at"]):
            interval = pd.Timedelta(bar_interval)
            if interval <= pd.Timedelta(0):
                raise ValueError("Barrier observation interval must be positive")
            expected = pd.date_range(at + interval, result["exit_at"], freq=interval)
            if (
                result["exit_at"] > at + horizon
                or not len(expected)
                or expected[-1] != result["exit_at"]
                or not expected.isin(prices.index).all()
            ):
                result.update(label=np.nan, exit_at=pd.NaT, log_return=np.nan)
        rows.append(result)
    return pd.DataFrame(rows, columns=["timestamp", "label", "exit_at", "log_return"]).set_index(
        "timestamp"
    )


def event_uniqueness(spans, observation_index):
    """Mean inverse concurrency over each observed event span (no dense date grid)."""
    index = pd.DatetimeIndex(observation_index)
    if not index.is_unique or not index.is_monotonic_increasing or index.tz is None:
        raise ValueError("Uniqueness requires an ordered observation clock")
    first = index.searchsorted(spans.index)
    # Construct from the Series values while preserving timezone.
    last = index.searchsorted(pd.DatetimeIndex(list(spans)), side="right")
    if (last <= first).any() or (first >= len(index)).any():
        raise ValueError("Event spans must contain observed timestamps")
    delta = np.zeros(len(index) + 1)
    np.add.at(delta, first, 1)
    np.add.at(delta, last, -1)
    concurrency = np.cumsum(delta[:-1])
    inverse = np.divide(1.0, concurrency, out=np.zeros(len(index)), where=concurrency > 0)
    sums = np.r_[0.0, np.cumsum(inverse)]
    return (sums[last] - sums[first]) / (last - first)


def alternative_features(prices, releases):
    """Release-aware revenue adapter; no period-end publication assumption.

    One company's positive revenue releases, with period_end and available_at.
    Later revisions affect only later observations. Missing history stays NaN.
    """
    prices = _series(prices)
    required = {"period_end", "available_at", "revenue"}
    if not required <= set(releases):
        raise ValueError("Revenue input requires period_end, available_at and revenue")
    r = releases.copy()
    r["available_at"] = pd.to_datetime(r.available_at, utc=True)
    r["period_end"] = pd.to_datetime(r.period_end, utc=True)
    r["revenue"] = pd.to_numeric(r.revenue, errors="raise")
    if (
        r.available_at.isna().any()
        or r.period_end.isna().any()
        or r.available_at.duplicated().any()
        or (r.available_at < r.period_end).any()
        or not np.isfinite(r.revenue).all()
        or (r.revenue <= 0).any()
    ):
        raise ValueError(
            "Revenue releases require unique valid publication times and positive values"
        )
    r = r.sort_values("available_at")
    # An amendment to an older quarter must not replace the latest known quarter.
    latest_period, latest_value, values = None, np.nan, []
    for release in r.itertuples(index=False):
        if latest_period is None or release.period_end >= latest_period:
            latest_period, latest_value = release.period_end, release.revenue
        values.append(latest_value)
    r["current_revenue"] = values
    positions = pd.DatetimeIndex(r.available_at).searchsorted(prices.index, side="right") - 1
    revenue = pd.Series(np.nan, index=prices.index)
    valid = positions >= 0
    revenue.iloc[np.flatnonzero(valid)] = r.current_revenue.to_numpy()[positions[valid]]
    out = pd.DataFrame({"revenue": revenue}, index=prices.index)
    for window in (7, 30, 90, 180, 360):
        for name, values in [("price", prices), ("revenue", revenue)]:
            logs = np.log(values)
            out[f"{name}_change_{window}"] = calendar_change(logs, window)
            out[f"{name}_vol_{window}"] = (
                logs.diff().rolling(f"{window}D", min_periods=2).std(ddof=1)
            )
    out["revenue_yoy"] = calendar_change(np.log(revenue), 365)
    return out


def event_model_study(prices, features, events, *, horizon, seed=42, estimators=100):
    """Purged chronological event classifier; diagnostic research only.

    Fixed log barriers +2%/-1%; volatility is an optional separate label study.
    Ternary class predictions are mapped to long/flat asset signals. This does
    not create a strategy or allow the classifier to place orders.
    """
    from sklearn.ensemble import RandomForestClassifier

    if type(estimators) is not int or not 50 <= estimators <= 500:
        raise ValueError("Event model requires 50 to 500 trees")
    labels = triple_barriers(prices, events, horizon=horizon)
    frame = features.reindex(labels.index).replace([np.inf, -np.inf], np.nan)
    # Eligibility and split are fixed before looking at future label availability.
    valid = frame.notna().all(axis=1)
    frame, labels = frame[valid], labels[valid]
    if len(frame) < 30:
        raise ValueError("Event model requires at least 30 fully observed labelled events")
    split = int(len(frame) * 0.7)
    target = frame.iloc[split:]
    train_labels = labels.iloc[:split]
    train_labels = train_labels[train_labels.exit_at < target.index[0]].dropna(subset=["label"])
    train = frame.loc[train_labels.index]
    if len(train) < 20:
        raise ValueError("Too few training events after purging overlapping labels")
    weights = event_uniqueness(train_labels.exit_at, prices.index)
    model = RandomForestClassifier(
        n_estimators=estimators,
        max_depth=5,
        min_samples_leaf=5,
        random_state=seed,
        n_jobs=1,
        class_weight="balanced",
    )
    model.fit(train.to_numpy(), train_labels.label.astype(int), sample_weight=weights)
    predicted = model.predict(target.to_numpy())
    actual = labels.loc[target.index, "label"].to_numpy()
    known = np.isfinite(actual)
    majority = int(train_labels.label.mode().iloc[0])
    return {
        "training_events": len(train),
        "evaluation_events": len(target),
        "purged_events": split - len(train),
        "labelled_evaluation_events": int(known.sum()),
        "accuracy_pct": float((predicted[known] == actual[known]).mean() * 100)
        if known.any()
        else None,
        "training_majority_baseline_pct": float((actual[known] == majority).mean() * 100)
        if known.any()
        else None,
        "feature_importance": dict(
            zip(features.columns, model.feature_importances_.tolist(), strict=True)
        ),
        "predictions": [
            {
                "timestamp": at.isoformat(),
                "label": int(pred),
                "actual": int(y) if np.isfinite(y) else None,
                "exit_at": labels.loc[at, "exit_at"].isoformat()
                if pd.notna(labels.loc[at, "exit_at"])
                else None,
            }
            for at, pred, y in zip(target.index, predicted, actual, strict=True)
        ],
        "deployment_supported": False,
        "seed": seed,
    }


def alternative_data_study(prices, releases, *, threshold=5.0, horizon="90D", seed=42):
    features = alternative_features(prices, releases)
    events = cusum_events(features.revenue_yoy, threshold)
    result = event_model_study(
        prices,
        features.drop(columns=["revenue", "revenue_yoy"]),
        events,
        horizon=horizon,
        seed=seed,
    )
    result["event_source"] = "CUSUM of observed trailing-calendar-year log revenue changes"
    prediction = {pd.Timestamp(r["timestamp"]): r["label"] for r in result["predictions"]}
    target_prices = prices.loc[min(prediction) :].to_frame("asset")
    signals = pd.DataFrame({"asset": pd.Series(prediction).reindex(target_prices.index).fillna(0)})
    preference = pd.DataFrame(1.0, index=target_prices.index, columns=["asset"])
    result["portfolio"] = preference_portfolio(target_prices, signals, preference, max_positions=1)
    result["portfolio_convention"] = (
        "Research event-only long/flat predictions; next-observed-close fractional-asset fills, gross of instrument costs."
    )
    return result


def equity_metrics(equity, benchmark=None, *, periods_per_year=252):
    equity = _series(equity)
    if len(equity) < 2 or not np.isfinite(equity).all() or (equity <= 0).any():
        raise ValueError("Metrics require at least two positive equity observations")
    returns = equity.pct_change(fill_method=None).iloc[1:]
    growth = float(equity.iloc[-1] / equity.iloc[0])
    # Avoid overflow on very short intraday experiments; annualization is a convention.
    annual_log = np.log(growth) * periods_per_year / len(returns)
    cagr = float(np.expm1(annual_log)) if annual_log < 700 else None
    peaks = equity.cummax()
    cash_dd, pct_dd, log_dd = peaks - equity, 1 - equity / peaks, np.log(peaks / equity)
    trough = pct_dd.idxmax()
    peak = equity.loc[:trough].idxmax()
    std = float(returns.std(ddof=1))
    downside = float(np.sqrt(np.square(returns.clip(upper=0)).mean()))
    r2 = float(np.corrcoef(np.arange(len(equity)), equity)[0, 1] ** 2) if equity.std() else 0.0
    alpha = beta = None
    if benchmark is not None:
        joined = pd.concat([returns.rename("r"), benchmark.rename("b")], axis=1).dropna()
        if len(joined) >= 3 and joined.b.var() > 0:
            beta = float(joined.r.cov(joined.b) / joined.b.var())
            alpha = float(joined.r.mean() - beta * joined.b.mean())
    result = {
        "return_pct": (growth - 1) * 100,
        "cagr": cagr,
        "volatility": std * np.sqrt(periods_per_year),
        "sharpe": float(returns.mean() / std * np.sqrt(periods_per_year)) if std else None,
        "sortino": float(returns.mean() / downside * np.sqrt(periods_per_year))
        if downside
        else None,
        "pure_profit_score": cagr * r2 if cagr is not None else None,
        "calmar": cagr / float(pct_dd.max()) if cagr is not None and pct_dd.max() else None,
        "max_drawdown_cash": float(cash_dd.max()),
        "max_drawdown_pct": float(pct_dd.max() * 100),
        "max_log_drawdown": float(log_dd.max()),
        "log_return_minus_max_log_drawdown": float(np.log(growth) - log_dd.max()),
        "drawdown_peak_at": peak.isoformat(),
        "drawdown_trough_at": trough.isoformat(),
        "jensen_alpha_per_period": alpha,
        "beta": beta,
    }
    return {
        k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in result.items()
    }


def preference_portfolio(closes, signals, preferences, *, max_positions=5, fee_bps=0.0):
    """Book-style long-asset ranking, next-observed-close fills, fractional units.

    Sell signals close holdings. Stronger buy candidates can replace the weakest
    held asset. Decisions and ranks use only the previous observation. This is
    an abstract asset benchmark, never claimed as executable index/options P&L.
    """
    if type(max_positions) is not int or max_positions < 1 or not 0 <= fee_bps < 10000:
        raise ValueError("Invalid portfolio constraints")
    if (
        closes.empty
        or not closes.index.is_unique
        or not closes.index.is_monotonic_increasing
        or closes.index.tz is None
        or not np.isfinite(closes).all().all()
        or (closes <= 0).any().any()
    ):
        raise ValueError("Portfolio needs complete aligned positive observations")
    if (
        not signals.index.equals(closes.index)
        or not preferences.index.equals(closes.index)
        or set(signals.columns) != set(closes.columns)
        or set(preferences.columns) != set(closes.columns)
    ):
        raise ValueError("Signals and preferences must align to the observed universe")
    fee, cash, holdings, trades, curve = fee_bps / 10000, 1.0, {}, [], [1.0]
    for i in range(1, len(closes)):
        at, decision = closes.index[i], closes.index[i - 1]
        price, signal, pref = closes.iloc[i], signals.iloc[i - 1], preferences.iloc[i - 1]

        def sell(symbol, price=price, at=at):
            nonlocal cash
            held = holdings.pop(symbol)
            proceeds = held["units"] * float(price[symbol]) * (1 - fee)
            cash += proceeds
            trades.append(
                {
                    **held,
                    "symbol": symbol,
                    "exit_at": at.isoformat(),
                    "net_pnl": proceeds - held["cost"],
                }
            )

        for symbol in sorted(holdings):
            if signal[symbol] < 0:
                sell(symbol)
        candidates = sorted(
            (s for s in closes if signal[s] > 0 and np.isfinite(pref[s]) and s not in holdings),
            key=lambda s: (-pref[s], s),
        )
        for symbol in candidates:
            if len(holdings) >= max_positions:
                worst = min(
                    holdings, key=lambda s: (pref[s] if np.isfinite(pref[s]) else -np.inf, s)
                )
                if pref[symbol] <= (pref[worst] if np.isfinite(pref[worst]) else -np.inf):
                    continue
                sell(worst)
            equity = cash + sum(h["units"] * float(price[s]) for s, h in holdings.items())
            cost = min(cash, equity / max_positions)
            if cost <= 1e-12:
                continue
            cash -= cost
            holdings[symbol] = {
                "signal_at": decision.isoformat(),
                "entry_at": at.isoformat(),
                "units": cost / (float(price[symbol]) * (1 + fee)),
                "cost": cost,
            }
        if i == len(closes) - 1:
            for symbol in sorted(holdings):
                sell(symbol)
        curve.append(cash + sum(h["units"] * float(price[s]) for s, h in holdings.items()))
    equity = pd.Series(curve, index=closes.index)
    return {
        "metrics": equity_metrics(equity),
        "equity": [{"timestamp": at.isoformat(), "equity": float(v)} for at, v in equity.items()],
        "trades": trades,
        "abstract_asset_simulation": True,
    }


def preference_controls(
    closes, signals, *, repeats=100, window=100, seed=42, max_positions=1, fee_bps=0.0
):
    if len(closes.columns) < 2:
        raise ValueError("Preference controls require at least two independent assets")
    if type(repeats) is not int or not 1 <= repeats <= 1000:
        raise ValueError("Control repeats must be between 1 and 1000")
    if len(closes) <= window:
        raise ValueError("Preference controls require more history than the rolling window")
    base = rolling_sharpe(closes, window)
    reference = preference_portfolio(
        closes, signals, base, max_positions=max_positions, fee_bps=fee_bps
    )
    rng = np.random.default_rng(seed)
    results = {"white_noise": [], "bootstrap_preference": []}
    returns = closes.pct_change(fill_method=None)
    for _ in range(repeats):
        noise = pd.DataFrame(
            rng.normal(size=closes.shape), index=closes.index, columns=closes.columns
        ).where(base.notna())
        bootstrap = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
        # Bootstrap only the trailing observable return window at each decision.
        for col in closes:
            values = returns[col].to_numpy()
            windows = np.lib.stride_tricks.sliding_window_view(values, window)
            draw = rng.integers(0, window, size=windows.shape)
            samples = np.take_along_axis(windows, draw, axis=1)
            std = samples.std(axis=1, ddof=1)
            bootstrap.loc[closes.index[window - 1 :], col] = np.divide(
                samples.mean(axis=1), std, out=np.full(len(std), np.nan), where=std > 0
            )
        for name, pref in [("white_noise", noise), ("bootstrap_preference", bootstrap)]:
            results[name].append(
                preference_portfolio(
                    closes, signals, pref, max_positions=max_positions, fee_bps=fee_bps
                )["metrics"]["return_pct"]
            )
    observed = reference["metrics"]["return_pct"]
    return {
        "seed": seed,
        "window": window,
        "reference": reference,
        **{
            name: {
                "repeats": repeats,
                "returns_pct": values,
                "median_return_pct": float(np.median(values)),
                "interval_95_pct": np.quantile(values, [0.025, 0.975]).tolist(),
                "upper_tail_fraction": (1 + sum(v >= observed for v in values)) / (repeats + 1),
            }
            for name, values in results.items()
        },
    }
