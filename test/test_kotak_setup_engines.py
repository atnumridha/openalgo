"""Causal engine contracts, using hand-checked candle and observed-price tapes."""

import importlib
import importlib.util
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

START = datetime(2026, 10, 16, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()


def engine():
    # A missing engine is a feature failure, rather than a collection/import error.
    assert importlib.util.find_spec("services.kotak_assistant.setups") is not None
    return importlib.import_module("services.kotak_assistant.setups")


def bar(i, o, h, low, c, start=START, seconds=60):
    return {"time": start + i * seconds, "open": o, "high": h, "low": low, "close": c}


def seed():
    highs = [22555, 22565, 22580, 22570, 22560, 22565, 22575, 22590, 22570, 22560]
    lows = [22535, 22530, 22520, 22530, 22535, 22530, 22500, 22520, 22530, 22535]
    return [
        bar(i, (h + low) / 2, h, low, (h + low) / 2)
        for i, (h, low) in enumerate(zip(highs, lows, strict=False))
    ]


def event(t, price, identity=None, source="websocket"):
    return {"time": START + t, "price": price, "id": identity or f"{t}:{price}", "source": source}


def advance(state, bars, t, price=None, session="2026-10-16", session_start=START, **kwargs):
    return engine().advance_opening(
        state,
        bars,
        event(t, price, **kwargs) if price is not None else None,
        START + t,
        session,
        session_start,
    )


def armed(direction="PE"):
    state = engine().initial_opening_state("2026-10-16")
    return advance(state, seed(), 610, 22620 if direction == "PE" else 22480)


def test_current_session_strict_pivots_number_by_confirmation_and_freeze_second():
    state = advance(engine().initial_opening_state("2026-10-16"), seed(), 600)
    result = engine().opening_result(state, START + 600)
    highs = [p for p in result["numbered_swings"] if p["kind"] == "high"]
    lows = [p for p in result["numbered_swings"] if p["kind"] == "low"]
    assert [(p["ordinal"], p["price"], p["known_at"] - START) for p in highs] == [
        (1, 22580, 300),
        (2, 22590, 600),
    ]
    assert [(p["ordinal"], p["price"], p["known_at"] - START) for p in lows] == [
        (1, 22520, 300),
        (2, 22500, 540),
    ]
    assert result["directions"]["PE"]["reference"]["price"] == 22590
    assert result["directions"]["CE"]["reference"]["price"] == 22500
    assert result["directions"]["PE"]["stage"] == "waiting_break"


@pytest.mark.parametrize(
    "direction,price,candle,equal,cross",
    [
        ("PE", 22620, (22625, 22630, 22608, 22612), 22608, 22607),
        ("CE", 22480, (22482, 22495, 22470, 22490), 22495, 22496),
    ],
)
def test_literal_reversal_can_trigger_while_still_beyond_original_reference(
    direction, price, candle, equal, cross
):
    state = armed(direction)
    bars = seed() + [bar(10, *candle)]
    state = advance(state, bars, 660, equal)
    assert (
        engine().opening_result(state, START + 660)["directions"][direction]["stage"]
        == "waiting_trigger"
    )
    state = advance(state, bars, 661, equal)
    assert state["directions"][direction]["stage"] == "waiting_trigger"
    state = advance(state, bars, 662, cross)
    result = engine().opening_result(state, START + 662)["directions"][direction]
    assert result["stage"] == "triggered"
    assert result["index_entry"] == cross
    assert result["trigger"] == equal
    assert result["triggered_at"] == START + 662
    assert result["consumed"] and result["eligible"]


def test_history_seed_never_arms_from_missed_ohlc_breaks():
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612), bar(11, 22612, 22620, 22580, 22590)]
    state = advance(engine().initial_opening_state("2026-10-16"), bars, 720)
    assert state["directions"]["PE"]["stage"] == "waiting_break"
    assert state["directions"]["PE"]["signal_candle"] is None
    # The first actual observation can establish a break, but cannot use a red
    # candle already closed before that observation as its signal candle.
    state = advance(state, bars, 721, 22620)
    assert state["directions"]["PE"]["stage"] == "waiting_signal"
    assert state["directions"]["PE"]["signal_candle"] is None


