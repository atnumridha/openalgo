"""Four-hour signal causality and missing-data handling, with hand-made candles."""

import pandas as pd
import pytest

from services.research.fourhour_range import range_signals


def session(day="2025-01-02"):
    ix = pd.date_range(f"{day} 09:16", f"{day} 15:30", freq="min", tz="Asia/Kolkata")
    return pd.DataFrame({"open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0}, index=ix)


def candle(f, at, *, opening, high, low, close):
    end = pd.Timestamp(f"{f.index[0].date()} {at}", tz="Asia/Kolkata")
    ix = pd.date_range(end - pd.Timedelta(minutes=4), end, freq="min")
    f.loc[ix, ["open", "high", "low", "close"]] = [opening, high, low, close]


def candidate_frame(f):
    result, audit = range_signals(f)
    return result[result.direction != ""], audit


def test_waits_for_full_range_and_later_closed_breakout_then_inside_close():
    f = session()
    # 13:20 has only a wick above 105; equality at 13:25 is not a breakout.
    candle(f, "13:20", opening=100, high=110, low=99, close=104)
    candle(f, "13:25", opening=104, high=110, low=100, close=105)
    candle(f, "13:30", opening=104, high=108, low=99, close=106)
    candle(f, "13:35", opening=106, high=109, low=102, close=103)
    rows, audit = candidate_frame(f)
    assert len(rows) == 1
    assert rows.index[0].strftime("%H:%M") == "13:35"
    assert rows.iloc[0].direction == "PE"
    assert rows.iloc[0].stop_price == 109
    assert rows.iloc[0].range_high == 105 and rows.iloc[0].range_low == 95
    assert audit["valid_range_sessions"] == 1
    assert candidate_frame(f.loc[:"2025-01-02 13:14"])[0].empty


def test_missing_range_minute_excludes_day_and_post_range_gap_discards_excursion():
    f = session()
    candle(f, "13:20", opening=105, high=110, low=103, close=107)
    candle(f, "13:25", opening=104, high=105, low=99, close=101)
    missing_range = f.drop(pd.Timestamp("2025-01-02 11:37", tz="Asia/Kolkata"))
    rows, audit = candidate_frame(missing_range)
    assert rows.empty and audit["excluded_range_sessions"] == 1
    missing_after = f.drop(pd.Timestamp("2025-01-02 13:23", tz="Asia/Kolkata"))
    rows, audit = candidate_frame(missing_after)
    assert rows.empty and audit["incomplete_trigger_buckets"] == 1


def test_reflected_long_stop_tracks_whole_excursion_and_new_breakout_rearms():
    f = session()
    candle(f, "13:20", opening=96, high=99, low=92, close=94)
    candle(f, "13:25", opening=93, high=97, low=89, close=92)
    candle(f, "13:30", opening=94, high=103, low=91, close=100)
    candle(f, "13:40", opening=96, high=99, low=90, close=93)
    candle(f, "13:45", opening=94, high=104, low=88, close=101)
    rows, _ = candidate_frame(f)
    assert rows.index.strftime("%H:%M").tolist() == ["13:30", "13:45"]
    assert rows.direction.tolist() == ["CE", "CE"]
    assert rows.stop_price.tolist() == [89, 88]
    reflected = f.copy()
    for name, source in (("open", "open"), ("close", "close"), ("high", "low"), ("low", "high")):
        reflected[name] = 200 - f[source]
    mirrored, _ = candidate_frame(reflected)
    assert mirrored.direction.tolist() == ["PE", "PE"]
    assert mirrored.stop_price.tolist() == [111, 112]


def test_opposite_boundary_jump_rearms_and_day_end_clears_pending_excursion():
    f = session()
    candle(f, "13:20", opening=105, high=110, low=103, close=107)
    candle(f, "13:25", opening=106, high=111, low=91, close=93)
    candle(f, "13:30", opening=94, high=103, low=92, close=100)
    candle(f, "15:30", opening=105, high=110, low=102, close=107)
    rows, _ = candidate_frame(pd.concat([f, session("2025-01-03")]))
    assert len(rows) == 1 and rows.iloc[0].direction == "CE"
    assert rows.iloc[0].stop_price == 91


def test_appending_future_never_changes_earlier_signals():
    f = session()
    candle(f, "13:20", opening=105, high=110, low=103, close=107)
    candle(f, "13:25", opening=104, high=105, low=99, close=101)
    prefix = f.loc[:"2025-01-02 13:47"]
    a, _ = range_signals(prefix)
    b, _ = range_signals(pd.concat([f, session("2025-01-03")]))
    pd.testing.assert_frame_equal(a, b.loc[a.index])


def test_timezone_and_duplicate_input_cannot_silently_change_session_anchor():
    f = session()
    utc = f.copy()
    utc.index = utc.index.tz_convert("UTC")
    a, _ = range_signals(f)
    b, _ = range_signals(utc)
    pd.testing.assert_frame_equal(a, b)
    with pytest.raises(ValueError):
        range_signals(pd.concat([f.iloc[:1], f]))
