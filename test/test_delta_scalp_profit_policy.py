from decimal import Decimal as D
import pytest
from services.delta_chart.scalp_policy import profit_protection


def calc(mark, peak=0, rate=0, size=4):
    return profit_protection(
        D(100),
        D(str(mark)),
        D(size),
        D(".001"),
        D(".5"),
        D(".01"),
        D(str(rate)),
        D(str(peak)),
    )


def test_peak_survives_pullback_and_closes_if_floor_crossed():
    peak, floor, stop, close = calc(240)
    assert peak > 30 and floor == peak - 10 and stop is not None and not close
    assert not calc(220, peak)[3]  # ₹6.80 pullback stays inside the new ₹10 gap.
    again = calc(210, peak)
    assert again[0] == peak and again[1] == floor and again[3]


def test_fee_waiver_expiry_does_not_reset_peak_or_profit_floor():
    peak, floor, stop, close = calc(240)
    after = calc(240, peak, ".05")
    assert after[0] == peak and after[1] == floor
    assert after[3] or after[2] >= stop


def test_short_mirrors_and_tick_floor_includes_exit_fee_at_stop():
    args = (D(78000), D(77800), D(-4), D(".001"), D(".5"), D(".073"), D(".00059"), D(0))
    peak, floor, stop, close = profit_protection(*args)
    assert peak > 30 and not close
    net_at_stop = (
        (args[0] - stop) * D(".004") - args[5] - stop * D(".004") * args[6]
    ) * 85
    assert net_at_stop >= floor


def test_no_profit_lock_before_ten_plus_broker_tick_space():
    assert calc(110)[1:] == (None, None, False)


def test_nearby_tick_rounded_stop_does_not_close_while_net_is_above_floor():
    # Four contracts: net=₹10.20, floor=₹10. Tick-rounded stop cannot yet
    # keep a full tick of distance. Keep existing protection, do not take profit.
    peak,floor,stop,close=calc(132.5, 15)
    assert peak == D(15) and floor == D(10)
    assert stop is None and not close


def test_fifteen_net_activates_ten_floor_for_long_and_short_after_fees():
    for size in (D(4),D(-4)):
        coin=abs(size)*D('.001')
        def at_net(net,peak=0):
            move=(D('.01')+D(str(net))/85)/coin
            mark=D(1000)+(move if size>0 else -move)
            return profit_protection(D(1000),mark,size,D('.001'),D('.5'),D('.01'),D(0),D(str(peak)))
        for net in (10,12,14.99):
            assert at_net(net)[1:] == (None,None,False)
        peak,floor,stop,close=at_net(15)
        assert abs(peak-D(15)) < D('.00000001')
        assert floor==10 and stop is not None and not close
        assert at_net(12,peak)[1]==10 and not at_net(12,peak)[3]
        assert at_net(9,peak)[3]


NOW = 1800000305