def test_reference_break_equality_and_future_pivot_do_not_arm():
    state = advance(engine().initial_opening_state("2026-10-16"), seed(), 600, 22590)
    assert state["directions"]["PE"]["stage"] == "waiting_break"
    state = advance(state, seed(), 601, 22590.01)
    assert state["directions"]["PE"]["stage"] == "waiting_signal"
    # A tape event delayed in transit cannot see a reference confirmed later.
    state = engine().advance_opening(
        engine().initial_opening_state("2026-10-16"),
        seed(),
        event(599, 22620),
        START + 700,
        "2026-10-16",
        START,
    )
    assert state["directions"]["PE"]["stage"] == "waiting_reference"


def test_doji_and_wrong_colour_skipped_first_red_is_frozen():
    state = armed()
    bars = seed() + [bar(10, 22615, 22630, 22608, 22615), bar(11, 22615, 22635, 22610, 22620)]
    state = advance(state, bars, 720)
    assert state["directions"]["PE"]["signal_candle"] is None
    bars += [bar(12, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 780)
    first_id = state["directions"]["PE"]["setup_id"]
    bars += [bar(13, 22612, 22615, 22570, 22580)]
    state = advance(state, bars, 840)
    result = engine().opening_result(state, START + 840)["directions"]["PE"]
    assert result["signal_candle"]["time"] == START + 720
    assert result["trigger"] == 22608
    assert result["setup_id"] == first_id
    assert result["stage"] == "waiting_trigger"  # Candle low alone is not a tick.


def test_signal_requires_observation_strictly_after_its_close():
    state = armed()
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 660, 22600)
    assert state["directions"]["PE"]["stage"] == "waiting_trigger"
    state = advance(state, bars, 661, 22600)
    assert state["directions"]["PE"]["stage"] == "triggered"


def test_expiry_needs_fresh_reference_recross_and_keeps_original_reference():
    state = armed()
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 660)
    state = advance(state, bars, 961, 22620)
    assert state["directions"]["PE"]["stage"] == "expired"
    state = advance(state, bars, 962, 22625)
    assert state["directions"]["PE"]["stage"] == "expired"
    state = advance(state, bars, 963, 22590)
    state = advance(state, bars, 964, 22590.01)
    assert state["directions"]["PE"]["stage"] == "waiting_signal"
    assert state["directions"]["PE"]["reference"]["price"] == 22590
    assert state["directions"]["PE"]["break_at"] == START + 964


def test_trigger_is_once_per_direction_session_even_after_serialized_restart():
    state = armed()
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 661, 22600)
    first_id = state["directions"]["PE"]["setup_id"]
    original = json.dumps(state, sort_keys=True, allow_nan=False)
    restored = json.loads(original)
    next_state = advance(restored, bars, 1000, 22650)
    result = engine().opening_result(next_state, START + 1000)["directions"]["PE"]
    assert json.dumps(state, sort_keys=True, allow_nan=False) == original
    assert result["stage"] == "triggered" and result["consumed"]
    assert not result["eligible"]
    assert result["setup_id"] == first_id
    assert result["triggered_at"] == START + 661
    new = engine().advance_opening(
        next_state, bars, None, START + 86400, "2026-10-17", START + 86400
    )
    assert new["directions"]["PE"]["stage"] == "waiting_reference"
    assert not new["directions"]["PE"]["consumed"]
    assert new["numbered_swings"] == []


def test_duplicate_and_out_of_order_events_cannot_rewrite_a_trigger():
    state = armed()
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 661, 22600, identity="fill-observation")
    expected = state["directions"]["PE"]["triggered_at"]
    state = advance(state, bars, 661, 22600, identity="fill-observation")
    state = advance(state, bars, 650, 22500)
    assert state["directions"]["PE"]["triggered_at"] == expected


def test_sampled_snapshot_is_observation_with_its_source_disclosed():
    state = advance(
        engine().initial_opening_state("2026-10-16"), seed(), 610, 22620, source="rest_snapshot"
    )
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 661, 22600, source="rest_snapshot")
    result = engine().opening_result(state, START + 661)["directions"]["PE"]
    assert result["stage"] == "triggered"
    assert result["price_source"] == "rest_snapshot"
    assert any("sampled" in item.lower() for item in result["evidence"])


