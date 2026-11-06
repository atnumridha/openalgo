"""Chart confirmation uses the shared three-average regime, not the 9/15 cross."""
from decimal import Decimal as D

import pytest
from services.delta_chart import three_ema
from test_delta_three_ema import fixture, decimals, controlled_readings


def chart_backfill(candles, seconds=None):
    from services.delta_chart.ema_chart import ema_chart_backfill
    return ema_chart_backfill(candles, seconds, observed_at=candles[-1]['time']+(seconds or 60) if candles else 0)


@pytest.mark.parametrize('short', [False, True])
def test_chart_has_one_first_triple_confirmation_after_pair_cross(short):
    fast, _ = fixture(short)
    result = chart_backfill(fast, 60)
    assert result['alignment_algorithm'] == 'ema-9-15-21-alignment-v1'
    assert len(result['alignment_crosses']) == 1
    event = result['alignment_crosses'][0]
    assert event['side'] == ('down' if short else 'up')
    assert result['crosses'][0]['time'] < event['time']
    fast_value = next(p['value'] for p in result['9']['points'] if p['time'] == event['time'])
    slow_value = next(p['value'] for p in result['21']['points'] if p['time'] == event['time'])
    assert event['value'] == pytest.approx((fast_value+slow_value)/2)
    before = [bar for bar in fast if bar['time'] < event['time']]
    assert chart_backfill(before, 60)['alignment_crosses'] == []


def test_legacy_close_only_and_missing_interval_never_create_triple_events():
    fast, _ = fixture()
    assert chart_backfill([dict(time=b['time'], close=b['close']) for b in fast], 60)['alignment_crosses'] == []
    assert chart_backfill(fast)['alignment_crosses'] == []


@pytest.mark.parametrize('kind', ['gap', 'unaligned', 'negative', 'inverted', 'nan', 'bad_interval'])
def test_malformed_chart_evidence_is_rejected(kind):
    fast, _ = fixture()
    interval = 60
    if kind == 'gap': del fast[30]
    if kind == 'unaligned': fast[-1]['time'] += 1
    if kind == 'negative': fast[-1]['low'] = -1
    if kind == 'inverted': fast[-1]['high'] = fast[-1]['low']-1
    if kind == 'nan': fast[-1]['high'] = float('nan')
    if kind == 'bad_interval': interval = 0
    with pytest.raises(ValueError):
        chart_backfill(fast, interval)


def test_shared_chart_event_qualifies_later_without_consuming_auto_filter(monkeypatch):
    fast, higher = controlled_readings(monkeypatch)
    events = three_ema.alignment_events(fast)
    assert len(events) == 1
    assert events[0]['setup_time'] == fast[65]['time']
    assert events[0]['source_time'] == fast[66]['time']
    assert three_ema.detect(fast, higher)[0] == events[0]


@pytest.mark.parametrize('period', ['9', '15', '21'])
def test_chart_requires_every_three_bar_slope(monkeypatch, period):
    fast, _ = controlled_readings(monkeypatch, bad_slope=period)
    assert three_ema.alignment_events(fast) == []


def test_chart_requires_both_atr_gaps(monkeypatch):
    fast, _ = controlled_readings(monkeypatch, gap_scale=.5)
    assert three_ema.alignment_events(fast) == []


def test_forming_and_future_rows_never_confirm_until_their_close():
    fast, _ = fixture()
    full = chart_backfill(fast, 60)
    signal_time = full['alignment_crosses'][0]['time']
    from services.delta_chart.ema_chart import ema_chart_backfill
    assert ema_chart_backfill(fast, 60, observed_at=signal_time+59)['alignment_crosses'] == []
    assert ema_chart_backfill(fast, 60, observed_at=signal_time+60)['alignment_crosses'] == full['alignment_crosses']
    # Forming rows still preserve the original legacy EMA calculation contract.
    assert ema_chart_backfill(fast, 60, observed_at=signal_time+59)['9'] == full['9']


def test_chart_interval_allows_market_specific_timestamp_phase():
    fast, _ = fixture()
    fast = [dict(b, time=b['time']+15) for b in fast]
    assert len(chart_backfill(fast, 60)['alignment_crosses']) == 1


def test_partial_ohlc_retains_lines_but_cannot_assert_confirmation():
    fast, _ = fixture()
    del fast[-1]['high']
    result = chart_backfill(fast, 60)
    assert result['alignment_crosses'] == []
    assert len(result['9']['points']) == len(fast)-8


def test_maximum_chart_history_is_supported():
    candles = [dict(time=i*60, open=100, high=101, low=99, close=100) for i in range(10000)]
    result = chart_backfill(candles, 60)
    assert len(result['21']['points']) == 9980
    assert result['alignment_crosses'] == []


def test_closed_session_gap_can_confirm_when_display_policy_explicitly_allows_it():
    from services.delta_chart.ema_chart import ema_chart_backfill
    candles, _ = fixture()
    # A full-day jump keeps the interval's phase while crossing UTC dates.
    candles = [dict(bar, time=bar['time']+(86400 if i >= 60 else 0))
               for i, bar in enumerate(candles)]
    observed = candles[-1]['time']+60
    with pytest.raises(ValueError):
        ema_chart_backfill(candles, 60, observed_at=observed)
    result = ema_chart_backfill(candles, 60, observed_at=observed, allow_session_gaps=True)
    assert len(result['alignment_crosses']) == 1
    assert result['alignment_crosses'][0]['side'] == 'up'


@pytest.mark.parametrize('allow', ['true', 1, None, [], {}])
def test_session_gap_policy_requires_boolean(allow):
    from services.delta_chart.ema_chart import ema_chart_backfill
    with pytest.raises(ValueError):
        ema_chart_backfill([], 60, allow_session_gaps=allow)


def test_default_crypto_policy_still_rejects_intraday_missing_candle():
    from services.delta_chart.ema_chart import ema_chart_backfill
    candles, _ = fixture()
    del candles[35]
    with pytest.raises(ValueError):
        ema_chart_backfill(candles, 60, observed_at=candles[-1]['time']+60)


def test_missing_intraday_session_bar_preserves_lines_without_asserting_x():
    from services.delta_chart.ema import ema_backfill
    from services.delta_chart.ema_chart import ema_chart_backfill
    candles, _ = fixture()
    del candles[35]
    legacy=ema_backfill(candles)
    result=ema_chart_backfill(candles,60,observed_at=candles[-1]['time']+60,allow_session_gaps=True)
    assert all(result[p]==legacy[p]for p in ('9','15','21'))
    assert result['alignment_crosses']==[]


def test_missing_session_bar_cannot_hide_later_malformed_ohlc():
    from services.delta_chart.ema_chart import ema_chart_backfill
    candles, _ = fixture()
    del candles[35]
    candles[-1]['low']=-1
    with pytest.raises(ValueError):
        ema_chart_backfill(candles,60,observed_at=candles[-1]['time']+60,allow_session_gaps=True)
