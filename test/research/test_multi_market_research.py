import numpy as np
import pandas as pd

from scripts.research.multi_market.engine import (
    Candidate,
    features,
    signal_series,
    simulate,
    summarize,
    choose_development,
)
from scripts.research.multi_market.data import clean_minutes, resample_complete


def bars(n=600, start=1791806400):
    rng = np.random.default_rng(19)
    close = 100 + np.cumsum(rng.normal(0, 0.2, n))
    return pd.DataFrame(
        dict(
            time=start + np.arange(n) * 60,
            open=close,
            high=close + 0.3,
            low=close - 0.3,
            close=close,
            volume=10.0,
        )
    )


def test_incomplete_bars_are_not_filled_and_index_volume_stays_zero():
    d = bars(10).drop(index=2).reset_index(drop=True)
    d["volume"] = 0
    a = resample_complete(d, 5, False)
    assert len(a) == 1
    assert a.iloc[0].time == d.iloc[4].time
    assert a.iloc[0].volume == 0


def test_features_and_signals_are_causal():
    raw = bars(1600)
    a = resample_complete(raw, 5, False)
    f = features(a, False)
    short = features(a.iloc[:230].copy(), False)
    for key in ["atr", "adx", "rsi", "ema20", "ema50", "prior_high", "prior_low"]:
        np.testing.assert_allclose(f[key].iloc[:230], short[key], equal_nan=True)
    for family in ["pullback", "retest", "range", "sweep", "regime"]:
        np.testing.assert_array_equal(
            signal_series(f, family, True, False)[:230], signal_series(short, family, True, False)
        )


def execution_case(side=1, high=112, low=88, opening=100):
    d = bars(4)
    d.loc[:, "open"] = 100.0
    d.loc[:, "close"] = 100.0
    d.loc[:, "high"] = 100.0
    d.loc[:, "low"] = 100.0
    d.loc[1, ["open", "high", "low", "close"]] = [opening, high, low, opening]
    sig = pd.DataFrame([dict(time=d.time.iloc[0], end=d.time.iloc[1], side=side, atr=10.0)])
    c = Candidate("pullback", 5, False, 1, 1, 30)
    return simulate(d, sig, c, False, slippage=0, fee_rate=0, units=1, max_per_day=3)


def test_stop_wins_when_same_minute_touches_both_and_short_is_symmetric():
    for side in [1, -1]:
        t = execution_case(side)[0]
        assert t["reason"] == "sl"
        assert t["net"] == -10


def test_gap_through_stop_fills_at_worse_open():
    d = bars(4)
    d.loc[:, ["open", "high", "low", "close"]] = 100.0
    d.loc[2, ["open", "high", "low", "close"]] = [80, 85, 75, 80]
    sig = pd.DataFrame([dict(time=d.time.iloc[0], end=d.time.iloc[1], side=1, atr=10.0)])
    t = simulate(
        d, sig, Candidate("pullback", 5, False, 1, 1, 30), False, slippage=0, fee_rate=0, units=1
    )[0]
    assert t["entry"] == 100 and t["exit"] == 80 and t["reason"] == "sl"


def test_fees_can_turn_gross_winner_into_net_loser():
    d = bars(3)
    d.loc[:, ["open", "close"]] = 100
    d.loc[:, "high"] = 100.6
    d.loc[:, "low"] = 100
    s = pd.DataFrame([dict(time=d.time.iloc[0], end=d.time.iloc[1], side=1, atr=0.5)])
    c = Candidate("pullback", 5, False, 1, 1, 30)
    t = simulate(d, s, c, False, slippage=0, fee_rate=0.004, units=1)[0]
    assert t["gross"] > 0 and t["net"] < 0


def test_missing_minute_is_unresolved_not_a_winner():
    d = bars(5)
    d.loc[:, ["open", "high", "low", "close"]] = 100.0
    s = pd.DataFrame([dict(time=d.time.iloc[0], end=d.time.iloc[1], side=1, atr=10)])
    d = d.drop(index=2).reset_index(drop=True)
    t = simulate(
        d, s, Candidate("pullback", 5, False, 1, 1, 30), False, slippage=0, fee_rate=0, units=1
    )[0]
    assert t["reason"] == "missing_data" and t["net"] is None
    assert summarize([t])["unresolved"] == 1


def test_selection_uses_development_only():
    rows = [
        dict(id="a", trades=50, win_rate=0.8, expectancy=0.1, profit_factor=1.5, drawdown=3),
        dict(id="b", trades=50, win_rate=0.9, expectancy=-0.1, profit_factor=0.5, drawdown=4),
    ]
    assert choose_development(rows)[0]["id"] == "a"


def test_bad_ohlc_and_repaired_rows_are_excluded():
    d = bars(5)
    d["repaired"] = False
    d.loc[1, "low"] = 200
    d.loc[2, "repaired"] = True
    clean, audit = clean_minutes(d, False)
    assert len(clean) == 3 and audit["invalid_or_repaired"] == 2


def test_daily_limit_prevents_fourth_entry():
    d = bars(8)
    d.loc[:, ["open", "close"]] = 100
    d.loc[:, "high"] = 103
    d.loc[:, "low"] = 99.9
    signals = pd.DataFrame(
        [dict(time=d.time.iloc[i], end=d.time.iloc[i + 1], side=1, atr=1) for i in range(6)]
    )
    trades = simulate(
        d,
        signals,
        Candidate("pullback", 5, False, 1, 1, 30),
        False,
        slippage=0,
        fee_rate=0,
        units=1,
    )
    assert len(trades) == 3