def test_equal_neighbour_is_not_strict_pivot_and_gap_cannot_confirm_one():
    bars = seed()
    bars[1] = {**bars[1], "high": 22580}
    state = advance(engine().initial_opening_state("2026-10-16"), bars, 600)
    assert [
        (p["ordinal"], p["price"]) for p in state["numbered_swings"] if p["kind"] == "high"
    ] == [(1, 22590)]
    state = advance(engine().initial_opening_state("2026-10-16"), seed()[:3] + seed()[4:], 600)
    assert not any(p["price"] == 22580 for p in state["numbered_swings"] if p["kind"] == "high")


def test_forming_candle_and_earlier_session_are_excluded_from_opening():
    old = [dict(b, time=b["time"] - 86400) for b in seed()]
    state = advance(engine().initial_opening_state("2026-10-16"), old + seed(), 599, 22620)
    assert state["directions"]["PE"]["stage"] == "waiting_reference"
    assert len([p for p in state["numbered_swings"] if p["kind"] == "high"]) == 1


def test_wilder_indicators_use_recursive_smoothing_not_rolling_average():
    e = engine()
    bars = [bar(i, 100, 101, 99, 100) for i in range(16)]
    bars[14] = bar(14, 100, 109, 99, 108)
    bars[15] = bar(15, 108, 109, 107, 108)
    values = e.indicators(bars)
    # 14 true ranges: thirteen 2s and one 10 -> 18/7. Next: (18/7*13+2)/14 = 124/49.
    assert values["atr14"][-1] == pytest.approx(124 / 49)
    assert values["rsi14"][-1] == 100
    assert values["adx14"][-1] is None  # Needs 14 DX observations after DM seed.
    flat = e.indicators([bar(i, 100, 101, 99, 100) for i in range(40)])
    assert flat["rsi14"][-1] == 50
    assert flat["adx14"][-1] == 0


