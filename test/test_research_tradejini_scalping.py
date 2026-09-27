import numpy as np
import pandas as pd
import pytest

from services.research.tradejini_scalping import premium_outcome, select_atm, tradejini_signals

COST = {
    "slippage_bps": 0,
    "brokerage_per_order": 0,
    "exchange_rate": 0,
    "sebi_rate": 0,
    "gst_rate": 0,
    "stamp_buy_rate": 0,
    "stt_sell_rate": 0,
}
AT = pd.Timestamp("2025-01-02 10:00", tz="Asia/Kolkata")


def path(rows):
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume"],
        index=pd.date_range(AT, periods=len(rows), freq="min"),
    )


def result(rows, **kwargs):
    return premium_outcome(path(rows), AT, 5, 75, COST, **kwargs)


def test_long_put_and_call_have_downward_stop_and_stop_first_ambiguity():
    r = result([[100, 121, 89, 100, 100]])
    assert r["reason"] == "priced" and r["exit_reason"] == "sl"
    assert r["stop"] == 90 and r["target"] == 120 and r["net_pnl"] == -750
    assert r["ambiguous"] and r["exit_at"] == (AT + pd.Timedelta(minutes=1)).isoformat()


@pytest.mark.parametrize(
    "opening,high,low,expected,reason", [(80, 100, 79, 80, "sl"), (130, 140, 89, 120, "target")]
)
def test_opening_gap_priority_worse_stop_but_target_capped(opening, high, low, expected, reason):
    r = result([[100, 101, 99, 100, 100], [opening, high, low, opening, 100]])
    assert r["exit_price"] == expected and r["exit_reason"] == reason
    assert r["exit_at"] == (AT + pd.Timedelta(minutes=1)).isoformat()


def test_early_exit_does_not_require_later_data():
    r = result([[100, 121, 99, 120, 100]])
    assert r["net_pnl"] == 1500 and not r["ambiguous"]


def test_missing_bar_before_exit_remains_unresolved_and_entered():
    r = result([[100, 101, 99, 100, 100]])
    assert r["reason"] == "missing_path" and r["entered"] and r["net_pnl"] is None


def test_funding_and_planned_risk_fail_before_entry():
    assert result([[300, 301, 299, 300, 100]])["reason"] == "unaffordable"
    assert result([[100, 101, 99, 100, 100]], risk_budget=700)["reason"] == "planned_risk_exceeded"


def test_time_exit_uses_boundary_open_not_its_later_high_low():
    r = result([[100, 101, 99, 100, 100]] * 5 + [[105, 200, 1, 100, 100]])
    assert r["exit_reason"] == "time" and r["exit_price"] == 105 and r["net_pnl"] == 375


def test_invalid_duplicate_and_zero_volume_prices_cannot_enter():
    q = path([[100, 101, 99, 100, 0]])
    assert premium_outcome(q, AT, 5, 75, COST)["entered"] is False
    q = path([[100, 101, 99, 100, 100]])
    assert premium_outcome(pd.concat([q, q]), AT, 5, 75, COST)["entered"] is False


def test_atm_selection_is_asof_ranked_with_no_later_expiry_or_missing_listing():
    quotes = pd.DataFrame(
        [
            {
                "expiry": "2025-01-02",
                "strike": 24950,
                "option_type": "PE",
                "close": 100,
                "volume": 750,
            },
            {
                "expiry": "2025-01-02",
                "strike": 25050,
                "option_type": "PE",
                "close": 80,
                "volume": 750,
            },
            {
                "expiry": "2025-01-09",
                "strike": 25000,
                "option_type": "PE",
                "close": 60,
                "volume": 750,
            },
        ]
    )
    listing = {
        (r.expiry, float(r.strike), r.option_type): {"lot_size": 75} for r in quotes.itertuples()
    }
    assert select_atm(quotes, listing, 25000, "PE", "2025-01-02")["strike"] == 24950
    assert select_atm(quotes, {}, 25000, "PE", "2025-01-02") is None


def minutes(n=350):
    close = 25000 + np.random.default_rng(19).normal(size=n).cumsum()
    return pd.DataFrame(
        {"open": close - 0.6, "high": close + 0.2, "low": close - 0.8, "close": close},
        index=pd.date_range("2025-01-02 09:16", periods=n, freq="min", tz="Asia/Kolkata"),
    )


