"""The smart exit's decision, case by case."""

from __future__ import annotations

from ml_signals.exits import decide_exit

BASE = {
    "side": "LONG",
    "opened_at": 1_000.0,
    "now": 1_000.0 + 5 * 60,
    "pnl_pct": 0.05,
    "exit_fee_pct_now": 0.0,
    "exit_fee_pct_after_window": 0.059,
    "window_remaining_minutes": 25.0,
    "max_hold_minutes": 28,
    "confirmations": 2,
}


def _signal(action="LONG", t=600, ev_long=0.2, ev_short=-0.1):
    return {"action": action, "time": t, "ev_long_pct": ev_long, "ev_short_pct": ev_short}


def test_a_healthy_trade_is_left_alone():
    decision = decide_exit(**BASE, signal=_signal())
    assert not decision.close
    assert decision.streak == 0


def test_one_opposite_bar_is_not_enough():
    decision = decide_exit(**BASE, signal=_signal("SHORT", ev_long=-0.1, ev_short=0.2))
    assert not decision.close
    assert decision.streak == 1 and decision.last_bar == 600


def test_two_opposite_bars_in_a_row_close_it():
    first = decide_exit(**BASE, signal=_signal("SHORT", 600, -0.1, 0.2))
    second = decide_exit(
        **BASE,
        signal=_signal("SHORT", 900, -0.1, 0.2),
        streak=first.streak,
        last_bar=first.last_bar,
    )
    assert second.close and second.reason == "model_flip"


def test_the_same_bar_is_counted_once():
    first = decide_exit(**BASE, signal=_signal("SHORT", 600, -0.1, 0.2))
    again = decide_exit(
        **BASE,
        signal=_signal("SHORT", 600, -0.1, 0.2),
        streak=first.streak,
        last_bar=first.last_bar,
    )
    assert not again.close and again.streak == 1


def test_a_good_bar_resets_the_count():
    first = decide_exit(**BASE, signal=_signal("SHORT", 600, -0.1, 0.2))
    good = decide_exit(**BASE, signal=_signal("LONG", 900), streak=first.streak, last_bar=600)
    assert good.streak == 0


def test_holding_worth_less_than_closing_exits_after_confirmation():
    args = {**BASE, "exit_fee_pct_now": 0.059, "window_remaining_minutes": None}
    first = decide_exit(**args, signal=_signal("WAIT", 600, ev_long=0.01))
    second = decide_exit(
        **args, signal=_signal("WAIT", 900, ev_long=0.02), streak=first.streak, last_bar=600
    )
    assert second.close and second.reason == "low_expected_value"


def test_the_hold_cap_closes_regardless_of_the_model():
    decision = decide_exit(**{**BASE, "now": 1_000.0 + 28 * 60}, signal=_signal())
    assert decision.close and decision.reason == "hold_cap"


def test_a_losing_trade_is_closed_before_the_free_window_shuts():
    args = {**BASE, "pnl_pct": -0.02, "window_remaining_minutes": 0.5}
    decision = decide_exit(**args, signal=_signal("WAIT", ev_long=0.03))
    assert decision.close and decision.reason == "scalper_window"


def test_a_winning_trade_is_not_closed_by_the_window():
    args = {**BASE, "pnl_pct": 0.1, "window_remaining_minutes": 0.5}
    assert not decide_exit(**args, signal=_signal()).close


def test_a_loser_the_model_still_backs_is_held_past_the_window():
    args = {**BASE, "pnl_pct": -0.02, "window_remaining_minutes": 0.5}
    assert not decide_exit(**args, signal=_signal(ev_long=0.3)).close


def test_shorts_read_the_short_expected_value():
    args = {**BASE, "side": "SHORT", "exit_fee_pct_now": 0.059, "window_remaining_minutes": None}
    first = decide_exit(**args, signal=_signal("WAIT", 600, ev_long=0.5, ev_short=0.0))
    assert first.streak == 1