def market_history():
    """250 completed 5m candles across real sessions, followed by current 1m tape."""
    days = [13, 14, 15, 16]
    five = []
    for day in days:
        start = datetime(2026, 10, day, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
        count = 75 if day < 16 else 25
        for i in range(count):
            price = 21000 + len(five) * 4
            five.append(bar(i, price, price + 8, price - 4, price + 4, start, 300))
    now = five[-1]["time"] + 300
    one = [bar(i, 21900 + i, 21903 + i, 21897 + i, 21901 + i, now - 60 * 60) for i in range(60)]
    return one, five, now


def test_trend_requires_exact_completed_warmup_and_fresh_contiguous_bars():
    one, five, now = market_history()
    e = engine()
    assert e.trend_setup(one, five[:-1], now)["stage"] == "waiting_history"
    assert e.trend_setup(one[:-1], five, now)["stage"] == "waiting_history"
    assert e.trend_setup(one, five, now + 126)["stage"] == "blocked"
    missing = one[:30] + one[31:] + [bar(60, 21960, 21963, 21957, 21961, now - 3600)]
    assert e.trend_setup(missing, five, now + 60)["stage"] == "blocked"
    # The overnight gaps in the warmup are expected exchange-session boundaries.
    assert e.trend_setup(one, five, now)["stage"] not in ("waiting_history", "blocked")


def test_trend_rsi_is_evidence_only_and_does_not_block_strong_direction():
    one, five, now = market_history()
    result = engine().trend_setup(one, five, now)
    assert result["direction"] == "CE"
    assert result["indicators"]["rsi14"] == 100
    assert result["stage"] != "waiting_trend"
    assert result["version"] and result["mode"] == "confirmed"
    with pytest.raises(ValueError):
        engine().trend_setup(one, five, now, mode="automatic")


def test_observation_reset_preserves_references_but_requires_real_recross():
    e = engine()
    state = armed()
    reference = state["directions"]["PE"]["reference"]
    original = json.dumps(state, sort_keys=True)
    assert callable(getattr(e, "reset_observation", None))
    state = e.reset_observation(state, START + 620, "feed reconnect")
    assert state["directions"]["PE"]["reference"] == reference
    assert state["directions"]["PE"]["stage"] == "expired"
    assert state["last_event"] is None
    assert "feed reconnect" in state["directions"]["PE"]["reason"]
    state = advance(state, seed(), 621, 22620)
    assert state["directions"]["PE"]["stage"] == "expired"
    state = advance(state, seed(), 622, 22590)
    state = advance(state, seed(), 623, 22590.01)
    assert state["directions"]["PE"]["stage"] == "waiting_signal"
    assert original != json.dumps(state, sort_keys=True)
    # A consumed signal survives feed resets and cannot emit again.
    done = advance(armed(), seed() + [bar(10, 22625, 22630, 22608, 22612)], 661, 22600)
    done = e.reset_observation(done, START + 700, "feed reconnect")
    assert done["directions"]["PE"]["stage"] == "triggered"
    assert done["directions"]["PE"]["triggered_at"] == START + 661


def trend_tape():
    _, five, _ = market_history()
    for _ in range(10):
        last = five[-1]
        price = last["open"] + 4
        five.append(
            {
                "time": last["time"] + 300,
                "open": price,
                "high": price + 8,
                "low": price - 4,
                "close": price + 4,
            }
        )
    now = five[-1]["time"] + 300
    one = [bar(i, 21910, 21912, 21908, 21910, now - 3600) for i in range(60)]
    one[58] = bar(58, 21910, 21923, 21909, 21920, now - 3600)
    one[59] = bar(59, 21920, 21925, 21915, 21922, now - 3600)
    return one, five, now


def test_confirmed_retest_freezes_entry_atr_zone_stop_and_projected_2r():
    one, five, now = trend_tape()
    result = engine().trend_setup(one, five, now)
    assert result["stage"] == "ready"
    assert result["pattern"] == "retest"
    assert result["reference"]["price"] == 21916  # First completed opening-15m high.
    assert result["reference"]["known_at"] == START + 900
    assert result["index_entry"] == 21922
    assert result["invalidation"] == pytest.approx(21914.49081632653)
    assert result["entry_zone"] == pytest.approx(
        {"lower": 21920.727040816328, "upper": 21923.272959183672}
    )
    assert result["index_target"] == pytest.approx(21937.01836734694)
    assert result["expires"] == now + 120
    assert result["target_source"] == "projected_2r"
    assert result["eligible"]


def test_early_is_first_buffered_break_and_does_not_refresh_on_later_closes():
    one, five, now = trend_tape()
    one[-1] = dict(one[-1], open=21920, high=21921, low=21919, close=21920)
    one.insert(0, dict(one[0], time=one[0]["time"] - 60))
    e = engine()
    early = e.trend_setup(one, five, now, "early")
    assert early["stage"] == "ready" and early["pattern"] == "early_break"
    assert early["index_entry"] == 21920
    assert early["signal_candle"]["time"] == now - 120
    assert e.trend_setup(one, five, now)["stage"] == "waiting_pattern"
    extra = {"time": now, "open": 21920, "high": 21921, "low": 21919, "close": 21920}
    later = e.trend_setup(one + [extra], five, now + 60, "early")
    assert later["stage"] == "expired"
    assert later["setup_id"] == early["setup_id"]
    assert later["index_entry"] == 21920


def test_confirmed_retest_window_is_three_bars_and_expires_after_two_more():
    one, five, now = trend_tape()
    e = engine()
    first = e.trend_setup(one, five, now)
    extra = [
        {"time": now + i * 60, "open": 21922, "high": 21923, "low": 21921, "close": 21922}
        for i in range(2)
    ]
    later = e.trend_setup(one + extra, five, now + 120)
    assert later["stage"] == "expired"
    assert later["setup_id"] == first["setup_id"]
    # A retest four bars after the first break cannot become a new setup.
    one[54] = bar(54, 21910, 21923, 21909, 21920, now - 3600)
    for i in range(55, 59):
        one[i] = bar(i, 21920, 21922, 21918, 21920, now - 3600)
    assert e.trend_setup(one, five, now)["stage"] == "waiting_pattern"


def test_missed_zone_does_not_chase_or_change_the_frozen_entry():
    one, five, now = trend_tape()
    first = engine().trend_setup(one, five, now)
    extra = {"time": now, "open": 21922, "high": 21940, "low": 21921, "close": 21939}
    later = engine().trend_setup(one + [extra], five, now + 60)
    assert later["stage"] == "missed" and not later["eligible"]
    assert later["setup_id"] == first["setup_id"]
    assert later["index_entry"] == 21922


def test_sweep_requires_subsequent_closed_confirmation_and_no_future_target_leak():
    one, five, now = trend_tape()
    one[-2] = bar(58, 21910, 21912, 21894, 21908, now - 3600)
    one[-1] = bar(59, 21908, 21922, 21907, 21920, now - 3600)
    e = engine()
    assert e.trend_setup(one, five, now - 60)["stage"] == "waiting_history"  # only 59 completed 1m
    result = e.trend_setup(one, five, now)
    assert result["stage"] == "ready" and result["pattern"] == "sweep"
    assert result["reference"]["price"] == 21896
    # A swing confirmed at 12:10 cannot alter a setup confirmed at 12:09.
    one, five, now = trend_tape()
    one[57], one[58], one[59] = (
        dict(one[58], time=now - 180),
        dict(one[59], time=now - 120),
        dict(one[59], time=now - 60),
    )
    one.insert(0, dict(one[0], time=one[0]["time"] - 60))
    five[257] = dict(five[257], high=22100)
    result = e.trend_setup(one, five, now)
    assert result["stage"] == "ready"
    assert result["target_source"] == "projected_2r"
    assert result["index_target"] < 22000
    assert result["signal_candle"]["closed_at"] == now - 60


def test_nearest_opposing_level_with_less_than_2r_blocks_instead_of_projecting():
    one, five, now = trend_tape()
    five[222] = dict(five[222], high=21925)
    result = engine().trend_setup(one, five, now)
    assert result["stage"] == "blocked"
    assert result["pattern"] == "retest"
    assert result["index_target"] == 21925
    assert "2R" in result["reason"]
    assert not result["eligible"]


def test_retest_ranks_before_simultaneous_sweep_and_nearest_retest_wins():
    one, five, now = trend_tape()
    one[56] = bar(56, 21910, 21920, 21909, 21918, now - 3600)
    one[57] = bar(57, 21918, 21920, 21894, 21918, now - 3600)
    one[58] = bar(58, 21918, 21924, 21915, 21922, now - 3600)
    one[59] = bar(59, 21922, 21923, 21921, 21922, now - 3600)
    one.insert(0, dict(one[0], time=one[0]["time"] - 60))
    result = engine().trend_setup(one, five, now)
    assert result["pattern"] == "retest" and result["reference"]["price"] == 21916
    one, five, now = trend_tape()
    for i in range(58):
        one[i] = bar(i, 21900, 21902, 21898, 21900, now - 3600)
    one[58] = bar(58, 21900, 21924, 21899, 21920, now - 3600)
    one[59] = bar(59, 21920, 21925, 21903, 21922, now - 3600)
    result = engine().trend_setup(one, five, now)
    assert result["reference"]["price"] == 21916


def test_trend_never_uses_unconfirmed_swing_as_break_reference():
    one, five, now = trend_tape()
    # This high becomes a strict pivot only when the final 5m bar closes.
    five[257] = dict(five[257], high=22100)
    for i in range(60):
        one[i] = bar(i, 22090, 22092, 22088, 22090, now - 3600)
    one[58] = bar(58, 22090, 22105, 22089, 22103, now - 3600)
    one[59] = bar(59, 22103, 22108, 22099, 22105, now - 3600)
    result = engine().trend_setup(one, five, now)
    assert result["stage"] == "waiting_pattern"
    assert result["index_entry"] is None


def test_pivot_numbering_survives_rolling_history_and_late_history_corrections():
    e = engine()
    state = advance(e.initial_opening_state("2026-10-16"), seed(), 600)
    frozen = state["numbered_swings"]
    state = advance(state, seed()[5:], 610)
    assert state["numbered_swings"] == frozen
    corrected = seed()
    corrected[3] = dict(corrected[3], low=22501)
    state = advance(state, corrected, 620)
    assert state["numbered_swings"] == frozen
    assert state["directions"]["PE"]["reference"]["ordinal"] == 2


def test_missing_candidate_candles_require_observed_recross_instead_of_inventing_first_red():
    state = armed()
    bars = seed() + [bar(12, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 780)
    assert state["directions"]["PE"]["stage"] == "expired"
    assert state["directions"]["PE"]["signal_candle"] is None
    assert state["directions"]["PE"]["rearm_needed"]


def test_trend_mirror_uses_pe_falling_context_and_symmetric_prices():
    one, five, now = trend_tape()

    def mirror(b):
        return {
            "time": b["time"],
            "open": 44000 - b["open"],
            "high": 44000 - b["low"],
            "low": 44000 - b["high"],
            "close": 44000 - b["close"],
        }

    result = engine().trend_setup([mirror(b) for b in one], [mirror(b) for b in five], now)
    assert result["stage"] == "ready" and result["direction"] == "PE"
    assert result["index_entry"] == 22078
    assert result["reference"]["price"] == 22084
    assert result["invalidation"] == pytest.approx(22085.50918367347)
    assert result["index_target"] == pytest.approx(22062.98163265306)


def test_adx_under_twenty_blocks_direction_and_early_requires_strict_atr_buffer():
    one, five, now = trend_tape()
    for i, b in enumerate(five):
        five[i] = dict(b, open=21900, high=21902, low=21898, close=21900)
    five[-1] = dict(five[-1], close=21901)
    assert engine().trend_setup(one, five, now)["stage"] == "waiting_trend"
    one, five, now = trend_tape()
    # Flat ATR 4 gives a 0.4 buffer. 21916.01 is over the level but insufficient.
    one[-2] = dict(one[-2], open=21915.9, high=21916.2, low=21915.8, close=21916.01)
    one[-1] = dict(one[-1], open=21916.01, high=21916.2, low=21915.8, close=21916.01)
    assert engine().trend_setup(one, five, now, "early")["stage"] == "waiting_pattern"


def test_opening_candle_trigger_does_not_invent_an_index_stop():
    state = advance(armed(), seed() + [bar(10, 22625, 22630, 22608, 22612)], 661, 22600)
    result = engine().opening_result(state, START + 661)["directions"]["PE"]
    assert result["invalidation"] is None
    assert result["index_target"] is None
    assert result["signal_candle"]["high"] == 22630


def test_delayed_event_cannot_process_candles_that_closed_after_event_timestamp():
    e = engine()
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    state = e.advance_opening(armed(), bars, event(650, 22620), START + 700, "2026-10-16", START)
    assert state["directions"]["PE"]["stage"] == "waiting_signal"
    assert state["directions"]["PE"]["signal_candle"] is None


def test_trend_honours_caller_supplied_special_session_start():
    one, five, now = trend_tape()
    shift = 8 * 3600
    one = [{**b, "time": b["time"] + shift} for b in one]
    five = [{**b, "time": b["time"] + shift if b["time"] >= START else b["time"]} for b in five]
    result = engine().trend_setup(one, five, now + shift, session_start=START + shift)
    assert result["stage"] == "ready"
    assert result["reference"]["known_at"] == START + shift + 900


def test_distinct_rearms_keep_unique_setup_ids_at_real_epoch_precision():
    bars = seed() + [bar(10, 22625, 22630, 22608, 22612)]
    state = advance(armed(), bars, 660)
    first_id = state["directions"]["PE"]["setup_id"]
    state = advance(state, bars, 961, 22590)
    state = advance(state, bars, 962, 22620)
    # Fill all intervening minutes so a history gap is not the cause of reset.
    bars += [bar(i, 22615, 22625, 22610, 22620) for i in range(11, 16)]
    bars += [bar(16, 22625, 22630, 22608, 22612)]
    state = advance(state, bars, 1020)
    assert state["directions"]["PE"]["stage"] == "waiting_trigger"
    assert state["directions"]["PE"]["setup_id"] != first_id