@pytest.mark.parametrize("tf", [1, 3])
def test_prefix_invariance_and_ema_warmup(tf):
    f = minutes()
    for family in ("ema921", "box"):
        full, prefix = tradejini_signals(f, tf, family), tradejini_signals(f.iloc[:240], tf, family)
        pd.testing.assert_frame_equal(full.loc[prefix.index], prefix)
    assert tradejini_signals(f, tf, "ema921").iloc[:104].direction.eq("").all()


def test_box_waits_for_full_range_and_first_breakout_only():
    f = minutes(35)
    f.loc[:, ["open", "high", "low", "close"]] = [100, 111, 89, 100]
    f.iloc[15] = [110, 115, 109, 114]
    f.iloc[17] = [114, 120, 113, 119]
    r = tradejini_signals(f, 1, "box")
    assert r[r.direction != ""].index.to_list() == [f.index[15]]
    assert tradejini_signals(f.drop(f.index[5]), 1, "box").direction.eq("").all()
    f.iloc[15] = [113, 116, 108, 114]  # First break is weak: later strong break is ignored.
    assert tradejini_signals(f, 1, "box").direction.eq("").all()


@pytest.mark.parametrize("tf,missing,breakout", [(1, 15, 19), (3, 15, 29)])
def test_box_missing_earlier_candle_cannot_prove_first_breakout(tf, missing, breakout):
    f = minutes(35)
    f.loc[:, ["open", "high", "low", "close"]] = [100, 111, 89, 100]
    f.iloc[breakout] = [100, 121, 99, 120]
    assert tradejini_signals(f, tf, "box").direction.ne("").sum() == 1
    assert tradejini_signals(f.drop(f.index[missing]), tf, "box").direction.eq("").all()


def test_future_duplicate_does_not_invalidate_earlier_exit():
    q = path([[100, 121, 99, 120, 100], [100, 101, 99, 100, 100]])
    q = pd.concat([q, q.iloc[1:]])
    assert premium_outcome(q, AT, 5, 75, COST)["net_pnl"] == 1500


def test_admission_cap_counts_only_entered_and_unresolved_blocks_until_deadline():
    from scripts.research_tradejini_scalping import simulate

    ats = [AT + pd.Timedelta(minutes=n) for n in (0, 1, 2, 6, 7, 8)]
    requests = pd.DataFrame(
        [
            {"id": i, "signal_time": at, "day": "2025-01-02", "direction": "PE"}
            for i, at in enumerate(ats)
        ]
    )
    selections = {i: {"lot_size": 75} for i in (1, 2, 3, 4, 5)}
    paths = {
        i: pd.DataFrame(
            [[100, 121, 99, 120, 100]],
            columns=["open", "high", "low", "close", "volume"],
            index=[at],
        )
        for i, at in enumerate(ats)
    }
    paths[1].loc[:, "high"] = 101  # Entered but no next bar: consumes slot and blocks until10:06.
    paths[1].loc[:, "close"] = 100
    rows, skipped = simulate(requests, selections, paths, 5, COST)
    assert [r["id"] for r in rows] == [0, 1, 3, 4]
    assert rows[1]["reason"] == "missing_path"
    assert skipped == {"position_open": 1, "daily_three_entry_cap": 1}


def test_stress_slippage_and_fees_reduce_net_reward_and_raise_planned_risk():
    costs = COST | {"slippage_bps": 30, "brokerage_per_order": 20, "gst_rate": 0.18}
    q = path([[100, 121, 99, 120, 100]])
    r = premium_outcome(q, AT, 5, 75, costs)
    assert r["entry_price"] == 100.3 and r["target"] == 120.3 and r["exit_price"] == 119.9
    assert r["net_pnl"] == 1422.8 and r["planned_loss"] == 819.7
    assert (
        premium_outcome(q, AT, 5, 75, costs, risk_budget=819.69)["reason"]
        == "planned_risk_exceeded"
    )
    assert premium_outcome(q, AT, 5, 75, costs, risk_budget=819.70)["reason"] == "priced"


def test_ema_fresh_up_and_down_crosses_require_directional_body():
    f = minutes(115)
    f.loc[:, ["open", "high", "low", "close"]] = [100, 101, 99, 100]
    f.iloc[109] = [100, 102.1, 99.9, 102]
    f.iloc[110] = [102, 102.1, 97.9, 98]
    r = tradejini_signals(f, 1, "ema921")
    assert r.iloc[109].direction == "CE" and r.iloc[110].direction == "PE"
    f.iloc[109] = [102.1, 102.2, 99.9, 102]
    assert tradejini_signals(f, 1, "ema921").iloc[109].direction == ""
