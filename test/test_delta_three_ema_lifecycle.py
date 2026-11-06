"""Exercise the shared owner with the new strategy identity and closed candles.

The fake service records decisions only; these tests cannot contact a broker.
"""
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from services.delta_chart.automation import Automation
from services.delta_chart.service import Store
from test.test_delta_automation import FakeService


def history(seconds, direction, now):
    end = (int(now) // seconds - 1) * seconds
    bars = []
    for index in range(80):
        price = 10000 + direction * index * 2
        bars.append(dict(time=end-(79-index)*seconds, open=price-direction,
                         high=price+3, low=price-3, close=price))
    return bars[::-1]


@pytest.mark.parametrize('side,direction', [('buy', -1), ('sell', 1)])
@pytest.mark.parametrize('status', ['active', 'awaiting_entry'])
def test_three_ema_owned_plan_exits_or_cancels_on_closed_opposite_cross(side, direction, status):
    now = time.time()
    with tempfile.TemporaryDirectory() as directory:
        service = FakeService(Store(Path(directory)/'owner.db'))
        auto = Automation(service)
        service.auto = auto
        auto.configure('alice', dict(account=service.account, symbol='BTCUSD', enabled=True))
        service.position = dict(size=1 if side=='buy' else -1) if status=='active' else None
        service.managed_plans = [dict(id='three', status=status, side=side,
            strategy_id='ema_three', target_mode='trend', source_time=int(now)-600,
            interval_seconds=60, entry_trend_direction='up' if side=='buy' else 'down')]
        decisions = []
        service.manage = lambda user, body: decisions.append(body) or dict(status='confirmed', plan_status='closing' if status=='active' else 'cancelled')
        with patch.object(auto, 'read_histories', return_value=(history(60,direction,now), history(300,direction,now), now)), patch('services.delta_chart.automation.evaluate_strategy', return_value=dict(context={}, action=None)):
            auto.tick_one('alice', force=True)
        assert decisions[0]['decision'] == ('exit' if status=='active' else 'cancel_entry')
        assert decisions[0]['source_time'] == (int(now)//60-1)*60
        assert not service.calls


@pytest.mark.parametrize('side,direction', [('buy', 1), ('sell', -1)])
def test_forming_opposite_bar_cannot_close_three_ema_position(side,direction):
    now=time.time()
    bars=history(60,direction,now)
    price=1000 if side=='buy' else 20000
    bars.insert(0,dict(time=int(now)//60*60,open=10000,high=max(price,10000),low=min(price,10000),close=price))
    with tempfile.TemporaryDirectory() as directory:
        service=FakeService(Store(Path(directory)/'owner.db'));auto=Automation(service);service.auto=auto
        auto.configure('alice',dict(account=service.account,symbol='BTCUSD',enabled=True))
        service.position=dict(size=1 if side=='buy' else -1)
        service.managed_plans=[dict(id='three',status='active',side=side,strategy_id='ema_three',target_mode='trend',source_time=int(now)-600,interval_seconds=60,entry_trend_direction='up'if side=='buy'else'down')]
        decisions=[]
        service.manage=lambda user,body:decisions.append(body)or dict(status='confirmed',plan_status='active')
        with patch.object(auto,'read_histories',return_value=(bars,history(300,direction,now),now)),patch('services.delta_chart.automation.evaluate_strategy',return_value=dict(context={},action=None)):
            auto.tick_one('alice',force=True)
        assert decisions[0]['decision']=='sync'
        assert not service.calls