def adaptive_bars(center=200, span=60, count=20):
    end = (NOW//span-1)*span
    return [dict(time=end-i*span,open=str(center-1),high=str(center+5),low=str(center-5),close=str(center))
            for i in range(count)]


def adaptive(mark=220, peak=0, size=4, bars=None, current_stop=95, observed=NOW, now=NOW, rate=0, first_fill=NOW//60*60-4*60):
    from services.delta_chart.scalp_policy import adaptive_profit_protection
    return adaptive_profit_protection(D(100) if size>0 else D(300),D(str(mark)),D(size),D('.001'),D('.5'),
        D('.01'),D(str(rate)),D(str(peak)),adaptive_bars() if bars is None else bars,
        60,observed,now,D(str(current_stop)),first_fill_at=first_fill)


def test_adaptive_long_structure_waits_for_room_then_locks_above_ten_net():
    # Lows near entry permit risk reduction, but cannot justify a ₹10 lock.
    result = adaptive(150,bars=adaptive_bars(110))
    assert result[0] > 15 and result[1] is None
    assert result[2] == D('102.5') and not result[3] and 'risk' in result[4].lower()
    ready = adaptive()
    assert ready[2] == D('192.5')  # low195 - .25*ATR10; at leastATR behindmark220.
    assert ready[1] == 10 and not ready[3]
    assert ((ready[2]-100)*D('.004')-D('.01'))*85 >= 10


def test_adaptive_normal_retrace_exceeding_ten_rupees_does_not_close_or_loosen():
    result = adaptive(mark=220,peak=60,current_stop=192.5)
    assert result[0] == 60 and result[2] is None and not result[3]
    # Even a structural breakdown is left to the acknowledged broker SL and
    # coordinator trend policy, never a synthetic rupee-peak market close.
    broken = adaptive(mark=185,peak=60,current_stop=192.5,bars=adaptive_bars(185))
    assert broken[2] is None and not broken[3]


def test_adaptive_short_mirrors_structure_and_respects_one_atr_space():
    result = adaptive(mark=180,size=-4,current_stop=305)
    assert result[2] == D('207.5')
    assert result[2] >= D(180)+10 and not result[3]
    assert ((300-result[2])*D('.004')-D('.01'))*85 >= 10
    # Peak pullback does not produce a fixed-gap exit or widen an existing stop.
    pullback = adaptive(mark=215,peak=60,size=-4,current_stop=207.5,bars=adaptive_bars(210))
    assert pullback[2] is None and not pullback[3]


def test_adaptive_stop_is_fee_aware_and_never_forces_lock_inside_structure():
    result = adaptive(mark=220,rate='.5')
    assert result[2] == D('192.5') and not result[3]
    assert result[1] is None  # High fees mean reduced risk, no claimed profit lock.
    assert 'fee' in result[4].lower()


def test_adaptive_stale_gapped_incomplete_and_future_evidence_preserves_stop():
    for kwargs in [dict(bars=[]),dict(bars=adaptive_bars(count=14)),dict(observed=NOW-31),dict(observed=NOW+1),
                   dict(now=NOW+60)]:
        result = adaptive(peak=60,**kwargs)
        assert result[2] is None and not result[3]
    bars=adaptive_bars(); del bars[4]
    result=adaptive(peak=60,bars=bars)
    assert result[2] is None and not result[3]


def test_adaptive_uses_completed_bars_and_rounds_away_from_mark():
    bars=adaptive_bars(); bars[0]['low']='194.93'
    result=adaptive(bars=bars)
    # ATR=(140+.07)/14; low194.93 minusquarterATR roundsdown to192.
    assert result[2] == 192
    forming=dict(bars[0],time=NOW//60*60,low='1')
    assert adaptive(bars=[forming]+bars)[2] == 192


@pytest.mark.parametrize('size,mark,center,current_stop,want',[(4,110,102,90,'94.5'),(-4,290,298,310,'305.5')])
def test_structural_reduction_starts_before_fifteen_peak_without_fake_breakeven(size,mark,center,current_stop,want):
    result=adaptive(mark=mark,size=size,bars=adaptive_bars(center),current_stop=current_stop)
    assert result[0]<15
    assert result[2]==D(want)
    assert result[1] is None and not result[3]
    assert 'risk' in result[4].lower()


@pytest.mark.parametrize('size,mark,center,current_stop,want',[(4,150,120,90,'112.5'),(-4,250,280,310,'287.5')])
def test_structural_partial_profit_lock_does_not_jump_to_ten_rupees(size,mark,center,current_stop,want):
    result=adaptive(mark=mark,size=size,bars=adaptive_bars(center),current_stop=current_stop)
    assert result[2]==D(want)
    assert result[1]==D('3.4') and not result[3]
    assert 'partial' in result[4].lower()


@pytest.mark.parametrize('first_fill',[None,NOW-5,NOW//60*60-2*60])
def test_structural_reduction_requires_three_fully_postfill_completed_bars(first_fill):
    result=adaptive(mark=150,bars=adaptive_bars(120),current_stop=90,first_fill=first_fill)
    assert result[2] is None and not result[3]
    assert 'post-fill' in result[4].lower()


@pytest.mark.parametrize('size,center,stop',[(D(4),1030,D(900)),(D(-4),970,D(1100))])
def test_partial_profit_lock_starts_at_exact_point_fifteen_usd_net(size,center,stop):
    from services.delta_chart.scalp_policy import adaptive_profit_protection
    def at_net(net_usd):
        move=(D('.01')+net_usd)/D('.004')
        mark=D(1000)+(move if size>0 else -move)
        return adaptive_profit_protection(D(1000),mark,size,D('.001'),D('.5'),D('.01'),D(0),D(0),
            adaptive_bars(center),60,NOW,NOW,stop,first_fill_at=NOW//60*60-4*60)
    below=at_net(D('12.7499')/85)
    assert below[2] is None and below[1] is None and not below[3]
    assert '0.15' in below[4]
    at=at_net(D('.15'))
    assert at[0]==D('12.75')
    assert at[1]==D('6.8')
    assert at[2]==(D('1022.5') if size>0 else D('977.5'))
    assert not at[3]


def test_staged_structure_uses_three_postfill_wicks_not_older_swing():
    bars=adaptive_bars()
    bars[3].update(open='195',high='200',low='190',close='195')
    result=adaptive(bars=bars,first_fill=NOW//60*60-3*60)
    assert result[2]==D('192.5')
    assert result[2]<D(195) and result[2]<=D(220)-10
