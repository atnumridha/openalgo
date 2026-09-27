"""Adapt complete, intraday replay outcomes to the existing portfolio analytics."""

import math
import warnings

import numpy as np
import pandas as pd


def session_returns(trades, sessions, *, initial=10000):
    daily = dict.fromkeys(sorted(sessions), 0.0)
    for trade in trades:
        daily[trade["exit_at"][:10]] += trade["net_pnl"]
    equity, values = float(initial), []
    for pnl in daily.values():
        if equity <= 0:
            raise ValueError("Session returns require positive prior equity")
        values.append(pnl / equity)
        equity += pnl
    return pd.Series(values, index=pd.to_datetime(list(daily)), dtype=float)


def session_analytics(report, sessions, *, initial=10000):
    result = {
        "session_count": len(sessions),
        "annualization_sessions": 252,
        "benchmark": None,
        "metrics": {},
        "convention": "Net closed-trade equity per session, including no-trade sessions; 252-session annualization, zero risk-free rate. Short-window annualization is unstable. No benchmark alpha is inferred.",
    }
    if report["incomplete_outcomes"] or len(sessions) < 2:
        return result
    returns = session_returns(report["trades"], sessions, initial=initial)
    if (returns == 0).all():
        result["metrics"] = {"cagr": 0.0, "volatility": 0.0, "sharpe": None, "sortino": None}
        return result
    from portfolio.analytics import summary

    # Ratios with zero denominators are unavailable, not infinity in a JSON report.
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        values = summary(returns)
    result["metrics"] = {
        key: value if math.isfinite(value) else None
        for key, value in values.items()
        if key in {"cagr", "volatility", "sharpe", "sortino"}
    }
    return result
