"""Rule-search timeframe alignment, V2 signal parity and account-risk tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml_signals.account import AccountConfig, contracts_for_trade
from ml_signals.search import _account_summary, resample_bars


def bars(n=1000):
    rng = np.random.default_rng(34)
    close = 85000 * np.exp(np.cumsum(rng.normal(0, 0.0004, n)))
    spread = close * 0.0006
    return pd.DataFrame(
        {
            "time": 1_700_000_000 + np.arange(n) * 60,
            "open": close,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.uniform(10, 200, n),
        }
    )


def test_resample_preserves_source_end_indices_and_ohlcv():
    minute = bars(1000)
    five = resample_bars(minute, 5)
    # UTC fixed-width bucket starts at 1_700_000_000, which is 200s into a
    # 5-minute bucket, so the first partial fold ends at source row 1.
    assert int(five.iloc[0].source_end_index) == 1
    assert int(five.iloc[-1].source_end_index) == 999
    assert len(five) == 201
    first = minute.iloc[:2]
    assert five.iloc[0].open == first.iloc[0].open
    assert five.iloc[0].close == first.iloc[-1].close
    assert five.iloc[0].high == first.high.max()
    assert five.iloc[0].low == first.low.min()
    assert five.iloc[0].volume == first.volume.sum()


def test_search_account_caps_max_loss_at_two_dollars_on_one_hundred_dollar_account():
    # A -0.2% price stop at 25x is -5% of margin; the sizing must only use
    # enough notional for that loss to be $0.20 (0.2% of the $100 account).
    trades = [{"entry_price": 85_000.0, "stop_pct": 0.2, "net_pct": -0.2}]
    result = _account_summary(trades, leverage=25, start_usd=100)
    assert result["max_risk_usd_per_trade"] == 0.2
    assert result["median_risk_usd"] <= 0.2
    assert result["median_notional_usd"] <= 100
    assert result["median_margin_usd"] <= result["start_usd"]


def test_account_size_respects_leverage_and_risk_limits():
    config = AccountConfig(
        start_usd=100, max_leverage=25, risk_fraction=0.002, max_loss_fraction=0.002
    )
    size = contracts_for_trade(
        equity=100, price=85_000, stop_pct=0.2, leverage=25, config=config, risk_fraction=0.002
    )
    assert size["notional_usd"] <= 2500
    assert size["risk_usd"] <= 0.2 + 1e-9
    assert size["margin_usd"] <= 100