def test_trailing_missing_minutes_before_planned_exit_are_unresolved():
    d = bars(2)
    d.loc[:, ["open", "high", "low", "close"]] = 100.0
    sig = pd.DataFrame([dict(time=d.time.iloc[0] - 60, end=d.time.iloc[0], side=1, atr=10.0)])
    t = simulate(
        d, sig, Candidate("pullback", 5, False, 1, 1, 30), False, slippage=0, fee_rate=0, units=1
    )[0]
    assert t["reason"] == "missing_data" and t["net"] is None


def test_all_winners_pass_factor_gate_but_require_enough_samples():
    from scripts.research.multi_market.engine import factor_at_least

    m = dict(
        trades=40, wins=40, profit_factor=None, net=20, expectancy=0.5, win_rate=1.0, unresolved=0
    )
    assert factor_at_least(m, 1.2)
    assert choose_development([m]) == [m]
    assert choose_development([{**m, "trades": 2, "wins": 2}]) == []
    assert not factor_at_least({**m, "wins": 0, "net": 0}, 1.2)
    assert factor_at_least({**m, "wins": 32}, 1.2)


def test_unresolved_stress_cannot_qualify():
    from scripts.research.multi_market.run import qualified

    m = dict(trades=100, wins=85, win_rate=0.85, expectancy=1, profit_factor=2.0, unresolved=0)
    assert not qualified(m, dict(net=100, unresolved=1), 180)
    assert qualified(m, dict(net=100, unresolved=0), 180)


def test_missing_tail_with_next_quote_beyond_exit_is_unresolved():
    d = bars(3)
    d.loc[:, ["open", "high", "low", "close"]] = 100.0
    d.loc[2, "time"] += 86400
    sig = pd.DataFrame([dict(time=d.time.iloc[0] - 60, end=d.time.iloc[0], side=1, atr=10.0)])
    t = simulate(
        d, sig, Candidate("pullback", 5, False, 1, 1, 30), False, slippage=0, fee_rate=0, units=1
    )[0]
    assert t["reason"] == "missing_data" and t["net"] is None


def test_exit_before_data_gap_remains_valid():
    d = bars(3)
    d.loc[:, ["open", "high", "low", "close"]] = 100.0
    d.loc[1, "high"] = 111
    d.loc[2, "time"] += 3600
    sig = pd.DataFrame([dict(time=d.time.iloc[0] - 60, end=d.time.iloc[0], side=1, atr=10.0)])
    t = simulate(
        d, sig, Candidate("pullback", 5, False, 1, 1, 30), False, slippage=0, fee_rate=0, units=1
    )[0]
    assert t["reason"] == "target" and t["net"] == 10


def test_indian_session_closes_at_1515_and_positions_cannot_overlap():
    start = int(pd.Timestamp("2026-10-15 14:45", tz="Asia/Kolkata").timestamp())
    d = bars(45, start)
    d.loc[:, ["open", "high", "low", "close"]] = 100.0
    s = pd.DataFrame(
        [
            dict(time=start - 300, end=start, side=1, atr=10.0),
            dict(time=start, end=start + 300, side=1, atr=10.0),
        ]
    )
    trades = simulate(
        d, s, Candidate("pullback", 5, False, 1, 1, 120), True, slippage=0, fee_rate=0, units=1
    )
    assert len(trades) == 1 and trades[0]["exit_time"] == start + 1800


def test_incomplete_overnight_boundary_resets_features():
    first = int(pd.Timestamp("2026-10-14 09:15", tz="Asia/Kolkata").timestamp())
    second = int(pd.Timestamp("2026-10-15 09:15", tz="Asia/Kolkata").timestamp())
    complete = pd.concat([bars(375, first), bars(100, second)], ignore_index=True)
    f = features(resample_complete(complete, 5, True), True)
    assert f.loc[f.time == second, "warm"].iloc[0]
    broken = complete[complete.time < first + 370 * 60].copy()
    broken = pd.concat([broken, bars(100, second)], ignore_index=True)
    g = features(resample_complete(broken, 5, True), True)
    assert not g.loc[g.time == second, "warm"].iloc[0]


def test_dated_option_exchange_names_are_normalized_and_zero_brokerage_has_costs():
    from scripts.research.multi_market.options import option_fees

    a = option_fees(dict(exchange="nse_fo", lot_size=65), 100, 105, "2026-10-01")
    b = option_fees(dict(exchange="NFO", lot_size=65), 100, 105, "2026-10-01")
    assert a == b and a > 0
    assert option_fees(dict(exchange="bse_fo", lot_size=20), 100, 105, "2026-10-01") > 0


def test_option_zero_volume_quotes_do_not_create_fills():
    from scripts.research.multi_market.options import executable_premiums

    d = bars(5)
    d.loc[:, ["open", "high", "low", "close"]] = 100.0
    d.loc[1, "volume"] = 0
    d.loc[2, "volume"] = np.nan
    clean = executable_premiums(d)
    assert list(clean.time) == list(d.time.iloc[[0, 3, 4]])
    signal = pd.DataFrame([dict(time=d.time.iloc[0], end=d.time.iloc[1], side=1, atr=10.0)])
    assert simulate(clean, signal, Candidate("pullback", 5, False, 1, 1, 30), True) == []
